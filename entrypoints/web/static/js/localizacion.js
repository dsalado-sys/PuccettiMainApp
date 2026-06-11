/* Buscar parcela — controlador Leaflet + sidebar + slider + subreferencias.
   Paleta Puccetti: fachada #B8960C, medianera #0A0A0A. */
(function () {
  "use strict";

  const COLOR_FACHADA = "#B8960C";
  const COLOR_MEDIANERA = "#0A0A0A";
  const PESO_LADO = 4;

  const cfg = window.PUCCETTI_LOC || {};
  const puedeEditar = !!cfg.puedeEditar;

  let parcelaActual = null;
  let capaContorno = null;
  let capaLados = [];
  let capaEtiquetasOri = [];
  let ladoSeleccionado = null;
  let debounceSimpl = null;
  let bloquearSlider = false;

  // Estado de los comboboxes
  const cbState = {
    provincia: { codigo: "", nombre: "" },
    municipio: { codigo: "", nombre: "" },
    via:       { tipo_via: "", calle: "", etiqueta: "" }
  };
  let debounceProv = null;
  let debounceMuni = null;

  // ── Mapa Leaflet con selector de capas ───────────────────────────────────
  const mapa = L.map("mapa", { zoomControl: true }).setView([40.0, -3.7], 6);

  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
    maxZoom: 22,
  });

  const pnoa = L.tileLayer.wms("https://www.ign.es/wms-inspire/pnoa-ma", {
    layers: "OI.OrthoimageCoverage",
    format: "image/png",
    transparent: true,
    attribution: "PNOA · IGN",
    maxZoom: 22,
  });

  const catastro = L.tileLayer.wms("https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", {
    layers: "Catastro",
    format: "image/png",
    transparent: true,
    opacity: 0.55,
    attribution: "© Catastro",
    maxZoom: 22,
  });

  // OSM por defecto, Catastro encima.
  osm.addTo(mapa);
  catastro.addTo(mapa);

  L.control.layers(
    { "OpenStreetMap": osm, "Ortofoto PNOA": pnoa },
    { "Catastro": catastro },
    { position: "topright", collapsed: false }
  ).addTo(mapa);

  // Click en mapa → buscar parcela en coordenada
  mapa.on("click", function (ev) {
    if (!puedeEditar) {
      mostrarMensaje("Tu rol no puede modificar la parcela.", "info");
      return;
    }
    buscarPorCoordenada(ev.latlng.lng, ev.latlng.lat);
  });

  // ── Tabs ─────────────────────────────────────────────────────────────────
  document.querySelectorAll(".loc-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".loc-tab").forEach(function (b) { b.classList.remove("activo"); });
      btn.classList.add("activo");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".loc-panel").forEach(function (p) {
        p.classList.toggle("oculto", p.dataset.panel !== tab);
      });
    });
  });

  // ── Forms ────────────────────────────────────────────────────────────────
  document.getElementById("form-rc").addEventListener("submit", function (ev) {
    ev.preventDefault();
    enviarForm("/modulos/localizacion/buscar/rc", new FormData(ev.target));
  });

  document.getElementById("form-direccion").addEventListener("submit", function (ev) {
    ev.preventDefault();
    enviarForm("/modulos/localizacion/buscar/direccion", new FormData(ev.target));
  });

  // ── Combobox custom (provincia, municipio, vía) ──────────────────────────
  const cbProv = setupCombobox("provincia");
  const cbMuni = setupCombobox("municipio");
  const cbVia  = setupCombobox("via");
  const inpProvincia = document.getElementById("inp-provincia");
  const inpMunicipio = document.getElementById("inp-municipio");
  const inpVia = document.getElementById("inp-via");
  let viasCache = [];     // cache local: vías del municipio actual
  let viasCargando = false;

  // PROVINCIA: fetch on input (contains, accent-insensitive, en backend)
  inpProvincia.addEventListener("input", function () {
    if (debounceProv) clearTimeout(debounceProv);
    const q = inpProvincia.value.trim();
    debounceProv = setTimeout(function () { cargarProvincias(q); }, 160);
    // Si cambia el texto y ya no coincide con la selección anterior, reset cascada.
    if (cbState.provincia.nombre !== inpProvincia.value) resetMunicipio();
  });
  inpProvincia.addEventListener("focus", function () { cargarProvincias(inpProvincia.value.trim()); });

  function cargarProvincias(q) {
    fetch("/modulos/localizacion/callejero/provincias?q=" + encodeURIComponent(q))
      .then(parseRespuesta)
      .then(function (lista) { cbProv.mostrar(lista.map(function (p) {
        return { etiqueta: p.nombre, datos: p };
      })); })
      .catch(function () { /* silencioso */ });
  }

  cbProv.onSeleccionar = function (item) {
    cbState.provincia = { codigo: item.datos.codigo, nombre: item.datos.nombre };
    inpProvincia.value = item.datos.nombre;
    // Habilitar municipio, resetear vía
    inpMunicipio.disabled = false;
    inpMunicipio.placeholder = "";
    resetMunicipio();
    // Cargar municipios iniciales (vacío = primeros 50)
    cargarMunicipios("");
    inpMunicipio.focus();
  };

  // MUNICIPIO
  inpMunicipio.addEventListener("input", function () {
    if (!cbState.provincia.codigo) return;
    if (debounceMuni) clearTimeout(debounceMuni);
    const q = inpMunicipio.value.trim();
    debounceMuni = setTimeout(function () { cargarMunicipios(q); }, 180);
    if (cbState.municipio.nombre !== inpMunicipio.value) resetVia();
  });
  inpMunicipio.addEventListener("focus", function () {
    if (cbState.provincia.codigo) cargarMunicipios(inpMunicipio.value.trim());
  });

  function cargarMunicipios(q) {
    if (!cbState.provincia.codigo) return;
    fetch("/modulos/localizacion/callejero/municipios?provincia="
      + encodeURIComponent(cbState.provincia.codigo) + "&q=" + encodeURIComponent(q))
      .then(parseRespuesta)
      .then(function (lista) { cbMuni.mostrar(lista.map(function (m) {
        return { etiqueta: m.nombre, datos: m };
      })); })
      .catch(function () { /* silencioso */ });
  }

  cbMuni.onSeleccionar = function (item) {
    cbState.municipio = { codigo: item.datos.codigo, nombre: item.datos.nombre };
    inpMunicipio.value = item.datos.nombre;
    // Habilitar input de vía y disparar carga automática de vías del municipio.
    inpVia.disabled = false;
    inpVia.placeholder = "Cargando vías del Catastro…";
    cargarVias();
  };

  // VÍA: una carga única al elegir municipio; filtrado en cliente al teclear.
  function cargarVias() {
    if (!cbState.provincia.nombre || !cbState.municipio.nombre) return;
    viasCargando = true;
    viasCache = [];
    cbVia.mostrar([{ etiqueta: "Cargando vías del Catastro…", datos: null, deshabilitada: true }]);
    fetch("/modulos/localizacion/callejero/vias?provincia="
      + encodeURIComponent(cbState.provincia.nombre)
      + "&municipio=" + encodeURIComponent(cbState.municipio.nombre))
      .then(parseRespuesta)
      .then(function (lista) {
        viasCache = lista.map(function (v) { return { etiqueta: v.etiqueta, datos: v }; });
        inpVia.placeholder = viasCache.length
          ? "Escribe para filtrar las " + viasCache.length + " vías"
          : "Sin vías para este municipio";
        // Mostrar dropdown completo si el usuario ya está enfocado en el input.
        if (document.activeElement === inpVia) {
          cbVia.mostrar(viasCache.length ? viasCache
            : [{ etiqueta: "Sin vías para este municipio", datos: null, deshabilitada: true }]);
        }
      })
      .catch(function (err) {
        inpVia.placeholder = "Error: " + (err.message || "");
        cbVia.mostrar([{ etiqueta: "Error: " + (err.message || ""), datos: null, deshabilitada: true }]);
      })
      .finally(function () { viasCargando = false; });
  }

  function filtrarVias(texto) {
    if (viasCargando) {
      cbVia.mostrar([{ etiqueta: "Cargando…", datos: null, deshabilitada: true }]);
      return;
    }
    if (!viasCache.length) return;
    const norm = normalizar(texto);
    const filt = norm
      ? viasCache.filter(function (it) { return normalizar(it.etiqueta).indexOf(norm) !== -1; })
      : viasCache;
    cbVia.mostrar(filt.length ? filt
      : [{ etiqueta: "Sin coincidencias", datos: null, deshabilitada: true }]);
  }

  inpVia.addEventListener("input", function () { filtrarVias(inpVia.value); });
  inpVia.addEventListener("focus", function () {
    if (!inpVia.disabled) filtrarVias(inpVia.value);
  });

  cbVia.onSeleccionar = function (item) {
    if (!item.datos) return;
    cbState.via = item.datos;
    inpVia.value = item.datos.etiqueta;
    document.querySelector('input[name="tipo_via"]').value = item.datos.tipo_via || "";
    document.querySelector('input[name="calle"]').value = item.datos.calle || "";
  };

  function resetMunicipio() {
    cbState.municipio = { codigo: "", nombre: "" };
    inpMunicipio.value = "";
    cbMuni.ocultar();
    resetVia();
  }


  function resetVia() {
    cbState.via = { tipo_via: "", calle: "", etiqueta: "" };
    inpVia.value = "";
    inpVia.disabled = true;
    inpVia.placeholder = "Selecciona municipio primero";
    cbVia.ocultar();
    viasCache = [];
    document.querySelector('input[name="tipo_via"]').value = "";
    document.querySelector('input[name="calle"]').value = "";
  }

  function normalizar(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }

  function setupCombobox(nombre) {
    const root = document.querySelector('[data-cb="' + nombre + '"]');
    const lista = root.querySelector(".cb-list");
    const api = {
      onSeleccionar: null,
      onMostrar: null,
      mostrar: function (items) {
        lista.innerHTML = "";
        if (api.onMostrar) api.onMostrar(items);
        items.forEach(function (it) {
          const li = document.createElement("li");
          li.textContent = it.etiqueta;
          if (it.deshabilitada) {
            li.classList.add("cb-vacio");
          } else {
            li.addEventListener("mousedown", function (ev) {
              ev.preventDefault();
              if (api.onSeleccionar) api.onSeleccionar(it);
              api.ocultar();
            });
          }
          lista.appendChild(li);
        });
        lista.hidden = items.length === 0;
      },
      ocultar: function () { lista.hidden = true; }
    };
    // Cerrar al perder foco (con delay para permitir click en la lista).
    root.querySelector(".cb-input").addEventListener("blur", function () {
      setTimeout(api.ocultar, 150);
    });
    return api;
  }

  // ── Slider ───────────────────────────────────────────────────────────────
  const slider = document.getElementById("slider-simpl");
  const sliderValor = document.getElementById("slider-valor");
  slider.addEventListener("input", function () {
    sliderValor.textContent = parseFloat(slider.value).toFixed(1);
    if (bloquearSlider || !parcelaActual) return;
    if (debounceSimpl) clearTimeout(debounceSimpl);
    const tol = parseFloat(slider.value);
    debounceSimpl = setTimeout(function () {
      fetch("/modulos/localizacion/simplificar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tolerancia_m: tol }),
      })
        .then(parseRespuesta)
        .then(pintarParcela)
        .catch(mostrarError);
    }, 220);
  });

  // ── HTTP ─────────────────────────────────────────────────────────────────
  function enviarForm(url, formData) {
    limpiarMensaje();
    mostrarSpinner();
    fetch(url, { method: "POST", body: formData })
      .then(parseRespuesta)
      .then(pintarParcela)
      .catch(mostrarError)
      .finally(ocultarSpinner);
  }

  function buscarPorCoordenada(lon, lat) {
    limpiarMensaje();
    mostrarSpinner();
    fetch("/modulos/localizacion/buscar/coordenada", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: lon, lat: lat }),
    })
      .then(parseRespuesta)
      .then(pintarParcela)
      .catch(mostrarError)
      .finally(ocultarSpinner);
  }

  function buscarPorRcStr(rc) {
    limpiarMensaje();
    mostrarSpinner();
    const fd = new FormData();
    fd.append("rc", rc);
    fetch("/modulos/localizacion/buscar/rc", { method: "POST", body: fd })
      .then(parseRespuesta)
      .then(pintarParcela)
      .catch(mostrarError)
      .finally(ocultarSpinner);
  }

  function cambiarTipoLado(indice, nuevoTipo) {
    fetch("/modulos/localizacion/lado/" + indice + "/tipo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo: nuevoTipo }),
    })
      .then(parseRespuesta)
      .then(pintarParcela)
      .catch(mostrarError);
  }

  function cambiarOrientacionLado(indice, nuevaOrientacion) {
    fetch("/modulos/localizacion/lado/" + indice + "/orientacion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orientacion: nuevaOrientacion }),
    })
      .then(parseRespuesta)
      .then(pintarParcela)
      .catch(mostrarError);
  }

  function parseRespuesta(resp) {
    if (!resp.ok) {
      return resp.json().catch(function () { return { detail: "Error " + resp.status }; })
        .then(function (j) { throw new Error(j.detail || "Error " + resp.status); });
    }
    return resp.json();
  }

  // ── Render ───────────────────────────────────────────────────────────────
  function pintarParcela(parcela) {
    parcelaActual = parcela;
    pintarFicha(parcela);
    pintarMapa(parcela);
    pintarTablaLados(parcela);
    pintarCardsSubref(parcela);
    pintarAgregados(parcela);
    pintarDatosCatastrales(parcela);
    actualizarToggleCards();

    bloquearSlider = true;
    slider.value = parcela.tolerancia_simplificacion_m || 0;
    sliderValor.textContent = parseFloat(slider.value).toFixed(1);
    bloquearSlider = false;
  }

  function pintarFicha(p) {
    document.getElementById("loc-ficha").classList.remove("oculto");
    document.getElementById("loc-ficha-titulo").textContent = p.direccion || p.referencia_catastral;
    document.getElementById("loc-ficha-rc").textContent = p.referencia_catastral || "—";
    document.getElementById("loc-ficha-muni").textContent = p.municipio || "—";
    document.getElementById("loc-ficha-prov").textContent = p.provincia || "—";
    document.getElementById("loc-ficha-sup").textContent =
      p.superficie_m2 ? formatoNum(p.superficie_m2, 0) + " m²" : "—";
  }

  function pintarAgregados(p) {
    const box = document.getElementById("loc-agregados");
    if (!p.agregados) {
      box.classList.add("oculto");
      return;
    }
    box.classList.remove("oculto");
    document.getElementById("loc-agg-n").textContent = p.agregados.num_referencias;
    document.getElementById("loc-agg-edif").textContent =
      p.agregados.edificabilidad_m2t_m2s > 0
        ? p.agregados.edificabilidad_m2t_m2s.toFixed(2) + " m²t/m²s" : "—";
    document.getElementById("loc-agg-viv").textContent = p.agregados.num_viviendas;
    document.getElementById("loc-agg-dens").textContent =
      p.agregados.densidad_viviendas_viv_ha > 0
        ? formatoNum(p.agregados.densidad_viviendas_viv_ha, 1) + " viv/ha" : "—";
  }

  function pintarDatosCatastrales(p) {
    const box = document.getElementById("loc-catastro");
    if (!box) return;
    // El bloque también incluye RC/Mun/Prov/Sup que siempre están presentes,
    // así que lo mostramos siempre que haya parcela; cada campo opcional cae
    // a "—" cuando el Catastro no lo devuelve.
    box.classList.remove("oculto");
    const tieneUso = !!(p.uso_catastral && p.uso_catastral.trim());
    const tieneAnio = p.anio_construccion != null && p.anio_construccion !== "";
    const tieneSup = p.superficie_construida_total_m2 != null
      && p.superficie_construida_total_m2 > 0;
    const tienePl = p.plantas_sobre_rasante != null;
    const tieneSo = p.plantas_bajo_rasante != null && p.plantas_bajo_rasante > 0;
    document.getElementById("loc-cat-uso").textContent = tieneUso ? p.uso_catastral : "—";
    document.getElementById("loc-cat-anio").textContent = tieneAnio ? String(p.anio_construccion) : "—";
    document.getElementById("loc-cat-supc").textContent = tieneSup
      ? formatoNum(p.superficie_construida_total_m2, 0) + " m²" : "—";
    document.getElementById("loc-cat-plantas").textContent = tienePl
      ? String(p.plantas_sobre_rasante) : "—";
    document.getElementById("loc-cat-sotanos").textContent = tieneSo
      ? String(p.plantas_bajo_rasante) : "—";
  }

  function pintarCardsSubref(p) {
    const box = document.getElementById("loc-subref");
    const cont = document.getElementById("loc-cards");
    cont.innerHTML = "";
    if (!p.subreferencias || !p.subreferencias.length) {
      box.classList.add("oculto");
      return;
    }
    box.classList.remove("oculto");

    p.subreferencias.forEach(function (s) {
      const card = document.createElement("article");
      card.className = "loc-card";
      card.title =
        "Click para abrir esta parcela · RC: " + s.rc +
        (s.localizacion ? "  ·  Localización: " + s.localizacion : "") +
        (s.uso ? "  ·  Uso: " + s.uso : "");
      card.tabIndex = 0;
      card.addEventListener("click", function () { buscarPorRcStr(s.rc); });
      card.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); buscarPorRcStr(s.rc); }
      });

      const head = document.createElement("header");
      head.className = "loc-card-head";
      const spanRc = document.createElement("span");
      spanRc.className = "loc-card-rc";
      spanRc.title = "Referencia catastral";
      spanRc.textContent = s.rc;
      const spanLoc = document.createElement("span");
      spanLoc.className = "loc-card-loc";
      spanLoc.title = "Localización (escalera · planta · puerta)";
      spanLoc.textContent = s.localizacion || "—";
      head.appendChild(spanRc);
      head.appendChild(spanLoc);

      const body = document.createElement("div");
      body.className = "loc-card-body";
      body.appendChild(spanConTitulo("Uso", s.uso || "—"));
      body.appendChild(spanConTitulo(
        "Superficie construida",
        s.superficie_construida_m2 ? formatoNum(s.superficie_construida_m2, 1) + " m²" : "—"
      ));
      body.appendChild(spanConTitulo(
        "Coeficiente de participación",
        s.coeficiente_participacion != null ? s.coeficiente_participacion.toFixed(3) + "%" : "—"
      ));
      body.appendChild(spanConTitulo(
        "Año de construcción",
        s.anio_construccion != null ? s.anio_construccion : "—"
      ));

      card.appendChild(head);
      card.appendChild(body);
      cont.appendChild(card);
    });
  }

  function spanConTitulo(titulo, valor) {
    const sp = document.createElement("span");
    sp.title = titulo;
    sp.textContent = valor;
    return sp;
  }

  function pintarMapa(p) {
    if (capaContorno) { mapa.removeLayer(capaContorno); capaContorno = null; }
    capaLados.forEach(function (cl) { mapa.removeLayer(cl.polyline); });
    capaLados = [];
    capaEtiquetasOri.forEach(function (m) { mapa.removeLayer(m); });
    capaEtiquetasOri = [];

    if (!p.contorno_simplificado_wgs84 || p.contorno_simplificado_wgs84.length < 3) return;

    const latlngs = p.contorno_simplificado_wgs84.map(function (pt) { return [pt[1], pt[0]]; });
    capaContorno = L.polygon(latlngs, {
      color: COLOR_FACHADA,
      weight: 0,
      fillColor: COLOR_FACHADA,
      fillOpacity: 0.12,
      interactive: false,
    }).addTo(mapa);

    p.lados.forEach(function (lado) {
      const ll = [[lado.p1[1], lado.p1[0]], [lado.p2[1], lado.p2[0]]];
      const pl = L.polyline(ll, {
        color: lado.tipo === "medianera" ? COLOR_MEDIANERA : COLOR_FACHADA,
        weight: PESO_LADO,
        opacity: 0.95,
        lineCap: "round",
      }).addTo(mapa);
      pl.on("click", function (ev) {
        L.DomEvent.stopPropagation(ev);
        seleccionarLado(lado.indice);
        if (puedeEditar) {
          const nuevo = lado.tipo === "medianera" ? "fachada" : "medianera";
          cambiarTipoLado(lado.indice, nuevo);
        }
      });

      // Etiqueta de orientación cardinal en el punto medio del lado.
      const latMid = (lado.p1[1] + lado.p2[1]) / 2.0;
      const lonMid = (lado.p1[0] + lado.p2[0]) / 2.0;
      const etiqueta = L.marker([latMid, lonMid], {
        icon: L.divIcon({
          className: "loc-orientacion-tag tipo-" + lado.tipo,
          html: lado.orientacion || "?",
          iconSize: null,
        }),
        interactive: false,
        keyboard: false,
      }).addTo(mapa);
      capaEtiquetasOri.push(etiqueta);
      capaLados.push({ lado: lado, polyline: pl });
    });

    mapa.fitBounds(capaContorno.getBounds(), { padding: [40, 40], maxZoom: 19 });
  }

  function pintarTablaLados(p) {
    const tbody = document.getElementById("loc-lados-tbody");
    tbody.innerHTML = "";
    p.lados.forEach(function (lado) {
      const tr = document.createElement("tr");
      tr.dataset.indice = lado.indice;
      if (!puedeEditar) tr.classList.add("deshabilitada");

      const tdIdx = document.createElement("td"); tdIdx.textContent = lado.indice + 1;
      const tdLon = document.createElement("td"); tdLon.textContent = lado.longitud_m.toFixed(1) + " m";

      // Orientación cardinal — editable
      const tdOri = document.createElement("td");
      const selOri = document.createElement("select");
      ["N", "NE", "E", "SE", "S", "SO", "O", "NO"].forEach(function (o) {
        const opt = document.createElement("option");
        opt.value = o;
        opt.textContent = o;
        if (o === lado.orientacion) opt.selected = true;
        selOri.appendChild(opt);
      });
      selOri.title = "Azimut auto: " + lado.azimut_grados.toFixed(0) + "° · click para corregir";
      selOri.addEventListener("change", function () {
        if (!puedeEditar) return;
        cambiarOrientacionLado(lado.indice, selOri.value);
      });
      selOri.addEventListener("focus", function () { seleccionarLado(lado.indice); });
      tdOri.appendChild(selOri);

      const tdTipo = document.createElement("td");
      const sel = document.createElement("select");
      ["fachada", "medianera"].forEach(function (t) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t.charAt(0).toUpperCase() + t.slice(1);
        if (t === lado.tipo) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", function () {
        if (!puedeEditar) return;
        cambiarTipoLado(lado.indice, sel.value);
      });
      sel.addEventListener("focus", function () { seleccionarLado(lado.indice); });
      tdTipo.appendChild(sel);

      tr.appendChild(tdIdx); tr.appendChild(tdLon); tr.appendChild(tdOri); tr.appendChild(tdTipo);
      tbody.appendChild(tr);
    });
  }

  function seleccionarLado(indice) {
    ladoSeleccionado = indice;
    document.querySelectorAll("#loc-lados-tbody tr").forEach(function (tr) {
      tr.classList.toggle("activo", parseInt(tr.dataset.indice, 10) === indice);
    });
    capaLados.forEach(function (cl) {
      cl.polyline.setStyle({ weight: cl.lado.indice === indice ? PESO_LADO + 3 : PESO_LADO });
    });
  }

  // ── Utilidades ───────────────────────────────────────────────────────────
  function formatoNum(n, decimales) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("es-ES", {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales,
    });
  }

  // ── Spinner global ───────────────────────────────────────────────────────
  let spinnerCount = 0;
  function mostrarSpinner() {
    spinnerCount += 1;
    const sp = document.getElementById("loc-spinner");
    if (sp) sp.classList.remove("oculto");
  }
  function ocultarSpinner() {
    spinnerCount = Math.max(0, spinnerCount - 1);
    if (spinnerCount === 0) {
      const sp = document.getElementById("loc-spinner");
      if (sp) sp.classList.add("oculto");
    }
  }

  function mostrarError(err) {
    mostrarMensaje((err && err.message) || "Error inesperado", "error");
  }
  function mostrarMensaje(texto, tipo) {
    const box = document.getElementById("loc-mensaje");
    box.textContent = texto;
    box.className = "loc-mensaje " + (tipo === "error" ? "error" : "info");
  }
  function limpiarMensaje() {
    const box = document.getElementById("loc-mensaje");
    box.textContent = "";
    box.className = "loc-mensaje oculto";
  }

  // ── Toggles de sidebar y de columna de cards ─────────────────────────────
  const layout = document.getElementById("loc-layout");
  const btnToggleSidebar = document.getElementById("toggle-sidebar");
  const btnToggleCards = document.getElementById("toggle-cards");
  if (btnToggleSidebar) {
    btnToggleSidebar.addEventListener("click", function () {
      layout.classList.toggle("sidebar-oculto");
      setTimeout(function () { if (mapa) mapa.invalidateSize(); }, 220);
    });
  }
  if (btnToggleCards) {
    btnToggleCards.addEventListener("click", function () {
      layout.classList.toggle("cards-oculto");
      setTimeout(function () { if (mapa) mapa.invalidateSize(); }, 220);
    });
  }

  // Mostrar/ocultar el botón de cards según haya o no subreferencias.
  function actualizarToggleCards() {
    if (!btnToggleCards) return;
    const subref = document.getElementById("loc-subref");
    btnToggleCards.hidden = subref.classList.contains("oculto");
  }

  // ── Botón "Guardar como proyecto": indicar estado de carga ──────────────
  const formGuardar = document.getElementById("form-guardar");
  if (formGuardar) {
    formGuardar.addEventListener("submit", function () {
      const btn = document.getElementById("btn-guardar");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Guardando… (cargando detalles del Catastro)";
      }
      mostrarSpinner();
    });
  }

  // ── Estado inicial ───────────────────────────────────────────────────────
  if (cfg.parcelaInicial) {
    pintarParcela(cfg.parcelaInicial);
  }
})();
