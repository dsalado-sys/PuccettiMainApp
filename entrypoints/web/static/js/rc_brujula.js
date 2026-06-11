/* §2.4 req.10 — Brújula y orientaciones cardinales de fachada.
   Dibuja un SVG inline en el contenedor #rc-brujula y resalta las fachadas
   según su azimut. Soporta interacción de rotación: mantener pulsado y
   arrastrar gira el render; click sin arrastre vuelve a 0° (norte arriba).
*/
(function () {
  "use strict";

  const CARDINAL_DEG = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SO: 225, O: 270, NO: 315 };
  const CARDINAL_LABEL = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

  const STATE = {
    container: null,
    rotationDeg: 0,
    dragging: false,
    moved: false,
    startAngle: 0,
    startRotation: 0,
    onRotate: null,
  };

  function svg(tag, attrs, parent) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) {
      for (const k in attrs) el.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(el);
    return el;
  }

  function _renderSvg(container, orientacionesFachadas) {
    container.innerHTML = "";

    const root = svg("svg", {
      viewBox: "-60 -60 120 120",
      width: "82", height: "82",
      role: "img",
      class: "rc-brujula-svg",
      "aria-label": "Brújula girable: norte arriba. " +
        "Mantén pulsado y arrastra para rotar el render; pulsa para volver a 0°.",
    });
    container.appendChild(root);

    const gira = svg("g", { class: "rc-brujula-gira", transform: `rotate(${STATE.rotationDeg})` }, root);

    svg("circle", { cx: 0, cy: 0, r: 48, fill: "#FFFFFF", stroke: "#B8960C", "stroke-width": 1 }, gira);

    const fachadas = new Set(orientacionesFachadas || []);
    for (const card of CARDINAL_LABEL) {
      const deg = CARDINAL_DEG[card];
      const rad = (deg - 90) * Math.PI / 180;
      const x1 = Math.cos(rad) * 30;
      const y1 = Math.sin(rad) * 30;
      const x2 = Math.cos(rad) * 44;
      const y2 = Math.sin(rad) * 44;
      const activo = fachadas.has(card);
      svg("line", {
        x1, y1, x2, y2,
        stroke: activo ? "#B8960C" : "#B8B6AE",
        "stroke-width": activo ? 2 : 1,
        "stroke-linecap": "round",
      }, gira);
    }

    const etiquetas = [
      { c: "N", x: 0, y: -38, dy: 4 },
      { c: "E", x: 38, y: 0, dy: 4 },
      { c: "S", x: 0, y: 42, dy: 0 },
      { c: "O", x: -38, y: 0, dy: 4 },
    ];
    for (const e of etiquetas) {
      const t = svg("text", {
        x: e.x, y: e.y, "text-anchor": "middle", dy: e.dy,
        "font-family": "Helvetica Neue, Inter, sans-serif",
        "font-size": "11", "font-weight": "700",
        fill: e.c === "N" ? "#0A0A0A" : "#444",
      }, gira);
      t.textContent = e.c;
    }

    svg("path", {
      d: "M 0,-30 L 6,0 L 0,28 L -6,0 Z",
      fill: "#0A0A0A",
    }, gira);

    root.style.cursor = "grab";
    root.addEventListener("mousedown", _onDown);
    root.addEventListener("touchstart", _onDown, { passive: false });
  }

  function _angleFromCenter(container, clientX, clientY) {
    const rect = container.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    return Math.atan2(clientX - cx, -(clientY - cy)) * 180 / Math.PI;
  }

  function _onDown(ev) {
    ev.preventDefault();
    const touch = ev.touches ? ev.touches[0] : ev;
    STATE.dragging = true;
    STATE.moved = false;
    STATE.startAngle = _angleFromCenter(STATE.container, touch.clientX, touch.clientY);
    STATE.startRotation = STATE.rotationDeg;
    const svgEl = STATE.container.querySelector(".rc-brujula-svg");
    if (svgEl) svgEl.style.cursor = "grabbing";
    window.addEventListener("mousemove", _onMove);
    window.addEventListener("mouseup", _onUp);
    window.addEventListener("touchmove", _onMove, { passive: false });
    window.addEventListener("touchend", _onUp);
  }

  function _onMove(ev) {
    if (!STATE.dragging) return;
    ev.preventDefault();
    const touch = ev.touches ? ev.touches[0] : ev;
    const ang = _angleFromCenter(STATE.container, touch.clientX, touch.clientY);
    const delta = ang - STATE.startAngle;
    if (Math.abs(delta) > 2) STATE.moved = true;
    const nuevo = ((STATE.startRotation + delta) % 360 + 360) % 360;
    _aplicarRotacion(nuevo);
  }

  function _onUp() {
    if (!STATE.dragging) return;
    STATE.dragging = false;
    const svgEl = STATE.container.querySelector(".rc-brujula-svg");
    if (svgEl) svgEl.style.cursor = "grab";
    window.removeEventListener("mousemove", _onMove);
    window.removeEventListener("mouseup", _onUp);
    window.removeEventListener("touchmove", _onMove);
    window.removeEventListener("touchend", _onUp);
    if (!STATE.moved) {
      _aplicarRotacion(0);
    }
  }

  function _aplicarRotacion(deg) {
    STATE.rotationDeg = deg;
    const g = STATE.container && STATE.container.querySelector("g.rc-brujula-gira");
    if (g) g.setAttribute("transform", `rotate(${deg})`);
    if (typeof STATE.onRotate === "function") STATE.onRotate(deg);
  }

  function dibujar(container, orientacionesFachadas) {
    if (!container) return;
    STATE.container = container;
    _renderSvg(container, orientacionesFachadas);
  }

  function onRotate(cb) { STATE.onRotate = cb; }
  function getRotation() { return STATE.rotationDeg; }
  function reset() { _aplicarRotacion(0); }

  window.RcBrujula = { dibujar, onRotate, getRotation, reset };
})();
