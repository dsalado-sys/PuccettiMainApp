/* Módulo Proyectos — layout 2 columnas (espejo de Normativa municipal).
   Carpetas <details> a la izquierda con sus proyectos dentro (más un grupo
   «Sin carpeta»). Click en un proyecto carga su detalle a la derecha, desde
   donde se abre (proyecto activo), se deselecciona, se mueve de carpeta o se
   elimina.
*/
(function () {
  "use strict";

  // Escapa texto antes de interpolarlo en innerHTML: nombres de carpeta y
  // proyecto son entrada libre del usuario (sin esto, un nombre con
  // `<img src=x onerror=...>` se ejecutaría al pintar la lista → XSS).
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const layout = document.querySelector(".pr-layout");
  if (!layout) return;
  const puedeEditar = layout.dataset.puedeEditar === "true";

  const API = "/proyectos";
  const SIN_CARPETA = "sin"; // clave del grupo de proyectos sin carpeta

  const STATE = {
    carpetas: [],          // [{id, nombre}]
    proyectos: [],         // [{id, nombre, referencia_catastral, direccion, estado, actualizado_en, carpeta_id}]
    activoId: layout.dataset.activoId || null,
    seleccionadoId: null,  // proyecto cuyo detalle se ve a la derecha
    filtro: "",
    abiertas: new Set(),   // claves de carpeta abiertas (id numérico o SIN_CARPETA)
  };

  // Oculta/muestra un elemento por id sin romper si no existe (la plantilla
  // puede no incluir el placeholder de estado vacío).
  function setHidden(id, hidden) {
    const e = document.getElementById(id);
    if (e) e.hidden = hidden;
  }

  const toast = document.getElementById("pr-toast");
  function mostrarToast(msg, esError = false) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.toggle("toast--error", esError);
    toast.classList.add("toast--on");
    setTimeout(() => toast.classList.remove("toast--on"), 2200);
  }

  // fetch que nunca lanza: ante error de red devuelve {ok:false} para que los
  // chequeos `resp.ok` muestren su toast de error en vez de un rechazo suelto.
  async function fetchSeguro(url, opts) {
    try { return await fetch(url, opts); }
    catch (e) { return { ok: false, redError: true }; }
  }

  // ─── Submodales ──────────────────────────────────────────────────────
  function abrir(id) {
    const d = document.getElementById(id);
    if (d && d.showModal) d.showModal();
    else if (d) d.setAttribute("open", "");
    return d;
  }
  function cerrar(id) {
    const d = document.getElementById(id);
    if (d && d.close) d.close();
    else if (d) d.removeAttribute("open");
  }
  document.querySelectorAll("[data-cerrar]").forEach(b => {
    b.addEventListener("click", () => cerrar(b.dataset.cerrar));
  });

  function pedirConfirmacion(mensaje, onAceptar) {
    const msgEl = document.getElementById("pr-submodal-confirmar-msg");
    const okBtn = document.getElementById("pr-submodal-confirmar-ok");
    if (!msgEl || !okBtn) return;
    msgEl.textContent = mensaje;
    const clon = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(clon, okBtn);
    clon.addEventListener("click", () => {
      cerrar("pr-submodal-confirmar");
      onAceptar();
    });
    abrir("pr-submodal-confirmar");
  }

  // ─── Carga ───────────────────────────────────────────────────────────
  async function cargarDatos() {
    const resp = await fetchSeguro(`${API}/datos`);
    if (!resp.ok) { mostrarToast("No se pudieron cargar los proyectos", true); return; }
    let data;
    try { data = await resp.json(); }
    catch (e) { mostrarToast("Respuesta inválida del servidor", true); return; }
    STATE.carpetas = data.carpetas || [];
    STATE.proyectos = data.proyectos || [];
    STATE.activoId = data.activo_id || null;
    // Abrir por defecto la carpeta del proyecto activo (si lo hay).
    if (STATE.activoId) {
      const act = STATE.proyectos.find(p => p.id === STATE.activoId);
      if (act) STATE.abiertas.add(act.carpeta_id == null ? SIN_CARPETA : act.carpeta_id);
    }
    repintar();
    if (STATE.seleccionadoId) pintarDetalle(STATE.seleccionadoId);
  }

  function proyectosDeCarpeta(carpetaId) {
    return STATE.proyectos.filter(p =>
      carpetaId === SIN_CARPETA ? p.carpeta_id == null : p.carpeta_id === carpetaId
    );
  }

  function coincide(p, f) {
    return (p.nombre || "").toLowerCase().includes(f)
      || (p.referencia_catastral || "").toLowerCase().includes(f)
      || (p.direccion || "").toLowerCase().includes(f);
  }

  // ─── Render columna izquierda ────────────────────────────────────────
  function repintar() {
    const cont = document.getElementById("pr-lista");
    if (!cont) return;
    const f = STATE.filtro.toLowerCase();
    cont.innerHTML = "";

    // Grupos: una entrada por carpeta + el grupo «Sin carpeta» al final.
    const grupos = STATE.carpetas.map(c => ({ key: c.id, nombre: c.nombre, esSin: false }));
    grupos.push({ key: SIN_CARPETA, nombre: "Sin carpeta", esSin: true });

    let algo = false;
    grupos.forEach(g => {
      const todos = proyectosDeCarpeta(g.key);
      const nombreMatch = !g.esSin && g.nombre.toLowerCase().includes(f);
      const visibles = f && !nombreMatch ? todos.filter(p => coincide(p, f)) : todos;
      // Con filtro activo, ocultar carpetas sin coincidencias (salvo match de nombre).
      if (f && !nombreMatch && !visibles.length) return;
      // El grupo «Sin carpeta» solo aparece si tiene proyectos.
      if (g.esSin && !todos.length) return;
      algo = true;
      cont.appendChild(construirCarpeta(g, visibles, !!f));
    });

    if (!algo) {
      cont.innerHTML = f
        ? '<p class="pr-vacio">Nada coincide con la búsqueda.</p>'
        : '<p class="pr-vacio">Aún no hay proyectos. Crea el primero.</p>';
    }
  }

  function construirCarpeta(g, proyectos, filtrando) {
    const det = document.createElement("details");
    det.className = "carpeta" + (g.esSin ? " carpeta--clara" : "");
    det.dataset.key = g.key;
    det.open = STATE.abiertas.has(g.key) || filtrando;

    const sum = document.createElement("summary");
    sum.className = "carpeta-summary";
    const accionesCarpeta = (!g.esSin && puedeEditar)
      ? '<span class="carpeta-acciones">' +
        '<button type="button" class="icon-btn icon-btn--peligro pr-btn-borrar-carpeta" ' +
        'title="Eliminar carpeta" aria-label="Eliminar carpeta">×</button>' +
        '</span>'
      : '';
    sum.innerHTML =
      `<span class="carpeta-nombre">${escapeHtml(g.nombre)}</span>` +
      `<span class="carpeta-cuenta">${proyectosDeCarpeta(g.key).length}</span>` +
      accionesCarpeta;
    det.appendChild(sum);

    det.addEventListener("toggle", () => {
      if (det.open) STATE.abiertas.add(g.key);
      else STATE.abiertas.delete(g.key);
    });

    const btnDel = sum.querySelector(".pr-btn-borrar-carpeta");
    if (btnDel) btnDel.addEventListener("click", ev => {
      ev.preventDefault(); ev.stopPropagation();
      pedirConfirmacion(
        `¿Eliminar la carpeta "${g.nombre}"? Sus proyectos no se borran: pasan a «Sin carpeta».`,
        () => eliminarCarpeta(g.key),
      );
    });

    const ul = document.createElement("ul");
    ul.className = "pr-proyectos";
    if (!proyectos.length) {
      ul.innerHTML = '<li class="pr-vacio">Carpeta vacía.</li>';
    } else {
      proyectos.forEach(p => ul.appendChild(construirProyecto(p)));
    }
    det.appendChild(ul);
    return det;
  }

  function construirProyecto(p) {
    const li = document.createElement("li");
    li.className = "pr-proyecto-item";
    if (STATE.seleccionadoId === p.id) li.classList.add("pr-proyecto-sel");
    li.dataset.id = p.id;
    const esActivo = STATE.activoId === p.id;
    const badge = esActivo ? '<span class="badge badge--oro-solido">Activo</span>' : '';
    li.innerHTML =
      `<button type="button" class="pr-proy-cargar">` +
      `<strong>${escapeHtml(p.nombre)}${badge}</strong>` +
      `<small>${escapeHtml(p.referencia_catastral || p.direccion || "Sin parcela aún")}</small>` +
      `</button>`;
    li.querySelector(".pr-proy-cargar").addEventListener("click", () => seleccionar(p.id));
    return li;
  }

  // Etiqueta humana del estado del proyecto (EstadoProyecto del núcleo) para la
  // pill. Valor desconocido → se muestra tal cual como fallback.
  const ESTADO_ETIQUETA = {
    borrador: "Borrador",
    en_analisis: "En análisis",
    entregado: "Entregado",
    archivado: "Archivado",
  };

  // Pinta el estado como .status-pill: oro para «entregado», neutro para el resto,
  // de modo que estado y la insignia «Activo» compartan un mismo lenguaje visual.
  function pintarEstado(estado) {
    const e = document.getElementById("pr-d-estado");
    if (!e) return;
    const v = estado || "";
    e.textContent = ESTADO_ETIQUETA[v] || (v || "—");
    e.classList.toggle("badge--oro", v === "entregado");
    e.classList.toggle("badge--gris", v !== "entregado");
  }

  // ─── Detalle (columna derecha) ───────────────────────────────────────
  function seleccionar(proyectoId) {
    STATE.seleccionadoId = proyectoId;
    document.querySelectorAll(".pr-proyecto-sel").forEach(li => li.classList.remove("pr-proyecto-sel"));
    const li = document.querySelector(`.pr-proyecto-item[data-id="${proyectoId}"]`);
    if (li) li.classList.add("pr-proyecto-sel");
    pintarDetalle(proyectoId);
  }

  function limpiarDetalle() {
    STATE.seleccionadoId = null;
    const titulo = document.getElementById("pr-detalle-titulo");
    if (titulo) titulo.textContent = "Selecciona un proyecto";
    setHidden("pr-detalle", true);
    setHidden("pr-detalle-vacio", false);
    document.querySelectorAll(".pr-proyecto-sel").forEach(li => li.classList.remove("pr-proyecto-sel"));
  }

  function pintarDetalle(proyectoId) {
    const p = STATE.proyectos.find(x => x.id === proyectoId);
    if (!p) { limpiarDetalle(); return; }
    setHidden("pr-detalle-vacio", true);
    setHidden("pr-detalle", false);
    document.getElementById("pr-detalle-titulo").textContent = p.nombre;

    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    set("pr-d-rc", p.referencia_catastral || "—");
    set("pr-d-direccion", p.direccion || "—");
    set("pr-d-actualizado", p.actualizado_en || "—");
    pintarEstado(p.estado);

    const esActivo = STATE.activoId === p.id;
    const aviso = document.getElementById("pr-activo-aviso");
    if (aviso) {
      aviso.classList.toggle("pr-es-activo", esActivo);
      aviso.innerHTML = esActivo
        ? "Este es el <strong>proyecto activo</strong>: los módulos trabajan sobre él."
        : "No es el proyecto activo. Ábrelo para que los módulos trabajen sobre él.";
    }
    const btnAct = document.getElementById("pr-btn-activar");
    const btnDes = document.getElementById("pr-btn-desactivar");
    if (btnAct) btnAct.hidden = esActivo;
    if (btnDes) btnDes.hidden = !esActivo;

    // Selector de carpeta (solo si puede editar; existe en el DOM en ese caso).
    const sel = document.getElementById("pr-d-carpeta");
    if (sel) {
      rellenarSelectCarpetas(sel, p.carpeta_id);
    }
  }

  function rellenarSelectCarpetas(sel, carpetaActual) {
    sel.innerHTML = "";
    const opSin = document.createElement("option");
    opSin.value = ""; opSin.textContent = "Sin carpeta";
    sel.appendChild(opSin);
    STATE.carpetas.forEach(c => {
      const op = document.createElement("option");
      op.value = String(c.id);
      op.textContent = c.nombre;
      sel.appendChild(op);
    });
    sel.value = carpetaActual == null ? "" : String(carpetaActual);
  }

  // ─── Acciones: activar / desactivar ──────────────────────────────────
  async function activar() {
    if (!STATE.seleccionadoId) return;
    const resp = await fetchSeguro(`${API}/${STATE.seleccionadoId}/activar`, { method: "POST" });
    if (!resp.ok) { mostrarToast("No se pudo abrir el proyecto", true); return; }
    STATE.activoId = STATE.seleccionadoId;
    const act = STATE.proyectos.find(p => p.id === STATE.activoId);
    if (act) STATE.abiertas.add(act.carpeta_id == null ? SIN_CARPETA : act.carpeta_id);
    mostrarToast("Proyecto abierto");
    repintar();
    pintarDetalle(STATE.seleccionadoId);
  }

  async function desactivar() {
    const resp = await fetchSeguro(`${API}/desactivar`, { method: "POST" });
    if (!resp.ok) { mostrarToast("No se pudo deseleccionar", true); return; }
    STATE.activoId = null;
    mostrarToast("Proyecto deseleccionado");
    repintar();
    if (STATE.seleccionadoId) pintarDetalle(STATE.seleccionadoId);
  }

  // ─── Acciones: mover / eliminar proyecto ─────────────────────────────
  async function moverProyecto(proyectoId, valorSelect) {
    const carpeta_id = valorSelect === "" ? null : parseInt(valorSelect, 10);
    const resp = await fetchSeguro(`${API}/${proyectoId}/carpeta`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ carpeta_id }),
    });
    if (!resp.ok) { mostrarToast("No se pudo mover", true); return; }
    const p = STATE.proyectos.find(x => x.id === proyectoId);
    if (p) p.carpeta_id = carpeta_id;
    if (carpeta_id != null) STATE.abiertas.add(carpeta_id);
    mostrarToast("Proyecto movido");
    repintar();
  }

  function eliminarProyecto(proyectoId, nombre) {
    pedirConfirmacion(`¿Eliminar el proyecto "${nombre}"? Esta acción no se puede deshacer.`, async () => {
      const resp = await fetchSeguro(`${API}/${proyectoId}`, { method: "DELETE" });
      if (!resp.ok) { mostrarToast("No se pudo eliminar", true); return; }
      STATE.proyectos = STATE.proyectos.filter(p => p.id !== proyectoId);
      if (STATE.activoId === proyectoId) STATE.activoId = null;
      mostrarToast("Proyecto eliminado");
      if (STATE.seleccionadoId === proyectoId) limpiarDetalle();
      repintar();
    });
  }

  // ─── Acciones: crear / eliminar carpeta ──────────────────────────────
  function abrirSubmodalNuevaCarpeta() {
    const inp = document.getElementById("pr-submodal-carpeta-nombre");
    if (inp) inp.value = "";
    abrir("pr-submodal-carpeta");
    if (inp) setTimeout(() => inp.focus(), 50);
  }

  async function guardarNuevaCarpeta() {
    const inp = document.getElementById("pr-submodal-carpeta-nombre");
    const nombre = inp ? inp.value.trim() : "";
    if (!nombre) { mostrarToast("Pon un nombre", true); return; }
    const resp = await fetchSeguro(`${API}/carpetas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre }),
    });
    if (!resp.ok) { mostrarToast("No se pudo crear", true); return; }
    let data; try { data = await resp.json(); } catch (e) { data = null; }
    cerrar("pr-submodal-carpeta");
    mostrarToast("Carpeta creada");
    if (data && data.id != null) STATE.abiertas.add(data.id);
    await cargarDatos();
  }

  async function eliminarCarpeta(carpetaId) {
    const resp = await fetchSeguro(`${API}/carpetas/${carpetaId}`, { method: "DELETE" });
    if (!resp.ok) { mostrarToast("No se pudo eliminar la carpeta", true); return; }
    STATE.abiertas.delete(carpetaId);
    mostrarToast("Carpeta eliminada");
    await cargarDatos();
  }

  // ─── Acciones: crear proyecto ────────────────────────────────────────
  function abrirSubmodalNuevoProyecto() {
    document.getElementById("pr-submodal-proyecto-nombre").value = "";
    const sel = document.getElementById("pr-submodal-proyecto-carpeta");
    // Preseleccionar la carpeta del proyecto seleccionado, si lo hay.
    let pre = "";
    if (STATE.seleccionadoId) {
      const p = STATE.proyectos.find(x => x.id === STATE.seleccionadoId);
      if (p && p.carpeta_id != null) pre = p.carpeta_id;
    }
    rellenarSelectCarpetas(sel, pre);
    abrir("pr-submodal-proyecto");
    setTimeout(() => document.getElementById("pr-submodal-proyecto-nombre").focus(), 50);
  }

  async function guardarNuevoProyecto() {
    const nombre = document.getElementById("pr-submodal-proyecto-nombre").value.trim();
    if (!nombre) { mostrarToast("Pon un nombre", true); return; }
    const valor = document.getElementById("pr-submodal-proyecto-carpeta").value;
    const carpeta_id = valor === "" ? null : parseInt(valor, 10);
    const resp = await fetchSeguro(`${API}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, carpeta_id }),
    });
    if (!resp.ok) { mostrarToast("No se pudo crear el proyecto", true); return; }
    let data; try { data = await resp.json(); } catch (e) { data = null; }
    cerrar("pr-submodal-proyecto");
    mostrarToast("Proyecto creado");
    if (carpeta_id != null) STATE.abiertas.add(carpeta_id);
    else STATE.abiertas.add(SIN_CARPETA);
    await cargarDatos();
    if (data && data.id) seleccionar(data.id);
  }

  // ─── Bindings ────────────────────────────────────────────────────────
  const bind = (id, ev, fn) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(ev, fn);
  };

  bind("pr-btn-nueva-carpeta", "click", abrirSubmodalNuevaCarpeta);
  bind("pr-submodal-carpeta-guardar", "click", guardarNuevaCarpeta);
  const inpCarpeta = document.getElementById("pr-submodal-carpeta-nombre");
  if (inpCarpeta) inpCarpeta.addEventListener("keydown", ev => {
    if (ev.key === "Enter") { ev.preventDefault(); guardarNuevaCarpeta(); }
  });

  bind("pr-btn-nuevo-proyecto", "click", abrirSubmodalNuevoProyecto);
  bind("pr-submodal-proyecto-guardar", "click", guardarNuevoProyecto);
  const inpProy = document.getElementById("pr-submodal-proyecto-nombre");
  if (inpProy) inpProy.addEventListener("keydown", ev => {
    if (ev.key === "Enter") { ev.preventDefault(); guardarNuevoProyecto(); }
  });

  bind("pr-btn-activar", "click", activar);
  bind("pr-btn-desactivar", "click", desactivar);

  const selCarpeta = document.getElementById("pr-d-carpeta");
  if (selCarpeta) selCarpeta.addEventListener("change", () => {
    if (STATE.seleccionadoId) moverProyecto(STATE.seleccionadoId, selCarpeta.value);
  });

  const btnEliminar = document.getElementById("pr-btn-eliminar");
  if (btnEliminar) btnEliminar.addEventListener("click", () => {
    if (!STATE.seleccionadoId) return;
    const p = STATE.proyectos.find(x => x.id === STATE.seleccionadoId);
    if (p) eliminarProyecto(p.id, p.nombre);
  });

  const inpBuscar = document.getElementById("pr-buscar");
  if (inpBuscar) inpBuscar.addEventListener("input", () => {
    STATE.filtro = inpBuscar.value.trim();
    repintar();
  });

  // Carga inicial
  cargarDatos();
})();
