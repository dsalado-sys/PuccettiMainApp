/* §2.4 — Edición interactiva de patios sobre el lienzo (RenderCanvas).
   Cada patio es una sección individual: se puede MOVER, GIRAR, ESTIRAR
   (escala anisótropa que conserva el área) y REFORMAR vértice a vértice
   (al soltar, se reescala respecto al centroide para recuperar los m²
   asignados). Toda operación queda RESTRINGIDA a que el patio siga dentro de
   la huella y sin solaparse con otros patios («impedir / encajar al borde»).

   No interfiere con la brújula (que vive en su propio SVG): este editor solo
   escucha el lienzo. Se dibuja como overlay al final de RenderCanvas.dibujar,
   dentro del contexto ya rotado, así los tiradores se pegan a la geometría.
*/
(function () {
  "use strict";

  const COLOR = {
    negro: "#0A0A0A", dorado: "#B8960C", doradoClaro: "#C9A84C",
    blanco: "#FFFFFF", error: "#8C2A1F",
  };
  const HIT_PX = 9;          // radio de acierto de un tirador (px de pantalla)
  const DRAG_PX = 4;         // umbral de PREVIEW: por debajo es un clic (jitter), no se arrastra en vivo
  const COMMIT_PX = 8;       // umbral de CONFIRMACIÓN de un 'mover' (> DRAG_PX): el jitter de un
                             // doble-clic (4-8px) hace preview pero nunca reordena/recalcula.
  const ROT_OFFSET_PX = 26;  // distancia del tirador de giro sobre el patio
  const K_MIN = 0.25, K_MAX = 4;   // tope del factor de estirado (el área se conserva igual)

  // ── Helpers geométricos (mundo UTM) ─────────────────────────────────────
  function bbox(v) {
    let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;
    for (const p of v) {
      if (p[0] < mnx) mnx = p[0]; if (p[0] > mxx) mxx = p[0];
      if (p[1] < mny) mny = p[1]; if (p[1] > mxy) mxy = p[1];
    }
    return { mnx, mny, mxx, mxy };
  }
  function areaPoly(v) {
    let a = 0;
    for (let i = 0, n = v.length; i < n; i++) {
      const p = v[i], q = v[(i + 1) % n];
      a += p[0] * q[1] - q[0] * p[1];
    }
    return Math.abs(a) / 2;
  }
  function centroide(v) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0, n = v.length; i < n; i++) {
      const p = v[i], q = v[(i + 1) % n];
      const cross = p[0] * q[1] - q[0] * p[1];
      a += cross; cx += (p[0] + q[0]) * cross; cy += (p[1] + q[1]) * cross;
    }
    if (Math.abs(a) < 1e-9) {  // degenerado → media de vértices
      let sx = 0, sy = 0; for (const p of v) { sx += p[0]; sy += p[1]; }
      return [sx / v.length, sy / v.length];
    }
    a *= 0.5; return [cx / (6 * a), cy / (6 * a)];
  }
  function trasladar(v, dx, dy) { return v.map(p => [p[0] + dx, p[1] + dy]); }
  function escalar(v, fx, fy, c) { return v.map(p => [c[0] + (p[0] - c[0]) * fx, c[1] + (p[1] - c[1]) * fy]); }
  function rotar(v, ang, c) {
    const s = Math.sin(ang), co = Math.cos(ang);
    return v.map(p => {
      const dx = p[0] - c[0], dy = p[1] - c[1];
      return [c[0] + dx * co - dy * s, c[1] + dx * s + dy * co];
    });
  }
  function escalarAArea(v, area) {
    const a = areaPoly(v);
    if (a <= 1e-9 || area <= 0) return v;
    const f = Math.sqrt(area / a);
    return escalar(v, f, f, centroide(v));
  }
  function puntoEnPoligono(pt, ring) {
    let dentro = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      const corta = (yi > pt[1]) !== (yj > pt[1])
        && pt[0] < ((xj - xi) * (pt[1] - yi)) / ((yj - yi) || 1e-12) + xi;
      if (corta) dentro = !dentro;
    }
    return dentro;
  }
  function segCruza(a, b, c, d) {
    const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
    const o1 = o(a, b, c), o2 = o(a, b, d), o3 = o(c, d, a), o4 = o(c, d, b);
    return o1 !== o2 && o3 !== o4;
  }
  function aristasCruzan(a, b) {
    for (let i = 0; i < a.length; i++) {
      const a1 = a[i], a2 = a[(i + 1) % a.length];
      for (let j = 0; j < b.length; j++) {
        if (segCruza(a1, a2, b[j], b[(j + 1) % b.length])) return true;
      }
    }
    return false;
  }
  // ¿El anillo se autointersecta? (par de aristas NO adyacentes que se cruzan). Una figura
  // así es "imposible": el backend no sabe adaptarla y el área (shoelace) sale falseada,
  // de modo que «no cabe» y la forma adaptada queda vacía. Hay que evitar producirla.
  function autoCruza(v) {
    const n = v ? v.length : 0;
    if (n < 4) return false;
    for (let i = 0; i < n; i++) {
      const a1 = v[i], a2 = v[(i + 1) % n];
      for (let j = i + 1; j < n; j++) {
        if (j === (i + 1) % n || (j + 1) % n === i) continue;   // aristas adyacentes (comparten vértice)
        if (segCruza(a1, a2, v[j], v[(j + 1) % n])) return true;
      }
    }
    return false;
  }
  function poligonoDentro(inner, outer) {
    if (!outer || outer.length < 3) return true;       // sin huella → no restringe
    for (const p of inner) if (!puntoEnPoligono(p, outer)) return false;
    return !aristasCruzan(inner, outer);
  }
  function solapan(a, b) {
    if (!a || !b || a.length < 3 || b.length < 3) return false;
    if (puntoEnPoligono(centroide(a), b) || puntoEnPoligono(centroide(b), a)) return true;
    for (const p of a) if (puntoEnPoligono(p, b)) return true;
    for (const p of b) if (puntoEnPoligono(p, a)) return true;
    return aristasCruzan(a, b);
  }
  function clon(v) { return v.map(p => [p[0], p[1]]); }
  // El backend serializa el anillo CERRADO (último punto = primero). Para editar
  // (tiradores, vértices) trabajamos con el anillo ABIERTO, sin ese duplicado, o se
  // pintaría un tirador doble en esa esquina.
  function abrirAnillo(v) {
    if (v && v.length > 1) {
      const a = v[0], b = v[v.length - 1];
      if (Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(a[1] - b[1]) < 1e-7) return v.slice(0, -1);
    }
    return v;
  }

  // ── Editor ───────────────────────────────────────────────────────────────
  class PatioEditor {
    constructor(renderer, opts) {
      this.r = renderer;
      this.opts = opts || {};
      this.activo = false;
      this.seleccionId = null;
      this.modo = null;          // 'mover' | 'vertice' | 'estirar' | 'rotar'
      this.handleIdx = -1;       // índice de vértice o de tirador de estirar (0=E,1=W,2=N,3=S)
      this._patioObj = null;     // patio del payload que se está arrastrando (se muta su poligono)
      this._poly0 = null;        // snapshot de vértices al iniciar el gesto
      this._area0 = 0;
      this._startW = null;       // [wx, wy] del puntero al iniciar
      this._ultimoValido = null; // último candidato que cumple la restricción
      this._movido = false;
      this._rafId = 0;
      this._ciclo = null;          // ciclado de tiradores superpuestos: {x,y,claves[],idx}
      this._cicloCands = null;     // candidatos del gesto en curso (para avanzar al soltar)
      this._avanzarEnUp = false;   // un clic suelto sobre un grupo cicla al siguiente al soltar
      this._handleResaltado = null; // tirador activo a dibujar ENCIMA cuando hay solape
      this._bind();
    }

    // ── API pública ──
    setActivo(b) {
      const antes = this.activo;
      this.activo = !!b;
      if (!this.activo && this.seleccionId) {
        this.seleccionId = null;
        this.opts.onSelect && this.opts.onSelect(null);
      }
      if (!this.modo) { this._patioObj = null; this._poly0 = null; }
      if (antes !== this.activo) this.r.repintar();
    }
    olvidar(id) {
      if (this.seleccionId === id) {
        this.seleccionId = null;
        this.opts.onSelect && this.opts.onSelect(null);
        this.r.repintar();
      }
    }

    // ── Datos de la planta activa (patios + huella) ──
    _plantaActiva() {
      const p = this.r._lastPayload;
      if (!p) return null;
      const plantas = (p.edificio && p.edificio.plantas) || (p.envolvente && p.envolvente.plantas) || [];
      if (!plantas.length) return null;
      const idx = Math.min(this.r._lastIndicePlanta || 0, plantas.length - 1);
      return plantas[idx] || null;
    }
    _patios() { const pl = this._plantaActiva(); return (pl && pl.patios) || []; }
    _footprint() { const pl = this._plantaActiva(); return (pl && pl.footprint) || null; }
    _patioPorId(id) { return this._patios().find(p => p.id === id) || null; }
    // Anillo EDITABLE de un patio = su forma EFECTIVA (la adaptada y VISIBLE): los gestos y
    // tiradores operan sobre lo que se dibuja, no sobre la ideal que pueda asomar fuera. Sin
    // adaptación `poligono == base`, así que coincide con la forma del usuario.
    _editable(patio) { return abrirAnillo(patio.poligono || patio.base); }

    // ── Coordenadas ──
    _pos(ev) {
      const rect = this.r.cv.getBoundingClientRect();
      const t = (ev.touches && ev.touches[0]) || (ev.changedTouches && ev.changedTouches[0]) || ev;
      return [t.clientX - rect.left, t.clientY - rect.top];
    }
    _mundo(ev) { const [px, py] = this._pos(ev); return this.r._pantallaAMundo(px, py); }

    // ── Tiradores de un patio (en mundo) ──
    _tiradoresEstirar(v) {
      const b = bbox(v), cy = (b.mny + b.mxy) / 2, cx = (b.mnx + b.mxx) / 2;
      return [[b.mxx, cy], [b.mnx, cy], [cx, b.mxy], [cx, b.mny]];   // E, W, N, S
    }
    _tiradorGiro(v) {
      const b = bbox(v);
      return [(b.mnx + b.mxx) / 2, b.mxy + ROT_OFFSET_PX / this.r.scale];
    }

    // TODOS los tiradores del patio seleccionado bajo (px,py), en orden de prioridad
    // (rotar → estirar → vértice). Si hay varios, se ciclará entre ellos al pulsar.
    _candidatosHandle(px, py) {
      const sel = this.seleccionId ? this._patioPorId(this.seleccionId) : null;
      if (!sel) return [];
      const v = this._editable(sel);   // tiradores sobre la forma EFECTIVA (visible)
      const cerca = (mundo) => {
        const s = this.r._mundoAPantalla(mundo[0], mundo[1]);
        return Math.hypot(s[0] - px, s[1] - py) <= HIT_PX;
      };
      const out = [];
      if (cerca(this._tiradorGiro(v))) out.push({ modo: "rotar", idx: -1, patio: sel });
      const est = this._tiradoresEstirar(v);
      for (let i = 0; i < est.length; i++) if (cerca(est[i])) out.push({ modo: "estirar", idx: i, patio: sel });
      for (let i = 0; i < v.length; i++) if (cerca(v[i])) out.push({ modo: "vertice", idx: i, patio: sel });
      return out;
    }

    // ¿Mismo grupo de tiradores que el ciclo en curso? (mismo punto y mismas claves)
    _mismoCiclo(px, py, claves) {
      return !!this._ciclo
        && Math.hypot(this._ciclo.x - px, this._ciclo.y - py) <= HIT_PX
        && this._ciclo.claves.length === claves.length
        && this._ciclo.claves.every((k, i) => k === claves[i]);
    }

    // ── Hit-test SOLO LECTURA: el tirador que se agarraría bajo (px,py), sin mutar
    // estado (lo usa _hover para el cursor). El ciclado lo gestionan _down/_up.
    _hit(px, py) {
      if (!this.activo) return null;
      const cands = this._candidatosHandle(px, py);
      if (cands.length) {
        const claves = cands.map(c => c.modo + ":" + c.idx);
        const idx = this._mismoCiclo(px, py, claves) ? this._ciclo.idx : 0;
        return cands[idx];
      }
      // Cuerpo de cualquier patio (último→primero = el de encima gana) → mover/seleccionar.
      const w = this.r._pantallaAMundo(px, py);
      const patios = this._patios();
      for (let i = patios.length - 1; i >= 0; i--) {
        if (puntoEnPoligono(w, patios[i].poligono)) return { modo: "mover", idx: -1, patio: patios[i] };
      }
      return null;
    }

    // (Sin restricción de encaje: el patio puede salir; al soltar, el backend lo
    //  recorta y rellena hacia dentro conservando el área — ver conformar_patio.)

    // ── Eventos ──
    _bind() {
      const cv = this.r.cv;
      this._onDown = (e) => this._down(e);
      this._onMove = (e) => this._move(e);
      this._onUp = (e) => this._up(e);
      this._onHover = (e) => this._hover(e);
      this._onDbl = (e) => this._dblclick(e);
      this._onCtx = (e) => this._contextmenu(e);
      cv.addEventListener("mousedown", this._onDown);
      cv.addEventListener("touchstart", this._onDown, { passive: false });
      window.addEventListener("mousemove", this._onMove);
      window.addEventListener("touchmove", this._onMove, { passive: false });
      window.addEventListener("mouseup", this._onUp);
      window.addEventListener("touchend", this._onUp);
      cv.addEventListener("mousemove", this._onHover);
      cv.addEventListener("dblclick", this._onDbl);
      cv.addEventListener("contextmenu", this._onCtx);
    }

    _hover(ev) {
      if (this.modo || !this.activo) return;
      const [px, py] = this._pos(ev);
      const h = this._hit(px, py);
      let c = "default";
      if (h) c = h.modo === "rotar" ? "grab" : (h.modo === "mover" ? "move" : "pointer");
      this.r.cv.style.cursor = c;
    }

    _down(ev) {
      if (!this.activo) return;
      const [px, py] = this._pos(ev);
      // Agarra SIN avanzar: el arrastre afectará al tirador resaltado. El ciclado al
      // siguiente ocurre solo en un clic suelto (sin arrastre), en `_up`.
      let h = null;
      const cands = this._candidatosHandle(px, py);
      if (cands.length) {
        const claves = cands.map(c => c.modo + ":" + c.idx);
        if (this._mismoCiclo(px, py, claves)) {
          // Re-pulsación en el mismo grupo: conserva el resaltado; un clic suelto ciclará.
          this._avanzarEnUp = cands.length > 1;
        } else {
          // Grupo nuevo: establece el primero (no cicla en este primer clic).
          this._ciclo = { x: px, y: py, claves, idx: 0 };
          this._avanzarEnUp = false;
        }
        this._cicloCands = cands;
        this._handleResaltado = cands.length > 1 ? cands[this._ciclo.idx] : null;
        h = cands[this._ciclo.idx];
      } else {
        this._handleResaltado = null; this._ciclo = null; this._cicloCands = null; this._avanzarEnUp = false;
        // Cuerpo de cualquier patio (último→primero = el de encima gana) → mover/seleccionar.
        const w = this.r._pantallaAMundo(px, py);
        const patios = this._patios();
        for (let i = patios.length - 1; i >= 0; i--) {
          if (puntoEnPoligono(w, patios[i].poligono)) { h = { modo: "mover", idx: -1, patio: patios[i] }; break; }
        }
      }
      if (!h) {                       // clic en vacío → deseleccionar
        if (this.seleccionId) { this.seleccionId = null; this.opts.onSelect && this.opts.onSelect(null); this.r.repintar(); }
        return;
      }
      ev.preventDefault();
      const idChange = this.seleccionId !== h.patio.id;
      this.seleccionId = h.patio.id;
      if (idChange) this.opts.onSelect && this.opts.onSelect(this.seleccionId);
      this.modo = h.modo;
      this.handleIdx = h.idx;
      this._patioObj = h.patio;
      this._poly0 = this._editable(h.patio);       // snapshot de la BASE
      this._ultimoValido = this._poly0;            // baseline simple (anti-autointersección al reformar)
      this._area0 = (typeof h.patio.area_m2 === "number") ? h.patio.area_m2 : areaPoly(this._poly0);
      this._startW = this.r._pantallaAMundo(px, py);
      this._startPx = [px, py];                     // origen en pantalla (umbral de arrastre)
      this._movido = false;
      this.r.repintar();   // refleja la selección y el tirador resaltado (encima)
    }

    _candidato(w) {
      const c = centroide(this._poly0);
      if (this.modo === "mover") {
        return trasladar(this._poly0, w[0] - this._startW[0], w[1] - this._startW[1]);
      }
      if (this.modo === "vertice") {
        const v = clon(this._poly0); v[this.handleIdx] = [w[0], w[1]]; return v;
      }
      if (this.modo === "rotar") {
        const a0 = Math.atan2(this._startW[1] - c[1], this._startW[0] - c[0]);
        const a1 = Math.atan2(w[1] - c[1], w[0] - c[0]);
        return rotar(this._poly0, a1 - a0, c);
      }
      if (this.modo === "estirar") {
        const b = bbox(this._poly0);
        let k;
        if (this.handleIdx <= 1) {  // E/W → escala X por k, Y por 1/k (área constante)
          const half0 = Math.max(1e-6, Math.abs((this.handleIdx === 0 ? b.mxx : b.mnx) - c[0]));
          k = Math.min(K_MAX, Math.max(K_MIN, Math.abs(w[0] - c[0]) / half0));
          return escalar(this._poly0, k, 1 / k, c);
        }
        const half0 = Math.max(1e-6, Math.abs((this.handleIdx === 2 ? b.mxy : b.mny) - c[1]));
        k = Math.min(K_MAX, Math.max(K_MIN, Math.abs(w[1] - c[1]) / half0));
        return escalar(this._poly0, 1 / k, k, c);
      }
      return clon(this._poly0);
    }

    // Aplica una forma BASE en vivo: durante el arrastre se dibuja la base moviéndose
    // (puede asomar fuera); al soltar, el backend la recorta/rellena (efectiva real).
    _aplicarLive(cand) {
      if (!this._patioObj) return;
      this._patioObj.base = cand;
      this._patioObj.poligono = cand;
    }

    _move(ev) {
      if (!this.modo || !this._patioObj) return;
      ev.preventDefault();
      const [px, py] = this._pos(ev);
      // Umbral de arrastre: ignora micro-movimientos (jitter de un clic / doble-clic) para no
      // cometer un "mover" accidental (que reordenaría y recalcularía el patio, moviéndolo).
      if (!this._movido && this._startPx
          && Math.hypot(px - this._startPx[0], py - this._startPx[1]) < DRAG_PX) return;
      const w = this.r._pantallaAMundo(px, py);
      const cand = this._candidato(w);   // libre: no se bloquea contra el borde
      // Reformar un vértice puede cruzar aristas (figura imposible que el backend no sabe
      // adaptar). Si el candidato se autointersecta, se mantiene el último válido.
      if (autoCruza(cand)) {
        if (this._ultimoValido) this._aplicarLive(this._ultimoValido);
      } else {
        this._ultimoValido = cand;
        this._aplicarLive(cand);
      }
      this._movido = true;
      if (!this._rafId) {
        this._rafId = window.requestAnimationFrame(() => { this._rafId = 0; this.r.repintar(); });
      }
    }

    _up(ev) {
      if (!this.modo) return;
      const movido = this._movido, id = this.seleccionId, modo = this.modo;
      // ¿Se CONFIRMA (sella + reordena + recalcula)? Un 'mover' solo confirma si el arrastre
      // desde el origen alcanza COMMIT_PX; así el jitter de un doble-clic (4-8px) hace preview
      // pero NUNCA comete un mover (que reordenaría + recalcularía → el backend re-adapta y
      // teletransporta el patio). El 2.º+ clic de un multi-clic (ev.detail>=2) NUNCA confirma,
      // sea cual sea el arrastre (backstop para derivas grandes del segundo clic).
      let dist = Infinity;
      if (this._startPx && ev) {
        const [px, py] = this._pos(ev);
        dist = Math.hypot(px - this._startPx[0], py - this._startPx[1]);
      }
      const segundoClic = !!ev && typeof ev.detail === "number" && ev.detail >= 2;
      const gateMover = (modo === "mover") ? (dist >= COMMIT_PX) : true;
      const confirmar = movido && !segundoClic && gateMover;
      // Se sella sobre la forma arrastrada en vivo (`poligono`), nunca sobre la ideal.
      let forma = null;
      if (confirmar && this._patioObj) {
        forma = abrirAnillo(this._patioObj.poligono);
        if (modo === "vertice") forma = escalarAArea(forma, this._area0);  // reformar → reescala al área
        this._aplicarLive(forma);
      } else if (movido && this._patioObj) {
        // Hubo preview en vivo pero NO se confirma (jitter / 2.º clic de un doble-clic): revierte
        // el micro-arrastre para no dejar deriva colgando — el patio vuelve a su sitio.
        this._aplicarLive(this._poly0);
      }
      this.modo = null; this.handleIdx = -1; this._patioObj = null; this._movido = false;
      // Clic suelto (sin arrastre) sobre un grupo de tiradores superpuestos → cicla al
      // siguiente y lo resalta para el próximo clic. El arrastre NO cicla (movido=true).
      if (!movido && this._avanzarEnUp && this._cicloCands && this._cicloCands.length > 1 && this._ciclo) {
        this._ciclo.idx = (this._ciclo.idx + 1) % this._cicloCands.length;
        this._handleResaltado = this._cicloCands[this._ciclo.idx];
      }
      this._avanzarEnUp = false;
      this.r.repintar();
      if (confirmar && id) this.opts.onCommit && this.opts.onCommit(id, forma);
    }

    // Fija una geometría EN SITIO (vía `onFijarGeom`): NO reordena a última prioridad ni
    // recalcula. Insertar/borrar un vértice CONSERVA el área asignada, así que la capacidad no
    // cambia y el backend no necesita re-adaptar; evita el teletransporte por re-adaptación.
    // Cae a `onCommit` solo si `onFijarGeom` no está cableado (compat).
    _fijar(id, geom) {
      const fijar = this.opts.onFijarGeom || this.opts.onCommit;
      fijar && fijar(id, geom);
    }

    _dblclick(ev) {   // doble-clic SOBRE una arista → inserta un vértice (EN SITIO, sin recálculo)
      if (!this.activo || !this.seleccionId) return;
      const sel = this._patioPorId(this.seleccionId);
      if (!sel) return;
      const w = this.r._pantallaAMundo(...this._pos(ev));
      const v = this._editable(sel), tolPx = HIT_PX + 2;   // arista de la forma efectiva
      let mejor = -1, mejorD = Infinity;
      for (let i = 0; i < v.length; i++) {
        const a = v[i], b = v[(i + 1) % v.length];
        const d = this._distPuntoSegmentoPx(w, a, b);
        if (d < mejorD) { mejorD = d; mejor = i; }
      }
      // Cerca de una arista → inserta un vértice. (El doble-clic «volver a cuadrado»/centrado en el
      // CUERPO se ELIMINÓ a petición del arquitecto: un doble-clic interior ya no hace nada.)
      if (mejor >= 0 && mejorD <= tolPx) {
        ev.preventDefault();
        const nuevo = clon(v); nuevo.splice(mejor + 1, 0, [w[0], w[1]]);
        const re = escalarAArea(nuevo, (typeof sel.area_m2 === "number") ? sel.area_m2 : areaPoly(nuevo));
        sel.base = re; sel.poligono = re; this.r.repintar();
        this._fijar(sel.id, re);   // EN SITIO: insertar vértice conserva el área → sin reorden ni recálculo
      }
    }

    _contextmenu(ev) {   // clic derecho sobre un vértice → lo elimina (si quedan ≥3)
      if (!this.activo || !this.seleccionId) return;
      const sel = this._patioPorId(this.seleccionId);
      if (!sel) return;
      const v = this._editable(sel);   // vértices de la forma efectiva
      if (v.length <= 3) return;   // un triángulo es el mínimo
      const [px, py] = this._pos(ev);
      for (let i = 0; i < v.length; i++) {
        const s = this.r._mundoAPantalla(v[i][0], v[i][1]);
        if (Math.hypot(s[0] - px, s[1] - py) <= HIT_PX) {
          ev.preventDefault();
          const nuevo = clon(v); nuevo.splice(i, 1);
          const re = escalarAArea(nuevo, (typeof sel.area_m2 === "number") ? sel.area_m2 : areaPoly(nuevo));
          sel.base = re; sel.poligono = re; this.r.repintar();
          this._fijar(sel.id, re);   // EN SITIO: borrar vértice conserva el área → sin reorden ni recálculo
          return;
        }
      }
    }

    _distPuntoSegmentoPx(wPt, aW, bW) {
      const p = this.r._mundoAPantalla(wPt[0], wPt[1]);
      const a = this.r._mundoAPantalla(aW[0], aW[1]);
      const b = this.r._mundoAPantalla(bW[0], bW[1]);
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const L2 = dx * dx + dy * dy || 1e-9;
      let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2;
      t = Math.max(0, Math.min(1, t));
      return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
    }

    // ── Overlay (se dibuja en el contexto YA rotado por la brújula) ──
    dibujarOverlay() {
      if (!this.activo || !this.seleccionId) return;
      const sel = this._patioPorId(this.seleccionId);
      if (!sel) return;
      // Tiradores y contorno sobre la forma EFECTIVA (la adaptada y visible): el contorno
      // discontinuo coincide con el relleno dibujado, así se edita lo que se ve (no una
      // forma ideal que asome fuera de la parcela).
      const r = this.r, ctx = r.ctx, v = this._editable(sel);
      ctx.save();
      // Contorno de selección
      ctx.beginPath();
      v.forEach((p, i) => { const x = r._x(p[0]), y = r._y(p[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.closePath();
      ctx.setLineDash([5, 3]); ctx.strokeStyle = COLOR.dorado; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.setLineDash([]);
      // Tirador de giro
      const g = this._tiradorGiro(v), b = bbox(v);
      const top = [(b.mnx + b.mxx) / 2, b.mxy];
      ctx.beginPath(); ctx.moveTo(r._x(top[0]), r._y(top[1])); ctx.lineTo(r._x(g[0]), r._y(g[1]));
      ctx.strokeStyle = COLOR.dorado; ctx.lineWidth = 1.2; ctx.stroke();
      this._disco(ctx, r._x(g[0]), r._y(g[1]), COLOR.dorado);
      // Tiradores de estirar (rombos)
      this._tiradoresEstirar(v).forEach(m => this._rombo(ctx, r._x(m[0]), r._y(m[1]), COLOR.dorado));
      // Vértices (cuadrados blancos)
      v.forEach(p => this._cuadrado(ctx, r._x(p[0]), r._y(p[1])));
      // Tirador activo (cuando vértice y rombo se solapan): se dibuja ENCIMA con un aro
      // dorado de realce, para ver cuál se cogerá. Cicla con clics sucesivos (ver _hit).
      const hr = this._handleResaltado;
      if (hr && hr.patio && hr.patio.id === this.seleccionId) {
        let pw = null;
        if (hr.modo === "rotar") pw = this._tiradorGiro(v);
        else if (hr.modo === "estirar") pw = this._tiradoresEstirar(v)[hr.idx];
        else if (hr.modo === "vertice") pw = v[hr.idx];
        if (pw) {
          const hx = r._x(pw[0]), hy = r._y(pw[1]);
          ctx.beginPath(); ctx.arc(hx, hy, HIT_PX, 0, Math.PI * 2);
          ctx.strokeStyle = COLOR.dorado; ctx.lineWidth = 2; ctx.stroke();
          if (hr.modo === "vertice") this._cuadrado(ctx, hx, hy);
          else if (hr.modo === "estirar") this._rombo(ctx, hx, hy, COLOR.dorado);
          else this._disco(ctx, hx, hy, COLOR.dorado);
        }
      }
      ctx.restore();
    }
    _cuadrado(ctx, x, y) {
      ctx.fillStyle = COLOR.blanco; ctx.strokeStyle = COLOR.negro; ctx.lineWidth = 1;
      ctx.fillRect(x - 4, y - 4, 8, 8); ctx.strokeRect(x - 4, y - 4, 8, 8);
    }
    _rombo(ctx, x, y, color) {
      ctx.beginPath(); ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.lineTo(x - 5, y); ctx.closePath();
      ctx.fillStyle = color; ctx.fill(); ctx.strokeStyle = COLOR.negro; ctx.lineWidth = 0.8; ctx.stroke();
    }
    _disco(ctx, x, y, color) {
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
      ctx.strokeStyle = COLOR.negro; ctx.lineWidth = 0.8; ctx.stroke();
    }
  }

  window.PatioEditor = PatioEditor;
})();
