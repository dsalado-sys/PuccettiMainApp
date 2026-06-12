/* §2.4 — Lienzo de dibujo interactivo sobre la parcela (capa manual).
   El centro de Render y cálculos pasa a ser un lienzo: el usuario pinta
   superficies (rectángulos / polígonos) y muros sobre la parcela. Cada pieza
   solo cuenta los m² DENTRO de la parcela (recorte visual con ctx.clip + área
   autoritativa de Shapely en el backend). Los parámetros (izq) y las tablas de
   cálculo (der) no se tocan: este módulo solo posee el canvas #rc-canvas.

   Coordenadas en metros UTM30N (mismo mundo que RenderCanvas). Se reutiliza una
   instancia de RenderCanvas como motor de viewport (_ajustarTamano/_calcViewport
   /_x/_y) y se añade el inverso pantalla→mundo. La rotación se hornea en los
   vértices (se envían ya rotados; el backend ignora el ángulo).
*/
(function () {
  "use strict";

  const form = document.getElementById("rc-form");
  if (!form) return;
  const canvasEl = document.getElementById("rc-canvas");
  if (!canvasEl || !window.RenderCanvas) return;

  // ── Constantes ────────────────────────────────────────────────────────────
  const COLORES = ["#D7263D", "#FFFFFF", "#2E9E5B", "#2D6CDF", "#F2C200"];
  const GROSOR_MURO = 0.3;            // grosor por defecto del muro (m)
  const TOL_VERT = 9, TOL_ROT = 13, TOL_MURO = 7, TOL_CIERRE = 11, UMBRAL_DRAG = 4;
  const MIN_LADO = 0.2;              // lado mínimo de un rectángulo (m)
  const MIN_MURO = 0.3;             // longitud mínima de un muro (m)
  const ALPHA = 0.32;
  const puedeEditar = form.dataset.puedeEditar === "true";

  // ── Motor de viewport (RenderCanvas reusado, sin dibujar) ────────────────
  const rc = new window.RenderCanvas(canvasEl);
  rc.dibujar = function () {};
  const ctx = canvasEl.getContext("2d");

  // ── DOM ───────────────────────────────────────────────────────────────────
  const tabsPlantasEl = document.getElementById("rc-tabs-plantas");
  const toolbarEl = document.getElementById("rc-lienzo-toolbar");
  const inspectorEl = document.getElementById("rc-lienzo-inspector");
  const inputNombre = document.getElementById("rc-lienzo-nombre");
  const coloresEl = document.getElementById("rc-lienzo-colores");
  const inputHex = document.getElementById("rc-lienzo-hex");
  const btnBorrarSel = document.getElementById("rc-lienzo-borrar-sel");
  const resumenEl = document.getElementById("rc-lienzo-resumen");

  const fmt = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  // ── Estado ────────────────────────────────────────────────────────────────
  const S = {
    tool: "seleccionar",
    planta: 0,
    parcela: null,            // {poligono:[[x,y]…], bbox:[…]}
    parcelaPath: null,        // Path2D en pantalla para clip
    dibujos: {},              // { idx: [fig…] }
    selId: null,
    rotArrow: false,
    drag: null,
    poly: null,               // {verts:[…], hover:[x,y]}
    muro: null,               // {p1:[x,y], hover:[x,y]}
    colorActual: COLORES[2],
    contador: 0,
  };
  let needsRender = true;

  const figs = () => (S.dibujos[S.planta] || (S.dibujos[S.planta] = []));
  const figPorId = (id) => figs().find((f) => f.id === id) || null;
  const sel = () => (S.selId ? figPorId(S.selId) : null);

  // ── Geometría auxiliar (arrays [x,y] en mundo) ───────────────────────────
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const scl = (a, k) => [a[0] * k, a[1] * k];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
  const len = (a) => Math.hypot(a[0], a[1]) || 1;
  const norm = (a) => scl(a, 1 / len(a));
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function centroide(pts) {
    let x = 0, y = 0;
    for (const p of pts) { x += p[0]; y += p[1]; }
    return [x / pts.length, y / pts.length];
  }
  function rotar(p, c, ang) {
    const s = Math.sin(ang), co = Math.cos(ang);
    const d = sub(p, c);
    return [c[0] + d[0] * co - d[1] * s, c[1] + d[0] * s + d[1] * co];
  }
  function pointInPoly(p, poly) {
    let dentro = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      const corta = (yi > p[1]) !== (yj > p[1]) &&
        p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi || 1e-12) + xi;
      if (corta) dentro = !dentro;
    }
    return dentro;
  }
  function shoelace(poly) {
    let a = 0;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      a += poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1];
    }
    return Math.abs(a) / 2;
  }

  // Polígono mundo de una figura (para hit-test, etiqueta y área aproximada).
  function poligonoMundo(f) {
    if (f.tipo === "muro") {
      const [p1, p2] = f.verts;
      const d = norm(sub(p2, p1));
      const n = [-d[1], d[0]];
      const h = (f.grosor || GROSOR_MURO) / 2;
      return [add(p1, scl(n, h)), add(p2, scl(n, h)), add(p2, scl(n, -h)), add(p1, scl(n, -h))];
    }
    return f.verts;
  }
  // Vértices editables (para manejadores): muro = extremos; resto = vértices.
  const verticesEditables = (f) => f.verts;

  // ── Transformación pantalla ↔ mundo ──────────────────────────────────────
  const sx = (x) => rc._x(x);
  const sy = (y) => rc._y(y);
  const toScreen = (p) => [rc._x(p[0]), rc._y(p[1])];
  const worldX = (px) => (px - rc.origenX) / rc.scale;
  const worldY = (py) => (rc.origenY - py) / rc.scale;

  function eventoPantalla(e) {
    const r = canvasEl.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }
  function eventoMundo(e) {
    const [px, py] = eventoPantalla(e);
    return [worldX(px), worldY(py)];
  }

  function recalcViewport() {
    if (!S.parcela) return;
    rc._ajustarTamano();
    rc._calcViewport(S.parcela.bbox);
    const path = new Path2D();
    S.parcela.poligono.forEach((p, i) => {
      const X = sx(p[0]), Y = sy(p[1]);
      if (i === 0) path.moveTo(X, Y); else path.lineTo(X, Y);
    });
    path.closePath();
    S.parcelaPath = path;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  function hexAlpha(hex, a) {
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return "rgba(120,120,120," + a + ")";
    let h = m[1];
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  function limpiar() {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
    ctx.restore();
  }

  function trazar(poly, cerrar) {
    ctx.beginPath();
    poly.forEach((p, i) => {
      const X = sx(p[0]), Y = sy(p[1]);
      if (i === 0) ctx.moveTo(X, Y); else ctx.lineTo(X, Y);
    });
    if (cerrar) ctx.closePath();
  }

  function dibujarFigura(f) {
    const poly = poligonoMundo(f);
    if (poly.length < 2) return;
    trazar(poly, true);
    ctx.fillStyle = hexAlpha(f.color, ALPHA);
    ctx.fill();
    ctx.strokeStyle = f.color;
    ctx.lineWidth = f.tipo === "muro" ? 1.2 : 1.4;
    ctx.stroke();
  }

  function etiqueta(f) {
    const poly = poligonoMundo(f);
    const c = centroide(poly);
    const X = sx(c[0]), Y = sy(c[1]);
    const m2 = (f.m2_aprox ? "~" : "") + fmt.format(f.m2 || 0) + " m²";
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "600 11px 'Helvetica Neue', Inter, sans-serif";
    const w = Math.max(ctx.measureText(f.nombre || "").width, ctx.measureText(m2).width) + 10;
    ctx.fillStyle = "rgba(255,255,255,0.86)";
    ctx.fillRect(X - w / 2, Y - 15, w, 30);
    ctx.fillStyle = "#0A0A0A";
    ctx.fillText(f.nombre || "", X, Y - 6);
    ctx.font = "10px 'Helvetica Neue', Inter, sans-serif";
    ctx.fillStyle = "#2B2B2B";
    ctx.fillText(m2, X, Y + 7);
    ctx.restore();
  }

  function rotHandlePos(f) {
    const sv = verticesEditables(f).map(toScreen);
    let minY = Infinity, cx = 0;
    for (const p of sv) { minY = Math.min(minY, p[1]); cx += p[0]; }
    return [cx / sv.length, minY - 26];
  }

  function dibujarManejadores(f) {
    const sv = verticesEditables(f).map(toScreen);
    ctx.save();
    ctx.fillStyle = "#FFFFFF";
    ctx.strokeStyle = "#B8960C";
    ctx.lineWidth = 1.4;
    for (const p of sv) {
      ctx.beginPath();
      ctx.rect(p[0] - 4, p[1] - 4, 8, 8);
      ctx.fill();
      ctx.stroke();
    }
    if (S.rotArrow && f.tipo !== "muro") {
      const h = rotHandlePos(f);
      const cen = toScreen(centroide(poligonoMundo(f)));
      ctx.strokeStyle = "#B8960C";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(cen[0], cen[1]);
      ctx.lineTo(h[0], h[1]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(h[0], h[1], 7, 0.3, Math.PI * 1.7);
      ctx.lineWidth = 2;
      ctx.stroke();
      // punta de flecha
      ctx.beginPath();
      ctx.moveTo(h[0] + 5, h[1] - 5);
      ctx.lineTo(h[0] + 8, h[1] + 1);
      ctx.lineTo(h[0] + 1, h[1] - 1);
      ctx.fillStyle = "#B8960C";
      ctx.fill();
    }
    ctx.restore();
  }

  function render() {
    if (!S.parcela) { limpiar(); return; }
    limpiar();
    // Parcela base (fantasma)
    trazar(S.parcela.poligono, true);
    ctx.fillStyle = "rgba(244,242,236,0.6)";
    ctx.fill();
    ctx.strokeStyle = "#B8B6AE";
    ctx.lineWidth = 1;
    ctx.stroke();
    // Capa recortada a la parcela
    ctx.save();
    ctx.clip(S.parcelaPath);
    for (const f of figs()) dibujarFigura(f);
    // overlays en progreso (también recortados)
    if (S.poly) {
      const pts = S.poly.hover ? S.poly.verts.concat([S.poly.hover]) : S.poly.verts;
      if (pts.length >= 2) {
        trazar(pts, false);
        ctx.strokeStyle = S.colorActual;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
    }
    if (S.muro && S.muro.hover) {
      const f = { tipo: "muro", verts: [S.muro.p1, S.muro.hover], grosor: GROSOR_MURO, color: S.colorActual };
      ctx.globalAlpha = 0.7;
      dibujarFigura(f);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    // Etiquetas (sin recorte, legibles aunque la figura se salga)
    for (const f of figs()) if ((f.m2 || 0) > 0 || f.tipo === "muro") etiqueta(f);
    // Vértices del primer punto del polígono en progreso (snap visual)
    if (S.poly && S.poly.verts.length) {
      const p0 = toScreen(S.poly.verts[0]);
      ctx.save();
      ctx.fillStyle = "#B8960C";
      ctx.beginPath();
      ctx.arc(p0[0], p0[1], 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    // Manejadores de la selección
    const f = sel();
    if (f) dibujarManejadores(f);
  }

  function loop() {
    if (needsRender) { needsRender = false; render(); }
    requestAnimationFrame(loop);
  }

  // ── Resumen por color (debajo del lienzo) ────────────────────────────────
  function agruparColor(lista) {
    const acc = {};
    for (const f of lista) {
      const a = f.m2 || 0;
      if (a <= 0) continue;
      const c = (f.color || "#000000").toLowerCase();
      (acc[c] || (acc[c] = { color: c, m2: 0, n: 0 }));
      acc[c].m2 += a; acc[c].n += 1;
    }
    return Object.values(acc).sort((x, y) => y.m2 - x.m2);
  }
  function renderResumen() {
    if (!resumenEl) return;
    if (!S.parcela) {
      resumenEl.innerHTML = '<p class="rc-lienzo-vacio">Localiza la parcela para empezar a dibujar.</p>';
      return;
    }
    const lista = figs();
    const sup = agruparColor(lista.filter((f) => f.tipo !== "muro"));
    const mur = agruparColor(lista.filter((f) => f.tipo === "muro"));
    const totalMur = mur.reduce((s, g) => s + g.m2, 0);
    const chips = (grupos) => grupos.map((g) =>
      `<span class="rc-lienzo-chip"><i style="background:${g.color}"></i>${fmt.format(g.m2)} m² <small>(${g.n})</small></span>`).join("");
    let html = "";
    html += `<div class="rc-lienzo-res-bloque"><h4>Superficies por color</h4><div class="rc-lienzo-chips">${sup.length ? chips(sup) : '<span class="rc-lienzo-vacio">—</span>'}</div></div>`;
    html += `<div class="rc-lienzo-res-bloque"><h4>Muros</h4><div class="rc-lienzo-chips">${mur.length ? chips(mur) : '<span class="rc-lienzo-vacio">—</span>'}<span class="rc-lienzo-total">Total muro: <strong>${fmt.format(totalMur)} m²</strong></span></div></div>`;
    resumenEl.innerHTML = html;
  }

  // ── Backend (calcular + guardar, debounced con AbortController) ───────────
  let tCalc = null, tSave = null, abCalc = null, abSave = null;

  function payloadPlanta() {
    const lista = figs();
    return {
      planta: S.planta,
      figuras: lista.filter((f) => f.tipo !== "muro").map((f) => ({
        id: f.id, tipo: f.tipo, nombre: f.nombre, color: f.color, vertices: f.verts, rotacion: 0,
      })),
      muros: lista.filter((f) => f.tipo === "muro").map((f) => ({
        id: f.id, nombre: f.nombre, color: f.color, p1: f.verts[0], p2: f.verts[1], grosor: f.grosor || GROSOR_MURO,
      })),
    };
  }

  function scheduleCalc() {
    if (tCalc) clearTimeout(tCalc);
    tCalc = setTimeout(calcular, 250);
  }
  function schedulePersist() {
    if (!puedeEditar) return;
    if (tSave) clearTimeout(tSave);
    tSave = setTimeout(persistir, 400);
  }

  async function calcular() {
    if (!S.parcela) return;
    if (abCalc) abCalc.abort();
    abCalc = new AbortController();
    try {
      const resp = await fetch("/modulos/render-calculos/lienzo/calcular", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadPlanta()), signal: abCalc.signal,
      });
      if (!resp.ok) return;
      const data = await resp.json();
      const areas = {};
      (data.figuras || []).concat(data.muros || []).forEach((p) => { areas[p.id] = p.area_m2; });
      for (const f of figs()) {
        if (f.id in areas) { f.m2 = areas[f.id]; f.m2_aprox = false; }
      }
      needsRender = true;
      renderResumen();
    } catch (err) {
      if (err.name !== "AbortError") { /* silencioso */ }
    }
  }

  async function persistir() {
    if (!puedeEditar || !S.parcela) return;
    if (abSave) abSave.abort();
    abSave = new AbortController();
    try {
      await fetch("/modulos/render-calculos/lienzo/guardar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadPlanta()), signal: abSave.signal,
      });
    } catch (err) { /* silencioso */ }
  }

  function onCambio() {
    renderResumen();
    needsRender = true;
    scheduleCalc();
    schedulePersist();
  }

  // ── Selección / inspector ─────────────────────────────────────────────────
  function pintarSwatches() {
    if (!coloresEl) return;
    coloresEl.innerHTML = COLORES.map((c) =>
      `<button type="button" class="rc-lienzo-swatch" data-color="${c}" style="background:${c}" title="${c}"></button>`).join("");
    coloresEl.querySelectorAll(".rc-lienzo-swatch").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        aplicarColor(b.dataset.color);
      });
    });
  }
  function marcarSwatchActivo(color) {
    if (!coloresEl) return;
    coloresEl.querySelectorAll(".rc-lienzo-swatch").forEach((b) =>
      b.classList.toggle("activo", (b.dataset.color || "").toLowerCase() === (color || "").toLowerCase()));
  }
  function aplicarColor(color) {
    S.colorActual = color;
    if (inputHex) inputHex.value = color;
    marcarSwatchActivo(color);
    const f = sel();
    if (f) { f.color = color; onCambio(); }
  }

  function seleccionar(id) {
    S.selId = id;
    S.rotArrow = false;
    const f = sel();
    if (f && inspectorEl) {
      inspectorEl.hidden = false;
      if (inputNombre) inputNombre.value = f.nombre || "";
      if (inputHex) inputHex.value = f.color || "";
      marcarSwatchActivo(f.color);
    } else if (inspectorEl) {
      inspectorEl.hidden = true;
    }
    needsRender = true;
  }
  function deseleccionar() {
    S.selId = null; S.rotArrow = false;
    if (inspectorEl) inspectorEl.hidden = true;
    needsRender = true;
  }

  function nuevaFigura(tipo, verts, grosor) {
    S.contador += 1;
    const pref = tipo === "muro" ? "M" : "S";
    const f = {
      id: "f" + Date.now().toString(36) + S.contador,
      tipo, nombre: pref + S.contador, color: S.colorActual,
      verts, grosor: grosor || GROSOR_MURO, m2: shoelace(poligonoMundo({ tipo, verts, grosor })), m2_aprox: true,
    };
    figs().push(f);
    seleccionar(f.id);
    onCambio();
    return f;
  }
  function borrarFigura(id) {
    const arr = figs();
    const i = arr.findIndex((f) => f.id === id);
    if (i >= 0) {
      arr.splice(i, 1);
      if (S.selId === id) deseleccionar();
      onCambio();
    }
  }

  // ── Hit-testing ───────────────────────────────────────────────────────────
  function hitVertice(f, pPant) {
    const sv = verticesEditables(f).map(toScreen);
    for (let i = 0; i < sv.length; i++) if (dist(sv[i], pPant) <= TOL_VERT) return i;
    return -1;
  }
  function figuraEn(w, tipoFiltro) {
    const arr = figs();
    for (let i = arr.length - 1; i >= 0; i--) {
      const f = arr[i];
      if (tipoFiltro === "superficie" && f.tipo === "muro") continue;
      if (tipoFiltro === "muro" && f.tipo !== "muro") continue;
      if (pointInPoly(w, poligonoMundo(f))) return f;
    }
    return null;
  }

  // ── Resize de rectángulo conservando ejes (aunque esté rotado) ───────────
  function resizeRect(snap, k, P) {
    const opp = (k + 2) % 4;
    const O = snap[opp];
    const ua = norm(sub(snap[(opp + 1) % 4], O));
    const ub = norm(sub(snap[(opp + 3) % 4], O));
    let la = dot(sub(P, O), ua), lb = dot(sub(P, O), ub);
    la = (la >= 0 ? 1 : -1) * Math.max(Math.abs(la), MIN_LADO);
    lb = (lb >= 0 ? 1 : -1) * Math.max(Math.abs(lb), MIN_LADO);
    const res = [];
    res[opp] = O.slice();
    res[(opp + 1) % 4] = add(O, scl(ua, la));
    res[(opp + 3) % 4] = add(O, scl(ub, lb));
    res[k] = add(O, add(scl(ua, la), scl(ub, lb)));
    return res;
  }

  // ── Eventos de ratón / teclado ───────────────────────────────────────────
  function onMouseDown(e) {
    if (!puedeEditar || !S.parcela) return;
    const w = eventoMundo(e), p = eventoPantalla(e);

    if (S.tool === "goma-sup") { const f = figuraEn(w, "superficie"); if (f) borrarFigura(f.id); return; }
    if (S.tool === "goma-muro") { const f = figuraEn(w, "muro"); if (f) borrarFigura(f.id); return; }

    if (S.tool === "rect") {
      S.drag = { modo: "dibujar-rect", ancla: w, moved: false };
      return;
    }
    if (S.tool === "poly") {
      if (!S.poly) S.poly = { verts: [w], hover: w };
      else {
        if (S.poly.verts.length >= 3 && dist(toScreen(S.poly.verts[0]), p) <= TOL_CIERRE) {
          cerrarPoly();
        } else {
          S.poly.verts.push(w);
        }
      }
      needsRender = true;
      return;
    }
    if (S.tool === "muro") {
      if (!S.muro) S.muro = { p1: w, hover: w };
      else {
        if (dist(S.muro.p1, w) >= MIN_MURO) nuevaFigura("muro", [S.muro.p1, w], GROSOR_MURO);
        S.muro = null;
        needsRender = true;
      }
      return;
    }

    // Herramienta seleccionar
    const f = sel();
    if (f && S.rotArrow && f.tipo !== "muro" && dist(rotHandlePos(f), p) <= TOL_ROT) {
      const c = centroide(poligonoMundo(f));
      S.drag = { modo: "rotar", figId: f.id, snap: f.verts.map((v) => v.slice()),
        c, ang0: Math.atan2(w[1] - c[1], w[0] - c[0]), moved: false };
      return;
    }
    if (f) {
      const vi = hitVertice(f, p);
      if (vi >= 0) {
        S.drag = { modo: f.tipo === "rect" ? "resize-rect" : "mover-vert",
          figId: f.id, vi, snap: f.verts.map((v) => v.slice()), moved: false };
        return;
      }
    }
    const obj = figuraEn(w, null);
    if (obj) {
      const prev = S.selId;
      if (S.selId !== obj.id) seleccionar(obj.id);
      S.drag = { modo: "mover", figId: obj.id, start: w, snap: obj.verts.map((v) => v.slice()),
        moved: false, prevSel: prev };
    } else {
      deseleccionar();
    }
  }

  function onMouseMove(e) {
    if (!S.parcela) return;
    const w = eventoMundo(e);
    if (S.drag) {
      const d = S.drag;
      const f = figPorId(d.figId);
      if (d.modo === "dibujar-rect") {
        d.cur = w; d.moved = d.moved || dist(d.ancla, w) > 0.05; needsRender = true; return;
      }
      if (!f) return;
      if (!d.moved && dist(eventoPantalla(e), toScreen(d.start || d.c || d.ancla || w)) > UMBRAL_DRAG) d.moved = true;
      if (d.modo === "mover") {
        const dx = sub(w, d.start);
        f.verts = d.snap.map((v) => add(v, dx));
      } else if (d.modo === "mover-vert") {
        f.verts = d.snap.map((v) => v.slice());
        f.verts[d.vi] = w;
      } else if (d.modo === "resize-rect") {
        f.verts = resizeRect(d.snap, d.vi, w);
      } else if (d.modo === "rotar") {
        const ang = Math.atan2(w[1] - d.c[1], w[0] - d.c[0]) - d.ang0;
        f.verts = d.snap.map((v) => rotar(v, d.c, ang));
      }
      f.m2 = shoelace(poligonoMundo(f)); f.m2_aprox = true;
      needsRender = true;
      return;
    }
    if (S.poly) { S.poly.hover = w; needsRender = true; }
    else if (S.muro) { S.muro.hover = w; needsRender = true; }
  }

  function onMouseUp(e) {
    if (!S.drag) return;
    const d = S.drag;
    S.drag = null;
    if (d.modo === "dibujar-rect") {
      const a = d.ancla, b = d.cur || a;
      if (Math.abs(a[0] - b[0]) >= MIN_LADO && Math.abs(a[1] - b[1]) >= MIN_LADO) {
        nuevaFigura("rect", [a, [b[0], a[1]], b, [a[0], b[1]]]);
      }
      needsRender = true;
      return;
    }
    if (d.modo === "mover" && !d.moved) {
      // Click simple: si ya estaba seleccionada, alterna la flecha de rotación.
      if (d.prevSel === d.figId) { S.rotArrow = !S.rotArrow; needsRender = true; }
      return;
    }
    onCambio();
  }

  function cerrarPoly() {
    if (S.poly && S.poly.verts.length >= 3) {
      nuevaFigura("poly", S.poly.verts.map((v) => v.slice()));
    }
    S.poly = null;
    needsRender = true;
  }

  function finPendientes() {
    if (S.poly) { if (S.poly.verts.length >= 3) cerrarPoly(); else { S.poly = null; needsRender = true; } }
    if (S.muro) { S.muro = null; needsRender = true; }
    S.drag = null;
  }

  function onKeyDown(e) {
    const enInput = document.activeElement &&
      ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (e.key === "Enter" && S.poly) { e.preventDefault(); cerrarPoly(); }
    else if (e.key === "Escape") { finPendientes(); deseleccionar(); }
    else if ((e.key === "Delete" || e.key === "Backspace") && S.selId && !enInput) {
      e.preventDefault(); borrarFigura(S.selId);
    }
  }

  // ── Toolbar ───────────────────────────────────────────────────────────────
  function setTool(tool) {
    finPendientes();
    S.tool = tool;
    if (toolbarEl) toolbarEl.querySelectorAll(".rc-tool").forEach((b) =>
      b.classList.toggle("rc-tool-activo", b.dataset.tool === tool));
    if (tool !== "seleccionar") deseleccionar();
    canvasEl.style.cursor = tool === "seleccionar" ? "default"
      : (tool.startsWith("goma") ? "not-allowed" : "crosshair");
    needsRender = true;
  }

  // ── Carga inicial ─────────────────────────────────────────────────────────
  function plantaActivaDOM() {
    const t = tabsPlantasEl && tabsPlantasEl.querySelector(".rc-tab-activo[data-indice]");
    return t ? Number(t.dataset.indice) : 0;
  }
  function adoptarDibujos(plantas) {
    S.dibujos = {};
    Object.keys(plantas || {}).forEach((k) => {
      const idx = Number(k);
      const blo = plantas[k] || {};
      const lista = [];
      (blo.figuras || []).forEach((f) => lista.push({
        id: f.id, tipo: f.tipo || "poly", nombre: f.nombre || "", color: f.color || "#000000",
        verts: f.vertices || [], m2: 0, m2_aprox: true,
      }));
      (blo.muros || []).forEach((m) => lista.push({
        id: m.id, tipo: "muro", nombre: m.nombre || "", color: m.color || "#000000",
        verts: [m.p1, m.p2], grosor: m.grosor || GROSOR_MURO, m2: 0, m2_aprox: true,
      }));
      S.dibujos[idx] = lista;
    });
  }

  async function cargar() {
    try {
      const resp = await fetch("/modulos/render-calculos/lienzo");
      if (!resp.ok) { S.parcela = null; renderResumen(); return; }
      const data = await resp.json();
      S.parcela = data.parcela;
      adoptarDibujos(data.plantas);
      S.planta = plantaActivaDOM();
      recalcViewport();
      renderResumen();
      needsRender = true;
      if (figs().length) calcular();
    } catch (err) {
      S.parcela = null; renderResumen();
    }
  }

  function cambiarPlanta(idx) {
    if (idx === S.planta) return;
    S.planta = idx;
    deseleccionar();
    finPendientes();
    renderResumen();
    needsRender = true;
    if (figs().length) calcular();
  }

  // ── Wiring ────────────────────────────────────────────────────────────────
  function init() {
    pintarSwatches();
    aplicarColor(S.colorActual);

    if (toolbarEl) {
      toolbarEl.querySelectorAll(".rc-tool").forEach((b) =>
        b.addEventListener("click", (e) => { e.preventDefault(); setTool(b.dataset.tool); }));
    }
    if (inputNombre) {
      inputNombre.addEventListener("input", (e) => {
        e.stopPropagation();
        const f = sel(); if (f) { f.nombre = inputNombre.value; onCambio(); }
      });
    }
    if (inputHex) {
      inputHex.addEventListener("input", (e) => e.stopPropagation());
      inputHex.addEventListener("change", (e) => {
        e.stopPropagation();
        const v = inputHex.value.trim();
        if (/^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(v)) {
          aplicarColor(v.startsWith("#") ? v : "#" + v);
          inputHex.classList.remove("rc-lienzo-hex-err");
        } else {
          inputHex.classList.add("rc-lienzo-hex-err");
        }
      });
    }
    if (btnBorrarSel) {
      btnBorrarSel.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        if (S.selId) borrarFigura(S.selId);
      });
    }

    if (puedeEditar) {
      canvasEl.addEventListener("mousedown", onMouseDown);
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
      window.addEventListener("keydown", onKeyDown);
    }

    // Sincronización con las pestañas de planta (solo lectura).
    if (tabsPlantasEl) {
      tabsPlantasEl.addEventListener("click", (e) => {
        const b = e.target.closest(".rc-tab[data-indice]");
        if (b) cambiarPlanta(Number(b.dataset.indice));
      });
    }

    if (window.ResizeObserver) {
      const wrap = canvasEl.parentElement;
      let raf = null;
      new ResizeObserver(() => {
        if (raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { recalcViewport(); needsRender = true; });
      }).observe(wrap);
    }

    requestAnimationFrame(loop);
    cargar();
  }

  init();
})();
