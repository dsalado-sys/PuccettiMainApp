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
    const cap = payload?.capacidad;
    const parcelaArea = payload?.parcela?.area_m2;
    // Fuente de verdad iter. 4: data.capacidad. Fallback a envolvente del preview.
    if (cap) {
      set("construida_total_m2", fmt.m2.format(cap.construida_total_m2) + " m²");
      set("superficie_parcela_m2", fmt.m2.format(cap.superficie_parcela_m2) + " m²");
      set("edificabilidad_m2", fmt.m2.format(cap.edificabilidad_m2) + " m²");
      set("n_viviendas", fmt.int.format(cap.n_viviendas_objetivo));
    } else if (env) {
      set("construida_total_m2", fmt.m2.format(env.edificabilidad_consumida_m2) + " m²");
      set("superficie_parcela_m2", fmt.m2.format(parcelaArea ?? 0) + " m²");
      set("edificabilidad_m2", fmt.m2.format(env.edificabilidad_max_m2) + " m²");
      set("n_viviendas", fmt.int.format(env.n_viviendas_objetivo) + " obj.");
    }
  }

  // ─── Tabs de planta ───────────────────────────────────────────────────
  function dibujarTabsPlantas(payload) {
    if (!tabsPlantasEl) return;
    let plantas = [];
    // Iter. 3: edificio normalmente null; usamos envolvente.plantas.
    if (payload?.edificio?.plantas?.length) plantas = payload.edificio.plantas;
    else if (payload?.envolvente?.plantas?.length) plantas = payload.envolvente.plantas;

    if (!plantas.length) {
      tabsPlantasEl.innerHTML = '<span class="rc-tab rc-tab-vacio">Pulsa «Calcular capacidad» o cambia un parámetro para empezar.</span>';
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

  // ─── Tabla por planta (iter. 4 — desglose muros/circulación/núcleo) ────
  function repintarTablaPlanta(filas) {
    if (!tablaPlantaBody) return;
    tablaPlantaBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaPlantaBody.innerHTML = '<tr><td colspan="7" class="rc-vacio">Sin datos. Calcula la capacidad.</td></tr>';
      return;
    }
    const tot = { c: 0, u: 0, mur: 0, circ: 0, nuc: 0, viv: 0 };
    filas.forEach(r => {
      tot.c += r.construida_m2 || 0;
      tot.u += r.util_viviendas_m2 || 0;
      tot.mur += r.muros_m2 || 0;
      tot.circ += r.circulacion_m2 || 0;
      tot.nuc += r.nucleo_m2 || 0;
      tot.viv += r.viviendas || 0;
      const tr = document.createElement("tr");
      const tipo = r.tipo || "regular";
      tr.className = "rc-fila-tipo-" + tipo;
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td>${fmt.int.format(r.viviendas)}</td>
        <td>${fmt.m2.format(r.construida_m2)}</td>
        <td>${fmt.m2.format(r.util_viviendas_m2)}</td>
        <td>${fmt.m2.format(r.muros_m2 || 0)}</td>
        <td>${fmt.m2.format(r.circulacion_m2 || 0)}</td>
        <td>${fmt.m2.format(r.nucleo_m2 || 0)}</td>`;
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
      <td>${fmt.m2.format(tot.mur)}</td>
      <td>${fmt.m2.format(tot.circ)}</td>
      <td>${fmt.m2.format(tot.nuc)}</td>`;
    tablaPlantaBody.appendChild(trTot);
  }

  function repintarTablaUnidad(filas) {
    if (!tablaUnidadBody) return;
    tablaUnidadBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaUnidadBody.innerHTML = '<tr><td colspan="7" class="rc-vacio">Sin unidades calculadas.</td></tr>';
      if (tablaAnexoWrap) {
        tablaAnexoWrap.innerHTML = '<p class="rc-vacio">Sin datos.</p>';
      }
      return;
    }
    filas.forEach(r => {
      const tr = document.createElement("tr");
      tr.className = "rc-fila-unidad-clicable";
      tr.dataset.id = r.vivienda;
      tr.dataset.planta = r.planta;
      tr.dataset.tipo = r.tipo || "vivienda";
      tr.dataset.dorms = r.dorms;
      tr.dataset.adaptada = r.adaptada ? "1" : "0";
      tr.dataset.construida = r.construida_por_unidad_m2 ?? 0;
      tr.dataset.util = r.util_por_unidad_m2 ?? 0;
      tr.dataset.muros = r.muros_por_unidad_m2 ?? 0;
      tr.dataset.circulacion = r.circulacion_por_unidad_m2 ?? 0;
      tr.dataset.estancias = JSON.stringify(r.estancias || []);
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td>${r.vivienda}</td>
        <td>${r.dorms}</td>
        <td>${r.tipo || "vivienda"}</td>
        <td>${fmt.m2.format(r.construida_por_unidad_m2 ?? 0)}</td>
        <td>${fmt.m2.format(r.util_por_unidad_m2 ?? 0)}</td>
        <td>${r.adaptada ? "✓" : "—"}</td>`;
      tr.addEventListener("click", () => abrirModalUnidad(tr));
      tablaUnidadBody.appendChild(tr);
    });
    if (tablaAnexoWrap) {
      tablaAnexoWrap.innerHTML = '<p class="rc-vacio">Anexo I aplicado al cálculo. Revisa las alertas del banner para incidencias.</p>';
    }
  }

  // ─── Modal "detalle de unidad" ─────────────────────────────────────────
  function abrirModalUnidad(tr) {
    const modalEl = document.getElementById("rc-modal-unidad");
    if (!modalEl) return;
    const ds = tr.dataset;
    const setT = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };

    setT("rc-mu-id", ds.id || "—");
    setT("rc-mu-planta", ds.planta || "—");
    setT("rc-mu-tipo", ds.tipo || "—");
    setT("rc-mu-dorms", ds.dorms || "—");
    setT("rc-mu-adapt", ds.adaptada === "1" ? "Sí" : "No");
    setT("rc-mu-construida", fmt.m2.format(parseFloat(ds.construida || 0)) + " m²");
    setT("rc-mu-util", fmt.m2.format(parseFloat(ds.util || 0)) + " m²");
    setT("rc-mu-muros", fmt.m2.format(parseFloat(ds.muros || 0)) + " m²");
    setT("rc-mu-circulacion", fmt.m2.format(parseFloat(ds.circulacion || 0)) + " m²");

    let estancias = [];
    try { estancias = JSON.parse(ds.estancias || "[]"); } catch (e) { estancias = []; }
    const ul = document.getElementById("rc-mu-estancias-lista");
    if (ul) {
      ul.innerHTML = "";
      if (!estancias.length) {
        ul.innerHTML = '<li class="rc-vacio">Sin programa de estancias para esta unidad.</li>';
      } else {
        estancias.forEach(e => {
          const li = document.createElement("li");
          li.className = "rc-mu-estancia rc-mu-estancia-" + (e.categoria || "");
          li.innerHTML = `<span class="rc-mu-est-nombre">${e.nombre}</span>
            <span class="rc-mu-est-cat">${e.categoria || ""}</span>
            <span class="rc-mu-est-m2">${fmt.m2.format(e.area_target_m2)} m²</span>`;
          ul.appendChild(li);
        });
      }
    }
    const totalEst = estancias.reduce((acc, e) => acc + (e.area_target_m2 || 0), 0);
    setT("rc-mu-total-estancias", fmt.m2.format(totalEst) + " m²");

    if (typeof modalEl.showModal === "function") modalEl.showModal();
    else modalEl.setAttribute("open", "");
  }

  const btnModalUnidadCerrar = document.getElementById("rc-modal-unidad-cerrar");
  if (btnModalUnidadCerrar) {
    btnModalUnidadCerrar.addEventListener("click", () => {
      const m = document.getElementById("rc-modal-unidad");
      if (m && m.close) m.close();
    });
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
      // Iter. 3: edificio = null. Usamos envolvente.plantas para los tabs.
      const n_plantas = (data.envolvente?.plantas?.length) || (data.edificio?.plantas?.length) || 1;
      ESTADO.plantaActiva = Math.min(ESTADO.plantaActiva, n_plantas - 1);
      dibujarTabsPlantas(data);
      renderer.dibujar(data, ESTADO.plantaActiva);
      actualizarBrujula(data);
      repintarKpis(data);
      repintarAlertas(data.alertas);
      repintarTablaPlanta(data.tabla_planta);
      repintarTablaUnidad(data.tabla_unidad);
      mostrarToast("Capacidad calculada");
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
    // Iter. 3: el resumen ahora viene de data.capacidad (no de edificio.totales).
    const resumen = ESTADO.fullPayload?.capacidad
      || ESTADO.fullPayload?.edificio?.totales
      || ESTADO.previewPayload?.envolvente
      || {};
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
      "rc-norm-coef": urb?.coeficiente_edificabilidad ?? urb?.edificabilidad_m2t_m2s ?? 2.5,
      "rc-norm-ocup": urb?.ocupacion_maxima_pct ?? 100,
      "rc-norm-plantas": urb?.n_plantas_max ?? 3,
      "rc-norm-rfach": urb?.retranqueo_fachada_m ?? 0,
      "rc-norm-rlind": urb?.retranqueo_linderos_m ?? 0,
      "rc-norm-luz": urb?.luz_recta_patio_min_m ?? 3,
      "rc-norm-areapatio": urb?.area_patio_min_m2 ?? 12,
    };
    for (const id in map) {
      const el = document.getElementById(id);
      if (el) el.value = map[id];
    }
    const usos = (urb?.usos_permitidos || ["residencial"]);
    const setUso = (id, val) => { const e = document.getElementById(id); if (e) e.checked = usos.includes(val); };
    setUso("rc-norm-uso-resi", "residencial");
    setUso("rc-norm-uso-hot", "hotelero");
    setUso("rc-norm-uso-terc", "terciario");
    setUso("rc-norm-uso-mixto", "mixto");
  }

  function leerFormNormativa() {
    const usos = [];
    const getUso = (id, val) => { const e = document.getElementById(id); if (e && e.checked) usos.push(val); };
    getUso("rc-norm-uso-resi", "residencial");
    getUso("rc-norm-uso-hot", "hotelero");
    getUso("rc-norm-uso-terc", "terciario");
    getUso("rc-norm-uso-mixto", "mixto");
    const valof = (id, def) => {
      const e = document.getElementById(id);
      return e ? (parseFloat(e.value) || def) : def;
    };
    return {
      municipio: document.getElementById("rc-norm-municipio").value.trim(),
      provincia: document.getElementById("rc-norm-provincia").value.trim(),
      urbanisticos: {
        coeficiente_edificabilidad: valof("rc-norm-coef", 2.5),
        ocupacion_maxima_pct: valof("rc-norm-ocup", 100),
        n_plantas_max: parseInt(document.getElementById("rc-norm-plantas").value) || 3,
        retranqueo_fachada_m: valof("rc-norm-rfach", 0),
        retranqueo_linderos_m: valof("rc-norm-rlind", 0),
        luz_recta_patio_min_m: valof("rc-norm-luz", 3),
        area_patio_min_m2: valof("rc-norm-areapatio", 12),
        usos_permitidos: usos,
      },
      fuente_pgou: document.getElementById("rc-norm-fuente").value,
    };
  }

  function aplicarNormativaAlForm() {
    const datos = leerFormNormativa();
    const urb = datos.urbanisticos;
    const map = {
      coeficiente_edificabilidad: urb.coeficiente_edificabilidad,
      ocupacion_maxima_pct: urb.ocupacion_maxima_pct,
      n_plantas_max: urb.n_plantas_max,
      retranqueo_fachada_m: urb.retranqueo_fachada_m,
      retranqueo_linderos_m: urb.retranqueo_linderos_m,
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

  // ─── Visibilidad de campos según uso (vivienda/apartamentos) ──────────
  function aplicarVisibilidadPorUso() {
    const sel = form.querySelector('select[name="uso"]');
    const usoActivo = sel ? sel.value : "vivienda";
    form.querySelectorAll("[data-cuando-uso]").forEach(el => {
      const usos = el.dataset.cuandoUso.split(/\s+/);
      el.hidden = !usos.includes(usoActivo);
    });
  }

  // ─── Bindings ─────────────────────────────────────────────────────────
  function calcularConDebounce() {
    aplicarVisibilidadPorUso();
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

  aplicarVisibilidadPorUso();

  // Toggle visual del input "coeficiente" según el checkbox "usar coef".
  const chkUsarCoef = document.getElementById("rc-chk-usar-coef");
  const inpCoef = document.getElementById("rc-input-coef");
  function aplicarToggleCoef() {
    if (!chkUsarCoef || !inpCoef) return;
    inpCoef.disabled = !chkUsarCoef.checked;
  }
  if (chkUsarCoef) chkUsarCoef.addEventListener("change", aplicarToggleCoef);
  aplicarToggleCoef();

  // Si hay proyecto + parcela, primer preview automático
  if (estado === "ok") {
    pedirPreview();
  }
})();
