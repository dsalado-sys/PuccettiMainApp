/* §2.4-2.7 — Render y cálculos. Estado, fetch y repintado.
   Estrategia:
   - cualquier cambio de input dispara /preview (debounce 250 ms) que pinta
     huella + patios + indicadores rápidos.
   - el botón «Distribuir viviendas» pide /calcular y trae el macro_layout
     completo (unidades, núcleo, pasillos, tabla por unidad). Spinner sobre canvas.
*/
(function () {
  "use strict";

  const form = document.getElementById("rc-form");
  if (!form) return;

  const puedeEditar = form.dataset.puedeEditar === "true";
  const estado = form.dataset.estado;

  const canvasEl = document.getElementById("rc-canvas");
  const brujulaEl = document.getElementById("rc-brujula");
  const spinnerEl = document.getElementById("rc-spinner");
  const tabsPlantasEl = document.getElementById("rc-tabs-plantas");
  const tablaPlantaBody = document.querySelector("#rc-tabla-planta tbody");
  const tablaUnidadBody = document.querySelector("#rc-tabla-unidad tbody");
  const tablaAnexoWrap = document.getElementById("rc-tabla-anexo-wrap");
  const alertasBox = document.getElementById("rc-alertas");
  const alertasUl = alertasBox.querySelector("ul");
  const toast = document.getElementById("rc-toast");
  const btnDistribuir = document.getElementById("rc-btn-distribuir");
  const btnGuardar = document.getElementById("rc-btn-guardar");
  const btnCsv = document.getElementById("rc-btn-csv");
  const btnNormativa = document.getElementById("rc-btn-normativa");
  const modal = document.getElementById("rc-modal-normativa");

  const renderer = new window.RenderCanvas(canvasEl);

  const fmt = {
    m2: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, minimumFractionDigits: 1 }),
    int: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 }),
    pct: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }),
  };

  const ESTADO = {
    previewPayload: null,
    fullPayload: null,
    plantaActiva: 0,
    abortPreview: null,
    abortCalcular: null,
    debounceId: null,
  };

  // ─── Lectura del formulario → payload backend ─────────────────────────
  function leerFormulario() {
    const fd = new FormData(form);
    const bloques = { urbanisticos: {}, diseno: {}, programa: {} };
    const inputs = form.querySelectorAll("[data-bloque]");
    inputs.forEach(inp => {
      const bloque = inp.dataset.bloque;
      const nombre = inp.name;
      if (!bloque || !nombre) return;
      if (inp.type === "checkbox") {
        if (nombre === "usos_permitidos") {
          if (!Array.isArray(bloques[bloque].usos_permitidos)) {
            bloques[bloque].usos_permitidos = [];
          }
          if (inp.checked) bloques[bloque].usos_permitidos.push(inp.value);
        } else {
          bloques[bloque][nombre] = inp.checked;
        }
      } else if (inp.tagName === "SELECT") {
        bloques[bloque][nombre] = inp.value;
      } else {
        const valor = inp.value === "" ? null : (inp.type === "number" ? Number(inp.value) : inp.value);
        bloques[bloque][nombre] = valor;
      }
    });
    // Aseguramos que usos_permitidos exista aunque ninguna casilla esté marcada
    if (!bloques.urbanisticos.usos_permitidos) bloques.urbanisticos.usos_permitidos = [];
    return bloques;
  }

  function actualizarResumen(bloques) {
    const set = (sel, v) => {
      const el = form.querySelector(`[data-resumen="${sel}"]`);
      if (el) el.textContent = v;
    };
    set("uso", bloques.programa.uso || "—");
    set("edif", bloques.urbanisticos.edificabilidad_m2t_m2s ?? "—");
    set("plantas", bloques.urbanisticos.n_plantas_max ?? "—");
    set("ocupacion", bloques.urbanisticos.ocupacion_maxima_pct ?? "—");
    set("adapt", bloques.programa.pct_unidades_adaptadas ?? "—");
  }

  // ─── Toast y spinner ──────────────────────────────────────────────────
  function mostrarToast(msg, esError = false) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.toggle("rc-toast-error", esError);
    toast.classList.add("rc-toast-on");
    setTimeout(() => toast.classList.remove("rc-toast-on"), 2200);
  }
  function spinner(on) { if (spinnerEl) spinnerEl.hidden = !on; }

  // ─── Repintado de KPIs ────────────────────────────────────────────────
  function repintarKpis(payload) {
    const set = (key, v) => {
      const el = document.querySelector(`[data-kpi="${key}"]`);
      if (el) el.textContent = v;
    };
    const env = payload?.envolvente;
    const edif = payload?.edificio;
    const ind = payload?.indicadores;
    if (edif && edif.totales) {
      set("construida_total_m2", fmt.m2.format(edif.totales.construida_total_m2) + " m²");
      set("util_total_m2", fmt.m2.format(edif.totales.util_total_m2) + " m²");
      set("n_viviendas", fmt.int.format(edif.totales.n_viviendas));
    } else if (env) {
      set("construida_total_m2", fmt.m2.format(env.edificabilidad_consumida_m2) + " m²");
      set("util_total_m2", "—");
      set("n_viviendas", fmt.int.format(env.n_viviendas_objetivo) + " obj.");
    }
    if (ind) {
      set("compacidad", fmt.pct.format(ind.compacidad));
      set("huecos", fmt.pct.format((ind.proporcion_huecos || 0) * 100));
    }
  }

  // ─── Tabs de planta ───────────────────────────────────────────────────
  function dibujarTabsPlantas(payload) {
    if (!tabsPlantasEl) return;
    let plantas = [];
    if (payload?.edificio?.plantas?.length) plantas = payload.edificio.plantas;
    else if (payload?.envolvente?.plantas?.length) plantas = payload.envolvente.plantas;

    if (!plantas.length) {
      tabsPlantasEl.innerHTML = '<span class="rc-tab rc-tab-vacio">Pulsa «Distribuir viviendas» o cambia un parámetro para empezar.</span>';
      return;
    }
    tabsPlantasEl.innerHTML = "";
    plantas.forEach((pl, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "rc-tab" + (i === ESTADO.plantaActiva ? " rc-tab-activo" : "");
      b.textContent = pl.nombre || (pl.n === 0 ? "PB" : "P" + pl.n);
      b.dataset.indice = i;
      b.addEventListener("click", () => {
        ESTADO.plantaActiva = i;
        dibujarTabsPlantas(payload);
        renderer.dibujar(payload, i);
      });
      tabsPlantasEl.appendChild(b);
    });
  }

  // ─── Tabla por planta ─────────────────────────────────────────────────
  function repintarTablaPlanta(filas) {
    if (!tablaPlantaBody) return;
    tablaPlantaBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaPlantaBody.innerHTML = '<tr><td colspan="8" class="rc-vacio">Sin datos. Calcula la distribución.</td></tr>';
      return;
    }
    let tot = { c: 0, u: 0, circ: 0, pat: 0, mur: 0, viv: 0 };
    filas.forEach(r => {
      tot.c += r.construida_m2 || 0;
      tot.u += r.util_viviendas_m2 || 0;
      tot.circ += r.circulacion_m2 || 0;
      tot.pat += r.patios_m2 || 0;
      tot.mur += r.muros_m2 || 0;
      tot.viv += r.viviendas || 0;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td>${fmt.int.format(r.viviendas)}</td>
        <td>${fmt.m2.format(r.construida_m2)}</td>
        <td>${fmt.m2.format(r.util_viviendas_m2)}</td>
        <td>${fmt.m2.format(r.circulacion_m2)}</td>
        <td>${fmt.m2.format(r.patios_m2)}</td>
        <td>${fmt.m2.format(r.muros_m2)}</td>
        <td>${fmt.pct.format(r.eficiencia_pct)}</td>`;
      tablaPlantaBody.appendChild(tr);
    });
    const trTot = document.createElement("tr");
    trTot.style.fontWeight = "600";
    trTot.style.background = "var(--gris-suave)";
    trTot.innerHTML = `
      <td>Total</td>
      <td>${fmt.int.format(tot.viv)}</td>
      <td>${fmt.m2.format(tot.c)}</td>
      <td>${fmt.m2.format(tot.u)}</td>
      <td>${fmt.m2.format(tot.circ)}</td>
      <td>${fmt.m2.format(tot.pat)}</td>
      <td>${fmt.m2.format(tot.mur)}</td>
      <td>${tot.c ? fmt.pct.format(100 * tot.u / tot.c) : "—"}</td>`;
    tablaPlantaBody.appendChild(trTot);
  }

  function repintarTablaUnidad(filas) {
    if (!tablaUnidadBody) return;
    tablaUnidadBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaUnidadBody.innerHTML = '<tr><td colspan="9" class="rc-vacio">Sin distribución calculada.</td></tr>';
      tablaAnexoWrap.innerHTML = '<p class="rc-vacio">Sin distribución calculada.</p>';
      return;
    }
    const noCumplen = [];
    filas.forEach(r => {
      const tr = document.createElement("tr");
      if (!r.cumple_min || !r.ventila_ok || !r.acceso) {
        tr.className = "rc-fila-incumple";
        noCumplen.push(r);
      }
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td>${r.vivienda}</td>
        <td>${r.dorms}</td>
        <td class="${r.cumple_min ? "" : "rc-celda-incumple"}">${fmt.m2.format(r.util_m2)}</td>
        <td>${fmt.m2.format(r.min_m2)}</td>
        <td>${r.cumple_min ? "✓" : "✗"}</td>
        <td>${r.ventilacion} ${r.ventila_ok ? "" : "⚠"}</td>
        <td>${r.acceso ? "✓" : "✗"}</td>
        <td>${r.adaptada ? "✓" : "—"}</td>`;
      tablaUnidadBody.appendChild(tr);
    });
    if (noCumplen.length) {
      const ul = document.createElement("ul");
      ul.style.padding = "0 16px";
      noCumplen.forEach(r => {
        const li = document.createElement("li");
        li.textContent = `${r.planta} · ${r.vivienda}: ${r.util_m2} m² (mín ${r.min_m2}) · ventila: ${r.ventilacion}`;
        ul.appendChild(li);
      });
      tablaAnexoWrap.innerHTML = "";
      tablaAnexoWrap.appendChild(ul);
    } else {
      tablaAnexoWrap.innerHTML = '<p class="rc-vacio">Todas las unidades cumplen Anexo I.5 y ventilación.</p>';
    }
  }

  // ─── Alertas ──────────────────────────────────────────────────────────
  function repintarAlertas(alertas) {
    if (!alertasBox || !alertasUl) return;
    if (!alertas || !alertas.length) {
      alertasBox.hidden = true;
      alertasUl.innerHTML = "";
      return;
    }
    alertasBox.hidden = false;
    alertasUl.innerHTML = "";
    alertas.forEach(a => {
      const li = document.createElement("li");
      li.className = "rc-alerta-" + a.nivel;
      const regla = document.createElement("span");
      regla.className = "rc-alerta-regla";
      regla.textContent = a.regla;
      li.appendChild(regla);
      li.appendChild(document.createTextNode(a.mensaje));
      alertasUl.appendChild(li);
    });
  }

  function actualizarBrujula(payload) {
    if (!window.RcBrujula || !brujulaEl) return;
    const ind = payload?.indicadores;
    window.RcBrujula.dibujar(brujulaEl, ind ? ind.orientaciones_fachadas : []);
  }

  // ─── Fetch /preview (rápido) ──────────────────────────────────────────
  async function pedirPreview() {
    if (estado !== "ok") return;
    const bloques = leerFormulario();
    actualizarResumen(bloques);
    if (ESTADO.abortPreview) ESTADO.abortPreview.abort();
    ESTADO.abortPreview = new AbortController();
    try {
      const resp = await fetch("/modulos/render-calculos/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bloques),
        signal: ESTADO.abortPreview.signal,
      });
      if (resp.status === 409) { mostrarToast("Localiza primero la parcela", true); return; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error en preview", true);
        return;
      }
      const data = await resp.json();
      ESTADO.previewPayload = data;
      ESTADO.plantaActiva = Math.min(ESTADO.plantaActiva, (data.envolvente?.plantas?.length || 1) - 1);
      dibujarTabsPlantas(data);
      renderer.dibujar(data, ESTADO.plantaActiva);
      actualizarBrujula(data);
      repintarKpis(data);
      repintarAlertas(data.alertas);
      // Marcamos botón "Distribuir" como stale si ya hubo full payload
      if (ESTADO.fullPayload) btnDistribuir.classList.add("rc-stale");
    } catch (e) {
      if (e.name !== "AbortError") mostrarToast("Error de red", true);
    }
  }

  // ─── Fetch /calcular (completo) ───────────────────────────────────────
  async function pedirCalculo() {
    if (estado !== "ok") return;
    const bloques = leerFormulario();
    if (ESTADO.abortCalcular) ESTADO.abortCalcular.abort();
    ESTADO.abortCalcular = new AbortController();
    spinner(true);
    btnDistribuir.classList.remove("rc-stale");
    try {
      const resp = await fetch("/modulos/render-calculos/calcular", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bloques),
        signal: ESTADO.abortCalcular.signal,
      });
      if (resp.status === 409) { mostrarToast("Localiza primero la parcela", true); return; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al calcular", true);
        return;
      }
      const data = await resp.json();
      ESTADO.fullPayload = data;
      const n_plantas = data.edificio?.plantas?.length || 1;
      ESTADO.plantaActiva = Math.min(ESTADO.plantaActiva, n_plantas - 1);
      dibujarTabsPlantas(data);
      renderer.dibujar(data, ESTADO.plantaActiva);
      actualizarBrujula(data);
      repintarKpis(data);
      repintarAlertas(data.alertas);
      repintarTablaPlanta(data.tabla_planta);
      repintarTablaUnidad(data.tabla_unidad);
      mostrarToast("Distribución actualizada");
    } catch (e) {
      if (e.name !== "AbortError") mostrarToast("Error de red", true);
    } finally {
      spinner(false);
    }
  }

  // ─── Guardar parámetros ───────────────────────────────────────────────
  async function guardar() {
    if (!puedeEditar) return;
    const bloques = leerFormulario();
    const resumen = ESTADO.fullPayload?.edificio?.totales || ESTADO.previewPayload?.envolvente || {};
    try {
      const resp = await fetch("/modulos/render-calculos/guardar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parametros: bloques, resumen }),
      });
      if (resp.status === 409) { mostrarToast("Crea o abre un proyecto primero", true); return; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al guardar", true);
        return;
      }
      mostrarToast("Guardado en el proyecto");
    } catch (e) { mostrarToast("Error de red", true); }
  }

  // ─── Export CSV ───────────────────────────────────────────────────────
  async function exportCsv() {
    const bloques = leerFormulario();
    try {
      const resp = await fetch("/modulos/render-calculos/export.csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parametros: bloques }),
      });
      if (!resp.ok) {
        mostrarToast("No se pudo exportar", true);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "puccetti_superficies.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { mostrarToast("Error de red", true); }
  }

  // ─── Tabs tabla derecha ───────────────────────────────────────────────
  document.querySelectorAll(".rc-tabla-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".rc-tabla-tab").forEach(t => {
        t.classList.remove("rc-tabla-tab-activo");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("rc-tabla-tab-activo");
      tab.setAttribute("aria-selected", "true");
      const tgt = tab.dataset.tab;
      document.getElementById("rc-tabla-planta-wrap").hidden = tgt !== "planta";
      document.getElementById("rc-tabla-unidad-wrap").hidden = tgt !== "unidad";
      document.getElementById("rc-tabla-anexo-wrap").hidden = tgt !== "anexo";
    });
  });

  // ─── Modal normativa ──────────────────────────────────────────────────
  if (btnNormativa && modal) {
    btnNormativa.addEventListener("click", () => {
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
    });
    document.getElementById("rc-modal-cerrar").addEventListener("click", () => modal.close());

    document.querySelectorAll(".rc-norm-item").forEach(b => {
      b.addEventListener("click", () => cargarNormativa(b.dataset.municipio, b.dataset.provincia));
    });
    document.getElementById("rc-norm-cargar").addEventListener("click", () => {
      const mun = document.getElementById("rc-norm-municipio").value.trim();
      const prov = document.getElementById("rc-norm-provincia").value.trim();
      if (mun && prov) cargarNormativa(mun, prov);
    });

    document.getElementById("rc-norm-aplicar").addEventListener("click", () => {
      aplicarNormativaAlForm();
      modal.close();
      mostrarToast("Normativa aplicada al proyecto");
      pedirPreview();
    });
    document.getElementById("rc-norm-guardar").addEventListener("click", guardarNormativaMunicipal);
  }

  async function cargarNormativa(mun, prov) {
    try {
      const resp = await fetch(`/modulos/render-calculos/normativa/${encodeURIComponent(prov)}/${encodeURIComponent(mun)}`);
      if (resp.ok) {
        const data = await resp.json();
        document.getElementById("rc-norm-municipio").value = mun;
        document.getElementById("rc-norm-provincia").value = prov;
        rellenarFormNormativa(data.urbanisticos);
      } else if (resp.status === 404) {
        document.getElementById("rc-norm-municipio").value = mun;
        document.getElementById("rc-norm-provincia").value = prov;
        rellenarFormNormativa(null);
      }
    } catch (e) { mostrarToast("Error al cargar normativa", true); }
  }

  function rellenarFormNormativa(urb) {
    const map = {
      "rc-norm-edif": urb?.edificabilidad_m2t_m2s ?? 2.5,
      "rc-norm-ocup": urb?.ocupacion_maxima_pct ?? 100,
      "rc-norm-plantas": urb?.n_plantas_max ?? 3,
      "rc-norm-altura": urb?.altura_planta_m ?? 3.0,
      "rc-norm-rfront": urb?.retranqueo_frontal_m ?? 0,
      "rc-norm-rlat": urb?.retranqueo_lateral_m ?? 0,
      "rc-norm-rtras": urb?.retranqueo_trasero_m ?? 0,
      "rc-norm-luz": urb?.luz_recta_patio_min_m ?? 3,
      "rc-norm-areapatio": urb?.area_patio_min_m2 ?? 12,
    };
    for (const id in map) {
      const el = document.getElementById(id);
      if (el) el.value = map[id];
    }
    const usos = (urb?.usos_permitidos || ["vivienda"]);
    document.getElementById("rc-norm-uso-viv").checked = usos.includes("vivienda");
    document.getElementById("rc-norm-uso-apt").checked = usos.includes("apartamentos_turisticos");
    document.getElementById("rc-norm-uso-hot").checked = usos.includes("hotelero");
  }

  function leerFormNormativa() {
    const usos = [];
    if (document.getElementById("rc-norm-uso-viv").checked) usos.push("vivienda");
    if (document.getElementById("rc-norm-uso-apt").checked) usos.push("apartamentos_turisticos");
    if (document.getElementById("rc-norm-uso-hot").checked) usos.push("hotelero");
    return {
      municipio: document.getElementById("rc-norm-municipio").value.trim(),
      provincia: document.getElementById("rc-norm-provincia").value.trim(),
      urbanisticos: {
        edificabilidad_m2t_m2s: parseFloat(document.getElementById("rc-norm-edif").value) || 2.5,
        ocupacion_maxima_pct: parseFloat(document.getElementById("rc-norm-ocup").value) || 100,
        n_plantas_max: parseInt(document.getElementById("rc-norm-plantas").value) || 3,
        altura_planta_m: parseFloat(document.getElementById("rc-norm-altura").value) || 3.0,
        retranqueo_frontal_m: parseFloat(document.getElementById("rc-norm-rfront").value) || 0,
        retranqueo_lateral_m: parseFloat(document.getElementById("rc-norm-rlat").value) || 0,
        retranqueo_trasero_m: parseFloat(document.getElementById("rc-norm-rtras").value) || 0,
        luz_recta_patio_min_m: parseFloat(document.getElementById("rc-norm-luz").value) || 3,
        area_patio_min_m2: parseFloat(document.getElementById("rc-norm-areapatio").value) || 12,
        usos_permitidos: usos,
      },
      fuente_pgou: document.getElementById("rc-norm-fuente").value,
    };
  }

  function aplicarNormativaAlForm() {
    const datos = leerFormNormativa();
    const urb = datos.urbanisticos;
    const map = {
      edificabilidad_m2t_m2s: urb.edificabilidad_m2t_m2s,
      ocupacion_maxima_pct: urb.ocupacion_maxima_pct,
      n_plantas_max: urb.n_plantas_max,
      altura_planta_m: urb.altura_planta_m,
      retranqueo_frontal_m: urb.retranqueo_frontal_m,
      retranqueo_lateral_m: urb.retranqueo_lateral_m,
      retranqueo_trasero_m: urb.retranqueo_trasero_m,
      luz_recta_patio_min_m: urb.luz_recta_patio_min_m,
      area_patio_min_m2: urb.area_patio_min_m2,
    };
    for (const k in map) {
      const inp = form.querySelector(`[name="${k}"]`);
      if (inp) inp.value = map[k];
    }
    form.querySelectorAll('[name="usos_permitidos"]').forEach(c => {
      c.checked = urb.usos_permitidos.includes(c.value);
    });
  }

  async function guardarNormativaMunicipal() {
    const datos = leerFormNormativa();
    if (!datos.municipio || !datos.provincia) {
      mostrarToast("Municipio y provincia son obligatorios", true); return;
    }
    try {
      const resp = await fetch(
        `/modulos/render-calculos/normativa/${encodeURIComponent(datos.provincia)}/${encodeURIComponent(datos.municipio)}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) }
      );
      if (resp.ok) mostrarToast("Normativa guardada");
      else mostrarToast("No se pudo guardar la normativa", true);
    } catch (e) { mostrarToast("Error de red", true); }
  }

  // ─── Bindings ─────────────────────────────────────────────────────────
  function calcularConDebounce() {
    if (ESTADO.debounceId) clearTimeout(ESTADO.debounceId);
    ESTADO.debounceId = setTimeout(pedirPreview, 250);
  }
  form.addEventListener("input", calcularConDebounce);
  form.addEventListener("change", calcularConDebounce);
  if (btnDistribuir) btnDistribuir.addEventListener("click", pedirCalculo);
  if (btnGuardar) btnGuardar.addEventListener("click", guardar);
  if (btnCsv) btnCsv.addEventListener("click", exportCsv);

  // Brújula inicial vacía
  if (window.RcBrujula) window.RcBrujula.dibujar(brujulaEl, []);

  // Si hay proyecto + parcela, primer preview automático
  if (estado === "ok") {
    pedirPreview();
  }
})();
