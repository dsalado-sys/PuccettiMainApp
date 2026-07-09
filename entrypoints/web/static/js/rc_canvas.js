/* §2.4 — Render 2D vectorial sobre HTML5 Canvas (req. 9).
   Recibe el JSON serializado del backend y dibuja:
   - contorno de la parcela
   - footprint de la planta activa (muros perimetrales)
   - lados (fachada en dorado · medianera en negro grueso · req. 1)
   - patios (rayado diagonal)
   - núcleo vertical (gris oscuro con etiqueta)
   - pasillos (blanco translúcido)
   - unidades (relleno dorado claro · adaptadas con borde discontinuo)
   - etiquetas de orientación N/NE/E/SE/... en cada fachada
   - cotas básicas y superficies por unidad
*/
(function () {
  "use strict";

  const COLOR = {
    negro: "#0A0A0A",
    dorado: "#B8960C",
    doradoClaro: "#C9A84C",
    blanco: "#FFFFFF",
    grisSuave: "#F4F2EC",
    grisMedio: "#B8B6AE",
    error: "#8C2A1F",
  };

  const ZOOM_MIN = 1;     // encaje a la bbox = lo más alejado
  const ZOOM_MAX = 12;
  const ZOOM_PASO = 1.1;  // factor por muesca de rueda

  class RenderCanvas {
    constructor(canvasEl) {
      this.cv = canvasEl;
      this.ctx = canvasEl.getContext("2d");
      this.bbox = null;     // [minx, miny, maxx, maxy]
      this.scale = 1;
      this.padPx = 28;
      this.origenX = 0;
      this.origenY = 0;
      this.rotationDeg = 0;
      this._lastPayload = null;
      this._lastIndicePlanta = 0;
      this._overlay = null;   // capa de edición (patios): fn(renderer) en ctx ya rotado
      // Capa raster del WMS de Catastro (opcional). Se pide una única imagen GetMap
      // en el CRS UTM de la parcela y se dibuja encima con globalAlpha (slider).
      this._catastro = {
        activa: false, alpha: 1,
        img: null, imgBbox: null,          // imagen mostrada + bbox con que se pidió
        pedidoBbox: null, pedidoEpsg: null, // última vista pedida (evita re-pedir igual)
        timer: null,                        // debounce de la petición al mover la vista
      };
      // Vista del usuario (zoom). Persiste entre repintados mientras la parcela (bbox)
      // no cambie; al cambiar de parcela, `_calcViewport` re-encaja.
      this._vistaUsuario = false;
      this._fitBbox = null;
      this._zoom = 1;         // multiplicador relativo al encaje
      this._bindZoom();
    }

    // Zoom con Ctrl + rueda del ratón, centrado en el cursor.
    _bindZoom() {
      this.cv.addEventListener("wheel", (e) => {
        if (!e.ctrlKey) return;        // sin Ctrl → scroll normal de la página
        e.preventDefault();            // Ctrl+rueda = zoom de página; lo capturamos aquí
        const r = this.cv.getBoundingClientRect();
        this.zoomEn(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? ZOOM_PASO : 1 / ZOOM_PASO);
      }, { passive: false });
    }

    // Acerca/aleja fijando bajo el cursor el mismo punto del mundo (respeta la rotación
    // de la brújula, igual que `_pantallaAMundo`).
    zoomEn(px, py, factor) {
      const nuevo = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, this._zoom * factor));
      if (nuevo <= ZOOM_MIN) { this.resetVista(); return; }   // al mínimo, encaje limpio
      const ef = nuevo / this._zoom;                          // factor efectivo tras el clamp
      if (ef === 1) return;
      const [rx, ry] = this._rotarPunto(px, py, -this.rotationDeg);   // píxel sin rotar
      const wx = (rx - this.origenX) / this.scale;
      const wy = (this.origenY - ry) / this.scale;            // mundo bajo el cursor
      this.scale *= ef;
      this.origenX = rx - wx * this.scale;                    // recoloca para fijar (wx,wy)
      this.origenY = ry + wy * this.scale;
      this._zoom = nuevo;
      this._vistaUsuario = true;
      this.repintar();
    }

    // Vuelve al encaje a la bbox en el próximo dibujado.
    resetVista() {
      this._vistaUsuario = false;
      this._zoom = 1;
      this.repintar();
    }

    setRotation(deg) {
      this.rotationDeg = ((deg % 360) + 360) % 360;
      this.repintar();
    }

    repintar() {
      if (this._lastPayload) this.dibujar(this._lastPayload, this._lastIndicePlanta);
    }

    // Capa de edición opcional, dibujada al final de `dibujar` dentro del contexto
    // YA rotado (así los tiradores se pegan a la geometría girada por la brújula).
    setOverlay(fn) { this._overlay = fn; }

    // Paneo del plano arrastrando con el ratón (como mover un mapa). Se registra
    // DESPUÉS del editor de patios: si el editor consumió el mousedown (agarró un
    // tirador/patio/botón), llama a preventDefault y aquí lo respetamos → solo se
    // panea al arrastrar sobre zona vacía. Mueve todo por igual (parcela, patios
    // bloqueados o no, y la capa de Catastro), porque todo se dibuja vía _x/_y.
    habilitarPaneo() {
      if (this._panBind) return;
      this._panBind = true;
      const cv = this.cv;
      cv.addEventListener("mousedown", (e) => {
        if (e.defaultPrevented || e.button !== 0 || !this._lastPayload) return;
        this._pan = { x: e.clientX, y: e.clientY, movido: false };
        cv.style.cursor = "grabbing";
      });
      window.addEventListener("mousemove", (e) => {
        if (!this._pan) return;
        const dx = e.clientX - this._pan.x, dy = e.clientY - this._pan.y;
        if (!this._pan.movido && Math.hypot(dx, dy) < 3) return;
        this._pan.movido = true;
        this._pan.x = e.clientX; this._pan.y = e.clientY;
        this.panear(dx, dy);
      });
      window.addEventListener("mouseup", () => {
        if (this._pan) { this._pan = null; cv.style.cursor = ""; }
      });
    }

    // Desplaza la vista un delta de PANTALLA. Como la rotación de la brújula se
    // aplica alrededor del centro en `dibujar` y origenX/Y viven en el marco SIN
    // rotar, se convierte el delta al marco sin rotar (R(-θ)) para que el plano
    // acompañe al cursor en cualquier ángulo.
    panear(dxPx, dyPx) {
      const rad = -this.rotationDeg * Math.PI / 180;
      const c = Math.cos(rad), s = Math.sin(rad);
      this.origenX += dxPx * c - dyPx * s;
      this.origenY += dxPx * s + dyPx * c;
      this._vistaUsuario = true;   // preserva la vista paneada (no re-encaja a la bbox)
      this.repintar();
    }

    // Activa/desactiva la capa de Catastro y fija su opacidad (0..1). Al activarse,
    // pide el WMS para la vista actual y repinta cuando cargue.
    setCapaCatastro({ activa, alpha }) {
      this._catastro.activa = !!activa;
      if (typeof alpha === "number") this._catastro.alpha = Math.max(0, Math.min(1, alpha));
      if (this._catastro.activa) this._refrescarCatastro();
      this.repintar();
    }

    // Bbox del MUNDO (UTM) visible ahora en el lienzo, con margen. Se calcula
    // proyectando a mundo las 4 esquinas de pantalla (deshaciendo la rotación),
    // de modo que al girar la brújula cubre todo el rectángulo girado.
    _viewportMundoBbox(pad) {
      const esq = [[0, 0], [this.wPx, 0], [0, this.hPx], [this.wPx, this.hPx]];
      let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;
      for (const [px, py] of esq) {
        const [wx, wy] = this._pantallaAMundo(px, py);
        if (wx < mnx) mnx = wx; if (wx > mxx) mxx = wx;
        if (wy < mny) mny = wy; if (wy > mxy) mxy = wy;
      }
      const dx = (mxx - mnx) * pad, dy = (mxy - mny) * pad;
      return [mnx - dx, mny - dy, mxx + dx, mxy + dy];
    }

    // Pide al WMS de Catastro una imagen para la vista actual, a la resolución de
    // la pantalla, y la re-pide (debounced) cuando la vista cambia lo suficiente
    // (zoom / rotación / nueva parcela). Así los detalles y etiquetas se rasterizan
    // a la escala correcta en cada nivel de zoom, igual que en «Buscar parcela».
    _refrescarCatastro() {
      const c = this._catastro;
      if (!c.activa) return;
      const parcela = this._lastPayload && this._lastPayload.parcela;
      const epsg = parcela && parcela.epsg;
      if (!epsg || !this.scale || this.scale <= 0) return;
      const bbox = this._viewportMundoBbox(0.15);
      const [minx, miny, maxx, maxy] = bbox;
      const W = maxx - minx, H = maxy - miny;
      if (!(W > 0) || !(H > 0)) return;
      // ¿La vista cambió de forma apreciable respecto a lo ya pedido? (evita
      // re-pedir en cada repintado, p.ej. el repaint del onload).
      const prev = c.pedidoBbox;
      if (prev && Math.abs(prev[0] - minx) < W * 0.06 && Math.abs(prev[1] - miny) < H * 0.06
          && Math.abs(prev[2] - maxx) < W * 0.06 && Math.abs(prev[3] - maxy) < H * 0.06
          && c.pedidoEpsg === epsg) return;
      c.pedidoBbox = bbox; c.pedidoEpsg = epsg;
      if (c.timer) clearTimeout(c.timer);
      c.timer = setTimeout(() => this._pedirCatastro(bbox, epsg), 160);
    }

    // Lanza la petición GetMap y, al cargar, sustituye la imagen mostrada (guardando
    // el bbox con el que se pidió, para dibujarla alineada). No fija crossOrigin: el
    // WMS no envía CORS; solo se dibuja, nunca se leen píxeles del canvas.
    _pedirCatastro(bbox, epsg) {
      const [minx, miny, maxx, maxy] = bbox;
      const W = maxx - minx, H = maxy - miny;
      // Resolución = px de pantalla que ocupa el bbox (× nitidez), acotada.
      const nitidez = 1.4, maxLado = 2048;
      let w = Math.round(W * this.scale * nitidez);
      let h = Math.round(H * this.scale * nitidez);
      const k = maxLado / Math.max(w, h);
      if (k < 1) { w = Math.round(w * k); h = Math.round(h * k); }
      w = Math.max(256, w); h = Math.max(256, h);
      const url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"
        + "?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=Catastro&STYLES="
        + "&SRS=EPSG:" + epsg
        + "&BBOX=" + [minx, miny, maxx, maxy].join(",")
        + "&WIDTH=" + w + "&HEIGHT=" + h
        + "&FORMAT=image/png&TRANSPARENT=TRUE&EXCEPTIONS=BLANK";
      const img = new Image();
      img.onload = () => {
        if (!img.naturalWidth) return;
        this._catastro.img = img;
        this._catastro.imgBbox = bbox;
        this.repintar();
      };
      img.src = url;
    }

    _dibujarCatastro() {
      const c = this._catastro;
      if (!c.activa || c.alpha <= 0 || !c.img || !c.img.complete || !c.img.naturalWidth || !c.imgBbox) return;
      const [minx, miny, maxx, maxy] = c.imgBbox;
      const ctx = this.ctx;
      ctx.save();
      ctx.globalAlpha = c.alpha;
      // Mapeado por _x/_y ⇒ dentro del contexto ya rotado sigue rotación y zoom.
      ctx.drawImage(c.img, this._x(minx), this._y(maxy), (maxx - minx) * this.scale, (maxy - miny) * this.scale);
      ctx.restore();
    }

    _ajustarTamano() {
      const dpr = window.devicePixelRatio || 1;
      const rect = this.cv.getBoundingClientRect();
      const w = Math.max(400, rect.width);
      const h = Math.max(400, rect.height);
      this.cv.width = Math.round(w * dpr);
      this.cv.height = Math.round(h * dpr);
      this.cv.style.width = w + "px";
      this.cv.style.height = h + "px";
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.wPx = w;
      this.hPx = h;
    }

    _mismaBbox(a, b) {
      if (!a || !b || a.length < 4 || b.length < 4) return false;
      for (let i = 0; i < 4; i++) if (Math.abs(a[i] - b[i]) > 1e-6) return false;
      return true;
    }

    _calcViewport(bbox) {
      // Si el usuario tiene zoom y la parcela (bbox) no cambió, conservamos su vista
      // (scale/origen) para que el zoom persista entre repintados y pestañas de planta.
      if (this._vistaUsuario && this._mismaBbox(bbox, this._fitBbox)) {
        this.bbox = bbox;
        return;
      }
      const [mnx, mny, mxx, mxy] = bbox;
      const W = mxx - mnx, H = mxy - mny;
      if (W <= 0 || H <= 0) { this.scale = 1; this.origenX = 0; this.origenY = 0; return; }
      const dispW = this.wPx - 2 * this.padPx;
      const dispH = this.hPx - 2 * this.padPx;
      this.scale = Math.min(dispW / W, dispH / H);
      // centramos
      this.origenX = this.padPx + (dispW - W * this.scale) / 2 - mnx * this.scale;
      this.origenY = this.padPx + (dispH - H * this.scale) / 2 + mxy * this.scale; // invertimos Y
      this.bbox = bbox;
      // Nuevo encaje (parcela distinta o primera vez): resetea la vista del usuario.
      this._fitBbox = bbox;
      this._vistaUsuario = false;
      this._zoom = 1;
    }

    _x(x) { return this.origenX + x * this.scale; }
    _y(y) { return this.origenY - y * this.scale; }

    // --- Inversas pantalla→mundo (edición interactiva de patios) ---
    // Rota (px,py) `deg` grados alrededor del centro del lienzo (igual que `dibujar`).
    _rotarPunto(px, py, deg) {
      if (!deg) return [px, py];
      const rad = deg * Math.PI / 180;
      const cx = this.wPx / 2, cy = this.hPx / 2;
      const dx = px - cx, dy = py - cy;
      const c = Math.cos(rad), s = Math.sin(rad);
      return [cx + dx * c - dy * s, cy + dx * s + dy * c];
    }
    // Pixel de lienzo (CSS px, ya restado el getBoundingClientRect) → coordenada UTM.
    // Primero deshace la rotación global de la brújula, luego invierte _x/_y.
    _pantallaAMundo(px, py) {
      const [rx, ry] = this._rotarPunto(px, py, -this.rotationDeg);
      return [(rx - this.origenX) / this.scale, (this.origenY - ry) / this.scale];
    }
    // Inverso exacto de _pantallaAMundo: UTM → pixel de lienzo (hit-test de tiradores).
    _mundoAPantalla(x, y) {
      return this._rotarPunto(this.origenX + x * this.scale, this.origenY - y * this.scale, this.rotationDeg);
    }

    _trazarPoligono(ring, fill, stroke, lineWidth) {
      if (!ring || ring.length < 2) return;
      const ctx = this.ctx;
      ctx.beginPath();
      ring.forEach((p, i) => {
        const px = this._x(p[0]);
        const py = this._y(p[1]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lineWidth || 1;
        ctx.stroke();
      }
    }

    _patronPatio(ring, huecos) {
      const ctx = this.ctx;
      ctx.save();
      const trazar = (anillo) => {
        anillo.forEach((p, i) => {
          const px = this._x(p[0]), py = this._y(p[1]);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.closePath();
      };
      ctx.beginPath();
      trazar(ring);
      // Huecos (edificio dentro del patio → anillo): con "evenodd" recortan el relleno.
      (huecos || []).forEach(h => { if (h && h.length >= 3) trazar(h); });
      ctx.fillStyle = COLOR.grisSuave;
      ctx.fill("evenodd");
      ctx.clip("evenodd");
      // Rayas diagonales (el clip las limita al anillo menos los huecos)
      ctx.strokeStyle = COLOR.grisMedio;
      ctx.lineWidth = 1;
      const xs = ring.map(p => this._x(p[0]));
      const ys = ring.map(p => this._y(p[1]));
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      for (let x = minX - (maxY - minY); x < maxX; x += 7) {
        ctx.beginPath();
        ctx.moveTo(x, minY);
        ctx.lineTo(x + (maxY - minY), maxY);
        ctx.stroke();
      }
      ctx.restore();
    }

    _marcarPatioBloqueado(ring, huecos) {
      // Patio bloqueado (catastral o fijado por el usuario): borde dorado
      // discontinuo + candado, para distinguirlo de un patio editable.
      if (!ring || ring.length < 2) return;
      const ctx = this.ctx;
      const xs = ring.map(p => this._x(p[0]));
      const ys = ring.map(p => this._y(p[1]));
      ctx.save();
      ctx.strokeStyle = COLOR.dorado;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      const contorno = (anillo) => {
        ctx.beginPath();
        anillo.forEach((p, i) => {
          const px = this._x(p[0]), py = this._y(p[1]);
          (i === 0) ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.stroke();
      };
      contorno(ring);
      (huecos || []).forEach(h => { if (h && h.length >= 3) contorno(h); });   // borde del edificio interior
      ctx.setLineDash([]);
      const w = Math.max(...xs) - Math.min(...xs);
      const h = Math.max(...ys) - Math.min(...ys);
      if (Math.min(w, h) >= 16) {
        const cx = xs.reduce((a, b) => a + b, 0) / xs.length;
        const cy = ys.reduce((a, b) => a + b, 0) / ys.length;
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("🔒", cx, cy);
      }
      ctx.restore();
    }

    _dibujarLado(lado) {
      const ctx = this.ctx;
      const a = lado.p1, b = lado.p2;
      ctx.beginPath();
      ctx.moveTo(this._x(a[0]), this._y(a[1]));
      ctx.lineTo(this._x(b[0]), this._y(b[1]));
      if (lado.tipo === "medianera") {
        ctx.strokeStyle = COLOR.negro;
        ctx.lineWidth = 4;
      } else {
        ctx.strokeStyle = COLOR.dorado;
        ctx.lineWidth = 2.5;
      }
      ctx.stroke();
    }

    // Ray casting en coordenadas de mundo: ¿(x,y) dentro del anillo?
    _puntoEnPoligono(x, y, ring) {
      let dentro = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const xi = ring[i][0], yi = ring[i][1];
        const xj = ring[j][0], yj = ring[j][1];
        if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
          dentro = !dentro;
        }
      }
      return dentro;
    }

    _etiquetaOrientacion(lado) {
      const a = lado.p1, b = lado.p2;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      // Normal al lado; el signo se decide para que la etiqueta caiga SIEMPRE fuera
      // del polígono (el winding del contorno no es fiable).
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const L = Math.hypot(dx, dy) || 1;
      let nx = dy / L;
      let ny = -dx / L;
      const offset = 16 / this.scale;
      const ring = this._lastPayload && this._lastPayload.parcela && this._lastPayload.parcela.poligono;
      if (ring && ring.length >= 3 && this._puntoEnPoligono(mx + nx * offset, my + ny * offset, ring)) {
        nx = -nx; ny = -ny;   // apuntaba hacia dentro → voltear hacia fuera
      }
      const tx = mx + nx * offset;
      const ty = my + ny * offset;

      const ctx = this.ctx;
      ctx.save();
      ctx.fillStyle = lado.tipo === "medianera" ? COLOR.negro : COLOR.dorado;
      ctx.font = "bold 11px Helvetica Neue, Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      // fondo blanco translúcido para legibilidad
      const txt = lado.orientacion || "";
      if (txt) {
        const w = ctx.measureText(txt).width + 6;
        ctx.fillStyle = "rgba(255,255,255,0.85)";
        ctx.fillRect(this._x(tx) - w / 2, this._y(ty) - 8, w, 16);
        ctx.fillStyle = lado.tipo === "medianera" ? COLOR.negro : COLOR.dorado;
        ctx.fillText(txt, this._x(tx), this._y(ty));
      }
      ctx.restore();
    }

    _etiquetaUnidad(unidad) {
      const ctx = this.ctx;
      const poly = unidad.poligono_util || unidad.poligono_construido;
      if (!poly || poly.length < 3) return;
      let cx = 0, cy = 0;
      for (const p of poly) { cx += p[0]; cy += p[1]; }
      cx /= poly.length; cy /= poly.length;
      ctx.save();
      ctx.fillStyle = COLOR.negro;
      ctx.font = "600 10px Helvetica Neue, Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(unidad.id, this._x(cx), this._y(cy) - 6);
      ctx.font = "10px Helvetica Neue, Inter, sans-serif";
      ctx.fillStyle = unidad.cumple_minimos ? "#2a2a2a" : COLOR.error;
      // es-ES: coma decimal en la etiqueta de superficie del canvas.
      ctx.fillText(unidad.area_util_m2.toFixed(1).replace(".", ",") + " m²", this._x(cx), this._y(cy) + 7);
      if (unidad.es_adaptada) {
        ctx.fillStyle = COLOR.dorado;
        ctx.font = "9px Helvetica Neue, Inter, sans-serif";
        ctx.fillText("adapt.", this._x(cx), this._y(cy) + 19);
      }
      ctx.restore();
    }

    _dibujarNucleo(nucleo) {
      if (!nucleo) return;
      this._trazarPoligono(nucleo.poligono, "rgba(10,10,10,0.10)", COLOR.negro, 1);
      // escalera + ascensor
      if (nucleo.escalera) this._trazarPoligono(nucleo.escalera, "rgba(184,150,12,0.10)", COLOR.negro, 0.8);
      if (nucleo.ascensor) {
        this._trazarPoligono(nucleo.ascensor, COLOR.blanco, COLOR.negro, 0.8);
        // X interior del ascensor
        const a = nucleo.ascensor;
        if (a.length >= 4) {
          const ctx = this.ctx;
          ctx.strokeStyle = COLOR.negro;
          ctx.lineWidth = 0.8;
          ctx.beginPath();
          ctx.moveTo(this._x(a[0][0]), this._y(a[0][1]));
          ctx.lineTo(this._x(a[2][0]), this._y(a[2][1]));
          ctx.moveTo(this._x(a[1][0]), this._y(a[1][1]));
          ctx.lineTo(this._x(a[3][0]), this._y(a[3][1]));
          ctx.stroke();
        }
      }
      // círculo libre Ø1.50
      if (nucleo.circulo_libre) {
        const c = nucleo.circulo_libre.centro;
        const r = nucleo.circulo_libre.radio_m * this.scale;
        const ctx = this.ctx;
        ctx.beginPath();
        ctx.arc(this._x(c[0]), this._y(c[1]), r, 0, Math.PI * 2);
        ctx.strokeStyle = nucleo.circulo_libre.cumple ? "#1a8b3a" : COLOR.error;
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1.2;
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    /**
     * Pinta una planta concreta.
     * @param payload  Estructura devuelta por /preview o /calcular
     * @param indicePlanta  Índice de la planta a dibujar (0 = PB)
     */
    dibujar(payload, indicePlanta) {
      this._lastPayload = payload;
      this._lastIndicePlanta = indicePlanta || 0;
      this._ajustarTamano();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.cv.width, this.cv.height);

      if (this.rotationDeg !== 0) {
        const cx = this.wPx / 2;
        const cy = this.hPx / 2;
        ctx.translate(cx, cy);
        ctx.rotate(this.rotationDeg * Math.PI / 180);
        ctx.translate(-cx, -cy);
      }

      if (!payload) {
        ctx.fillStyle = COLOR.grisMedio;
        ctx.font = "13px Helvetica Neue, Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Sin datos para dibujar.", this.cv.width / 2 / (window.devicePixelRatio || 1), this.cv.height / 2 / (window.devicePixelRatio || 1));
        return;
      }

      const parcela = payload.parcela || (payload.edificio && payload.edificio.parcela) || null;
      const bbox = (parcela && parcela.bbox)
        || (payload.envolvente && payload.envolvente.bbox)
        || (payload.edificio && payload.edificio.parcela && payload.edificio.parcela.bbox);
      if (!bbox || bbox.length < 4) {
        ctx.fillStyle = COLOR.grisMedio;
        ctx.font = "13px Helvetica Neue, Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Geometría no disponible.", this.wPx / 2, this.hPx / 2);
        return;
      }
      this._calcViewport(bbox);

      // Contorno de la parcela (fantasma)
      if (parcela && parcela.poligono) {
        this._trazarPoligono(parcela.poligono, "rgba(244,242,236,0.6)", COLOR.grisMedio, 1);
      }

      // Obtener la planta activa (del edificio si hay; si no, del preview)
      let planta = null;
      if (payload.edificio && payload.edificio.plantas && payload.edificio.plantas.length) {
        planta = payload.edificio.plantas[Math.min(indicePlanta || 0, payload.edificio.plantas.length - 1)];
      } else if (payload.envolvente && payload.envolvente.plantas && payload.envolvente.plantas.length) {
        planta = payload.envolvente.plantas[Math.min(indicePlanta || 0, payload.envolvente.plantas.length - 1)];
      }

      if (planta) {
        // Footprint con muros. La huella llega íntegra tras retranqueos normativos
        // (la ocupación máxima ya no la recorta: no hay anillo de retranqueo por ocupación).
        if (planta.footprint) {
          this._trazarPoligono(planta.footprint, "rgba(255,255,255,0.85)", null, 0);
        }
        // Patios
        (planta.patios || []).forEach(p => {
          this._patronPatio(p.poligono, p.huecos);
          if (p.bloqueado) this._marcarPatioBloqueado(p.poligono, p.huecos);
        });
        // Pasillos
        (planta.pasillos || []).forEach(p =>
          this._trazarPoligono(p.poligono, "rgba(255,255,255,0.95)", COLOR.grisMedio, 0.8)
        );
        // Núcleo
        this._dibujarNucleo(planta.nucleo);
        // Unidades
        (planta.unidades || []).forEach(u => {
          const fill = u.es_adaptada ? "rgba(184,150,12,0.40)" : "rgba(201,168,76,0.22)";
          const stroke = u.es_adaptada ? COLOR.dorado : COLOR.doradoClaro;
          this._trazarPoligono(u.poligono_construido, fill, stroke, 1);
          if (u.es_adaptada) {
            // borde discontinuo encima
            const ctx2 = this.ctx;
            ctx2.save();
            ctx2.setLineDash([4, 3]);
            ctx2.strokeStyle = COLOR.dorado;
            ctx2.lineWidth = 1.4;
            this._trazarPoligono(u.poligono_construido, null, COLOR.dorado, 1.4);
            ctx2.restore();
          }
          this._etiquetaUnidad(u);
        });
      }

      // Lados (fachada/medianera) — req. 1 distinción visual
      (payload.lados || []).forEach(l => {
        this._dibujarLado(l);
        this._etiquetaOrientacion(l);
      });

      // Capa de Catastro (raster WMS) encima de la geometría. Al mínimo de
      // transparencia (alpha=1) tapa el render → vista limpia del parcelario.
      // Adaptativa al zoom: re-pide el WMS a la escala de la vista actual.
      if (this._catastro.activa) {
        this._refrescarCatastro();        // re-pide si la vista cambió (zoom/rotación/parcela)
        this._dibujarCatastro();
      }

      // Capa de edición de patios (tiradores, selección, arrastre en vivo). Se
      // dibuja en el contexto YA rotado para pegarse a la geometría de la planta.
      if (this._overlay) this._overlay(this);
    }
  }

  window.RenderCanvas = RenderCanvas;
})();
