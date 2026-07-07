/* Módulo Informe — flujo de estados de los proyectos.
   Una card grande por proyecto: tronco (Parcela → Normativa) que se bifurca en
   una fila por pestaña (escenario de render), cada una con su rama completa
   errores/avisos → Viabilidad → Informe. Un nodo solo se «ilumina» (muestra su
   color real) si el anterior está en verde; excepción: una pestaña en amarillo
   no bloquea a su Viabilidad. Viabilidad e Informe son de proyecto (mismo valor
   repetido en cada fila). Los datos vienen de GET /modulos/informe/datos y el
   flujo lo deriva `contextos/proyectos/flujo.py`.
*/
(function () {
  "use strict";

  // Escapa texto antes de interpolarlo en innerHTML (nombres de proyecto y de
  // escenario son entrada libre del usuario → sin esto, XSS al pintar).
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const panel = document.querySelector(".inf-panel");
  if (!panel) return;
  const puedeEditar = panel.dataset.puedeEditar === "true";

  const STATE = { proyectos: [], filtro: "" };

  // ─── Toast ─────────────────────────────────────────────────────────────
  const toast = document.getElementById("inf-toast");
  function mostrarToast(msg, esError = false) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.toggle("toast--error", esError);
    toast.classList.add("toast--on");
    setTimeout(() => toast.classList.remove("toast--on"), 2200);
  }

  async function fetchSeguro(url, opts) {
    try { return await fetch(url, opts); }
    catch (e) { return { ok: false, redError: true }; }
  }

  // ─── Carga ─────────────────────────────────────────────────────────────
  async function cargarDatos() {
    const resp = await fetchSeguro("/modulos/informe/datos");
    if (!resp.ok) { mostrarError("No se pudieron cargar los proyectos"); return; }
    let data;
    try { data = await resp.json(); }
    catch (e) { mostrarError("Respuesta inválida del servidor"); return; }
    STATE.proyectos = data.proyectos || [];
    repintar();
  }

  function mostrarError(msg) {
    const cont = document.getElementById("inf-lista");
    if (cont) cont.innerHTML = `<p class="inf-vacio">${escapeHtml(msg)}</p>`;
    mostrarToast(msg, true);
  }

  // ─── Filtro ────────────────────────────────────────────────────────────
  function coincide(p, f) {
    return (p.nombre || "").toLowerCase().includes(f)
      || (p.referencia_catastral || "").toLowerCase().includes(f)
      || (p.direccion || "").toLowerCase().includes(f);
  }

  // ─── Render de la lista ────────────────────────────────────────────────
  function repintar() {
    const cont = document.getElementById("inf-lista");
    if (!cont) return;
    const f = STATE.filtro.toLowerCase();
    const visibles = f ? STATE.proyectos.filter(p => coincide(p, f)) : STATE.proyectos;
    cont.innerHTML = "";
    if (!visibles.length) {
      cont.innerHTML = f
        ? '<p class="inf-vacio">Nada coincide con la búsqueda.</p>'
        : '<p class="inf-vacio">Aún no hay proyectos. Crea el primero desde Proyectos.</p>';
      return;
    }
    visibles.forEach(p => cont.appendChild(construirCard(p)));
  }

  // ─── Semáforo / gating ─────────────────────────────────────────────────
  const DIM_NOMBRE = {
    parcela: "Parcela",
    normativa: "Normativa",
    errores_avisos: "Errores y avisos",
    viabilidad: "Viabilidad",
    informe: "Informe",
  };
  const MODO_NOMBRE = {
    "obra-nueva": "Obra nueva",
    "rehabilitacion": "Rehabilitación",
    "inmueble": "Inmueble",
  };

  function esVerde(estado) { return !!estado && estado.color === "verde"; }
  function noEsRojo(estado) { return !!estado && estado.color !== "rojo"; }

  // Estado del botón «Aprobar» (aprueba la Viabilidad → verde). Habilitado solo
  // si el tronco está en verde, ninguna pestaña está en rojo y hay un estudio de
  // viabilidad guardado sin aprobar (amarillo). Si ya está aprobada, se muestra
  // deshabilitado con etiqueta distinta.
  function estadoAprobar(flujo) {
    const viab = flujo.viabilidad || null;
    const escenarios = Array.isArray(flujo.escenarios) ? flujo.escenarios : [];
    if (viab && viab.clave === "estudio_aprobado") {
      return { modo: "aprobado", label: "Viabilidad aprobada" };
    }
    const troncoOk = esVerde(flujo.parcela) && esVerde(flujo.normativa);
    const sinPestanaRoja = escenarios.every(e => !e.errores_avisos || e.errores_avisos.color !== "rojo");
    const viabPresente = viab && viab.clave === "estudio_sin_aprobar";
    if (troncoOk && sinPestanaRoja && viabPresente) {
      return { modo: "habilitado", label: "Aprobar" };
    }
    return { modo: "bloqueado", label: "Aprobar" };
  }

  // Un nodo: `estado` = {clave, etiqueta, color}; `dim` = clave de dimensión;
  // `iluminado` = si muestra su color real (o gris/atenuado si bloqueado).
  function nodoHtml(dim, estado, iluminado) {
    const color = iluminado && estado ? estado.color : null;
    const claseColor = color === "verde" ? "inf-nodo--verde"
      : color === "amarillo" ? "inf-nodo--ambar"
        : color === "rojo" ? "inf-nodo--rojo"
          : "inf-nodo--bloqueado";
    const etiqueta = estado && estado.etiqueta ? estado.etiqueta : "—";
    return (
      `<div class="inf-nodo ${claseColor}">` +
      `<span class="inf-luz" aria-hidden="true"></span>` +
      `<span class="inf-nodo-txt">` +
      `<span class="inf-nodo-dim">${escapeHtml(DIM_NOMBRE[dim] || dim)}</span>` +
      `<span class="inf-nodo-estado">${escapeHtml(etiqueta)}</span>` +
      `</span></div>`
    );
  }

  function conectorHtml() {
    return '<span class="inf-conector" aria-hidden="true"></span>';
  }

  function construirCard(p) {
    const flujo = p.flujo || {};
    const parcela = flujo.parcela || null;
    const normativa = flujo.normativa || null;
    const viab = flujo.viabilidad || null;
    const informe = flujo.informe || null;
    const escenarios = Array.isArray(flujo.escenarios) ? flujo.escenarios : [];

    // Gating del tronco.
    const normativaIluminada = esVerde(parcela);

    // Filas por pestaña.
    let filasHtml;
    if (!escenarios.length) {
      filasHtml =
        '<div class="inf-rama inf-rama--vacia">' +
        '<span class="inf-rama-nota">Sin escenarios de render todavía.</span>' +
        '</div>';
    } else {
      filasHtml = escenarios.map(e => {
        const ea = e.errores_avisos || null;
        const eaIluminado = normativaIluminada;              // depende de Normativa verde
        const viabIluminado = eaIluminado && noEsRojo(ea);    // excepción: amarillo no bloquea
        const infIluminado = viabIluminado && esVerde(viab);  // Viab no es pestaña → su amarillo bloquea
        const modo = MODO_NOMBRE[e.modo] || e.modo || "";
        const chip = (modo ? modo + " · " : "") + (e.nombre || "Escenario");
        return (
          '<div class="inf-rama">' +
          `<span class="inf-rama-chip" title="${escapeHtml(chip)}">${escapeHtml(chip)}</span>` +
          '<div class="inf-rama-nodos">' +
          nodoHtml("errores_avisos", ea, eaIluminado) +
          conectorHtml() +
          nodoHtml("viabilidad", viab, viabIluminado) +
          conectorHtml() +
          nodoHtml("informe", informe, infIluminado) +
          '</div></div>'
        );
      }).join("");
    }

    const subtitulo = p.referencia_catastral || p.direccion || "Sin parcela aún";
    const apr = estadoAprobar(flujo);
    const aprDeshabilitado = apr.modo !== "habilitado";
    const botones = puedeEditar
      ? '<footer class="inf-card-acciones">' +
        '<button type="button" class="boton-secundario inf-btn-revisar">Revisar proyecto</button>' +
        `<button type="button" class="boton-primario inf-btn-aprobar"${aprDeshabilitado ? " disabled" : ""}>` +
        `${escapeHtml(apr.label)}</button>` +
        '</footer>'
      : "";

    const card = document.createElement("article");
    card.className = "aviso inf-card";
    card.innerHTML =
      '<header class="inf-card-cab">' +
      `<h2 class="inf-card-titulo">${escapeHtml(p.nombre)}</h2>` +
      `<span class="inf-card-sub">${escapeHtml(subtitulo)}</span>` +
      '</header>' +
      '<div class="inf-flujo">' +
      '<div class="inf-tronco">' +
      nodoHtml("parcela", parcela, true) +
      conectorHtml() +
      nodoHtml("normativa", normativa, normativaIluminada) +
      '</div>' +
      `<div class="inf-ramas">${filasHtml}</div>` +
      '</div>' +
      botones;

    // «Revisar proyecto» sigue como placeholder (se cableará más adelante).
    const rev = card.querySelector(".inf-btn-revisar");
    if (rev) rev.addEventListener("click", () => mostrarToast("Revisión: función pendiente"));
    // «Aprobar» aprueba la viabilidad del proyecto (→ verde).
    const btnApr = card.querySelector(".inf-btn-aprobar");
    if (btnApr && !btnApr.disabled) btnApr.addEventListener("click", () => aprobarProyecto(p.id));
    return card;
  }

  // ─── Aprobar ───────────────────────────────────────────────────────────
  async function aprobarProyecto(proyectoId) {
    const resp = await fetchSeguro(`/modulos/informe/${encodeURIComponent(proyectoId)}/aprobar`, {
      method: "POST",
    });
    if (!resp.ok) {
      if (resp.status === 409) { mostrarToast("No hay estudio de viabilidad que aprobar", true); return; }
      if (resp.status === 403) { mostrarToast("No tienes permiso para aprobar", true); return; }
      mostrarToast("No se pudo aprobar", true);
      return;
    }
    mostrarToast("Viabilidad aprobada");
    await cargarDatos();   // recarga y repinta con el nuevo flujo
  }

  // ─── Bindings ──────────────────────────────────────────────────────────
  const inpBuscar = document.getElementById("inf-buscar");
  if (inpBuscar) inpBuscar.addEventListener("input", () => {
    STATE.filtro = inpBuscar.value.trim();
    repintar();
  });

  cargarDatos();
})();
