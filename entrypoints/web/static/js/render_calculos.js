/* §2.4-2.7 — Render y cálculos. Estado, fetch y repintado.
   Estrategia:
   - cualquier cambio de parámetro recalcula la CAPACIDAD COMPLETA de forma
     automática y silenciosa (recalcularAuto → /calcular; en modo inmueble,
     /estancias). Debounce 300 ms. Repinta capacidad, tablas por planta/unidad,
     KPIs, alertas y canvas, sin spinner ni toasts.
   - el botón «Calcular capacidad» queda RESERVADO para pintar el render
     geométrico (unidades, núcleo, pasillos) en una próxima iteración.
*/
(function () {
  "use strict";

  // Escapa texto antes de interpolarlo en innerHTML. Cubre nombres editables de
  // carpeta/normativa, etiquetas de estancias y mensajes de error del servidor:
  // sin esto, un valor con HTML (p. ej. `<img src=x onerror=...>`) se ejecutaría.
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const form = document.getElementById("rc-form");
  if (!form) return;

  const puedeEditar = form.dataset.puedeEditar === "true";
  const estado = form.dataset.estado;
  // Modo activo (obra-nueva / rehabilitacion) y superficie construida del edificio
  // existente (catastral). Pilotan el aviso de exceso, exclusivo de rehabilitación.
  const modoActivo = form.dataset.modo || "";
  const construidaExistente = parseFloat(form.dataset.construidaExistente);  // NaN si vacío
  // Modo «inmueble»: se trabaja sobre un inmueble concreto (estancias de UNA unidad)
  // a partir de su construida. No hay envolvente, canvas ni tabs de planta: el cálculo
  // va a /estancias y la columna derecha es una sola tabla de estancias.
  const esInmueble = modoActivo === "inmueble";
  const normativaAplicadaProyecto = window.__RC_NORMATIVA_APLICADA__ || null;

  const canvasEl = document.getElementById("rc-canvas");
  const brujulaEl = document.getElementById("rc-brujula");
  const spinnerEl = document.getElementById("rc-spinner");
  const tabsPlantasEl = document.getElementById("rc-tabs-plantas");
  const tablaPlantaBody = document.querySelector("#rc-tabla-planta tbody");
  const tablaUnidadBody = document.querySelector("#rc-tabla-unidad tbody");
  // Solo existen en modo inmueble (tabla única de estancias).
  const tablaEstanciasBody = document.querySelector("#rc-tabla-estancias tbody");
  const estTotalUtilEl = document.getElementById("rc-est-total-util");
  const alertasBox = document.getElementById("rc-alertas");
  const alertasUl = alertasBox.querySelector("ul");
  const toast = document.getElementById("rc-toast");
  const btnDistribuir = document.getElementById("rc-btn-distribuir");
  const btnGuardar = document.getElementById("rc-btn-guardar");
  const btnCsv = document.getElementById("rc-btn-csv");
  const btnNormativa = document.getElementById("rc-btn-normativa");
  const modal = document.getElementById("rc-modal-normativa");

  // En modo inmueble no hay canvas → no se instancia el renderer.
  const renderer = canvasEl ? new window.RenderCanvas(canvasEl) : null;

  // Editor interactivo de patios (mover/estirar/girar/reformar). Solo activo sobre
  // la planta baja, donde se definen los patios. Sus callbacks (declaraciones
  // hoisteadas) sincronizan la edición con el formulario y el recálculo.
  const patioEditor = (renderer && window.PatioEditor) ? new window.PatioEditor(renderer, {
    onCommit: (id, vertices) => commitPatioGeom(id, vertices),
    onFijarGeom: (id, vertices) => fijarPatioGeom(id, vertices),
    onSelect: (id) => resaltarFilaPatio(id),
    onMerge: (idA, idB) => fusionarPatios(idA, idB),
  }) : null;
  if (renderer && patioEditor) renderer.setOverlay(() => patioEditor.dibujarOverlay());

  let _patioSeq = 0;   // contador para ids temporales de patios nuevos

  const fmt = {
    m2: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, minimumFractionDigits: 1 }),
    int: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 }),
    pct: new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }),
  };

  const ESTADO = {
    previewPayload: null,
    fullPayload: null,
    plantaActiva: 0,
    abortCalcular: null,
    debounceId: null,
    // §2.5 — combinación de dormitorios elegida en el modal (apartamentos
    // turísticos). Temporal: se inyecta en /calcular como `combo_dormitorios`
    // pero NO se persiste en el formulario ni en /guardar.
    comboDormitorios: null,   // { slug, etiqueta } | null
    // Aviso de exceso de construida (rehabilitación): el modal salta una vez al
    // superar; tras aceptarlo, solo queda el aviso inferior. `interaccionUsuario`
    // evita que el modal salte en la carga inicial automática.
    excesoAceptado: false,
    interaccionUsuario: false,
  };

  function usoActivoForm() {
    const sel = form.querySelector('select[name="uso"]');
    return sel ? sel.value : "vivienda";
  }

  // §2.5 — usos que se definen por nº de dormitorios + combinaciones.
  function usoUsaCombo() {
    return ["vivienda", "apartamentos_turisticos"].includes(usoActivoForm());
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
      } else if (nombre === "patios") {
        // Patios: un objeto por fila { id, area_m2, vertices? }. La geometría
        // (polígono UTM) viaja en data-vertices de la fila; las filas nuevas sin
        // posición se envían sin vertices → el backend las auto-coloca. Vacíos se saltan.
        if (!Array.isArray(bloques[bloque].patios)) bloques[bloque].patios = [];
        if (inp.value !== "") {
          const fila = inp.closest(".rc-patio-fila");
          const obj = { id: (fila && fila.dataset.patioId) || "", area_m2: Number(inp.value) };
          if (fila && fila.dataset.vertices) {
            try {
              const vs = JSON.parse(fila.dataset.vertices);
              if (Array.isArray(vs) && vs.length >= 3) obj.vertices = vs;
            } catch (e) { /* geometría corrupta → se auto-coloca */ }
          }
          if (fila && fila.dataset.bloqueado === "true") obj.bloqueado = true;
          if (fila && fila.dataset.origen) obj.origen = fila.dataset.origen;
          if (fila && fila.dataset.huecos) {
            // Anillos interiores (edificio dentro del patio → anillo). Corruptos → sin huecos.
            try {
              const hs = JSON.parse(fila.dataset.huecos);
              if (Array.isArray(hs) && hs.length) obj.huecos = hs;
            } catch (e) { /* huecos corruptos → patio macizo */ }
          }
          bloques[bloque].patios.push(obj);
        }
      } else {
        const valor = inp.value === "" ? null : (inp.type === "number" ? Number(inp.value) : inp.value);
        bloques[bloque][nombre] = valor;
      }
    });
    // Aseguramos que los arrays existan aunque ninguna casilla esté marcada
    if (!bloques.urbanisticos.usos_permitidos) bloques.urbanisticos.usos_permitidos = [];
    if (!bloques.urbanisticos.patios) bloques.urbanisticos.patios = [];
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
    // Área REAL del polígono (geometría), distinta de la superficie catastral (area_m2):
    // es la que se muestra en el KPI «Superficie del polígono». La catastral sigue
    // gobernando edificabilidad/ocupación (cap.*), solo cambia lo que se ENSEÑA aquí.
    const parcelaGeom = payload?.parcela?.area_geometrica_m2;
    // Fuente de verdad iter. 4: data.capacidad. Fallback a envolvente del preview.
    if (cap) {
      set("construida_total_m2", fmt.m2.format(cap.construida_total_m2) + " m²");
      set("superficie_poligono_m2", fmt.m2.format(parcelaGeom ?? cap.superficie_parcela_m2) + " m²");
      set("edificabilidad_m2", fmt.m2.format(cap.edificabilidad_m2) + " m²");
      set("n_viviendas", fmt.int.format(cap.n_viviendas_objetivo));
    } else if (env) {
      set("construida_total_m2", fmt.m2.format(env.edificabilidad_consumida_m2) + " m²");
      set("superficie_poligono_m2", fmt.m2.format(parcelaGeom ?? parcelaArea ?? 0) + " m²");
      set("edificabilidad_m2", fmt.m2.format(env.edificabilidad_max_m2) + " m²");
      set("n_viviendas", fmt.int.format(env.n_viviendas_objetivo) + " obj.");
    }
  }

  // ─── Aviso de exceso de construida (solo Rehabilitación) ──────────────
  const modalExceso = document.getElementById("rc-modal-exceso");
  const avisoExceso = document.getElementById("rc-aviso-exceso");

  function construidaProyectada(payload) {
    const cap = payload?.capacidad;
    const env = payload?.envolvente;
    if (cap && typeof cap.construida_total_m2 === "number") return cap.construida_total_m2;
    if (env && typeof env.edificabilidad_consumida_m2 === "number") return env.edificabilidad_consumida_m2;
    return null;
  }

  function pintarTextoExceso(proyectada) {
    const txtP = fmt.m2.format(proyectada) + " m²";
    const txtE = fmt.m2.format(construidaExistente) + " m²";
    document.querySelectorAll('[data-exceso="proyectada"]').forEach(el => el.textContent = txtP);
    document.querySelectorAll('[data-exceso="existente"]').forEach(el => el.textContent = txtE);
    const pm = document.getElementById("rc-exceso-proyectada");
    const em = document.getElementById("rc-exceso-existente");
    if (pm) pm.textContent = txtP;
    if (em) em.textContent = txtE;
  }

  function abrirModalExceso() {
    if (!modalExceso) return;
    if (typeof modalExceso.showModal === "function") { try { modalExceso.showModal(); } catch (e) { modalExceso.setAttribute("open", ""); } }
    else modalExceso.setAttribute("open", "");
  }
  function cerrarModalExceso() {
    if (!modalExceso) return;
    if (modalExceso.close) modalExceso.close();
    else modalExceso.removeAttribute("open");
  }

  function verificarExcesoConstruida(payload) {
    // Exclusivo de rehabilitación y solo si conocemos la construida existente.
    if (modoActivo !== "rehabilitacion" || !(construidaExistente > 0)) return;
    const proyectada = construidaProyectada(payload);
    if (proyectada === null) return;
    const excede = proyectada > construidaExistente + 1e-6;

    if (!excede) {
      if (avisoExceso) avisoExceso.hidden = true;   // vuelve a estar dentro de lo existente
      return;
    }
    pintarTextoExceso(proyectada);
    // En la carga inicial automática (sin interacción) no abrimos el modal.
    if (!ESTADO.interaccionUsuario) return;
    if (!ESTADO.excesoAceptado) {
      abrirModalExceso();
    } else if (avisoExceso) {
      avisoExceso.hidden = false;                    // ya aceptado → solo aviso inferior
    }
  }

  // Aceptar (o cerrar) = se ha visto la advertencia: a partir de ahí, aviso inferior.
  function aceptarExceso() {
    ESTADO.excesoAceptado = true;
    cerrarModalExceso();
    if (avisoExceso) avisoExceso.hidden = false;
  }
  const btnExcesoAceptar = document.getElementById("rc-modal-exceso-aceptar");
  if (btnExcesoAceptar) btnExcesoAceptar.addEventListener("click", aceptarExceso);
  // Solo se cierra con «Aceptar»: bloqueamos el cierre por tecla Escape.
  if (modalExceso) modalExceso.addEventListener("cancel", ev => ev.preventDefault());

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
        if (patioEditor) patioEditor.setActivo(puedeEditar && categoriaPlantaActiva(payload) === "pb");
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
      tablaPlantaBody.innerHTML = '<tr><td colspan="13" class="rc-vacio">Sin datos. Calcula la capacidad.</td></tr>';
      return;
    }
    const tot = { c: 0, u: 0, mur: 0, murInt: 0, murEst: 0, circ: 0, nuc: 0, pat: 0, loc: 0, otr: 0, com: 0, viv: 0 };
    filas.forEach(r => {
      tot.c += r.construida_m2 || 0;
      tot.u += r.util_viviendas_m2 || 0;
      tot.mur += r.muros_m2 || 0;
      tot.murInt += r.muros_interior_m2 || 0;
      tot.murEst += r.muros_estimados_m2 || 0;
      tot.circ += r.circulacion_m2 || 0;
      tot.nuc += r.nucleo_m2 || 0;
      tot.pat += r.patios_m2 || 0;
      tot.loc += r.local_m2 || 0;
      tot.otr += r.otros_m2 || 0;
      tot.com += r.usos_comunes_m2 || 0;
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
        <td>${fmt.m2.format(r.muros_interior_m2 || 0)}</td>
        <td>${fmt.m2.format(r.muros_estimados_m2 || 0)}</td>
        <td>${fmt.m2.format(r.circulacion_m2 || 0)}</td>
        <td>${fmt.m2.format(r.nucleo_m2 || 0)}</td>
        <td>${fmt.m2.format(r.patios_m2 || 0)}</td>
        <td class="rc-col-local">${fmt.m2.format(r.local_m2 || 0)}</td>
        <td>${fmt.m2.format(r.otros_m2 || 0)}</td>
        <td class="rc-col-comunes">${fmt.m2.format(r.usos_comunes_m2 || 0)}</td>`;
      tablaPlantaBody.appendChild(tr);
    });
    const trTot = document.createElement("tr");
    trTot.className = "rc-fila-total";
    trTot.innerHTML = `
      <td>Total</td>
      <td>${fmt.int.format(tot.viv)}</td>
      <td>${fmt.m2.format(tot.c)}</td>
      <td>${fmt.m2.format(tot.u)}</td>
      <td>${fmt.m2.format(tot.mur)}</td>
      <td>${fmt.m2.format(tot.murInt)}</td>
      <td>${fmt.m2.format(tot.murEst)}</td>
      <td>${fmt.m2.format(tot.circ)}</td>
      <td>${fmt.m2.format(tot.nuc)}</td>
      <td>${fmt.m2.format(tot.pat)}</td>
      <td class="rc-col-local">${fmt.m2.format(tot.loc)}</td>
      <td>${fmt.m2.format(tot.otr)}</td>
      <td class="rc-col-comunes">${fmt.m2.format(tot.com)}</td>`;
    tablaPlantaBody.appendChild(trTot);
    _gatearColumnasUso();
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
      const esReserva = r.tipo === "local" || r.tipo === "otros" || r.tipo === "usos_comunes";
      tr.className = esReserva ? "rc-fila-unidad-local" : "rc-fila-unidad-clicable";
      if (!esReserva && r.adaptada) tr.classList.add("rc-fila-unidad-adaptada");
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
      tr.dataset.murosInt = r.muros_interior_por_unidad_m2 ?? 0;
      tr.dataset.estancias = JSON.stringify(r.estancias || []);
      const utilCelda = esReserva
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
      if (!esReserva) tr.addEventListener("click", () => abrirModalUnidad(tr));
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
    setT("rc-mu-muros", fmt.m2.format(parseFloat(ds.muros || 0)) + " m²");
    setT("rc-mu-muros-int", fmt.m2.format(parseFloat(ds.murosInt || 0)) + " m²");

    // La columna/fila "Computable" (útil − circulación) se muestra en vivienda y
    // en usos turísticos; en local (sin estancias) se oculta. La nota turística y
    // el matiz "de acceso" de la circulación solo aplican a usos turísticos.
    const esTurismo = ["apartamento", "habitacion"].includes(ds.tipo);
    const mostrarComputable = esTurismo || ds.tipo === "vivienda";
    modalEl.classList.toggle("rc-mu-no-turismo", !esTurismo);
    modalEl.classList.toggle("rc-mu-no-comp", !mostrarComputable);
    setT("rc-mu-circ-label", esTurismo ? "Circulación de acceso (no computable)" : "Circulación interior");
    setT("rc-mu-comp-label", esTurismo ? "Computable turismo" : "Computable");

    let estancias = [];
    try { estancias = JSON.parse(ds.estancias || "[]"); } catch (e) { estancias = []; }
    const tbody = document.getElementById("rc-mu-estancias-lista");
    let totalUtil = 0, totalComputable = 0;
    if (tbody) {
      tbody.innerHTML = "";
      if (!estancias.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="rc-vacio">Sin programa de estancias para esta unidad.</td></tr>';
      } else {
        estancias.forEach(e => {
          const util = e.area_target_m2 || 0;
          const esCirculacion = e.categoria === "circulacion";
          const computa = e.computa_turismo !== false && !esCirculacion;
          totalUtil += util;
          if (computa) totalComputable += util;
          // La circulación interior/de acceso no se lista como estancia (vive en
          // el reparto de m² de arriba).
          if (esCirculacion) return;
          const tr = document.createElement("tr");
          tr.className = "rc-mu-estancia rc-mu-estancia-" + (e.categoria || "");
          // Dos niveles de fallo del círculo mínimo inscribible (Ø):
          //  · rojo    → no cabe ni en planta cuadrada (imposible geométricamente).
          //  · amarillo → cabe en cuadrado pero no con la proporción realista 1:1.5.
          const nivel = e.nivel_diametro || (e.cabe_diametro === false ? "amarillo" : "ok");
          let warn = "";
          if (nivel === "rojo") {
            tr.classList.add("rc-mu-estancia-rojo");
            warn = `<span class="rc-mu-est-warn rc-mu-est-warn-rojo" title="No cabe el círculo de Ø ${e.diametro_min_m} m ni en planta cuadrada">⚠</span>`;
          } else if (nivel === "amarillo") {
            tr.classList.add("rc-mu-estancia-amarillo");
            warn = `<span class="rc-mu-est-warn rc-mu-est-warn-amarillo" title="El círculo de Ø ${e.diametro_min_m} m solo cabe en planta cuadrada; no con proporción 1:1.5">⚠</span>`;
          }
          const compCelda = computa
            ? `${fmt.m2.format(util)} m²`
            : '<span class="rc-mu-nocomp">no computa</span>';
          tr.innerHTML = `<td class="rc-mu-est-nombre">${warn}${escapeHtml(e.etiqueta || e.nombre)}</td>
            <td class="rc-mu-est-cat">${escapeHtml(e.categoria || "")}</td>
            <td class="rc-num rc-mu-col-comp">${compCelda}</td>`;
          tbody.appendChild(tr);
        });
      }
    }
    setT("rc-mu-total-computable", fmt.m2.format(totalComputable) + " m²");
    setT("rc-mu-computable", fmt.m2.format(totalComputable) + " m²");
    setT("rc-mu-circ", fmt.m2.format(Math.max(0, totalUtil - totalComputable)) + " m²");

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
  // Debe contener EXACTAMENTE los literales de NivelAlerta del backend
  // (dominio.py): antes faltaba "incumplimiento" e inventaba un "error" no emitido,
  // y por el fallback `?? 1` todo incumplimiento se degradaba al peso de "aviso".
  const NIVEL_PESO = { error: 0, incumplimiento: 1, aviso: 2, info: 3 };
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
      const pa = Math.min(...grupos.get(a).map(x => NIVEL_PESO[x.nivel] ?? NIVEL_PESO.info));
      const pb = Math.min(...grupos.get(b).map(x => NIVEL_PESO[x.nivel] ?? NIVEL_PESO.info));
      return pa - pb;
    });

    reglas.forEach(regla => {
      const items = grupos.get(regla);
      const nivelTop = items.reduce(
        (acc, x) => (NIVEL_PESO[x.nivel] ?? NIVEL_PESO.info) < (NIVEL_PESO[acc] ?? NIVEL_PESO.info) ? x.nivel : acc,
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
        sum.innerHTML = `<span class="rc-alerta-regla">${escapeHtml(regla)}</span>
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

  // ─── Payload con normativa de referencia ──────────────────────────────
  function payloadConNormativa(bloques) {
    const p = { ...bloques };
    // El modo permite al backend aplicar reglas propias del modo: en rehabilitación,
    // los parámetros urbanísticos ocultos del panel (edificabilidad, ocupación,
    // retranqueos) se toman de la normativa en vez de los defaults del motor.
    p.modo = modoActivo;
    if (ESTADO_NORM.aplicada && ESTADO_NORM.aplicada.urbanisticos) {
      p.normativa_referencia = { urbanisticos: ESTADO_NORM.aplicada.urbanisticos };
    }
    // §2.5 — combinación elegida (vivienda / apartamentos). En /calcular
    // sustituye la tipología por la combinación.
    if (usoUsaCombo() && ESTADO.comboDormitorios) {
      p.combo_dormitorios = ESTADO.comboDormitorios.slug;
    }
    return p;
  }

  // Recálculo automático y silencioso. Cualquier cambio de parámetro recalcula
  // la capacidad COMPLETA (tablas + KPIs + alertas + canvas) sin spinner ni
  // toasts. En modo inmueble, pedirCalculo redirige a /estancias.
  function recalcularAuto() {
    return pedirCalculo({ auto: true });
  }

  // ─── Fetch /calcular (completo) ───────────────────────────────────────
  // Único camino de cálculo. Lo dispara recalcularAuto (opts.auto) en cada
  // cambio de parámetro. En modo `auto` NO muestra spinner, toast de éxito ni
  // toast de error de validación; las alertas se repintan igualmente. Los
  // errores técnicos (red / servidor) sí se notifican siempre.
  async function pedirCalculo(opts = {}) {
    if (estado !== "ok") return;
    if (esInmueble) return pedirEstancias(opts);
    const auto = opts.auto === true;
    ESTADO.interaccionUsuario = true;
    const bloques = leerFormulario();
    actualizarResumen(bloques);
    if (ESTADO.abortCalcular) ESTADO.abortCalcular.abort();
    ESTADO.abortCalcular = new AbortController();
    if (!auto) spinner(true);
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
      // Error bloqueante (p. ej. R3: Σ mínimos > útil máximo). Repinta la alerta
      // y NO pinta capacidad vacía. En auto, sin toast (no interrumpe el tecleo).
      if (data.error) {
        repintarAlertas(data.alertas);
        if (!auto) mostrarToast(data.error, true);
        return;
      }
      ESTADO.fullPayload = data;
      // Re-sella cada fila de patio con el polígono devuelto (identidad por id): así
      // un patio auto-colocado «se queda» donde el backend lo puso y se puede arrastrar.
      sincronizarPatiosDesdePayload(data);
      // Iter. 3: edificio = null. Usamos envolvente.plantas para los tabs.
      const n_plantas = (data.envolvente?.plantas?.length) || (data.edificio?.plantas?.length) || 1;
      ESTADO.plantaActiva = Math.min(ESTADO.plantaActiva, n_plantas - 1);
      dibujarTabsPlantas(data);
      if (renderer) renderer.dibujar(data, ESTADO.plantaActiva);
      if (patioEditor) patioEditor.setActivo(puedeEditar && categoriaPlantaActiva(data) === "pb");
      actualizarBrujula(data);
      repintarKpis(data);
      repintarAlertas(data.alertas);
      repintarTablaPlanta(data.tabla_planta);
      repintarTablaUnidad(data.tabla_unidad);
      verificarExcesoConstruida(data);
      if (!auto) mostrarToast("Capacidad calculada");
    } catch (e) {
      if (e.name !== "AbortError") mostrarToast("Error de red", true);
    } finally {
      if (!auto) spinner(false);
    }
  }

  // ─── Modo «inmueble»: estancias de UNA unidad ─────────────────────────
  // Nº de dormitorios del inmueble (el input directo del panel; en modo inmueble
  // no hay combinaciones — pilota las estancias de esta única vivienda).
  function ndormsInmueble() {
    const inp = document.getElementById("rc-apt-ndorms");
    const n = inp ? parseInt(inp.value, 10) : 0;
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  function repintarKpisInmueble(t) {
    const set = (key, v) => {
      const el = document.querySelector(`[data-kpi="${key}"]`);
      if (el) el.textContent = v;
    };
    if (!t) {
      ["inm_construida_m2", "inm_util_m2", "inm_n_estancias", "inm_n_dormitorios"]
        .forEach(k => set(k, "—"));
      return;
    }
    set("inm_construida_m2", fmt.m2.format(t.construida_m2) + " m²");
    set("inm_util_m2", fmt.m2.format(t.util_m2) + " m²");
    set("inm_n_estancias", fmt.int.format(t.n_estancias));
    set("inm_n_dormitorios", fmt.int.format(t.n_dormitorios));
  }

  function repintarTablaEstancias(estancias, totales) {
    if (!tablaEstanciasBody) return;
    tablaEstanciasBody.innerHTML = "";
    if (!estancias || !estancias.length) {
      tablaEstanciasBody.innerHTML =
        '<tr><td colspan="4" class="rc-vacio">Sin estancias. Ajusta el nº de dormitorios y calcula.</td></tr>';
      if (estTotalUtilEl) estTotalUtilEl.textContent = "—";
      return;
    }
    let totalUtil = 0;
    estancias.forEach(e => {
      const sup = e.area_target_m2 || 0;
      totalUtil += sup;
      const tr = document.createElement("tr");
      tr.className = "rc-mu-estancia rc-mu-estancia-" + (e.categoria || "");
      // Dos niveles de fallo del círculo mínimo inscribible (Ø), igual que el modal.
      const nivel = e.nivel_diametro || (e.cabe_diametro === false ? "amarillo" : "ok");
      let warn = "";
      if (nivel === "rojo") {
        tr.classList.add("rc-mu-estancia-rojo");
        warn = `<span class="rc-mu-est-warn rc-mu-est-warn-rojo" title="No cabe el círculo de Ø ${e.diametro_min_m} m ni en planta cuadrada">⚠</span>`;
      } else if (nivel === "amarillo") {
        tr.classList.add("rc-mu-estancia-amarillo");
        warn = `<span class="rc-mu-est-warn rc-mu-est-warn-amarillo" title="El círculo de Ø ${e.diametro_min_m} m solo cabe en planta cuadrada; no con proporción 1:1.5">⚠</span>`;
      }
      tr.innerHTML = `
        <td class="rc-mu-est-nombre">${warn}${escapeHtml(e.etiqueta || e.nombre)}</td>
        <td class="rc-mu-est-cat">${escapeHtml(e.categoria || "")}</td>
        <td class="rc-num">${fmt.m2.format(sup)} m²</td>
        <td class="rc-num">${fmt.m2.format(e.area_min_m2 || 0)} m²</td>`;
      tablaEstanciasBody.appendChild(tr);
    });
    if (estTotalUtilEl) {
      const t = totales && typeof totales.util_m2 === "number" ? totales.util_m2 : totalUtil;
      estTotalUtilEl.textContent = fmt.m2.format(t) + " m²";
    }
  }

  async function pedirEstancias(opts = {}) {
    if (estado !== "ok") return;
    const auto = opts.auto === true;
    ESTADO.interaccionUsuario = true;
    const bloques = leerFormulario();
    if (ESTADO.abortCalcular) ESTADO.abortCalcular.abort();
    ESTADO.abortCalcular = new AbortController();
    try {
      const resp = await fetch("/modulos/render-calculos/estancias", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...bloques, n_dormitorios: ndormsInmueble() }),
        signal: ESTADO.abortCalcular.signal,
      });
      if (resp.status === 409) { mostrarToast("Elige un inmueble en la localización", true); return; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al calcular estancias", true);
        return;
      }
      const data = await resp.json();
      if (data.error) {
        repintarAlertas(data.alertas || []);
        repintarTablaEstancias([], null);
        repintarKpisInmueble(null);
        if (!auto) mostrarToast(data.error, true);
        return;
      }
      ESTADO.fullPayload = data;
      repintarKpisInmueble(data.totales);
      repintarTablaEstancias(data.estancias, data.totales);
      repintarAlertas(data.alertas || []);
    } catch (e) {
      if (e.name !== "AbortError") mostrarToast("Error de red", true);
    }
  }

  // ─── Guardar parámetros ───────────────────────────────────────────────
  let guardando = false;   // anti-doble-click: evita POST /guardar concurrentes
  async function guardar() {
    if (!puedeEditar || guardando) return;
    guardando = true;
    if (btnGuardar) btnGuardar.disabled = true;
    try {
      const bloques = leerFormulario();
      // Iter. 3: el resumen ahora viene de data.capacidad (no de edificio.totales).
      const resumen = ESTADO.fullPayload?.capacidad
        || ESTADO.fullPayload?.totales          // modo inmueble (estancias)
        || ESTADO.fullPayload?.edificio?.totales
        || ESTADO.previewPayload?.envolvente
        || {};
      const resp = await fetch("/modulos/render-calculos/guardar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parametros: bloques, resumen, modo: modoActivo }),
      });
      if (resp.status === 409) { mostrarToast("Crea o abre un proyecto primero", true); return; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al guardar", true);
        return;
      }
      mostrarToast("Guardado en el proyecto");
    } catch (e) { mostrarToast("Error de red", true); }
    finally {
      guardando = false;
      if (btnGuardar) btnGuardar.disabled = false;
    }
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
  let normativaObligatoria = false;

  if (normativaAplicadaProyecto) {
    ESTADO_NORM.aplicada = normativaAplicadaProyecto;
    if (btnNormativa) btnNormativa.textContent = `Normativa: ${normativaAplicadaProyecto.nombre}`;
  }

  if (btnNormativa && modal) {
    btnNormativa.addEventListener("click", () => {
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
      ocultarResumenNormativa();
      pintarNormativaActual();
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

  if (!esInmueble && modal) {
    modal.addEventListener("cancel", e => {
      if (normativaObligatoria) e.preventDefault();
    });
    if (!normativaAplicadaProyecto) {
      normativaObligatoria = true;
      const cerrar = document.getElementById("rc-modal-cerrar");
      if (cerrar) cerrar.hidden = true;
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
      ocultarResumenNormativa();
      refrescarCarpetasNormativa();
    }
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
      sum.innerHTML = `<span class="rc-carpeta-nombre">${escapeHtml(c.nombre)}</span>`;
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
            <strong>${escapeHtml(n.nombre)}</strong>
            <small>${escapeHtml(n.direccion || "—")}</small>
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

  // Etiqueta + unidad de cada parámetro urbanístico de una normativa, en orden de
  // lectura. Cubre todos los campos que captura el editor de Normativa municipal.
  const NORM_CAMPOS = [
    ["coeficiente_edificabilidad", "Coef. edificabilidad", " m²t/m²s"],
    ["ocupacion_maxima_pct", "Ocupación máx.", " %"],
    ["n_plantas_max", "Plantas máx.", ""],
    ["retranqueo_fachada_m", "Retranq. fachada", " m"],
    ["retranqueo_linderos_m", "Retranq. linderos", " m"],
    ["retranqueo_atico_m", "Retranq. ático", " m"],
    ["ancho_min_fachada_m", "Fachada mín.", " m"],
    ["luz_recta_patio_min_m", "Luz mín. patio", " m"],
    ["area_patio_min_m2", "Área mín. patio", " m²"],
    ["diametro_max_vestibulo_m", "Ø máx. vestíbulo", " m"],
    ["espesor_muro_medianero_max_m", "Muro medianero máx.", " m"],
    ["espesor_separacion_unidades_max_m", "Separación uds. máx.", " m"],
    ["espesor_tabique_min_m", "Tabique mín.", " m"],
    ["ancho_min_pasillo_comun_m", "Pasillo común mín.", " m"],
    ["ancho_min_pasillo_vivienda_m", "Pasillo vivienda mín.", " m"],
    ["ancho_min_puerta_m", "Puerta mín.", " m"],
  ];

  // Pinta (solo lectura) la normativa que el proyecto ya tiene aplicada al abrir
  // el modal, para ver de un vistazo cuál está aplicada y con TODOS sus parámetros.
  // Es informativo: muestra todo lo que define la normativa, sin filtrar por modo
  // (a diferencia del panel de cálculo). Si no hay ninguna aplicada, oculta el bloque.
  function pintarNormativaActual() {
    const box = document.getElementById("rc-norm-actual");
    if (!box) return;
    const a = ESTADO_NORM.aplicada;
    if (!a) { box.hidden = true; return; }
    const urb = a.urbanisticos || {};
    const nombreEl = document.getElementById("rc-norm-actual-nombre");
    if (nombreEl) nombreEl.textContent = a.nombre || "—";
    const cont = document.getElementById("rc-norm-actual-lista");
    if (cont) {
      cont.innerHTML = "";
      for (const [clave, label, unidad] of NORM_CAMPOS) {
        const v = urb[clave];
        if (v == null || v === "") continue;
        const div = document.createElement("div");
        div.innerHTML = `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(v))}${escapeHtml(unidad)}</dd>`;
        cont.appendChild(div);
      }
      const usos = urb.usos_permitidos;
      if (Array.isArray(usos) && usos.length) {
        const div = document.createElement("div");
        div.className = "rc-norm-actual-usos";
        div.innerHTML = `<dt>Usos permitidos</dt><dd>${escapeHtml(usos.join(", "))}</dd>`;
        cont.appendChild(div);
      }
      if (!cont.children.length) {
        cont.innerHTML = '<div class="rc-norm-actual-usos"><dd class="rc-vacio">Sin parámetros registrados.</dd></div>';
      }
    }
    box.hidden = false;
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
    recalcularAuto();
    // Persistir en el proyecto (fire and forget)
    fetch("/modulos/render-calculos/aplicar-normativa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: data.id, nombre: data.nombre, urbanisticos: urb }),
    });
    if (btnNormativa) btnNormativa.textContent = `Normativa: ${data.nombre}`;
    if (normativaObligatoria) {
      normativaObligatoria = false;
      const cerrar = document.getElementById("rc-modal-cerrar");
      if (cerrar) cerrar.hidden = false;
    }
  }

  // ─── Modal "Combinaciones de dormitorios" (§2.5 — apartamentos) ───────
  const modalTip = document.getElementById("rc-modal-tipologias");
  const btnCombinaciones = document.getElementById("rc-btn-combinaciones");
  const inpNdorms = document.getElementById("rc-apt-ndorms");
  const comboElegidoBox = document.getElementById("rc-combo-elegido");
  const comboElegidoTxt = document.getElementById("rc-combo-elegido-txt");
  const btnComboLimpiar = document.getElementById("rc-combo-limpiar");

  function refrescarChipCombo() {
    if (!comboElegidoBox) return;
    if (ESTADO.comboDormitorios) {
      comboElegidoBox.hidden = false;
      comboElegidoTxt.textContent = ESTADO.comboDormitorios.etiqueta;
    } else {
      comboElegidoBox.hidden = true;
      comboElegidoTxt.textContent = "";
    }
  }

  function fijarCombo(combo) {
    ESTADO.comboDormitorios = combo;   // { slug, etiqueta } | null
    refrescarChipCombo();
  }

  async function abrirModalCombinaciones() {
    if (!modalTip) return;
    if (estado !== "ok") { mostrarToast("Localiza primero la parcela", true); return; }
    const nDorms = Math.max(0, parseInt(inpNdorms && inpNdorms.value, 10) || 0);
    const bloques = leerFormulario();
    const sub = document.getElementById("rc-modal-tip-sub");
    const body = document.getElementById("rc-modal-tip-body");
    const vacio = document.getElementById("rc-modal-tip-vacio");
    const podadas = document.getElementById("rc-modal-tip-podadas");
    const excluidasEl = document.getElementById("rc-modal-tip-excluidas");
    body.innerHTML = '<tr><td colspan="5" class="rc-vacio">Calculando…</td></tr>';
    vacio.hidden = true;
    podadas.hidden = true;
    if (excluidasEl) excluidasEl.hidden = true;
    if (typeof modalTip.showModal === "function") modalTip.showModal();
    else modalTip.setAttribute("open", "");
    try {
      const resp = await fetch("/modulos/render-calculos/tipologias-dormitorios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...bloques, n_dormitorios: nDorms }),
      });
      if (resp.status === 409) {
        body.innerHTML = '<tr><td colspan="5" class="rc-vacio">Localiza primero la parcela.</td></tr>';
        return;
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        body.innerHTML = `<tr><td colspan="5" class="rc-vacio">${escapeHtml(err.detail || "Error")}</td></tr>`;
        return;
      }
      const data = await resp.json();
      if (data.error) {
        body.innerHTML = `<tr><td colspan="5" class="rc-vacio">${escapeHtml(data.error)}</td></tr>`;
        return;
      }
      const lbl = nDorms === 0 ? "estudio (0 dormitorios)" : `${nDorms} dormitorio${nDorms > 1 ? "s" : ""}`;
      sub.textContent = `Combinaciones para ${lbl} · categoría ${data.categoria}.`;
      const combos = data.combinaciones || [];
      const excluidas = data.excluidas_util_maximo || [];

      // Combinaciones que no caben en el útil máximo de la tipología (R3): se
      // muestran las viables y se avisa de las excluidas, en vez de bloquear todo.
      if (excluidasEl && excluidas.length) {
        excluidasEl.hidden = false;
        const techo = excluidas[0].util_maximo_m2;
        const detalle = excluidas
          .map(e => `«${e.etiqueta}» (necesita ${fmt.m2.format(e.util_minimo_m2)} m²)`)
          .join(", ");
        excluidasEl.textContent =
          `${excluidas.length} combinación(es) no caben en el útil máximo de la tipología ` +
          `(${fmt.m2.format(techo)} m²): ${detalle}. Sube el útil máximo de esa tipología ` +
          `o reduce sus superficies mínimas.`;
      }

      body.innerHTML = "";
      if (!combos.length) {
        // Si todas se excluyeron por útil máximo, la nota de arriba ya lo explica;
        // si no, el vacío genérico (no caben en la envolvente).
        if (!excluidas.length) vacio.hidden = false;
        return;
      }
      for (const c of combos) {
        const tr = document.createElement("tr");
        const elegida = ESTADO.comboDormitorios && ESTADO.comboDormitorios.slug === c.slug;
        tr.className = "rc-modal-tip-fila" + (elegida ? " rc-modal-tip-elegida" : "");
        tr.innerHTML =
          `<td>${c.etiqueta}</td>` +
          `<td class="rc-num">${c.plazas}</td>` +
          `<td class="rc-num">${fmt.m2.format(c.util_objetivo_m2)} m²</td>` +
          `<td class="rc-num"><strong>${fmt.int.format(c.n_unidades)}</strong></td>` +
          `<td><button type="button" class="boton-secundario rc-btn-pequeno rc-modal-tip-elegir">Elegir</button></td>`;
        tr.querySelector(".rc-modal-tip-elegir").addEventListener("click", () => {
          fijarCombo({ slug: c.slug, etiqueta: c.etiqueta });
          modalTip.close();
          mostrarToast(`Combinación "${c.etiqueta}" aplicada`);
          pedirCalculo();
        });
        body.appendChild(tr);
      }
      if (data.podadas > 0) {
        podadas.hidden = false;
        podadas.textContent = `Se descartaron ${data.podadas} combinación(es) que no caben en la envolvente actual.`;
      }
    } catch (e) {
      body.innerHTML = '<tr><td colspan="5" class="rc-vacio">Error de red</td></tr>';
    }
  }

  if (btnCombinaciones) btnCombinaciones.addEventListener("click", abrirModalCombinaciones);
  const btnModalTipCerrar = document.getElementById("rc-modal-tip-cerrar");
  if (btnModalTipCerrar && modalTip) btnModalTipCerrar.addEventListener("click", () => modalTip.close());
  if (btnComboLimpiar) btnComboLimpiar.addEventListener("click", () => {
    fijarCombo(null);
    pedirCalculo();
  });
  // Cambiar el nº de dormitorios invalida la combinación elegida (era de otro N).
  if (inpNdorms) inpNdorms.addEventListener("change", () => {
    if (ESTADO.comboDormitorios) fijarCombo(null);
  });
  refrescarChipCombo();

  // ─── Modal "Superficies mínimas de estancias" (vivienda · Normativa) ──
  const API_SUP = "/modulos/render-calculos/superficies-vivienda";
  const modalSup = document.getElementById("rc-modal-superficies");
  const btnSuperficies = document.getElementById("rc-btn-superficies");
  const LBL_TIPOLOGIA_VIV = {
    0: "Estudio", 1: "1 dormitorio", 2: "2 dormitorios",
    3: "3 dormitorios", 4: "4 dormitorios", 5: "Más de 4 dormitorios",
  };

  async function abrirModalSuperficies() {
    if (!modalSup) return;
    const cont = document.getElementById("rc-sup-secciones");
    cont.innerHTML = '<p class="rc-vacio">Cargando…</p>';
    if (typeof modalSup.showModal === "function") modalSup.showModal();
    else modalSup.setAttribute("open", "");
    try {
      const resp = await fetch(API_SUP);
      if (!resp.ok) { cont.innerHTML = '<p class="rc-vacio">No se pudieron cargar las superficies.</p>'; return; }
      const data = await resp.json();
      pintarSeccionesSuperficies(data.filas || [], data.util_maximo || {});
    } catch (e) {
      cont.innerHTML = '<p class="rc-vacio">Error de red.</p>';
    }
  }

  // Construye una fila <tr> de estancia editable. `f` es la fila del backend.
  function filaSuperficie(f) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.textContent = f.etiqueta;
    const td2 = document.createElement("td");
    const inp = document.createElement("input");
    inp.type = "number";
    inp.min = "0";
    inp.step = "0.5";
    inp.value = f.min_m2;
    inp.className = "rc-sup-input";
    inp.dataset.ndorms = f.n_dormitorios;
    inp.dataset.estancia = f.estancia;
    inp.dataset.original = f.min_m2;
    if (!puedeEditar) inp.disabled = true;
    td2.appendChild(inp);
    tr.appendChild(td1);
    tr.appendChild(td2);
    return tr;
  }

  // Fila del ÚTIL MÁXIMO de una tipología (R3). No es una estancia: su mínimo
  // es el techo de la unidad. Se envía con estancia "_util_maximo".
  function filaUtilMaximo(nDorms, valor) {
    const tr = document.createElement("tr");
    tr.className = "rc-sup-fila-maximo";
    const td1 = document.createElement("td");
    td1.textContent = "Útil máximo de la unidad";
    const td2 = document.createElement("td");
    const inp = document.createElement("input");
    inp.type = "number";
    inp.min = "0";
    inp.step = "1";
    inp.value = valor;
    inp.className = "rc-sup-input";
    inp.dataset.ndorms = nDorms;
    inp.dataset.estancia = "_util_maximo";
    inp.dataset.original = valor;
    if (!puedeEditar) inp.disabled = true;
    td2.appendChild(inp);
    tr.appendChild(td1);
    tr.appendChild(td2);
    return tr;
  }

  // Construye una sección (título + tabla). `utilMaximo` (n_dorms→m²) añade,
  // solo en las secciones por tipología, la fila editable del útil máximo.
  function seccionSuperficies(titulo, filas, nDorms, utilMaximo) {
    const sec = document.createElement("section");
    sec.className = "rc-sup-seccion";
    const h = document.createElement("h3");
    h.textContent = titulo;
    sec.appendChild(h);
    const tabla = document.createElement("table");
    tabla.className = "rc-sup-tabla";
    tabla.innerHTML = "<thead><tr><th>Estancia</th><th>Mínimo (m²)</th></tr></thead>";
    const tbody = document.createElement("tbody");
    filas.forEach(f => tbody.appendChild(filaSuperficie(f)));
    if (nDorms != null && utilMaximo != null && utilMaximo[nDorms] != null) {
      tbody.appendChild(filaUtilMaximo(nDorms, utilMaximo[nDorms]));
    }
    tabla.appendChild(tbody);
    sec.appendChild(tabla);
    return sec;
  }

  function pintarSeccionesSuperficies(filas, utilMaximo) {
    const cont = document.getElementById("rc-sup-secciones");
    cont.innerHTML = "";
    if (!filas.length) {
      cont.innerHTML = '<p class="rc-vacio">No hay superficies registradas.</p>';
      return;
    }
    // 1) Mínimos GLOBALES (comunes a todas las tipologías): se muestran una sola
    //    vez. Editarlos propaga a todas las tipologías en el backend (resuelve R1).
    const globales = [];
    const vistos = new Set();
    filas.forEach(f => {
      if (f.ambito !== "global") return;
      if (vistos.has(f.clave_global)) return;
      vistos.add(f.clave_global);
      globales.push(f);
    });
    if (globales.length) {
      cont.appendChild(seccionSuperficies("Comunes a todas las tipologías", globales));
    }

    // 2) Mínimos POR TIPOLOGÍA (Estancia y Estancia+comedor+cocina), agrupados
    //    por nº de dormitorios (el backend ya envía las filas ordenadas).
    const grupos = new Map();
    filas.forEach(f => {
      if (f.ambito === "global") return;
      if (!grupos.has(f.n_dormitorios)) grupos.set(f.n_dormitorios, []);
      grupos.get(f.n_dormitorios).push(f);
    });
    Array.from(grupos.keys()).sort((a, b) => a - b).forEach(n => {
      const titulo = LBL_TIPOLOGIA_VIV[n] || (n + " dormitorios");
      cont.appendChild(seccionSuperficies(titulo, grupos.get(n), n, utilMaximo));
    });
  }

  async function guardarSuperficies() {
    if (!puedeEditar) { mostrarToast("Sin permiso para editar", true); return; }
    const inputs = document.querySelectorAll("#rc-sup-secciones .rc-sup-input");
    const cambios = [];
    inputs.forEach(inp => {
      if (inp.value === "") return;
      const v = Number(inp.value);
      if (Number.isNaN(v)) return;
      if (Number(inp.dataset.original) === v) return;   // sin cambio
      cambios.push({ n_dormitorios: Number(inp.dataset.ndorms), estancia: inp.dataset.estancia, valor: v });
    });
    if (!cambios.length) { mostrarToast("No hay cambios que guardar"); return; }
    try {
      const resp = await fetch(API_SUP, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cambios }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al guardar", true);
        return;
      }
      const data = await resp.json();
      inputs.forEach(inp => { inp.dataset.original = inp.value; });   // nuevos originales
      mostrarToast(`Superficies guardadas (${data.aplicados})`);
      if (estado === "ok") recalcularAuto();
    } catch (e) { mostrarToast("Error de red", true); }
  }

  async function resetSuperficies() {
    if (!puedeEditar) { mostrarToast("Sin permiso para editar", true); return; }
    try {
      const resp = await fetch(`${API_SUP}/reset`, { method: "POST" });
      if (!resp.ok) { mostrarToast("No se pudo restablecer", true); return; }
      mostrarToast("Valores restablecidos");
      abrirModalSuperficies();   // recarga la tabla con los defaults
    } catch (e) { mostrarToast("Error de red", true); }
  }

  if (btnSuperficies) btnSuperficies.addEventListener("click", abrirModalSuperficies);
  const btnSupCerrar = document.getElementById("rc-sup-cerrar");
  if (btnSupCerrar && modalSup) btnSupCerrar.addEventListener("click", () => modalSup.close());
  const btnSupGuardar = document.getElementById("rc-sup-guardar");
  if (btnSupGuardar) btnSupGuardar.addEventListener("click", guardarSuperficies);
  const btnSupReset = document.getElementById("rc-sup-reset");
  if (btnSupReset) btnSupReset.addEventListener("click", resetSuperficies);

  // ─── Modal "Superficies mínimas" para usos turístico/hoteleros ────────
  // Réplica del editor de vivienda, acotado a la categoría seleccionada en el
  // panel (apartamentos turísticos · hotelero).
  const API_MIN = "/modulos/render-calculos/minimos";
  const modalMin = document.getElementById("rc-modal-minimos");
  const LBL_TIP_MIN = {
    estudio: "Estudio", "1d": "1 dormitorio", "2d": "2 dormitorios",
    "3d": "3 dormitorios", "4d": "4 o más dormitorios",
    individual: "Individual", doble: "Doble", triple: "Triple",
    cuadruple: "Cuádruple", multiple: "Múltiple (albergue)",
    salon_comedor: "Salón-comedor (común de la unidad)", comunes: "Áreas comunes",
  };
  const SELECT_CATEGORIA_MIN = {
    apartamentos_turisticos: "categoria_apartamentos",
    hotelero: "categoria_hotelero",
  };
  let MIN_CTX = { uso: null, categoria: "", grupo: "edificios" };

  function _categoriaDeUso(uso) {
    const sel = form.querySelector(`select[name="${SELECT_CATEGORIA_MIN[uso]}"]`);
    return sel ? sel.value : "";
  }

  async function abrirModalMinimos(uso) {
    if (!modalMin) return;
    const categoria = _categoriaDeUso(uso);
    const grupoSel = form.querySelector('select[name="grupo_apartamentos"]');
    const grupo = uso === "apartamentos_turisticos" && grupoSel ? grupoSel.value : "edificios";
    MIN_CTX = { uso, categoria, grupo };
    const cont = document.getElementById("rc-min-secciones");
    const subt = document.getElementById("rc-min-subtitulo");
    cont.innerHTML = '<p class="rc-vacio">Cargando…</p>';
    if (subt) {
      const grupoTxt = grupo === "conjuntos" ? "Conjuntos" : "Edificios";
      subt.textContent = `Categoría: ${categoria}` +
        (uso === "apartamentos_turisticos" ? ` · ${grupoTxt}` : "");
    }
    if (typeof modalMin.showModal === "function") modalMin.showModal();
    else modalMin.setAttribute("open", "");
    try {
      const q = new URLSearchParams({ categoria, grupo });
      const resp = await fetch(`${API_MIN}/${uso}?${q.toString()}`);
      if (!resp.ok) { cont.innerHTML = '<p class="rc-vacio">No se pudieron cargar las superficies.</p>'; return; }
      const data = await resp.json();
      pintarSeccionesMinimos(data.filas || []);
    } catch (e) {
      cont.innerHTML = '<p class="rc-vacio">Error de red.</p>';
    }
  }

  function pintarSeccionesMinimos(filas) {
    const cont = document.getElementById("rc-min-secciones");
    cont.innerHTML = "";
    if (!filas.length) {
      cont.innerHTML = '<p class="rc-vacio">No hay superficies registradas para esta categoría.</p>';
      return;
    }
    // Agrupar por tipología (el backend ya envía las filas ordenadas).
    const grupos = new Map();
    filas.forEach(f => {
      if (!grupos.has(f.tipologia)) grupos.set(f.tipologia, []);
      grupos.get(f.tipologia).push(f);
    });
    grupos.forEach((rows, tip) => {
      const sec = document.createElement("section");
      sec.className = "rc-sup-seccion";
      const h = document.createElement("h3");
      h.textContent = LBL_TIP_MIN[tip] || tip;
      sec.appendChild(h);
      const tabla = document.createElement("table");
      tabla.className = "rc-sup-tabla";
      tabla.innerHTML = "<thead><tr><th>Estancia</th><th>Mínimo (m²)</th></tr></thead>";
      const tbody = document.createElement("tbody");
      rows.forEach(f => {
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        td1.textContent = f.etiqueta;
        const td2 = document.createElement("td");
        const inp = document.createElement("input");
        inp.type = "number";
        inp.min = "0";
        inp.step = "0.5";
        inp.value = f.min_m2;
        inp.className = "rc-min-input";
        inp.dataset.tipologia = f.tipologia;
        inp.dataset.estancia = f.estancia;
        inp.dataset.original = f.min_m2;
        if (!puedeEditar) inp.disabled = true;
        td2.appendChild(inp);
        tr.appendChild(td1);
        tr.appendChild(td2);
        tbody.appendChild(tr);
      });
      tabla.appendChild(tbody);
      sec.appendChild(tabla);
      cont.appendChild(sec);
    });
  }

  async function guardarMinimos() {
    if (!puedeEditar) { mostrarToast("Sin permiso para editar", true); return; }
    if (!MIN_CTX.uso) return;
    const inputs = document.querySelectorAll("#rc-min-secciones .rc-min-input");
    const cambios = [];
    inputs.forEach(inp => {
      if (inp.value === "") return;
      const v = Number(inp.value);
      if (Number.isNaN(v)) return;
      if (Number(inp.dataset.original) === v) return;   // sin cambio
      cambios.push({ tipologia: inp.dataset.tipologia, estancia: inp.dataset.estancia, valor: v });
    });
    if (!cambios.length) { mostrarToast("No hay cambios que guardar"); return; }
    try {
      const resp = await fetch(`${API_MIN}/${MIN_CTX.uso}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoria: MIN_CTX.categoria, grupo: MIN_CTX.grupo, cambios }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "Error al guardar", true);
        return;
      }
      const data = await resp.json();
      inputs.forEach(inp => { inp.dataset.original = inp.value; });   // nuevos originales
      mostrarToast(`Superficies guardadas (${data.aplicados})`);
      if (estado === "ok") recalcularAuto();
    } catch (e) { mostrarToast("Error de red", true); }
  }

  async function resetMinimos() {
    if (!puedeEditar) { mostrarToast("Sin permiso para editar", true); return; }
    if (!MIN_CTX.uso) return;
    try {
      const resp = await fetch(`${API_MIN}/${MIN_CTX.uso}/reset`, { method: "POST" });
      if (!resp.ok) { mostrarToast("No se pudo restablecer", true); return; }
      mostrarToast("Valores restablecidos");
      abrirModalMinimos(MIN_CTX.uso);   // recarga la tabla con los defaults
    } catch (e) { mostrarToast("Error de red", true); }
  }

  document.querySelectorAll(".rc-btn-minimos").forEach(btn => {
    btn.addEventListener("click", () => abrirModalMinimos(btn.dataset.uso));
  });
  const btnMinCerrar = document.getElementById("rc-min-cerrar");
  if (btnMinCerrar && modalMin) btnMinCerrar.addEventListener("click", () => modalMin.close());
  const btnMinGuardar = document.getElementById("rc-min-guardar");
  if (btnMinGuardar) btnMinGuardar.addEventListener("click", guardarMinimos);
  const btnMinReset = document.getElementById("rc-min-reset");
  if (btnMinReset) btnMinReset.addEventListener("click", resetMinimos);

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
    _gatearColumnasUso();
  }

  // Columnas de la tabla "por planta" condicionadas por uso: "Local" en vivienda
  // y AT; "Usos com." en AT / hoteles (no vivienda). "Otros" se ve siempre.
  function _gatearColumnasUso() {
    const tabla = document.getElementById("rc-tabla-planta");
    if (!tabla) return;
    const uso = usoActivoForm();
    const localAplica = uso === "vivienda" || uso === "apartamentos_turisticos";
    const comunesAplica = uso !== "vivienda";
    tabla.querySelectorAll(".rc-col-local").forEach(el => el.classList.toggle("rc-col-oculta", !localAplica));
    tabla.querySelectorAll(".rc-col-comunes").forEach(el => el.classList.toggle("rc-col-oculta", !comunesAplica));
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

  // ─── Edición de patios: enlace lienzo ↔ panel ─────────────────────────
  function filaPorPatioId(id) {
    if (!id) return null;
    try { return form.querySelector(`.rc-patio-fila[data-patio-id="${CSS.escape(id)}"]`); }
    catch (e) { return null; }
  }

  // Tras editar un patio en el lienzo: guarda su polígono en la fila y recalcula
  // UNA vez (sin debounce). `abortCalcular` cancela cualquier cálculo en vuelo.
  function commitPatioGeom(id, vertices) {
    const fila = filaPorPatioId(id);
    if (fila) {
      fila.dataset.vertices = JSON.stringify(vertices);
      // El patio recién editado pasa a tener la prioridad MÁS BAJA del reparto (último
      // de la lista): así es ÉL quien se adapta a los demás patios al borde, dejándolos
      // donde estaban. El backend cede solo ante los patios anteriores (ver colocar_patios).
      const lista = document.getElementById("rc-patios-lista");
      if (lista && fila.parentElement === lista) lista.appendChild(fila);
    }
    pedirCalculo();
  }

  // Fija la geometría de un patio EN SITIO (doble-clic «volver a cuadrado»): solo persiste el
  // polígono en la fila. NO reordena (conserva su prioridad de reparto) y NO recalcula —
  // cuadrar conserva el área asignada, así que la capacidad no cambia y el backend no necesita
  // tocar nada. El lienzo ya se ha repintado localmente; así el patio NO se mueve. El cuadrado
  // viaja al backend en el próximo recálculo real (otra edición) o al guardar.
  function fijarPatioGeom(id, vertices) {
    const fila = filaPorPatioId(id);
    if (fila) fila.dataset.vertices = JSON.stringify(vertices);
  }

  // Resalta la fila del panel correspondiente al patio seleccionado en el lienzo.
  function resaltarFilaPatio(id) {
    form.querySelectorAll(".rc-patio-fila-activa").forEach(f => f.classList.remove("rc-patio-fila-activa"));
    const fila = filaPorPatioId(id);
    if (fila) fila.classList.add("rc-patio-fila-activa");
  }

  // ─── Fusión de patios próximos (≤ 0,1 m) ──────────────────────────────
  // Anillo efectivo de un patio (por id) del último payload pintado; cae a data-vertices.
  function ringPatioPorId(id) {
    if (renderer && renderer._lastPayload) {
      const pls = (renderer._lastPayload.envolvente && renderer._lastPayload.envolvente.plantas)
        || (renderer._lastPayload.edificio && renderer._lastPayload.edificio.plantas) || [];
      for (const planta of pls) {
        for (const p of (planta.patios || [])) {
          if (p.id === id && (p.poligono || p.base)) return p.poligono || p.base;
        }
      }
    }
    const fila = filaPorPatioId(id);
    if (fila && fila.dataset.vertices) {
      try { const v = JSON.parse(fila.dataset.vertices); if (Array.isArray(v) && v.length >= 3) return v; }
      catch (e) { /* corrupto */ }
    }
    return null;
  }

  // Fusiona dos patios en uno conservando AMBAS formas exactas: el backend une los dos
  // anillos con un cuello finísimo (sin envolvente convexa ni relleno). Superficie = SUMA
  // de las dos áreas. El patio A se reutiliza como fusionado (al final de la lista, para
  // que sea él quien se adapte); el B se elimina.
  async function fusionarPatios(idA, idB) {
    const filaA = filaPorPatioId(idA), filaB = filaPorPatioId(idB);
    if (!filaA || !filaB) return;
    // Un patio bloqueado no participa en la fusión.
    if (filaA.dataset.bloqueado === "true" || filaB.dataset.bloqueado === "true") return;
    const inA = filaA.querySelector('input[name="patios"]');
    const inB = filaB.querySelector('input[name="patios"]');
    const areaA = inA ? Number(inA.value) || 0 : 0;
    const areaB = inB ? Number(inB.value) || 0 : 0;
    const suma = areaA + areaB;
    if (suma <= 0) return;
    const ringA = ringPatioPorId(idA), ringB = ringPatioPorId(idB);
    if (!ringA || !ringB) return;
    // El backend (shapely) calcula la unión con cuello fino: conserva las dos formas.
    let fused = null;
    try {
      const resp = await fetch("/modulos/render-calculos/fusionar-patios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ a: ringA, b: ringB }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        mostrarToast(err.detail || "No se pudieron fusionar los patios", true);
        return;
      }
      fused = (await resp.json()).poligono;
    } catch (e) {
      mostrarToast("No se pudieron fusionar los patios", true);
      return;
    }
    if (!Array.isArray(fused) || fused.length < 3) return;
    // El patio A se queda como el fusionado (anillo unido + área = suma).
    filaA.dataset.vertices = JSON.stringify(fused);
    if (inA) inA.value = String(Math.round(suma * 100) / 100);
    // Limpia el aviso «no cabe» heredado y baja la prioridad (al final de la lista).
    filaA.classList.remove("rc-patio-fila-nocabe");
    const avisoA = filaA.querySelector(".rc-patio-aviso");
    if (avisoA) { avisoA.hidden = true; avisoA.textContent = ""; }
    const lista = document.getElementById("rc-patios-lista");
    if (lista && filaA.parentElement === lista) lista.appendChild(filaA);
    // Elimina el patio B.
    filaB.remove();
    if (patioEditor) patioEditor.olvidar(idB);
    pedirCalculo();
  }

  // Margen de seguridad (m²) que «Adaptar» resta al área efectiva: el polígono que
  // serializa el backend es aproximado (ring() simplifica + redondea a cm y descarta
  // agujeros), así que pedir el área efectiva EXACTA puede quedar un pelo por encima de
  // lo que cabe y no encajar. Restar este margen garantiza el encaje perdiendo m²
  // imperceptibles. (Reproducido y verificado: con −0.05 encaja en todos los casos.)
  const MARGEN_ADAPTAR_M2 = 0.05;

  // Sincroniza cada fila de patio (por id) con lo devuelto por el backend (PB):
  //  - `data-vertices` = forma EFECTIVA (la adaptada y visible), para editar/persistir
  //    desde ella; así al re-seleccionar NO se revierte a la ideal que asomaba fuera.
  //  - aviso «no cabe»: si la efectiva no alcanza el área asignada, marca la fila en
  //    rojo con el texto del área real lograda + botón «Adaptar».
  function sincronizarPatiosDesdePayload(payload) {
    const plantas = payload?.envolvente?.plantas || payload?.edificio?.plantas || [];
    let patios = [];
    for (const pl of plantas) { if (pl.tipo === "regular") { patios = pl.patios || []; break; } }
    patios.forEach(p => {
      if (!p.id) return;
      const fila = filaPorPatioId(p.id);
      if (!fila) return;
      // Refleja el estado de bloqueo que confirma el backend (persiste entre recálculos).
      aplicarEstadoBloqueo(fila, !!p.bloqueado);
      const forma = p.poligono || p.base;
      if (forma) fila.dataset.vertices = JSON.stringify(forma);
      // Huecos (edificio dentro del patio → anillo): persisten para el siguiente recálculo/guardado.
      if (Array.isArray(p.huecos) && p.huecos.length) fila.dataset.huecos = JSON.stringify(p.huecos);
      else delete fila.dataset.huecos;
      const cabe = p.cabe !== false;
      fila.classList.toggle("rc-patio-fila-nocabe", !cabe);
      let aviso = fila.querySelector(".rc-patio-aviso");
      if (!cabe) {
        if (!aviso) {
          aviso = document.createElement("span");
          aviso.className = "rc-patio-aviso";
          fila.appendChild(aviso);
        }
        const xx = fmt.m2.format(p.area_m2 || 0), yy = fmt.m2.format(p.area_efectiva_m2 || 0);
        aviso.textContent = `El patio de ${xx} m² ahora tiene ${yy} m² y no cabe en esa zona. `;
        // Botón «Adaptar»: adopta la forma EFECTIVA (la que cupo) y fija el área a la que
        // de verdad cabe (la efectiva que calculó el backend, NO la recalculada en JS sobre
        // el polígono aproximado). Los datos viajan en el dataset del botón.
        const efectiva = p.poligono || p.base;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "rc-patio-adaptar";
        btn.textContent = "Adaptar";
        btn.title = `Ajustar el patio a ${yy} m² para que quepa en este hueco`;
        if (efectiva) btn.dataset.vertices = JSON.stringify(efectiva);
        btn.dataset.area = String(p.area_efectiva_m2 || 0);
        aviso.appendChild(btn);
        aviso.hidden = false;
      } else if (aviso) {
        aviso.hidden = true;
        aviso.textContent = "";
      }
    });
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
    wrap.innerHTML = `<select name="tipologias_extra" class="select" data-bloque="${bloque}">${_opcionesTipologia(opciones, inicial)}</select>
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

  // "+ Añadir patio": inserta una fila de patio vacía en la lista.
  const btnPatioAdd = document.getElementById("rc-patio-add");
  const listaPatios = document.getElementById("rc-patios-lista");
  if (btnPatioAdd && listaPatios) {
    btnPatioAdd.addEventListener("click", () => {
      const fila = document.createElement("div");
      fila.className = "rc-patio-fila";
      // Id temporal estable: el patio nuevo se envía sin geometría → el backend lo
      // auto-coloca y devuelve su polígono, que adoptamos por este mismo id.
      fila.dataset.patioId = "tmp-" + (++_patioSeq);
      fila.innerHTML =
        '<input type="number" name="patios" min="0" step="0.5" placeholder="m²"' +
        ' data-bloque="urbanisticos" aria-label="Área del patio (m²)">' +
        '<button type="button" class="rc-patio-bloquear" aria-pressed="false"' +
        ' aria-label="Bloquear patio" title="Bloquear patio (no se podrá editar)">🔓</button>' +
        '<button type="button" class="rc-patio-quitar" aria-label="Quitar patio">×</button>';
      listaPatios.appendChild(fila);
      fila.querySelector("input").focus();
    });
  }

  // Delegación global: click en × elimina la fila de patio.
  form.addEventListener("click", ev => {
    const btn = ev.target.closest(".rc-patio-quitar");
    if (!btn) return;
    const fila = btn.closest(".rc-patio-fila");
    // Un patio bloqueado no se puede borrar: hay que desbloquearlo primero.
    if (fila && fila.dataset.bloqueado === "true") return;
    const id = fila && fila.dataset.patioId;
    if (fila) fila.remove();
    if (patioEditor && id) patioEditor.olvidar(id);
    calcularConDebounce();
  });

  // ─── Bloqueo de patios ────────────────────────────────────────────────
  // Fija el estado bloqueado/desbloqueado de una fila (clase, dataset, input
  // readonly, × deshabilitado, candado) y lo refleja en el objeto del payload
  // (para que el editor del lienzo lo respete en vivo, sin esperar al recálculo).
  function aplicarEstadoBloqueo(fila, bloqueado) {
    if (!fila) return;
    bloqueado = !!bloqueado;
    fila.dataset.bloqueado = bloqueado ? "true" : "";
    if (!bloqueado) delete fila.dataset.bloqueado;
    fila.classList.toggle("rc-patio-fila-bloqueada", bloqueado);
    const input = fila.querySelector('input[name="patios"]');
    if (input) input.readOnly = bloqueado;
    const quitar = fila.querySelector(".rc-patio-quitar");
    if (quitar) quitar.disabled = bloqueado;
    const candado = fila.querySelector(".rc-patio-bloquear");
    if (candado) {
      candado.setAttribute("aria-pressed", bloqueado ? "true" : "false");
      candado.setAttribute("aria-label", bloqueado ? "Desbloquear patio" : "Bloquear patio");
      candado.title = bloqueado ? "Desbloquear patio" : "Bloquear patio (no se podrá editar)";
      candado.textContent = bloqueado ? "🔒" : "🔓";
    }
    // Refleja el estado en el patio del payload activo (el editor lo lee en vivo).
    marcarPatioPayloadBloqueado(fila.dataset.patioId, bloqueado);
  }

  // Marca `bloqueado` en el objeto de patio del último payload pintado (por id), en
  // todas las plantas, para que el editor del lienzo lo respete inmediatamente.
  function marcarPatioPayloadBloqueado(id, bloqueado) {
    if (!id || !renderer || !renderer._lastPayload) return;
    const pl = (renderer._lastPayload.envolvente && renderer._lastPayload.envolvente.plantas)
      || (renderer._lastPayload.edificio && renderer._lastPayload.edificio.plantas) || [];
    for (const planta of pl) {
      for (const p of (planta.patios || [])) {
        if (p.id === id) p.bloqueado = !!bloqueado;
      }
    }
  }

  // Delegación global: click en 🔒/🔓 alterna el bloqueo del patio.
  form.addEventListener("click", ev => {
    const btn = ev.target.closest(".rc-patio-bloquear");
    if (!btn) return;
    const fila = btn.closest(".rc-patio-fila");
    if (!fila) return;
    const bloqueado = fila.dataset.bloqueado !== "true";
    aplicarEstadoBloqueo(fila, bloqueado);
    // Al bloquear, suelta la selección del lienzo y repinta para quitar tiradores.
    if (bloqueado && patioEditor) patioEditor.olvidar(fila.dataset.patioId);
    if (renderer) renderer.repintar();
    // Recalcula: el backend re-prioriza (un bloqueado congela su zona y los vecinos
    // se adaptan alrededor) y persiste el estado en los parámetros del proyecto.
    pedirCalculo();
  });

  // Delegación global: «Adaptar» fija el patio a la forma/área que CABEN en su hueco.
  // Adopta la forma efectiva como nueva base y su área efectiva menos un pequeño margen
  // (MARGEN_ADAPTAR_M2), para que al re-conformar encaje seguro y desaparezca el aviso.
  form.addEventListener("click", ev => {
    const btn = ev.target.closest(".rc-patio-adaptar");
    if (!btn) return;
    const fila = btn.closest(".rc-patio-fila");
    if (!fila) return;
    const input = fila.querySelector('input[name="patios"]');
    if (btn.dataset.vertices) fila.dataset.vertices = btn.dataset.vertices;
    const area = Number(btn.dataset.area) || 0;
    const objetivo = Math.max(0, Math.round((area - MARGEN_ADAPTAR_M2) * 100) / 100);
    if (input && objetivo > 0) input.value = String(objetivo);
    // Limpia el estado de error mientras recalcula (el backend confirmará el encaje).
    fila.classList.remove("rc-patio-fila-nocabe");
    const aviso = fila.querySelector(".rc-patio-aviso");
    if (aviso) { aviso.hidden = true; aviso.textContent = ""; }
    pedirCalculo();
  });

  // ─── Bindings ─────────────────────────────────────────────────────────
  function calcularConDebounce() {
    ESTADO.interaccionUsuario = true;   // cualquier edición habilita el modal de exceso
    aplicarVisibilidad();
    actualizarOpcionesCondicionales();
    if (ESTADO.debounceId) clearTimeout(ESTADO.debounceId);
    ESTADO.debounceId = setTimeout(recalcularAuto, 300);
  }
  form.addEventListener("input", calcularConDebounce);
  form.addEventListener("change", calcularConDebounce);
  // El botón «Calcular capacidad» queda reservado para pintar el render (próxima
  // iteración): el cálculo ya es automático con cada cambio, sin binding aquí.
  if (btnGuardar) btnGuardar.addEventListener("click", guardar);
  if (btnCsv) btnCsv.addEventListener("click", exportCsv);

  // Brújula inicial vacía + handler de rotación → render (no existe en inmueble).
  if (window.RcBrujula && brujulaEl) {
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

  // Si hay proyecto + parcela, primer cálculo automático
  if (estado === "ok") {
    recalcularAuto();
  }
})();
