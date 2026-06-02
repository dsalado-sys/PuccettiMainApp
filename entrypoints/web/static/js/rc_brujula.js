/* §2.4 req.10 — Brújula y orientaciones cardinales de fachada.
   Dibuja un SVG inline en el contenedor #rc-brujula y resalta las fachadas
   según su azimut (en grados desde norte).
*/
(function () {
  "use strict";

  const CARDINAL_DEG = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SO: 225, O: 270, NO: 315 };
  const CARDINAL_LABEL = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

  function svg(tag, attrs, parent) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) {
      for (const k in attrs) el.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(el);
    return el;
  }

  function dibujar(container, orientacionesFachadas) {
    if (!container) return;
    container.innerHTML = "";

    const root = svg("svg", {
      viewBox: "-60 -60 120 120",
      width: "82", height: "82",
      role: "img",
      "aria-label": "Brújula: norte arriba, " +
        (orientacionesFachadas && orientacionesFachadas.length
          ? "fachadas hacia " + orientacionesFachadas.join(", ") + "."
          : "sin fachadas clasificadas."),
    });
    container.appendChild(root);

    svg("circle", { cx: 0, cy: 0, r: 48, fill: "#FFFFFF", stroke: "#B8960C", "stroke-width": 1 }, root);

    // sectores resaltados para cada fachada
    const fachadas = new Set(orientacionesFachadas || []);
    for (const card of CARDINAL_LABEL) {
      const deg = CARDINAL_DEG[card];
      const rad = (deg - 90) * Math.PI / 180; // SVG: 0° = derecha, queremos N arriba
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
      }, root);
    }

    // etiquetas N S E O
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
      }, root);
      t.textContent = e.c;
    }

    // flecha norte (rombo)
    svg("path", {
      d: "M 0,-30 L 6,0 L 0,28 L -6,0 Z",
      fill: "#0A0A0A",
    }, root);
  }

  // API global
  window.RcBrujula = { dibujar };
})();
