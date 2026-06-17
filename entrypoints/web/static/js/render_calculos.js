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

  function usoActivoForm() {
    const sel = form.querySelector('select[name="uso"]');
    return sel ? sel.value : "vivienda";
  }

  // ─── Lectura del formulario → payload backend ─────────────────────────
  function leerFormulario() {
    const bloques = {
      urbanisticos: {}, diseno: {}, programa: {},
      diseno_tipo: {}, diseno_atico: {}, diseno_sotano: {}, programa_tipo: {},
    };
    const usoActivo = usoActivoForm();
    const inputs = form.querySelectorAll("[data-bloque]");
    inputs.forEach(inp => {
      // Los bloques de otro USO no entran al payload (cada uso tiene su categoría
      // y su lista de extras). En cambio, los campos ocultos por PLANTA SÍ se leen:
      // cada categoría de planta (pb/tipo/atico/sotano) tiene su propio valor que
      // debe persistir aunque la pestaña activa no lo muestre.
      const bloqueUso = inp.closest("[data-cuando-uso]");
      if (bloqueUso && !bloqueUso.dataset.cuandoUso.split(/\s+/).includes(usoActivo)) return;
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
        if (nombre === "tipologias_extra") {
          if (!Array.isArray(bloques[bloque].tipologias_extra)) {
            bloques[bloque].tipologias_extra = [];
          }
          if (inp.value) bloques[bloque].tipologias_extra.push(inp.value);
        } else {
          bloques[bloque][nombre] = inp.value;
        }
      } else {
        const valor = inp.value === "" ? null : (inp.type === "number" ? Number(inp.value) : inp.value);
        bloques[bloque][nombre] = valor;
      }
    });
    // Aseguramos que los arrays existan aunque ninguna casilla esté marcada
    if (!bloques.urbanisticos.usos_permitidos) bloques.urbanisticos.usos_permitidos = [];
    if (!bloques.programa.tipologias_extra) bloques.programa.tipologias_extra = [];
    if (!bloques.programa_tipo.tipologias_extra) bloques.programa_tipo.tipologias_extra = [];
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
        aplicarVisibilidad(payload);
      });
      tabsPlantasEl.appendChild(b);
    });
    aplicarVisibilidad(payload);
  }

  // ─── Tabla por planta (iter. 4 — desglose muros/circulación/núcleo) ────
  function repintarTablaPlanta(filas) {
    if (!tablaPlantaBody) return;
    tablaPlantaBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaPlantaBody.innerHTML = '<tr><td colspan="10" class="rc-vacio">Sin datos. Calcula la capacidad.</td></tr>';
      return;
    }
    const tot = { c: 0, u: 0, mur: 0, murEst: 0, circ: 0, nuc: 0, pat: 0, loc: 0, viv: 0 };
    filas.forEach(r => {
      tot.c += r.construida_m2 || 0;
      tot.u += r.util_viviendas_m2 || 0;
      tot.mur += r.muros_m2 || 0;
      tot.murEst += r.muros_estimados_m2 || 0;
      tot.circ += r.circulacion_m2 || 0;
      tot.nuc += r.nucleo_m2 || 0;
      tot.pat += r.patios_m2 || 0;
      tot.loc += r.local_m2 || 0;
      tot.viv += r.viviendas || 0;
      const tr = document.createElement("tr");
      const tipo = r.tipo || "regular";
      tr.className = "rc-fila-tipo-" + tipo;
      const mixStr = r.mix_tipologia && Object.keys(r.mix_tipologia).length
        ? " title=\"" + Object.entries(r.mix_tipologia).map(([k, v]) => `${v}×${/^\d+$/.test(k) ? k + "d" : k}`).join(", ") + "\""
        : "";
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td${mixStr}>${fmt.int.format(r.viviendas)}</td>
        <td>${fmt.m2.format(r.construida_m2)}</td>
        <td>${fmt.m2.format(r.util_viviendas_m2)}</td>
        <td>${fmt.m2.format(r.muros_m2 || 0)}</td>
        <td>${fmt.m2.format(r.muros_estimados_m2 || 0)}</td>
        <td>${fmt.m2.format(r.circulacion_m2 || 0)}</td>
        <td>${fmt.m2.format(r.nucleo_m2 || 0)}</td>
        <td>${fmt.m2.format(r.patios_m2 || 0)}</td>
        <td>${fmt.m2.format(r.local_m2 || 0)}</td>`;
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
      <td>${fmt.m2.format(tot.murEst)}</td>
      <td>${fmt.m2.format(tot.circ)}</td>
      <td>${fmt.m2.format(tot.nuc)}</td>
      <td>${fmt.m2.format(tot.pat)}</td>
      <td>${fmt.m2.format(tot.loc)}</td>`;
    tablaPlantaBody.appendChild(trTot);
  }

  // Etiqueta legible de una tipología (busca en todos los conjuntos de opciones).
  function _labelTipologia(slug) {
    if (!slug) return null;
    for (const set of Object.values(OPCIONES_TIPOLOGIA)) {
      if (set[slug]) return set[slug];
    }
    return slug;
  }

  function repintarTablaUnidad(filas) {
    if (!tablaUnidadBody) return;
    tablaUnidadBody.innerHTML = "";
    if (!filas || !filas.length) {
      tablaUnidadBody.innerHTML = '<tr><td colspan="7" class="rc-vacio">Sin unidades calculadas.</td></tr>';
      return;
    }
    filas.forEach(r => {
      const tr = document.createElement("tr");
      const esLocal = r.tipo === "local";
      tr.className = esLocal ? "rc-fila-unidad-local" : "rc-fila-unidad-clicable";
      tr.dataset.id = r.vivienda;
      tr.dataset.planta = r.planta;
      tr.dataset.tipo = r.tipo || "vivienda";
      tr.dataset.dorms = r.dorms;
      tr.dataset.tipologia = r.tipologia || "";
      tr.dataset.adaptada = r.adaptada ? "1" : "0";
      tr.dataset.construida = r.construida_por_unidad_m2 ?? 0;
      tr.dataset.util = r.util_por_unidad_m2 ?? 0;
      tr.dataset.circ = r.circulacion_interior_por_unidad_m2 ?? 0;
      tr.dataset.muros = r.muros_por_unidad_m2 ?? 0;
      tr.dataset.estancias = JSON.stringify(r.estancias || []);
      const utilCelda = esLocal
        ? `${fmt.m2.format(r.util_por_unidad_m2 ?? 0)} <small>(${fmt.pct.format(r.pct_util_destinado ?? 0)}% útil)</small>`
        : fmt.m2.format(r.util_por_unidad_m2 ?? 0);
      // En vivienda la columna muestra nº de dormitorios; en el resto, la tipología.
      const dormsCelda = (r.tipo && r.tipo !== "vivienda" && r.tipologia)
        ? _labelTipologia(r.tipologia)
        : r.dorms;
      tr.innerHTML = `
        <td>${r.planta}</td>
        <td>${r.vivienda}</td>
        <td>${dormsCelda}</td>
        <td>${r.tipo || "vivienda"}</td>
        <td>${fmt.m2.format(r.construida_por_unidad_m2 ?? 0)}</td>
        <td>${utilCelda}</td>
        <td>${r.adaptada ? "✓" : "—"}</td>`;
      if (!esLocal) tr.addEventListener("click", () => abrirModalUnidad(tr));
      tablaUnidadBody.appendChild(tr);
    });
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
    const dormsLabel = (ds.tipo && ds.tipo !== "vivienda" && ds.tipologia)
      ? _labelTipologia(ds.tipologia)
      : (ds.dorms || "—");
    setT("rc-mu-dorms", dormsLabel);
    setT("rc-mu-adapt", ds.adaptada === "1" ? "Sí" : "No");
    setT("rc-mu-construida", fmt.m2.format(parseFloat(ds.construida || 0)) + " m²");
    setT("rc-mu-util", fmt.m2.format(parseFloat(ds.util || 0)) + " m²");
    setT("rc-mu-circ", fmt.m2.format(parseFloat(ds.circ || 0)) + " m²");
    setT("rc-mu-muros", fmt.m2.format(parseFloat(ds.muros || 0)) + " m²");

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
          const warn = (e.cabe_diametro === false)
            ? `<span class="rc-mu-est-warn" title="No cabe Ø ${e.diametro_min_m} m">⚠</span>`
            : "";
          if (e.cabe_diametro === false) li.classList.add("rc-mu-estancia-warn");
          li.innerHTML = `${warn}<span class="rc-mu-est-nombre">${e.nombre}</span>
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

  // ─── Alertas — agrupadas por regla en acordeón ────────────────────────
  const NIVEL_PESO = { error: 0, aviso: 1, info: 2 };
  function repintarAlertas(alertas) {
    if (!alertasBox || !alertasUl) return;
    if (!alertas || !alertas.length) {
      alertasBox.hidden = true;
      alertasUl.innerHTML = "";
      return;
    }
    alertasBox.hidden = false;
    alertasUl.innerHTML = "";

    const grupos = new Map();
    alertas.forEach(a => {
      const key = a.regla || "general";
      if (!grupos.has(key)) grupos.set(key, []);
      grupos.get(key).push(a);
    });

    const reglas = Array.from(grupos.keys()).sort((a, b) => {
      const pa = Math.min(...grupos.get(a).map(x => NIVEL_PESO[x.nivel] ?? 1));
      const pb = Math.min(...grupos.get(b).map(x => NIVEL_PESO[x.nivel] ?? 1));
      return pa - pb;
    });

    reglas.forEach(regla => {
      const items = grupos.get(regla);
      const nivelTop = items.reduce(
        (acc, x) => (NIVEL_PESO[x.nivel] ?? 1) < (NIVEL_PESO[acc] ?? 1) ? x.nivel : acc,
        "info"
      );
      const li = document.createElement("li");
      li.className = "rc-alerta-grupo rc-alerta-" + nivelTop;

      if (items.length === 1) {
        const span = document.createElement("span");
        span.className = "rc-alerta-regla";
        span.textContent = regla;
        li.appendChild(span);
        li.appendChild(document.createTextNode(items[0].mensaje));
      } else {
        const det = document.createElement("details");
        det.className = "rc-alerta-detalles";
        const sum = document.createElement("summary");
        sum.innerHTML = `<span class="rc-alerta-regla">${regla}</span>
          <span class="rc-alerta-contador">${items.length} avisos</span>`;
        det.appendChild(sum);
        const ul = document.createElement("ul");
        ul.className = "rc-alerta-sublista";
        items.forEach(a => {
          const sli = document.createElement("li");
          sli.className = "rc-alerta-" + a.nivel;
          sli.textContent = a.mensaje;
          ul.appendChild(sli);
        });
        det.appendChild(ul);
        li.appendChild(det);
      }
      alertasUl.appendChild(li);
    });
  }

  function actualizarBrujula(payload) {
    if (!window.RcBrujula || !brujulaEl) return;
    const ind = payload?.indicadores;
    window.RcBrujula.dibujar(brujulaEl, ind ? ind.orientaciones_fachadas : []);
  }

  // ─── Fetch /preview (rápido) ──────────────────────────────────────────
  function payloadConNormativa(bloques) {
    if (ESTADO_NORM.aplicada && ESTADO_NORM.aplicada.urbanisticos) {
      return { ...bloques, normativa_referencia: { urbanisticos: ESTADO_NORM.aplicada.urbanisticos } };
    }
    return bloques;
  }

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
        body: JSON.stringify(payloadConNormativa(bloques)),
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
        body: JSON.stringify(payloadConNormativa(bloques)),
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

  // ─── Modal "Elegir normativa a aplicar" ───────────────────────────────
  // Render ya NO gestiona carpetas/normativas (eso vive en /modulos/normativa-municipal).
  // Aquí solo se elige una normativa archivada y se inyecta al form del proyecto.
  const API_NORM = "/modulos/normativa-municipal";
  const ESTADO_NORM = { carpetas: [], filtro: "", seleccionada: null, aplicada: null };

  if (btnNormativa && modal) {
    btnNormativa.addEventListener("click", () => {
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
      ocultarResumenNormativa();
      refrescarCarpetasNormativa();
    });
    document.getElementById("rc-modal-cerrar").addEventListener("click", () => modal.close());

    document.getElementById("rc-norm-aplicar").addEventListener("click", () => {
      if (!ESTADO_NORM.seleccionada) {
        mostrarToast("Selecciona una normativa primero", true); return;
      }
      aplicarNormativaAlProyecto(ESTADO_NORM.seleccionada);
    });

    const inpBuscar = document.getElementById("rc-carpeta-buscar");
    if (inpBuscar) inpBuscar.addEventListener("input", () => {
      ESTADO_NORM.filtro = inpBuscar.value.trim();
      repintarCarpetasNormativa();
    });
  }

  async function refrescarCarpetasNormativa() {
    try {
      const resp = await fetch(`${API_NORM}/carpetas`);
      if (!resp.ok) return;
      const data = await resp.json();
      ESTADO_NORM.carpetas = data.carpetas || [];
      repintarCarpetasNormativa();
    } catch (e) { /* silencioso */ }
  }

  function repintarCarpetasNormativa() {
    const cont = document.getElementById("rc-carpetas-lista");
    if (!cont) return;
    const filtro = (ESTADO_NORM.filtro || "").toLowerCase();
    const items = filtro
      ? ESTADO_NORM.carpetas.filter(c => c.nombre.toLowerCase().includes(filtro))
      : ESTADO_NORM.carpetas;
    cont.innerHTML = "";
    if (!items.length) {
      cont.innerHTML = filtro
        ? '<p class="rc-vacio">Ninguna carpeta coincide.</p>'
        : '<p class="rc-vacio">Aún no hay carpetas. Crea normativas en el módulo «Normativa municipal».</p>';
      return;
    }
    for (const c of items) {
      const det = document.createElement("details");
      det.className = "rc-carpeta";
      det.dataset.id = c.id;
      const sum = document.createElement("summary");
      sum.innerHTML = `<span class="rc-carpeta-nombre">${c.nombre}</span>`;
      det.appendChild(sum);
      const ul = document.createElement("ul");
      ul.className = "rc-carpeta-normativas";
      ul.innerHTML = '<li class="rc-vacio">Cargando…</li>';
      det.appendChild(ul);
      det.addEventListener("toggle", () => {
        if (det.open) cargarNormativasParaSeleccion(c.id, ul);
      });
      cont.appendChild(det);
    }
  }

  async function cargarNormativasParaSeleccion(carpetaId, ul) {
    try {
      const resp = await fetch(`${API_NORM}/carpetas/${carpetaId}/normativas`);
      if (!resp.ok) { ul.innerHTML = '<li class="rc-vacio">Error.</li>'; return; }
      const data = await resp.json();
      const items = data.normativas || [];
      ul.innerHTML = "";
      if (!items.length) {
        ul.innerHTML = '<li class="rc-vacio">Carpeta vacía.</li>';
        return;
      }
      for (const n of items) {
        const li = document.createElement("li");
        li.className = "rc-carpeta-normativa-item";
        if (ESTADO_NORM.seleccionada && ESTADO_NORM.seleccionada.id === n.id) {
          li.classList.add("rc-norm-seleccionada");
        }
        li.dataset.id = n.id;
        li.innerHTML = `<button type="button" class="rc-carpeta-cargar">
            <strong>${n.nombre}</strong>
            <small>${n.direccion || "—"}</small>
          </button>`;
        li.querySelector(".rc-carpeta-cargar").addEventListener("click", () =>
          seleccionarNormativa(n.id)
        );
        ul.appendChild(li);
      }
    } catch (e) { ul.innerHTML = '<li class="rc-vacio">Error de red.</li>'; }
  }

  async function seleccionarNormativa(normativaId) {
    try {
      const r = await fetch(`${API_NORM}/normativas/${normativaId}`);
      if (!r.ok) { mostrarToast("No se pudo cargar", true); return; }
      const data = await r.json();
      ESTADO_NORM.seleccionada = data;
      pintarResumenNormativa(data);
      // marcar visualmente
      document.querySelectorAll(".rc-norm-seleccionada").forEach(li => li.classList.remove("rc-norm-seleccionada"));
      const li = document.querySelector(`.rc-carpeta-normativa-item[data-id="${normativaId}"]`);
      if (li) li.classList.add("rc-norm-seleccionada");
    } catch (e) { mostrarToast("Error de red", true); }
  }

  function pintarResumenNormativa(data) {
    const urb = data.urbanisticos || {};
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    set("rc-norm-resumen-nombre", data.nombre || "—");
    set("rc-norm-resumen-direccion", data.direccion || "—");
    set("rc-norm-resumen-coef", urb.coeficiente_edificabilidad != null ? urb.coeficiente_edificabilidad : "—");
    set("rc-norm-resumen-ocup", urb.ocupacion_maxima_pct != null ? `${urb.ocupacion_maxima_pct} %` : "—");
    set("rc-norm-resumen-plantas", urb.n_plantas_max != null ? urb.n_plantas_max : "—");
    set("rc-norm-resumen-rfach", urb.retranqueo_fachada_m != null ? `${urb.retranqueo_fachada_m} m` : "—");
    set("rc-norm-resumen-rlind", urb.retranqueo_linderos_m != null ? `${urb.retranqueo_linderos_m} m` : "—");
    document.getElementById("rc-norm-resumen").hidden = false;
  }
  function ocultarResumenNormativa() {
    ESTADO_NORM.seleccionada = null;
    const r = document.getElementById("rc-norm-resumen");
    if (r) r.hidden = true;
  }

  function aplicarNormativaAlProyecto(data) {
    const urb = data.urbanisticos || {};
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
      if (map[k] == null) continue;
      const inp = form.querySelector(`[name="${k}"]`);
      if (inp) inp.value = map[k];
    }
    const usos = urb.usos_permitidos || [];
    if (usos.length) {
      form.querySelectorAll('[name="usos_permitidos"]').forEach(c => {
        c.checked = usos.includes(c.value);
      });
    }
    // Guardar la normativa aplicada para que el backend la use como referencia
    // al calcular avisos (incumplimientos / valores inferiores a la normativa).
    ESTADO_NORM.aplicada = { id: data.id, nombre: data.nombre, urbanisticos: urb };
    modal.close();
    mostrarToast(`Normativa "${data.nombre}" aplicada`);
    pedirPreview();
  }

  // ─── Visibilidad combinada: uso × categoría de planta ─────────────────
  // Un campo se ve solo si su `data-cuando-uso` (si lo tiene) incluye el uso activo
  // Y su `data-visible-en-planta` (si lo tiene) incluye la categoría de planta activa.
  function aplicarVisibilidad(payload) {
    const usoActivo = usoActivoForm();
    const cat = categoriaPlantaActiva(payload || ESTADO.fullPayload || ESTADO.previewPayload);
    form.querySelectorAll("[data-cuando-uso], [data-visible-en-planta]").forEach(el => {
      const usoOk = !el.dataset.cuandoUso
        || el.dataset.cuandoUso.split(/\s+/).includes(usoActivo);
      const plantaOk = !el.dataset.visibleEnPlanta
        || el.dataset.visibleEnPlanta.split(/\s+/).includes(cat);
      el.hidden = !(usoOk && plantaOk);
    });
  }

  // ─── Opciones condicionales dentro del panel ──────────────────────────
  function _toggleOpcion(select, valor, permitido, fallback) {
    if (!select) return;
    const opt = Array.from(select.options).find(o => o.value === valor);
    if (!opt) return;
    opt.hidden = !permitido;
    opt.disabled = !permitido;
    if (!permitido && select.value === valor) select.value = fallback;
  }

  // Conjuntos (apartamentos turísticos) solo admite 1L y 2L.
  function _filtrarCategoriaApartamentos() {
    const grupoSel = form.querySelector('select[name="grupo_apartamentos"]');
    const catSel = form.querySelector('select[name="categoria_apartamentos"]');
    if (!grupoSel || !catSel) return;
    const soloDos = grupoSel.value === "conjuntos";
    _toggleOpcion(catSel, "3L", !soloDos, "2L");
    _toggleOpcion(catSel, "4L", !soloDos, "2L");
  }

  // "Múltiple" solo existe en albergue (resto: individual/doble/triple/cuádruple).
  function _filtrarTipologiaHotelero() {
    const catSel = form.querySelector('select[name="categoria_hotelero"]');
    if (!catSel) return;
    const permite = catSel.value === "albergue";
    // PB y plantas tipo tienen cada una su contenedor de tipología hotelera.
    form.querySelectorAll('[data-opciones="hotelero"] select').forEach(
      sel => _toggleOpcion(sel, "multiple", permite, "doble")
    );
  }

  function actualizarOpcionesCondicionales() {
    _filtrarCategoriaApartamentos();
    _filtrarTipologiaHotelero();
  }

  // ─── Categoría de la planta activa (pb / tipo / atico / sotano) ───────
  function categoriaPlantaActiva(payload) {
    const plantas = payload?.envolvente?.plantas
      || payload?.edificio?.plantas || [];
    if (!plantas.length) return "pb";   // sin cálculo aún → se edita la PB
    const idx = Math.min(ESTADO.plantaActiva, plantas.length - 1);
    if (idx < 0) return "pb";
    const pl = plantas[idx];
    if (!pl) return "pb";
    if (pl.tipo === "sotano") return "sotano";
    if (pl.tipo === "atico") return "atico";
    // primera planta regular = PB
    let primeraRegular = -1;
    for (let i = 0; i < plantas.length; i++) {
      if (plantas[i].tipo === "regular") { primeraRegular = i; break; }
    }
    return idx === primeraRegular ? "pb" : "tipo";
  }

  // ─── Selector dinámico de tipologías extra (por uso) ──────────────────
  const OPCIONES_TIPOLOGIA = {
    vivienda: { "estudio": "Estudio", "1d": "1 dormitorio", "2d": "2 dormitorios", "3d": "3 dormitorios", "4d+": "4 o más dormitorios" },
    apartamento: { "estudio": "Estudio", "individual": "Individual", "doble": "Doble", "triple": "Triple", "cuadruple": "Cuádruple" },
    hotelero: { "individual": "Individual", "doble": "Doble", "triple": "Triple", "cuadruple": "Cuádruple", "multiple": "Múltiple (albergue)" },
  };
  const DEFAULT_TIPOLOGIA = { vivienda: "1d", apartamento: "doble", hotelero: "doble" };

  function _opcionesTipologia(opciones, seleccionado) {
    const labels = OPCIONES_TIPOLOGIA[opciones] || OPCIONES_TIPOLOGIA.vivienda;
    return Object.entries(labels).map(([v, label]) =>
      `<option value="${v}"${v === seleccionado ? " selected" : ""}>${label}</option>`
    ).join("");
  }

  function anadirTipologia(contenedor) {
    if (!contenedor) return;
    const opciones = contenedor.dataset.opciones || "vivienda";
    // El contenedor de las plantas tipo enruta sus extras a `programa_tipo`.
    const bloque = contenedor.dataset.bloque || "programa";
    const inicial = DEFAULT_TIPOLOGIA[opciones] || Object.keys(OPCIONES_TIPOLOGIA[opciones])[0];
    const wrap = document.createElement("div");
    wrap.className = "rc-tipologia-extra";
    wrap.innerHTML = `<select name="tipologias_extra" data-bloque="${bloque}">${_opcionesTipologia(opciones, inicial)}</select>
      <button type="button" class="rc-tip-quitar" aria-label="Eliminar tipología">−</button>`;
    contenedor.appendChild(wrap);
  }

  // "+ Tipología" en cualquier bloque de uso (cada botón apunta a su contenedor).
  form.querySelectorAll(".rc-btn-add-tipologia").forEach(btn => {
    btn.addEventListener("click", () => {
      anadirTipologia(document.getElementById(btn.dataset.target));
      calcularConDebounce();
    });
  });

  // Delegación global: click en − elimina la fila de tipología extra.
  form.addEventListener("click", ev => {
    const btn = ev.target.closest(".rc-tip-quitar");
    if (!btn) return;
    const wrap = btn.closest(".rc-tipologia-extra");
    if (wrap) wrap.remove();
    calcularConDebounce();
  });

  // ─── Bindings ─────────────────────────────────────────────────────────
  function calcularConDebounce() {
    aplicarVisibilidad();
    actualizarOpcionesCondicionales();
    if (ESTADO.debounceId) clearTimeout(ESTADO.debounceId);
    ESTADO.debounceId = setTimeout(pedirPreview, 250);
  }
  form.addEventListener("input", calcularConDebounce);
  form.addEventListener("change", calcularConDebounce);
  if (btnDistribuir) btnDistribuir.addEventListener("click", pedirCalculo);
  if (btnGuardar) btnGuardar.addEventListener("click", guardar);
  if (btnCsv) btnCsv.addEventListener("click", exportCsv);

  // Brújula inicial vacía + handler de rotación → render
  if (window.RcBrujula) {
    window.RcBrujula.dibujar(brujulaEl, []);
    window.RcBrujula.onRotate(deg => {
      if (renderer && typeof renderer.setRotation === "function") {
        renderer.setRotation(deg);
      }
    });
  }

  aplicarVisibilidad();
  actualizarOpcionesCondicionales();

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
