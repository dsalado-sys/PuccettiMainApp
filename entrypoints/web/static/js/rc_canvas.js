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

  class RenderCanvas {
    constructor(canvasEl) {
      this.cv = canvasEl;
      this.ctx = canvasEl.getContext("2d");
      this.bbox = null;     // [minx, miny, maxx, maxy]
      this.scale = 1;
      this.padPx = 28;
      this.origenX = 0;
      this.origenY = 0;
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

    _calcViewport(bbox) {
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
    }

    _x(x) { return this.origenX + x * this.scale; }
    _y(y) { return this.origenY - y * this.scale; }

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

    _patronPatio(ring) {
      const ctx = this.ctx;
      ctx.save();
      ctx.beginPath();
      ring.forEach((p, i) => {
        const px = this._x(p[0]);
        const py = this._y(p[1]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fillStyle = COLOR.grisSuave;
      ctx.fill();
      ctx.clip();
      // Rayas diagonales
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

    _etiquetaOrientacion(lado) {
      const a = lado.p1, b = lado.p2;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      // normal exterior (apuntando hacia fuera) — depende del winding del contorno
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const L = Math.hypot(dx, dy) || 1;
      const nx = dy / L;
      const ny = -dx / L;
      const offset = 14 / this.scale;
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
      ctx.fillText(unidad.area_util_m2.toFixed(1) + " m²", this._x(cx), this._y(cy) + 7);
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
      this._ajustarTamano();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.cv.width, this.cv.height);

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
        // Footprint con muros
        if (planta.footprint) {
          this._trazarPoligono(planta.footprint, "rgba(255,255,255,0.85)", null, 0);
        }
        // Patios
        (planta.patios || []).forEach(p => this._patronPatio(p.poligono));
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
    }
  }

  window.RenderCanvas = RenderCanvas;
})();
