/* §2.9 — Viabilidad financiera (DCF). Sección independiente del cálculo de margen
   (`viabilidad.js`). Combina los parámetros de margen (#form-viabilidad) con los
   supuestos DCF (#form-dcf) y pinta escenarios, semáforo, precio máximo y sensibilidad. */
(function () {
  "use strict";
  const seccion = document.getElementById("vb-dcf");
  if (!seccion) return;
  const formMargen = document.getElementById("form-viabilidad");
  const formDcf = document.getElementById("form-dcf");
  if (!formMargen || !formDcf) return;
  const puedeEditar = seccion.dataset.puedeEditar === "true";

  const fmtEur = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
  const ESC_LABEL = { base: "Base", optimista: "Optimista", estres: "Estrés" };
  const LUZ_LABEL = { verde: "Viable", ambar: "Ajustado", rojo: "No viable", sin_dato: "Sin datos" };
  const METRICA_LABEL = { tir: "TIR", payback: "Payback", yield: "Yield", capex_hab: "CAPEX/hab" };
  const DRIVER_LABEL = { precio_compra: "Precio compra", capex: "CAPEX", ingreso: "Ingreso" };

  const num = (v) => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };
  const fmtTir = (x) => (x == null ? "—" : (x * 100).toFixed(1) + " %");

  // ── Serialización del payload (margen + DCF) ──────────────────────────────
  function margenPayload() {
    const d = Object.fromEntries(new FormData(formMargen).entries());
    if (d.ocupacion_anual_pct !== undefined) d.ocupacion_anual_pct = num(d.ocupacion_anual_pct) / 100;
    if (d.pct_costes_indirectos_pct !== undefined) {
      d.pct_costes_indirectos = num(d.pct_costes_indirectos_pct) / 100;
      delete d.pct_costes_indirectos_pct;
    }
    return d;
  }

  function escenariosPayload(s) {
    const f = (esc, c) => num(s[esc + "_factor_" + c]) || 1;
    return [
      { escenario: "base", factor_precio: 1, factor_capex: 1, factor_ingreso: 1 },
      { escenario: "optimista", factor_precio: f("optimista", "precio"), factor_capex: f("optimista", "capex"), factor_ingreso: f("optimista", "ingreso") },
      { escenario: "estres", factor_precio: f("estres", "precio"), factor_capex: f("estres", "capex"), factor_ingreso: f("estres", "ingreso") },
    ];
  }

  function payload() {
    const s = Object.fromEntries(new FormData(formDcf).entries());
    return Object.assign({}, margenPayload(), {
      tipologia: s.tipologia,
      dcf: {
        supuestos: {
          horizonte_anios: num(s.horizonte_anios),
          periodo_obra_anios: num(s.periodo_obra_anios),
          tasa_descuento_anual: num(s.tasa_descuento_pct) / 100,
          exit_cap_rate: num(s.exit_cap_rate_pct) / 100,
          tir_objetivo: num(s.tir_objetivo_pct) / 100,
          escenarios: escenariosPayload(s),
        },
        financiacion: {},
        benchmarks: {
          revpar_eur: num(s.revpar_eur),
          adr_eur: num(s.adr_eur),
          yield_comparable: num(s.yield_comparable_pct) / 100,
          fuente: s.fuente || "",
        },
      },
    });
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const fila = (dt, dd) => "<div><dt>" + dt + "</dt><dd>" + dd + "</dd></div>";

  function renderEscenarios(estudio) {
    const cont = document.getElementById("dcf-escenarios");
    cont.innerHTML = "";
    (estudio.escenarios || []).forEach((e) => {
      const card = document.createElement("article");
      card.className = "vb-card card vb-escenario vb-escenario--" + e.escenario;
      card.innerHTML =
        '<header class="vb-card-h"><h3 class="eyebrow">' + (ESC_LABEL[e.escenario] || e.escenario) + "</h3></header>" +
        '<dl class="dl-ficha vb-dl-desglose">' +
        fila("TIR", fmtTir(e.tir)) +
        fila("MOIC", e.moic ? e.moic.toFixed(2) + "×" : "—") +
        fila("Payback", e.payback_anios == null ? "—" : e.payback_anios.toFixed(1) + " años") +
        fila("VAN", fmtEur.format(e.van_eur) + " €") +
        fila("Capital", fmtEur.format(e.capital_necesario_eur) + " €") +
        "</dl>";
      cont.appendChild(card);
    });
  }

  function renderSemaforo(sem) {
    const luz = seccion.querySelector("[data-luz]");
    const txt = seccion.querySelector("[data-semaforo-txt]");
    const met = seccion.querySelector("[data-semaforo-metricas]");
    const g = (sem && sem.global) || "sin_dato";
    luz.className = "vb-luz vb-luz--" + g;
    txt.textContent = LUZ_LABEL[g] || g;
    met.innerHTML = "";
    const pm = (sem && sem.por_metrica) || {};
    Object.keys(pm).forEach((k) => {
      const chip = document.createElement("span");
      chip.className = "vb-chip vb-chip--" + pm[k];
      chip.textContent = METRICA_LABEL[k] || k;
      met.appendChild(chip);
    });
  }

  function renderAvisos(estudio) {
    const box = document.getElementById("dcf-avisos");
    const ul = box.querySelector("ul");
    const avisos = new Set(estudio.avisos || []);
    (estudio.escenarios || []).forEach((e) => (e.avisos || []).forEach((a) => avisos.add(a)));
    ul.innerHTML = "";
    if (avisos.size) {
      avisos.forEach((a) => { const li = document.createElement("li"); li.textContent = a; ul.appendChild(li); });
      box.classList.remove("vb-oculto");
    } else {
      box.classList.add("vb-oculto");
    }
  }

  function pintar(estudio, sem) {
    renderEscenarios(estudio);
    if (sem) renderSemaforo(sem);
    renderAvisos(estudio);
    if (estudio.precio_maximo_compra_eur != null) {
      seccion.querySelector("[data-precio-max]").textContent = fmtEur.format(estudio.precio_maximo_compra_eur) + " €";
    }
  }

  function initFactores(estudio) {
    const escs = (estudio.supuestos && estudio.supuestos.escenarios) || [];
    escs.forEach((e) => {
      if (e.escenario === "base") return;
      ["precio", "capex", "ingreso"].forEach((c) => {
        const inp = formDcf.querySelector('[name="' + e.escenario + "_factor_" + c + '"]');
        if (inp) inp.value = e["factor_" + c];
      });
    });
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  const toast = document.getElementById("dcf-toast");
  let toastId;
  function mostrarToast(msg, err) {
    toast.textContent = msg;
    toast.classList.toggle("toast--error", !!err);
    toast.classList.add("toast--on");
    clearTimeout(toastId);
    toastId = setTimeout(() => toast.classList.remove("toast--on"), 2600);
  }

  async function postJson(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  // ── Acciones ────────────────────────────────────────────────────────────────
  async function calcular() {
    if (!puedeEditar) return;
    try {
      const resp = await postJson("/modulos/viabilidad/calcular-dcf", payload());
      if (!resp.ok) return mostrarToast("Error al calcular", true);
      const data = await resp.json();
      pintar(data.estudio_dcf, data.semaforo);
    } catch (e) { mostrarToast("Error de red al calcular", true); }
  }

  async function guardar() {
    if (!puedeEditar) return;
    try {
      const resp = await postJson("/modulos/viabilidad/guardar-dcf", payload());
      if (resp.status === 409) return mostrarToast("Necesitas un proyecto activo para guardar", true);
      if (!resp.ok) return mostrarToast("Error al guardar", true);
      const data = await resp.json();
      pintar(data.estudio_dcf, data.semaforo);
      mostrarToast("Guardado.");
    } catch (e) { mostrarToast("Error de red al guardar", true); }
  }

  async function precioMax() {
    if (!puedeEditar) return;
    const resp = await postJson("/modulos/viabilidad/precio-maximo", payload());
    if (!resp.ok) return mostrarToast("Error", true);
    const data = await resp.json();
    seccion.querySelector("[data-precio-max]").textContent =
      data.precio_maximo_compra_eur == null
        ? "No calculable (revisa horizonte, periodo de obra y TIR objetivo)"
        : fmtEur.format(data.precio_maximo_compra_eur) + " €";
  }

  async function sensibilidad() {
    if (!puedeEditar) return;
    const resp = await postJson("/modulos/viabilidad/sensibilidad", payload());
    if (!resp.ok) return mostrarToast("Error", true);
    const data = await resp.json();
    const box = document.getElementById("dcf-sensibilidad");
    let html = '<table class="vb-tabla-sens"><thead><tr><th>Variable</th><th>−Δ</th><th>Base</th><th>+Δ</th></tr></thead><tbody>';
    (data.drivers || []).forEach((d) => {
      html += "<tr><td>" + (DRIVER_LABEL[d.driver] || d.driver) + "</td><td>" + fmtTir(d.tir_abajo) +
        "</td><td>" + fmtTir(data.base_tir) + "</td><td>" + fmtTir(d.tir_arriba) + "</td></tr>";
    });
    html += "</tbody></table>";
    box.innerHTML = html;
    box.classList.remove("vb-oculto");
  }

  async function guardarUmbrales() {
    const formU = document.getElementById("form-umbrales");
    if (!formU) return;
    const s = Object.fromEntries(new FormData(formU).entries());
    const body = {
      tir_min_btr_residencial: num(s.tir_min_btr_residencial) / 100,
      tir_min_hotelero: num(s.tir_min_hotelero) / 100,
      tir_min_rehab_intensiva: num(s.tir_min_rehab_intensiva) / 100,
      yield_neto_minimo: num(s.yield_neto_minimo) / 100,
      yield_objetivo: num(s.yield_objetivo) / 100,
      payback_maximo_anios: num(s.payback_maximo_anios),
      capex_maximo_hab_eur: num(s.capex_maximo_hab_eur),
    };
    const resp = await postJson("/modulos/viabilidad/umbrales", body);
    if (!resp.ok) return mostrarToast("No autorizado o error al guardar umbrales", true);
    mostrarToast("Umbrales guardados. Recalcula para aplicar el semáforo.");
  }

  // ── Bindings ────────────────────────────────────────────────────────────────
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener("click", fn); };
  on("btn-calcular-dcf", calcular);
  on("btn-guardar-dcf", guardar);
  on("btn-precio-max", precioMax);
  on("btn-sensibilidad", sensibilidad);
  on("btn-guardar-umbrales", guardarUmbrales);
  on("btn-onepager", () => window.print());

  // ── Arranque: hidrata desde las islas JSON ──────────────────────────────────
  try {
    const estudio = JSON.parse(document.getElementById("dcf-datos").textContent);
    const sem = JSON.parse(document.getElementById("dcf-semaforo-datos").textContent);
    initFactores(estudio);
    pintar(estudio, sem);
  } catch (e) {
    /* islas ausentes: sección sin datos iniciales */
  }
})();
