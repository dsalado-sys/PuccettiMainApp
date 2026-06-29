/* Módulo Normativa municipal — layout 2 columnas.
   Carpetas <details> a la izquierda (con normativas en su interior). Click en
   una normativa carga su detalle en el formulario de la derecha.
*/
(function () {
  "use strict";

  // Escapa texto antes de interpolarlo en innerHTML. Los nombres de carpeta y
  // normativa son entrada libre del usuario: sin esto, un nombre con
  // `<img src=x onerror=...>` se ejecutaría al pintar la lista (XSS almacenado).
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const layout = document.querySelector(".nm-layout");
  if (!layout) return;
  const puedeEditar = layout.dataset.puedeEditar === "true";

  const API = "/modulos/normativa-municipal";

  const STATE = {
    carpetas: [],            // [{id, nombre}]
    filtro: "",
    normativasPorCarpeta: {}, // id → [{id, nombre, direccion}]
    seleccionada: null,       // id de normativa
  };

  const toast = document.getElementById("nm-toast");
  function mostrarToast(msg, esError = false) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.toggle("toast--error", esError);
    toast.classList.add("toast--on");
    setTimeout(() => toast.classList.remove("toast--on"), 2200);
  }

  // fetch que nunca lanza: ante un error de red (servidor caído, sin conexión)
  // devuelve un objeto con `ok:false` para que los chequeos `resp.ok` de los
  // mutadores muestren su toast de error en vez de un rechazo sin capturar.
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
    const msgEl = document.getElementById("nm-submodal-confirmar-msg");
    const okBtn = document.getElementById("nm-submodal-confirmar-ok");
    if (!msgEl || !okBtn) return;
    msgEl.textContent = mensaje;
    const clon = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(clon, okBtn);
    clon.addEventListener("click", () => {
      cerrar("nm-submodal-confirmar");
      onAceptar();
    });
    abrir("nm-submodal-confirmar");
  }

  // ─── Cargas iniciales ────────────────────────────────────────────────
  async function cargarCarpetas() {
    try {
      const resp = await fetch(`${API}/carpetas`);
      if (!resp.ok) { mostrarToast("No se pudieron cargar las carpetas", true); return; }
      const data = await resp.json();
      STATE.carpetas = data.carpetas || [];
      repintarCarpetas();
    } catch (e) { mostrarToast("Error de red al cargar las carpetas", true); }
  }

  async function cargarNormativasDeCarpeta(carpetaId, ul) {
    try {
      const resp = await fetch(`${API}/carpetas/${carpetaId}/normativas`);
      if (!resp.ok) { ul.innerHTML = '<li class="nm-vacio">Error.</li>'; return; }
      const data = await resp.json();
      STATE.normativasPorCarpeta[carpetaId] = data.normativas || [];
      pintarNormativas(carpetaId, ul);
    } catch (e) { ul.innerHTML = '<li class="nm-vacio">Error de red.</li>'; }
  }

  // ─── Render columna izquierda ────────────────────────────────────────
  function repintarCarpetas() {
    const cont = document.getElementById("nm-lista");
    if (!cont) return;
    const filtro = STATE.filtro.toLowerCase();
    const items = filtro
      ? STATE.carpetas.filter(c => c.nombre.toLowerCase().includes(filtro))
      : STATE.carpetas;
    cont.innerHTML = "";
    if (!items.length) {
      cont.innerHTML = filtro
        ? '<p class="nm-vacio">Ninguna carpeta coincide.</p>'
        : '<p class="nm-vacio">Sin carpetas todavía.</p>';
      return;
    }
    items.forEach(c => {
      const det = document.createElement("details");
      det.className = "carpeta";
      det.dataset.id = c.id;
      const sum = document.createElement("summary");
      sum.className = "carpeta-summary";
      sum.innerHTML = `<span class="carpeta-nombre">${escapeHtml(c.nombre)}</span>
        <span class="carpeta-acciones">
          ${puedeEditar ? '<button type="button" class="icon-btn nm-btn-nueva-norma" title="Crear normativa" aria-label="Crear normativa">+</button>' : ''}
          ${puedeEditar ? '<button type="button" class="icon-btn icon-btn--peligro nm-btn-borrar-carpeta" title="Eliminar carpeta" aria-label="Eliminar carpeta">×</button>' : ''}
        </span>`;
      det.appendChild(sum);
      const ul = document.createElement("ul");
      ul.className = "nm-normativas";
      ul.innerHTML = '<li class="nm-vacio">Cargando…</li>';
      det.appendChild(ul);

      sum.setAttribute("aria-expanded", "false");
      det.addEventListener("toggle", () => {
        sum.setAttribute("aria-expanded", det.open ? "true" : "false");
        if (det.open) cargarNormativasDeCarpeta(c.id, ul);
      });
      const btnAdd = sum.querySelector(".nm-btn-nueva-norma");
      if (btnAdd) btnAdd.addEventListener("click", ev => {
        ev.preventDefault(); ev.stopPropagation();
        abrirSubmodalNuevaNormativa(c.id);
      });
      const btnDel = sum.querySelector(".nm-btn-borrar-carpeta");
      if (btnDel) btnDel.addEventListener("click", ev => {
        ev.preventDefault(); ev.stopPropagation();
        pedirConfirmacion(`¿Eliminar la carpeta "${c.nombre}" y todas sus normativas?`, async () => {
          const resp = await fetchSeguro(`${API}/carpetas/${c.id}`, { method: "DELETE" });
          if (!resp.ok) { mostrarToast("No se pudo eliminar", true); return; }
          mostrarToast("Carpeta eliminada");
          cargarCarpetas();
          if (STATE.seleccionada) limpiarDetalle();
        });
      });
      cont.appendChild(det);
    });
  }

  function pintarNormativas(carpetaId, ul) {
    const items = STATE.normativasPorCarpeta[carpetaId] || [];
    ul.innerHTML = "";
    if (!items.length) {
      ul.innerHTML = '<li class="nm-vacio">Carpeta vacía.</li>';
      return;
    }
    items.forEach(n => {
      const li = document.createElement("li");
      li.className = "nm-normativa-item";
      if (STATE.seleccionada === n.id) li.classList.add("nm-normativa-activa");
      li.dataset.id = n.id;
      li.innerHTML = `<button type="button" class="nm-norma-cargar">
          <strong>${escapeHtml(n.nombre)}</strong>
          <small>${escapeHtml(n.direccion || "—")}</small>
        </button>
        ${puedeEditar ? '<button type="button" class="nm-norma-borrar" title="Eliminar" aria-label="Eliminar normativa">×</button>' : ''}`;
      li.querySelector(".nm-norma-cargar").addEventListener("click", () => {
        cargarDetalle(n.id, carpetaId);
      });
      const btn = li.querySelector(".nm-norma-borrar");
      if (btn) btn.addEventListener("click", () => {
        pedirConfirmacion(`¿Eliminar "${n.nombre}"?`, async () => {
          const resp = await fetchSeguro(`${API}/normativas/${n.id}`, { method: "DELETE" });
          if (!resp.ok) { mostrarToast("No se pudo eliminar", true); return; }
          mostrarToast("Normativa eliminada");
          cargarNormativasDeCarpeta(carpetaId, ul);
          if (STATE.seleccionada === n.id) limpiarDetalle();
        });
      });
      ul.appendChild(li);
    });
  }

  // ─── Detalle (columna derecha) ───────────────────────────────────────
  function limpiarDetalle() {
    STATE.seleccionada = null;
    document.getElementById("nm-detalle-titulo").textContent = "Selecciona una normativa";
    document.getElementById("nm-detalle-acciones").hidden = true;
    document.getElementById("nm-detalle-form").hidden = true;
    document.getElementById("nm-detalle-vacio").hidden = false;
    document.querySelectorAll(".nm-normativa-activa").forEach(li => li.classList.remove("nm-normativa-activa"));
  }

  async function cargarDetalle(normativaId, carpetaId) {
    try {
      const resp = await fetch(`${API}/normativas/${normativaId}`);
      if (!resp.ok) { mostrarToast("No se pudo cargar", true); return; }
      const data = await resp.json();
      STATE.seleccionada = normativaId;
      document.querySelectorAll(".nm-normativa-activa").forEach(li => li.classList.remove("nm-normativa-activa"));
      const li = document.querySelector(`.nm-normativa-item[data-id="${normativaId}"]`);
      if (li) li.classList.add("nm-normativa-activa");

      document.getElementById("nm-detalle-vacio").hidden = true;
      document.getElementById("nm-detalle-form").hidden = false;
      document.getElementById("nm-detalle-acciones").hidden = false;
      document.getElementById("nm-detalle-titulo").textContent = data.nombre;

      const urb = data.urbanisticos || {};
      const set = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
      set("nm-f-nombre", data.nombre || "");
      set("nm-f-direccion", data.direccion || "");
      set("nm-f-coef", urb.coeficiente_edificabilidad ?? 2.5);
      set("nm-f-ocup", urb.ocupacion_maxima_pct ?? 100);
      set("nm-f-plantas", urb.n_plantas_max ?? 3);
      set("nm-f-rfach", urb.retranqueo_fachada_m ?? 0);
      set("nm-f-rlind", urb.retranqueo_linderos_m ?? 0);
      set("nm-f-ratico", urb.retranqueo_atico_m ?? 3);
      set("nm-f-anchofach", urb.ancho_min_fachada_m ?? 5);
      set("nm-f-luz", urb.luz_recta_patio_min_m ?? 3);
      set("nm-f-areapatio", urb.area_patio_min_m2 ?? 12);
      set("nm-f-vest", urb.diametro_max_vestibulo_m ?? 1.5);
      set("nm-f-emurom", urb.espesor_muro_medianero_max_m ?? 0.25);
      set("nm-f-eseppu", urb.espesor_separacion_unidades_max_m ?? 0.20);
      set("nm-f-etab", urb.espesor_tabique_min_m ?? 0.10);
      set("nm-f-pasc", urb.ancho_min_pasillo_comun_m ?? 1.20);
      set("nm-f-pasv", urb.ancho_min_pasillo_vivienda_m ?? 1.00);
      set("nm-f-puerta", urb.ancho_min_puerta_m ?? 0.80);

      const usos = urb.usos_permitidos || ["residencial"];
      document.querySelectorAll(".nm-f-uso").forEach(cb => {
        cb.checked = usos.includes(cb.value);
      });
    } catch (e) { mostrarToast("Error de red", true); }
  }

  function leerDetalle() {
    const valof = (id, def) => {
      const e = document.getElementById(id);
      const v = e ? parseFloat(e.value) : NaN;
      return Number.isFinite(v) ? v : def;
    };
    const ivalof = (id, def) => {
      const e = document.getElementById(id);
      const v = e ? parseInt(e.value) : NaN;
      return Number.isFinite(v) ? v : def;
    };
    const usos = [];
    document.querySelectorAll(".nm-f-uso").forEach(cb => {
      if (cb.checked) usos.push(cb.value);
    });
    return {
      nombre: document.getElementById("nm-f-nombre").value.trim(),
      direccion: document.getElementById("nm-f-direccion").value.trim(),
      urbanisticos: {
        coeficiente_edificabilidad: valof("nm-f-coef", 2.5),
        ocupacion_maxima_pct: valof("nm-f-ocup", 100),
        n_plantas_max: ivalof("nm-f-plantas", 3),
        retranqueo_fachada_m: valof("nm-f-rfach", 0),
        retranqueo_linderos_m: valof("nm-f-rlind", 0),
        retranqueo_atico_m: valof("nm-f-ratico", 3),
        ancho_min_fachada_m: valof("nm-f-anchofach", 5),
        luz_recta_patio_min_m: valof("nm-f-luz", 3),
        area_patio_min_m2: valof("nm-f-areapatio", 12),
        diametro_max_vestibulo_m: valof("nm-f-vest", 1.5),
        espesor_muro_medianero_max_m: valof("nm-f-emurom", 0.25),
        espesor_separacion_unidades_max_m: valof("nm-f-eseppu", 0.20),
        espesor_tabique_min_m: valof("nm-f-etab", 0.10),
        ancho_min_pasillo_comun_m: valof("nm-f-pasc", 1.20),
        ancho_min_pasillo_vivienda_m: valof("nm-f-pasv", 1.00),
        ancho_min_puerta_m: valof("nm-f-puerta", 0.80),
        usos_permitidos: usos,
      },
    };
  }

  async function guardarDetalle() {
    if (!STATE.seleccionada) return;
    const datos = leerDetalle();
    if (!datos.nombre) { mostrarToast("Falta el nombre", true); return; }
    const resp = await fetchSeguro(`${API}/normativas/${STATE.seleccionada}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    });
    if (resp.ok) {
      mostrarToast("Cambios guardados");
      // refrescar la lista de la carpeta para reflejar el nombre/dirección
      const li = document.querySelector(`.nm-normativa-item[data-id="${STATE.seleccionada}"]`);
      const det = li ? li.closest(".carpeta") : null;
      if (det) {
        const carpetaId = parseInt(det.dataset.id);
        const ul = det.querySelector(".nm-normativas");
        if (ul) cargarNormativasDeCarpeta(carpetaId, ul);
      }
    } else {
      mostrarToast("No se pudo guardar", true);
    }
  }

  // ─── Submodales de creación ──────────────────────────────────────────
  function abrirSubmodalNuevaCarpeta() {
    const inp = document.getElementById("nm-submodal-carpeta-nombre");
    if (inp) inp.value = "";
    abrir("nm-submodal-carpeta");
    if (inp) setTimeout(() => inp.focus(), 50);
  }

  async function guardarNuevaCarpeta() {
    const inp = document.getElementById("nm-submodal-carpeta-nombre");
    const nombre = inp ? inp.value.trim() : "";
    if (!nombre) { mostrarToast("Pon un nombre", true); return; }
    const resp = await fetchSeguro(`${API}/carpetas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre }),
    });
    if (resp.ok) {
      cerrar("nm-submodal-carpeta");
      mostrarToast("Carpeta creada");
      cargarCarpetas();
    } else {
      mostrarToast("No se pudo crear", true);
    }
  }

  let carpetaIdParaNuevaNorma = null;
  function abrirSubmodalNuevaNormativa(carpetaId) {
    carpetaIdParaNuevaNorma = carpetaId;
    document.getElementById("nm-submodal-nueva-nombre").value = "";
    document.getElementById("nm-submodal-nueva-direccion").value = "";
    abrir("nm-submodal-nueva-norma");
    setTimeout(() => document.getElementById("nm-submodal-nueva-nombre").focus(), 50);
  }

  async function guardarNuevaNormativa() {
    if (!carpetaIdParaNuevaNorma) return;
    const nombre = document.getElementById("nm-submodal-nueva-nombre").value.trim();
    const direccion = document.getElementById("nm-submodal-nueva-direccion").value.trim();
    if (!nombre) { mostrarToast("Pon un nombre", true); return; }
    const resp = await fetchSeguro(`${API}/carpetas/${carpetaIdParaNuevaNorma}/normativas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, direccion, urbanisticos: {} }),
    });
    if (resp.ok) {
      const data = await resp.json();
      cerrar("nm-submodal-nueva-norma");
      mostrarToast("Normativa creada");
      const det = document.querySelector(`.carpeta[data-id="${carpetaIdParaNuevaNorma}"]`);
      if (det) {
        const ul = det.querySelector(".nm-normativas");
        if (ul) await cargarNormativasDeCarpeta(carpetaIdParaNuevaNorma, ul);
        if (!det.open) det.open = true;
      }
      // Abrir el detalle de la recién creada para que se pueda editar.
      if (data && data.id) await cargarDetalle(data.id, carpetaIdParaNuevaNorma);
    } else {
      mostrarToast("No se pudo crear", true);
    }
  }

  // ─── Bindings ────────────────────────────────────────────────────────
  const btnNuevaCarpeta = document.getElementById("nm-btn-nueva-carpeta");
  if (btnNuevaCarpeta) btnNuevaCarpeta.addEventListener("click", abrirSubmodalNuevaCarpeta);
  const btnCarpetaGuardar = document.getElementById("nm-submodal-carpeta-guardar");
  if (btnCarpetaGuardar) {
    btnCarpetaGuardar.addEventListener("click", guardarNuevaCarpeta);
    const inp = document.getElementById("nm-submodal-carpeta-nombre");
    if (inp) inp.addEventListener("keydown", ev => {
      if (ev.key === "Enter") { ev.preventDefault(); guardarNuevaCarpeta(); }
    });
  }
  const btnNuevaNormaGuardar = document.getElementById("nm-submodal-nueva-guardar");
  if (btnNuevaNormaGuardar) btnNuevaNormaGuardar.addEventListener("click", guardarNuevaNormativa);

  const btnGuardar = document.getElementById("nm-btn-guardar");
  if (btnGuardar) btnGuardar.addEventListener("click", guardarDetalle);

  const inpBuscar = document.getElementById("nm-buscar");
  if (inpBuscar) inpBuscar.addEventListener("input", () => {
    STATE.filtro = inpBuscar.value.trim();
    repintarCarpetas();
  });

  // Carga inicial
  cargarCarpetas();
})();
