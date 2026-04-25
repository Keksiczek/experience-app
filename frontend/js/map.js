(function () {
  const escapeHtml = (window.ui && window.ui.escapeHtml) || function (str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  function cssVar(name, fallback) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (_) {
      return fallback;
    }
  }

  function firstSentence(text) {
    if (!text) return '';
    const m = String(text).match(/^[\s\S]*?[.!?](\s|$)/);
    return (m ? m[0] : text).trim();
  }

  // Three free-tier tile layers. Each is rendered with the same coordinate
  // grid so toggling does not require re-fitting bounds.
  const BASE_LAYERS = {
    osm: {
      label: 'Mapa',
      title: 'Standardní mapa (OpenStreetMap)',
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      options: {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors',
      },
    },
    satellite: {
      label: 'Satelit',
      title: 'Satelitní snímky (Esri World Imagery)',
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      options: {
        maxZoom: 19,
        attribution: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics',
      },
    },
    terrain: {
      label: 'Terén',
      title: 'Topografická mapa (OpenTopoMap)',
      url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      options: {
        maxZoom: 17,
        attribution:
          '© OpenTopoMap (CC-BY-SA), © OpenStreetMap contributors, SRTM',
      },
    },
  };

  const STORAGE_KEY = 'experience.basemap';

  function readPreferredBaseLayer() {
    try {
      const v = window.localStorage && localStorage.getItem(STORAGE_KEY);
      if (v && BASE_LAYERS[v]) return v;
    } catch (_) { /* ignore */ }
    return 'osm';
  }

  function persistBaseLayer(name) {
    try { localStorage.setItem(STORAGE_KEY, name); } catch (_) { /* ignore */ }
  }

  function makeMarkerIcon(stopOrderLabel, fallbackLevel) {
    const cls = `stop-marker ${fallbackLevel || 'MINIMAL'}`;
    return L.divIcon({
      className: '',
      html: `<div class="${cls}">${escapeHtml(String(stopOrderLabel))}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function buildBasemapControl(initial, onSelect) {
    const wrap = document.createElement('div');
    wrap.className = 'basemap-control';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Mapový podklad');
    wrap.innerHTML = Object.entries(BASE_LAYERS)
      .map(([key, cfg]) => `
        <button type="button"
                class="basemap-btn ${key === initial ? 'active' : ''}"
                data-basemap="${key}"
                title="${escapeHtml(cfg.title)}"
                aria-pressed="${key === initial ? 'true' : 'false'}">
          ${escapeHtml(cfg.label)}
        </button>
      `).join('');
    wrap.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-basemap]');
      if (!btn) return;
      const name = btn.getAttribute('data-basemap');
      onSelect(name);
    });
    L.DomEvent.disableClickPropagation(wrap);
    L.DomEvent.disableScrollPropagation(wrap);
    return wrap;
  }

  function initMap(elementId) {
    const el = document.getElementById(elementId);
    if (!el) throw new Error(`Map container '#${elementId}' not found`);

    const map = L.map(el, {
      zoomControl: true,
      attributionControl: true,
    }).setView([49.8, 15.5], 7); // Default: Czechia

    let activeBaseLayer = null;
    let activeBaseLayerName = null;

    // A small spinner badge shown while tiles are loading.  Tile loads can
    // take a while on slow tile servers (e.g. OpenTopoMap) and a silent
    // grey square is a worse experience than an obvious "working…" hint.
    const tileLoader = document.createElement('div');
    tileLoader.className = 'map-tile-loader hidden';
    tileLoader.setAttribute('aria-hidden', 'true');
    tileLoader.innerHTML = '<span class="spinner"></span><span>Načítám&nbsp;dlaždice…</span>';
    el.appendChild(tileLoader);
    L.DomEvent.disableClickPropagation(tileLoader);

    let pendingTileLoads = 0;
    function showTileSpinner() {
      pendingTileLoads += 1;
      tileLoader.classList.remove('hidden');
    }
    function hideTileSpinner() {
      pendingTileLoads = Math.max(0, pendingTileLoads - 1);
      if (pendingTileLoads === 0) tileLoader.classList.add('hidden');
    }

    function setBaseLayer(name) {
      const cfg = BASE_LAYERS[name];
      if (!cfg) return;
      if (activeBaseLayer) {
        activeBaseLayer.off('loading', showTileSpinner);
        activeBaseLayer.off('load', hideTileSpinner);
        map.removeLayer(activeBaseLayer);
      }
      // Switching layers nukes any in-flight load — reset the counter so
      // the spinner doesn't get stuck visible.
      pendingTileLoads = 0;
      tileLoader.classList.add('hidden');

      activeBaseLayer = L.tileLayer(cfg.url, cfg.options);
      activeBaseLayer.on('loading', showTileSpinner);
      activeBaseLayer.on('load', hideTileSpinner);
      activeBaseLayer.addTo(map);
      activeBaseLayerName = name;
      persistBaseLayer(name);
      el.querySelectorAll('[data-basemap]').forEach((btn) => {
        const isActive = btn.getAttribute('data-basemap') === name;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
    }

    const initial = readPreferredBaseLayer();
    setBaseLayer(initial);

    const control = buildBasemapControl(initial, setBaseLayer);
    el.appendChild(control);

    const markers = new Map(); // stopId -> marker
    let routeLine = null;

    function clear() {
      markers.forEach((m) => map.removeLayer(m));
      markers.clear();
      if (routeLine) {
        map.removeLayer(routeLine);
        routeLine = null;
      }
    }

    function setExperience(experience, options = {}) {
      clear();
      if (!experience || !Array.isArray(experience.stops) || experience.stops.length === 0) return;

      const onMarkerClick = options.onMarkerClick;
      const sortedStops = experience.stops.slice().sort(
        (a, b) => (a.stop_order ?? a.order ?? 0) - (b.stop_order ?? b.order ?? 0),
      );

      const latlngs = [];

      sortedStops.forEach((stop, idx) => {
        if (typeof stop.lat !== 'number' || typeof stop.lon !== 'number') return;
        const label = (stop.stop_order ?? idx) + 1;
        const icon = makeMarkerIcon(label, stop.fallback_level);

        const marker = L.marker([stop.lat, stop.lon], { icon }).addTo(map);
        const title = stop.short_title || stop.name || `Zastávka ${label}`;
        const whyFirst = firstSentence(stop.why_here || stop.narration || '');

        const popupHtml = `
          <strong>${escapeHtml(title)}</strong>
          <div>${escapeHtml(whyFirst)}</div>
          <a href="#stop-${escapeHtml(stop.id)}" data-stop-link="${escapeHtml(stop.id)}">Zobrazit detail</a>
        `;
        marker.bindPopup(popupHtml);
        marker.on('click', () => {
          if (typeof onMarkerClick === 'function') onMarkerClick(stop.id);
        });

        markers.set(stop.id, marker);
        latlngs.push([stop.lat, stop.lon]);
      });

      const style = (experience.generation_metadata && experience.generation_metadata.route_style_used) || '';
      if ((style === 'linear' || style === 'loop') && latlngs.length >= 2) {
        const linePoints = latlngs.slice();
        if (style === 'loop') linePoints.push(latlngs[0]);
        routeLine = L.polyline(linePoints, {
          color: cssVar('--accent', '#58a6ff'),
          weight: 3,
          opacity: 0.7,
          dashArray: '6 6',
        }).addTo(map);
      }

      if (latlngs.length > 0) {
        map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], maxZoom: 13 });
      }
    }

    function focusStop(stopId, opts = {}) {
      const marker = markers.get(stopId);
      if (!marker) return;
      const ll = marker.getLatLng();
      const targetZoom = opts.zoom != null ? opts.zoom : Math.max(map.getZoom(), 11);
      if (opts.animate === false) {
        map.setView(ll, targetZoom, { animate: false });
      } else {
        map.flyTo(ll, targetZoom, { duration: opts.duration || 1.0, easeLinearity: 0.25 });
      }
      if (opts.openPopup !== false) marker.openPopup();
    }

    function flyToBounds() {
      const points = Array.from(markers.values()).map((m) => m.getLatLng());
      if (points.length === 0) return;
      map.flyToBounds(L.latLngBounds(points), {
        padding: [40, 40],
        maxZoom: 13,
        duration: 0.8,
      });
    }

    return {
      map,
      setExperience,
      focusStop,
      flyToBounds,
      setBaseLayer,
      getBaseLayer: () => activeBaseLayerName,
    };
  }

  window.map_ui = { initMap };
})();
