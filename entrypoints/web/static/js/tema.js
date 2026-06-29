/* ════════════════════════════════════════════════════════════════════════
   Puccetti — conmutador de tema (claro / oscuro)
   --------------------------------------------------------------------------
   El tema se materializa con data-theme="dark" en <html> (puccetti.css §1):
   los tokens cambian solos, los módulos no conocen el tema.
   · Persistencia en localStorage ('puccetti-tema').
   · El "anti-flash" lo resuelve un <script> inline pre-paint en <head> que
     fija el atributo ANTES del primer render; aquí solo gestionamos el cambio
     en caliente y la sincronización del botón.
   · Atajo de teclado: Ctrl+O (también Cmd+O). Se hace preventDefault para
     anular el "abrir archivo" del navegador.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";
  var CLAVE = "puccetti-tema";
  var _limpiarTrans = null;

  function temaActual() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  // Activa una transición de color SUAVE solo durante el cambio de tema (no en la
  // carga ni en hovers): clase temporal en <html> que el CSS usa para animar, y
  // que se retira al terminar para no ralentizar el resto de interacciones.
  function transicionarTema() {
    var raiz = document.documentElement;
    raiz.classList.add("tema-transicion");
    if (_limpiarTrans) clearTimeout(_limpiarTrans);
    _limpiarTrans = setTimeout(function () {
      raiz.classList.remove("tema-transicion");
      _limpiarTrans = null;
    }, 600);
  }

  function sincronizarBoton(tema) {
    var btn = document.querySelector("[data-tema-toggle]");
    if (!btn) return;
    var oscuro = tema === "dark";
    btn.setAttribute("aria-pressed", String(oscuro));
    var etiqueta = oscuro ? "Cambiar a tema claro (Ctrl+O)" : "Cambiar a tema oscuro (Ctrl+O)";
    btn.setAttribute("aria-label", etiqueta);
    btn.setAttribute("title", etiqueta);
  }

  function aplicar(tema) {
    transicionarTema();
    if (tema === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
    }
    try { localStorage.setItem(CLAVE, tema); } catch (e) { /* almacenamiento bloqueado: el tema vive solo en esta página */ }
    sincronizarBoton(tema);
  }

  function alternar() {
    aplicar(temaActual() === "dark" ? "light" : "dark");
  }

  // Sincroniza el botón con el estado fijado por el script pre-paint.
  document.addEventListener("DOMContentLoaded", function () {
    sincronizarBoton(temaActual());
    var btn = document.querySelector("[data-tema-toggle]");
    if (btn) btn.addEventListener("click", alternar);
  });

  // Ctrl+O / Cmd+O — alternar tema (sin modificar el comportamiento si hay Alt/Shift).
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "o" || e.key === "O")) {
      e.preventDefault();
      alternar();
    }
  });
})();
