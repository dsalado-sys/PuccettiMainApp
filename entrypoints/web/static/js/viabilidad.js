/* §2.9 — Estudio de viabilidad: preview en vivo y guardado.
   Lee el formulario, llama a /modulos/viabilidad/calcular y repinta KPIs.
*/
(function () {
  "use strict";

  const form = document.getElementById("form-viabilidad");
  if (!form) return;

  const puedeEditar = form.dataset.puedeEditar === "true";
  const btnCalcular = document.getElementById("btn-calcular");
  const btnGuardar = document.getElementById("btn-guardar");
  const toast = document.getElementById("vb-toast");
  const avisosBox = document.getElementById("vb-avisos");
  const avisosLista = avisosBox ? avisosBox.querySelector("ul") : null;

  const FUENTE_LABEL = {
    catastro_existente: "superficie · catastro",
    manual: "superficie · manual",
    parcela_x_edificabilidad: "superficie · parcela × edif.",
    vacio: "sin superficie",
  };

  // ── Conversión form → payload del backend ───────────────────────────
  function payloadDesdeForm() {
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    // Porcentajes en UI vienen como 0–100; el backend espera fracción 0–1.
    if (data.ocupacion_anual_pct !== undefined) {
      data.ocupacion_anual_pct = (parseFloat(data.ocupacion_anual_pct) || 0) / 100;
    }
    if (data.pct_costes_indirectos_pct !== undefined) {
      data.pct_costes_indirectos =
        (parseFloat(data.pct_costes_indirectos_pct) || 0) / 100;
      delete data.pct_costes_indirectos_pct;
    }
    return data;
  }

  // ── Formato 1.234.567 € (locale es-ES, sin decimales) ───────────────
  const fmtEur = new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  });
  const fmtPct = new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
  const fmtM2 = new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });

  function repintar(estudio) {
    if (!estudio) return;
    const set = (key, valor) => {
      const el = form.querySelector(`[data-kpi="${key}"]`);
      if (el) el.textContent = valor;
    };
    set("ingresos_eur", fmtEur.format(estudio.ingresos_eur) + " €");
    set("coste_total_eur", fmtEur.format(estudio.coste_total_eur) + " €");
    set("margen_eur", fmtEur.format(estudio.margen_eur) + " €");
    set("margen_pct", fmtPct.format(estudio.margen_pct) + " %");
    set("superficie_aplicada_m2", fmtM2.format(estudio.superficie_aplicada_m2));
    set("coste_construccion_eur", fmtEur.format(estudio.coste_construccion_eur));
    set("coste_indirectos_eur", fmtEur.format(estudio.coste_indirectos_eur));
    set("coste_suelo_eur", fmtEur.format(estudio.coste_suelo_eur));
    set("fuente_superficie", FUENTE_LABEL[estudio.fuente_superficie] || estudio.fuente_superficie);

    // KPI margen en rojo si es negativo
    const kpiMargen = form.querySelector('[data-kpi="margen_eur"]')?.closest(".kpi");
    const kpiPct = form.querySelector('[data-kpi="margen_pct"]')?.closest(".kpi");
    [kpiMargen, kpiPct].forEach((el) => {
      if (!el) return;
      el.classList.toggle("kpi--negativo", estudio.margen_eur < 0);
    });

    // Avisos
    if (avisosBox && avisosLista) {
      if (estudio.avisos && estudio.avisos.length) {
        avisosLista.innerHTML = estudio.avisos
          .map((a) => `<li>${escapeHtml(a)}</li>`)
          .join("");
        avisosBox.classList.remove("vb-oculto");
      } else {
        avisosBox.classList.add("vb-oculto");
        avisosLista.innerHTML = "";
      }
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ── Visibilidad dinámica: ocupación (solo renta), edificabilidad (solo obra nueva) ──
  function aplicarVisibilidad() {
    const operacion = form.querySelector('input[name="operacion"]:checked')?.value || "venta";
    const intervencion = form.querySelector('input[name="intervencion"]:checked')?.value || "obra_nueva";

    const campoRenta = form.querySelector(".vb-campo-renta");
    const campoObra = form.querySelector(".vb-campo-obra-nueva");
    if (campoRenta) campoRenta.classList.toggle("vb-oculto", operacion !== "renta");
    if (campoObra) campoObra.classList.toggle("vb-oculto", intervencion !== "obra_nueva");

    // Label dinámico del precio
    const lblPrecio = document.getElementById("lbl-precio");
    const hintPrecio = document.getElementById("hint-precio");
    if (operacion === "renta") {
      if (lblPrecio) lblPrecio.textContent = "Precio renta (€/m²·mes)";
      if (hintPrecio) hintPrecio.textContent = "€/m²·mes sobre la superficie construida";
    } else {
      if (lblPrecio) lblPrecio.textContent = "Precio venta (€/m²)";
      if (hintPrecio) hintPrecio.textContent = "€/m² construido";
    }
  }

  // ── Llamadas al backend ─────────────────────────────────────────────
  let abortController = null;
  let debounceId = null;
  let ultimoPayload = "";

  async function calcular() {
    if (!puedeEditar) return; // backend devolverá 403 igualmente
    const payload = payloadDesdeForm();
    const cuerpo = JSON.stringify(payload);
    if (cuerpo === ultimoPayload) return;
    // `ultimoPayload` se fija SOLO tras un cálculo con éxito (más abajo). Si se
    // marcara aquí, un fallo transitorio (red caída, 500/422) con el mismo payload
    // ya no se reintentaría: la guarda de arriba lo bloquearía y el preview quedaría
    // pegado hasta editar un campo o pulsar Calcular.

    if (abortController) abortController.abort();
    abortController = new AbortController();

    try {
      const resp = await fetch("/modulos/viabilidad/calcular", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: cuerpo,
        signal: abortController.signal,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al calcular", true);
        return;
      }
      const estudio = await resp.json();
      ultimoPayload = cuerpo;   // memoiza solo el último cálculo correcto
      repintar(estudio);
    } catch (err) {
      if (err.name === "AbortError") return;
      mostrarToast("Error de red al calcular", true);
      // ultimoPayload sin actualizar → el próximo intento con el mismo payload reintenta
    }
  }

  function calcularConDebounce() {
    aplicarVisibilidad();
    if (debounceId) clearTimeout(debounceId);
    debounceId = setTimeout(calcular, 250);
  }

  async function guardar(ev) {
    ev.preventDefault();
    if (!puedeEditar) return;
    const payload = payloadDesdeForm();
    try {
      const resp = await fetch("/modulos/viabilidad/guardar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.status === 409) {
        mostrarToast("Necesitas un proyecto activo para guardar", true);
        return;
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "No se pudo guardar", true);
        return;
      }
      const data = await resp.json();
      if (data && data.estudio) repintar(data.estudio);
      mostrarToast("Guardado.");
    } catch (err) {
      mostrarToast("Error de red al guardar", true);
    }
  }

  function mostrarToast(msg, esError = false) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.toggle("toast--error", esError);
    toast.classList.add("toast--on");
    setTimeout(() => toast.classList.remove("toast--on"), 2200);
  }

  // ── Bindings ───────────────────────────────────────────────────────
  form.addEventListener("input", calcularConDebounce);
  form.addEventListener("change", calcularConDebounce);
  if (btnCalcular) btnCalcular.addEventListener("click", () => {
    ultimoPayload = ""; // forzar recálculo
    calcular();
  });
  form.addEventListener("submit", guardar);

  aplicarVisibilidad();
})();
