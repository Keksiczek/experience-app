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

  function makeMarkerIcon(stopOrderLabel, fallbackLevel) {
    const cls = `stop-marker ${fallbackLevel || 'MINIMAL'}`;
    return L.divIcon({
      className: '',
      html: `<div class="${cls}">${escapeHtml(String(stopOrderLabel))}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  /**
   * Initialise Leaflet map into the #map container.
   * Returns an object { setExperience(exp, { onMarkerClick }), focusStop(stopId) }.
   */
  function initMap(elementId) {
    const el = document.getElementById(elementId);
    if (!el) throw new Error(`Map container '#${elementId}' not found`);

    const map = L.map(el, {
      zoomControl: true,
      attributionControl: true,
    }).setView([49.8, 15.5], 7); // Default: Czechia

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors',
    }).addTo(map);

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

    function focusStop(stopId) {
      const marker = markers.get(stopId);
      if (!marker) return;
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 11), { animate: true });
      marker.openPopup();
    }

    return { map, setExperience, focusStop };
  }

  window.map_ui = { initMap };
})();
