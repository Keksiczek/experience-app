(function () {
  const { escapeHtml, statusLabel, fallbackLabel, pluralCz, toast } = window.ui;
  const media = window.media;

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  // ── Trip stats ───────────────────────────────────────────────────────────
  // Naive haversine sum across consecutive stops.  Driving estimate uses a
  // mixed-rural average of 50 km/h — good enough for a header hint, not for
  // navigation.

  const AVG_KMH = 50;

  function haversineKm(a, b) {
    const R = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLon = toRad(b.lon - a.lon);
    const lat1 = toRad(a.lat);
    const lat2 = toRad(b.lat);
    const x = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  function tripStats(sortedStops, routeStyle) {
    const pts = (sortedStops || []).filter(
      (s) => typeof s.lat === 'number' && typeof s.lon === 'number',
    );
    if (pts.length < 2) return null;
    let km = 0;
    for (let i = 1; i < pts.length; i += 1) km += haversineKm(pts[i - 1], pts[i]);
    if (routeStyle === 'loop') km += haversineKm(pts[pts.length - 1], pts[0]);
    const hours = km / AVG_KMH;
    return { km, hours };
  }

  function formatKm(km) {
    if (km < 10) return `${km.toFixed(1)} km`;
    return `${Math.round(km)} km`;
  }

  function formatHours(h) {
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
    if (h < 10) return `${h.toFixed(1)} h`;
    return `${Math.round(h)} h`;
  }

  // ── External links per stop ─────────────────────────────────────────────
  // place_id format from the backend is "osm:<type>:<id>" where type is
  // node/way/relation.  Anything else returns null and the link is skipped.

  function osmEntityLink(placeId) {
    if (!placeId || typeof placeId !== 'string') return null;
    const parts = placeId.split(':');
    if (parts.length !== 3 || parts[0] !== 'osm') return null;
    const [, type, id] = parts;
    if (type !== 'node' && type !== 'way' && type !== 'relation') return null;
    return `https://www.openstreetmap.org/${type}/${encodeURIComponent(id)}`;
  }

  function osmCoordLink(stop) {
    if (typeof stop.lat !== 'number' || typeof stop.lon !== 'number') return null;
    return `https://www.openstreetmap.org/?mlat=${stop.lat}&mlon=${stop.lon}#map=15/${stop.lat}/${stop.lon}`;
  }

  function renderStopLinks(stop) {
    const items = [];
    const osmEntity = osmEntityLink(stop.place_id);
    if (osmEntity) {
      items.push(`<a class="stop-link" href="${escapeHtml(osmEntity)}" target="_blank" rel="noopener noreferrer" title="Otevřít prvek na OpenStreetMap">OSM ↗</a>`);
    }
    const osmCoord = osmCoordLink(stop);
    if (osmCoord && !osmEntity) {
      items.push(`<a class="stop-link" href="${escapeHtml(osmCoord)}" target="_blank" rel="noopener noreferrer" title="Otevřít místo na mapě">Mapa ↗</a>`);
    }
    const mediaExt = media.externalUrl(stop.media_id);
    const mediaSource = media.sourceLabel(stop.media_id);
    if (mediaExt && mediaSource) {
      items.push(`<a class="stop-link" href="${escapeHtml(mediaExt)}" target="_blank" rel="noopener noreferrer" title="Otevřít zdroj média">${escapeHtml(mediaSource)} ↗</a>`);
    }
    (stop.grounding_sources || []).slice(0, 3).forEach((src) => {
      if (typeof src === 'string' && /^https?:\/\//.test(src)) {
        const host = (() => { try { return new URL(src).hostname.replace(/^www\./, ''); } catch (_) { return 'zdroj'; } })();
        items.push(`<a class="stop-link" href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer">${escapeHtml(host)} ↗</a>`);
      }
    });
    if (items.length === 0) return '';
    return `<div class="stop-links">${items.join('')}</div>`;
  }

  function renderTripStats(sortedStops, routeStyle) {
    const stats = tripStats(sortedStops, routeStyle);
    if (!stats) return '';
    return `
      <div class="trip-stats" title="Vzdušná čára mezi zastávkami; jízda odhadnuta při ~${AVG_KMH} km/h">
        <span>🛣️ ~${escapeHtml(formatKm(stats.km))}</span>
        <span>· ⏱️ ~${escapeHtml(formatHours(stats.hours))} jízdy</span>
      </div>
    `;
  }

  const METRIC_HINTS = {
    'Kvalita narace': 'Průměrná spolehlivost narace napříč zastávkami (grounding na zdrojích).',
    'Koherence trasy': 'Jak dobře po sobě zastávky geograficky navazují v daném stylu (linear/loop).',
    'Pokrytí médii': 'Poměr zastávek s použitelným obrázkem (Wikimedia/Mapillary).',
    'Diverzita míst': 'Průměrná vzdálenost mezi zastávkami proti cílovému rozsahu regionu.',
  };

  function renderMetricBar(label, value) {
    const v = Math.max(0, Math.min(1, Number(value) || 0));
    const pct = Math.round(v * 100);
    let cls = 'low';
    if (v >= 0.7) cls = 'high';
    else if (v >= 0.4) cls = 'mid';
    const hint = METRIC_HINTS[label] || '';
    return `
      <div class="metric"${hint ? ` title="${escapeHtml(hint)}"` : ''}>
        <div class="metric-label">
          <span>${escapeHtml(label)}</span>
          <span class="metric-value">${pct}%</span>
        </div>
        <div class="metric-bar" role="progressbar"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"
             aria-label="${escapeHtml(label)}${hint ? `: ${escapeHtml(hint)}` : ''}">
          <div class="metric-fill ${cls}" style="width:${pct}%"></div>
        </div>
      </div>
    `;
  }

  function routeStyleTag(style) {
    if (!style) return '';
    const map = { linear: '➡️ lineární', loop: '🔁 loop', scattered: '✳️ scattered' };
    const label = map[style] || style;
    return `<span class="meta-tag">${escapeHtml(label)}</span>`;
  }

  function llmTag(meta) {
    if (!meta || !meta.llm_narration_used) return '';
    const model = meta.llm_narration_model || '';
    return `<span class="meta-tag">🤖 AI narace${model ? ` (${escapeHtml(model)})` : ''}</span>`;
  }

  function renderStopCard(stop, idx) {
    const stopNum = (stop.stop_order ?? idx) + 1;
    const title = stop.short_title || stop.name || `Zastávka ${stopNum}`;
    const score = Number(stop.score || 0).toFixed(2);
    const narrationConf = Number(stop.narration_confidence || 0);

    let mediaHtml = '';
    const thumb = media.thumbUrl(stop.media_id, 400);
    const ext = media.externalUrl(stop.media_id);
    const sourceLabel = media.sourceLabel(stop.media_id);
    if (thumb) {
      mediaHtml = `<img class="stop-media" src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" data-fallback="img"/>`;
    } else if (media.isExternalOnly(stop.media_id) && ext) {
      mediaHtml = `
        <a class="stop-media-placeholder stop-media-external" href="${escapeHtml(ext)}" target="_blank" rel="noopener noreferrer" aria-label="Otevřít na ${escapeHtml(sourceLabel)}">
          <span>Otevřít na ${escapeHtml(sourceLabel)} ↗</span>
        </a>
      `;
    } else if (stop.fallback_level === 'NO_MEDIA') {
      mediaHtml = `<div class="stop-media-placeholder" aria-hidden="true">Bez média</div>`;
    }

    // Compact gallery row when extras are present.  Limit to 4 visible
    // thumbs (+ "+N" badge when more) so the card stays compact.
    const galleryIds = [];
    if (stop.media_id) galleryIds.push(stop.media_id);
    (stop.extra_media || []).forEach((id) => {
      if (id && !galleryIds.includes(id)) galleryIds.push(id);
    });
    let galleryHtml = '';
    if (galleryIds.length > 1) {
      const visible = galleryIds.slice(0, 4);
      const remaining = galleryIds.length - visible.length;
      const items = visible.map((id, i) => {
        const t = media.thumbUrl(id, 160);
        if (!t) return '';
        return `
          <button type="button"
                  class="stop-thumb"
                  data-stop-thumb-index="${i}"
                  aria-label="Zvětšit obrázek ${i + 1}">
            <img src="${escapeHtml(t)}" alt="" loading="lazy" data-fallback="img"/>
          </button>
        `;
      }).filter(Boolean).join('');
      const more = remaining > 0
        ? `<span class="stop-thumbs-more" aria-hidden="true">+${remaining}</span>`
        : '';
      if (items) {
        galleryHtml = `<div class="stop-thumbs" data-gallery='${escapeHtml(JSON.stringify(galleryIds))}'>${items}${more}</div>`;
      }
    }

    const warningHtml = narrationConf < 0.5
      ? `<div class="stop-warning">⚠️ Omezený kontext (confidence ${narrationConf.toFixed(2)})</div>`
      : '';

    const llmBadge = stop.used_llm_narration ? `<span class="llm-badge" title="Generováno LLM">AI</span>` : '';

    const fbLabel = fallbackLabel(stop.fallback_level);
    const fallbackBadge = stop.fallback_level
      ? `
        <span title="${escapeHtml(fbLabel)}" aria-label="${escapeHtml(fbLabel)}">
          <span class="fallback-dot ${escapeHtml(stop.fallback_level)}" aria-hidden="true"></span>
          ${escapeHtml(stop.fallback_level)}
        </span>
      `
      : '';

    return `
      <div class="stop-card"
           id="stop-${escapeHtml(stop.id)}"
           data-stop-id="${escapeHtml(stop.id)}"
           role="button"
           tabindex="0"
           aria-label="Zastávka ${stopNum}: ${escapeHtml(title)}">
        ${mediaHtml}
        <h3>${stopNum}. ${escapeHtml(title)}</h3>
        ${stop.name ? `<div class="stop-name">${escapeHtml(stop.name)}</div>` : ''}
        ${stop.why_here ? `<div class="stop-why"><strong>Proč zde:</strong> ${escapeHtml(stop.why_here)}</div>` : ''}
        ${stop.narration ? `<div class="stop-narration">${escapeHtml(stop.narration)}</div>` : ''}
        ${galleryHtml}
        ${renderWikipediaBlock(stop, { compact: true })}
        ${warningHtml}
        <div class="stop-footer">
          <span title="Skóre"><span class="score-star" aria-hidden="true">★</span> ${score}</span>
          ${fallbackBadge}
          ${llmBadge}
        </div>
        ${renderStopLinks(stop)}
      </div>
    `;
  }

  function renderWikipediaBlock(stop, opts = {}) {
    if (!stop || !stop.wikipedia_summary) return '';
    const compact = !!opts.compact;
    const lang = stop.wikipedia_lang || '';
    const labelLang = lang ? lang.toUpperCase() : 'wiki';
    const url = stop.wikipedia_url || '';
    const linkHtml = url
      ? `<a class="wiki-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="Otevřít článek na Wikipedii">Wikipedia ↗</a>`
      : '';
    const summary = escapeHtml(stop.wikipedia_summary);
    if (compact) {
      return `
        <details class="wiki-block">
          <summary>
            <span class="wiki-label">📖 Wikipedia · ${escapeHtml(labelLang)}</span>
            <span class="wiki-summary-collapsed">${summary}</span>
          </summary>
          <div class="wiki-summary">${summary}</div>
          ${linkHtml ? `<div class="wiki-actions">${linkHtml}</div>` : ''}
        </details>
      `;
    }
    return `
      <section class="wiki-block wiki-block-full" aria-labelledby="wiki-h-${escapeHtml(stop.id)}">
        <h3 id="wiki-h-${escapeHtml(stop.id)}" class="wiki-heading">📖 Z Wikipedie · ${escapeHtml(labelLang)}</h3>
        <div class="wiki-summary">${summary}</div>
        ${linkHtml ? `<div class="wiki-actions">${linkHtml}</div>` : ''}
      </section>
    `;
  }

  function renderSkeletonStops(count = 3) {
    const one = `
      <div class="skeleton" aria-hidden="true">
        <div class="skeleton-line long"></div>
        <div class="skeleton-line med"></div>
        <div class="skeleton-line short"></div>
      </div>
    `;
    return one.repeat(count);
  }

  function renderProviderTable(metadata) {
    if (!metadata) return '';
    const calls = metadata.provider_calls || {};
    const entries = Object.entries(calls);
    if (entries.length === 0) {
      return '<div class="provider-empty">Žádná data.</div>';
    }
    const rows = entries.map(
      ([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`,
    ).join('');
    return `
      <table class="provider-table">
        <thead><tr><th>Provider</th><th>Volání</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderExperience(exp, mapInstance) {
    const header = document.getElementById('detail-header');
    const metrics = document.getElementById('detail-metrics');
    const stopsList = document.getElementById('stops-list');
    const stopsCount = document.getElementById('stops-count');
    const providerDetails = document.getElementById('provider-details-body');
    if (!header || !metrics || !stopsList) return;

    const isSample = document.body.classList.contains('sample-mode');
    if (isSample && exp.prompt) {
      document.title = `${exp.prompt.slice(0, 60)} — Inspirace`;
    } else if (exp.prompt) {
      document.title = `${exp.prompt.slice(0, 60)} — Experience`;
    } else {
      document.title = 'Experience — Detail';
    }
    updateMetaTags(exp);

    const badges = [
      `<span class="badge badge-${escapeHtml(exp.job_status)}">${escapeHtml(statusLabel(exp.job_status))}</span>`,
      exp.selected_region ? `<span class="badge badge-region">${escapeHtml(exp.selected_region)}</span>` : '',
    ].filter(Boolean).join('');

    const qualityFlags = (exp.quality_flags || [])
      .map((f) => `<span class="meta-tag">⚑ ${escapeHtml(f)}</span>`)
      .join('');

    const qm = exp.quality_metrics || {};
    const meta = exp.generation_metadata || null;
    const sortedStops = (exp.stops || []).slice().sort(
      (a, b) => (a.stop_order ?? a.order ?? 0) - (b.stop_order ?? b.order ?? 0),
    );
    const tripStatsHtml = renderTripStats(sortedStops, meta && meta.route_style_used);

    header.innerHTML = `
      <h1>${escapeHtml(exp.prompt || '(bez promptu)')}</h1>
      <div class="detail-header-badges">${badges}</div>
      ${tripStatsHtml}
      ${exp.summary ? `<div class="detail-summary">${escapeHtml(exp.summary)}</div>` : ''}
      ${qualityFlags ? `<div class="meta-tags">${qualityFlags}</div>` : ''}
    `;

    const metricTags = [routeStyleTag(meta && meta.route_style_used), llmTag(meta)]
      .filter(Boolean)
      .join('');

    metrics.innerHTML = `
      <div class="metrics-box">
        ${renderMetricBar('Kvalita narace', qm.narration_confidence)}
        ${renderMetricBar('Koherence trasy', qm.route_coherence_score)}
        ${renderMetricBar('Pokrytí médii', qm.imagery_coverage_ratio)}
        ${renderMetricBar('Diverzita míst', qm.diversity_score)}
        ${metricTags ? `<div class="meta-tags">${metricTags}</div>` : ''}
      </div>
    `;

    orderedStopIds = sortedStops.map((s) => s.id).filter(Boolean);

    if (stopsCount) {
      const n = sortedStops.length;
      stopsCount.textContent = n
        ? `${n} ${pluralCz(n, 'zastávka', 'zastávky', 'zastávek')}`
        : '';
    }

    if (sortedStops.length === 0) {
      const errMsg = exp.error_message ? ` — ${escapeHtml(exp.error_message)}` : '';
      const running = exp.job_status === 'pending' || exp.job_status === 'running';
      stopsList.innerHTML = running
        ? renderSkeletonStops(3)
        : `<div class="history-empty">Žádné zastávky${errMsg}.</div>`;
    } else {
      stopsList.innerHTML = sortedStops.map((s, i) => renderStopCard(s, i)).join('');
      stopsList.querySelectorAll('img[data-fallback="img"]').forEach((img) => {
        img.addEventListener('error', () => { img.style.display = 'none'; }, { once: true });
      });
      stopsList.querySelectorAll('.stop-thumbs').forEach((row) => {
        let ids = [];
        try { ids = JSON.parse(row.getAttribute('data-gallery') || '[]'); } catch (_) { ids = []; }
        row.querySelectorAll('.stop-thumb').forEach((btn) => {
          const i = parseInt(btn.getAttribute('data-stop-thumb-index'), 10);
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            if (Number.isFinite(i)) openLightbox(ids, i);
          });
        });
      });
    }

    if (providerDetails) providerDetails.innerHTML = renderProviderTable(meta);

    // Show "Spustit experience" once we know the experience has stops.
    const playBtn = document.getElementById('play-btn');
    if (playBtn) {
      if (sortedStops.length > 0) {
        playBtn.classList.remove('hidden');
        playBtn.onclick = () => enterTheater();
      } else {
        playBtn.classList.add('hidden');
        playBtn.onclick = null;
      }
    }

    lastExperience = exp;
    lastSortedStops = sortedStops;

    // If theater is open, re-render its current stop with the latest data
    // (e.g. polling completed mid-presentation).
    if (theaterActive) renderTheaterStage();

    if (mapInstance) {
      try {
        if (typeof mapInstance.suggestBaseLayer === 'function') {
          mapInstance.suggestBaseLayer(meta && meta.intent_mode);
        }
        mapInstance.setExperience(exp, {
          onMarkerClick: (stopId) => activateStop(stopId, { scroll: true, openMarker: false }),
        });
      } catch (err) {
        console.error('Map setExperience failed:', err);
        renderMapFallback(err);
        populateMapFallback(sortedStops);
      }
    } else if (mapFallbackActive) {
      populateMapFallback(sortedStops);
    }

    stopsList.querySelectorAll('.stop-card').forEach((card) => {
      const id = card.getAttribute('data-stop-id');
      const activate = () => activateStop(id, { scroll: false, openMarker: true, mapInstance });
      card.addEventListener('click', activate);
      card.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); }
      });
    });

    const mapEl = document.getElementById('map');
    if (mapEl && !mapEl._delegatedBound) {
      mapEl.addEventListener('click', (ev) => {
        const link = ev.target.closest('[data-stop-link]');
        if (!link) return;
        ev.preventDefault();
        const id = link.getAttribute('data-stop-link');
        activateStop(id, { scroll: true, openMarker: false });
      });
      mapEl._delegatedBound = true;
    }
  }

  let currentMapInstance = null;
  let currentActiveId = null;
  let orderedStopIds = [];
  let mapFallbackActive = false;

  // Theater mode state
  let theaterActive = false;
  let theaterIndex = 0;
  let autoplayTimer = null;
  let autoplayActive = false;
  let ttsEnabled = false;
  let lastExperience = null;
  let lastSortedStops = [];
  let lastFocusedBeforeTheater = null;

  const AUTOPLAY_BASE_MS = 8000;       // floor — even an empty card stays this long
  const AUTOPLAY_PER_WORD_MS = 320;    // ~190 wpm reading speed
  const AUTOPLAY_MAX_MS = 30000;       // ceiling per slide

  const PREFS_KEY = 'experience.theaterPrefs';

  // Selectors of page chrome that must not steal focus while the theater
  // is on screen.  Using `inert` (modern browsers) hides them from the
  // accessibility tree and the Tab order in one shot.
  const THEATER_INERT_SELECTORS = [
    '.app-header',
    '#detail-header',
    '#detail-metrics',
    '.stops-header',
    '#stops-list',
    '.detail-footer',
  ];

  function setChromeInert(on) {
    THEATER_INERT_SELECTORS.forEach((sel) => {
      document.querySelectorAll(sel).forEach((el) => {
        if (on) el.setAttribute('inert', '');
        else el.removeAttribute('inert');
      });
    });
  }

  function loadPrefs() {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return {};
      return JSON.parse(raw) || {};
    } catch (_) { return {}; }
  }

  function savePrefs(patch) {
    try {
      const current = loadPrefs();
      localStorage.setItem(PREFS_KEY, JSON.stringify({ ...current, ...patch }));
    } catch (_) { /* ignore */ }
  }

  // ── Speech synthesis voice cache ────────────────────────────────────────
  // `getVoices()` is async on Chrome — voices may not be available on the
  // first call.  We cache them and refresh on the `voiceschanged` event.

  let cachedVoices = [];
  let cachedCsVoice = null;

  function refreshVoices() {
    if (!window.speechSynthesis) return;
    cachedVoices = window.speechSynthesis.getVoices() || [];
    cachedCsVoice = cachedVoices.find((v) => /^cs/i.test(v.lang)) || null;
  }

  if (window.speechSynthesis) {
    refreshVoices();
    if (typeof window.speechSynthesis.addEventListener === 'function') {
      window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    } else {
      window.speechSynthesis.onvoiceschanged = refreshVoices;
    }
  }

  function renderMapFallback(err) {
    const mapEl = document.getElementById('map');
    if (!mapEl) return;
    mapFallbackActive = true;
    mapEl.classList.add('map-fallback');
    mapEl.innerHTML = `
      <div class="map-fallback-inner">
        <div class="map-fallback-title">Mapa nedostupná</div>
        <div class="map-fallback-hint">
          ${err ? escapeHtml(err.message || String(err)) : 'Zkus obnovit stránku nebo zkontrolovat připojení.'}
        </div>
        <ul id="map-fallback-list" class="map-fallback-list"></ul>
      </div>
    `;
  }

  function populateMapFallback(stops) {
    const list = document.getElementById('map-fallback-list');
    if (!list) return;
    const items = stops
      .filter((s) => typeof s.lat === 'number' && typeof s.lon === 'number')
      .map((s, i) => {
        const title = s.short_title || s.name || `Zastávka ${i + 1}`;
        const num = (s.stop_order ?? i) + 1;
        const osm = `https://www.openstreetmap.org/?mlat=${s.lat}&mlon=${s.lon}#map=13/${s.lat}/${s.lon}`;
        return `
          <li>
            <strong>${num}. ${escapeHtml(title)}</strong>
            <a href="${osm}" target="_blank" rel="noopener noreferrer">otevřít v OSM ↗</a>
          </li>
        `;
      })
      .join('');
    list.innerHTML = items || '<li class="map-fallback-empty">Bez souřadnic.</li>';
  }

  // ── Theater mode ─────────────────────────────────────────────────────────

  function bindGalleryControls(stage, stop) {
    const buttons = stage.querySelectorAll('.theater-thumb');
    if (buttons.length === 0) return;
    let galleryIds = [];
    try {
      const stopEl = stage.querySelector('[data-gallery]');
      if (stopEl) galleryIds = JSON.parse(stopEl.getAttribute('data-gallery') || '[]');
    } catch (_) { galleryIds = []; }

    const heroEl = stage.querySelector('.theater-hero');
    const overlay = stage.querySelector('.theater-hero-overlay');

    function swapHero(newId) {
      if (!newId || !heroEl) return;
      const url = media.thumbUrl(newId, 1200);
      if (!url) return;
      // Re-render the hero body but keep the overlay markup intact.
      const overlayHtml = overlay ? overlay.outerHTML : '';
      heroEl.innerHTML =
        `<img class="theater-hero-img" src="${escapeHtml(url)}" alt="" loading="lazy" data-fallback="hero"/>` +
        overlayHtml;
      const img = heroEl.querySelector('.theater-hero-img');
      if (img) {
        img.addEventListener('error', () => replaceHeroWithFallback(stage), { once: true });
        img.addEventListener('click', () => openLightbox(galleryIds, galleryIds.indexOf(newId)));
      }
    }

    buttons.forEach((btn) => {
      const i = parseInt(btn.getAttribute('data-gallery-index'), 10);
      btn.addEventListener('click', () => {
        if (!Number.isFinite(i)) return;
        buttons.forEach((b) => b.classList.toggle('active', b === btn));
        swapHero(galleryIds[i]);
      });
      const thumbImg = btn.querySelector('img[data-fallback="thumb"]');
      if (thumbImg) {
        thumbImg.addEventListener('error', () => { btn.style.display = 'none'; }, { once: true });
      }
    });

    // Make the visible hero clickable to open the lightbox at slot 0.
    const initialHero = stage.querySelector('.theater-hero-img');
    if (initialHero) {
      initialHero.style.cursor = 'zoom-in';
      initialHero.addEventListener('click', () => openLightbox(galleryIds, 0));
    }
  }

  // ── Lightbox ──────────────────────────────────────────────────────────

  let lightboxIds = [];
  let lightboxIndex = 0;

  function ensureLightboxNode() {
    let el = document.getElementById('lightbox');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'lightbox';
    el.className = 'lightbox';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', 'Zvětšený obrázek');
    el.hidden = true;
    el.innerHTML = `
      <button type="button" class="lightbox-close" aria-label="Zavřít" data-lightbox-action="close">×</button>
      <button type="button" class="lightbox-prev" aria-label="Předchozí" data-lightbox-action="prev">◀</button>
      <img class="lightbox-img" alt="" />
      <button type="button" class="lightbox-next" aria-label="Další" data-lightbox-action="next">▶</button>
      <div class="lightbox-counter" aria-live="polite"></div>
    `;
    document.body.appendChild(el);
    el.addEventListener('click', (ev) => {
      const action = ev.target && ev.target.getAttribute && ev.target.getAttribute('data-lightbox-action');
      if (action === 'close' || ev.target === el) closeLightbox();
      else if (action === 'prev') stepLightbox(-1);
      else if (action === 'next') stepLightbox(+1);
    });
    return el;
  }

  function renderLightboxFrame() {
    const el = document.getElementById('lightbox');
    if (!el || lightboxIds.length === 0) return;
    const id = lightboxIds[lightboxIndex];
    const img = el.querySelector('.lightbox-img');
    const counter = el.querySelector('.lightbox-counter');
    const url = media.thumbUrl(id, 1600);
    if (img) img.src = url || '';
    if (counter) counter.textContent = `${lightboxIndex + 1} / ${lightboxIds.length}`;
    const prev = el.querySelector('.lightbox-prev');
    const next = el.querySelector('.lightbox-next');
    if (prev) prev.style.visibility = lightboxIds.length > 1 ? 'visible' : 'hidden';
    if (next) next.style.visibility = lightboxIds.length > 1 ? 'visible' : 'hidden';
  }

  function openLightbox(ids, startIndex) {
    if (!ids || ids.length === 0) return;
    lightboxIds = ids.slice();
    lightboxIndex = Math.max(0, Math.min(startIndex || 0, lightboxIds.length - 1));
    const el = ensureLightboxNode();
    el.hidden = false;
    document.body.classList.add('lightbox-open');
    renderLightboxFrame();
  }

  function closeLightbox() {
    const el = document.getElementById('lightbox');
    if (!el) return;
    el.hidden = true;
    document.body.classList.remove('lightbox-open');
    lightboxIds = [];
  }

  function stepLightbox(delta) {
    if (lightboxIds.length === 0) return;
    lightboxIndex = (lightboxIndex + delta + lightboxIds.length) % lightboxIds.length;
    renderLightboxFrame();
  }

  function isLightboxOpen() {
    const el = document.getElementById('lightbox');
    return !!(el && !el.hidden);
  }

  function renderTheaterStopCard(stop, idx, total) {
    const stopNum = idx + 1;
    const title = stop.short_title || stop.name || `Zastávka ${stopNum}`;

    // Build the gallery list.  Always start with the primary media_id so
    // it occupies slot 0 (the visible hero).  De-dupe extras that match.
    const galleryIds = [];
    if (stop.media_id) galleryIds.push(stop.media_id);
    (stop.extra_media || []).forEach((id) => {
      if (id && !galleryIds.includes(id)) galleryIds.push(id);
    });

    const heroId = galleryIds[0] || null;
    const thumb = heroId ? media.thumbUrl(heroId, 1200) : null;
    const ext = heroId ? media.externalUrl(heroId) : null;
    const sourceLabel = heroId ? media.sourceLabel(heroId) : null;

    let heroBody = '';
    if (thumb) {
      heroBody = `<img class="theater-hero-img" src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" data-fallback="hero"/>`;
    } else if (ext && sourceLabel) {
      heroBody = `
        <div class="theater-hero-fallback">
          <div class="theater-hero-fallback-text">Streetview / fotografie</div>
          <a class="theater-hero-fallback-link" href="${escapeHtml(ext)}" target="_blank" rel="noopener noreferrer">
            Otevřít na ${escapeHtml(sourceLabel)} ↗
          </a>
        </div>
      `;
    } else {
      heroBody = `<div class="theater-hero-fallback"><div class="theater-hero-fallback-text">Bez obrázku</div></div>`;
    }

    // Render thumbnail strip only when there is more than the hero.
    let thumbStripHtml = '';
    if (galleryIds.length > 1) {
      const thumbs = galleryIds.map((id, i) => {
        const t = media.thumbUrl(id, 200);
        if (!t) return '';
        return `
          <button type="button"
                  class="theater-thumb ${i === 0 ? 'active' : ''}"
                  data-gallery-index="${i}"
                  aria-label="Zobrazit obrázek ${i + 1}">
            <img src="${escapeHtml(t)}" alt="" loading="lazy" data-fallback="thumb"/>
          </button>
        `;
      }).filter(Boolean).join('');
      if (thumbs) {
        thumbStripHtml = `<div class="theater-thumbs">${thumbs}</div>`;
      }
    }

    const ticks = Array.from({ length: total }, (_, i) => {
      let cls = '';
      if (i < idx) cls = 'done';
      else if (i === idx) cls = 'current';
      return `<button type="button"
                      class="theater-progress-tick ${cls}"
                      data-tick-index="${i}"
                      aria-label="Skočit na zastávku ${i + 1}"
                      ${i === idx ? 'aria-current="true"' : ''}></button>`;
    }).join('');

    const fbLabel = fallbackLabel(stop.fallback_level);
    const llmTagHtml = stop.used_llm_narration
      ? '<span class="meta-tag">🤖 AI narace</span>'
      : '';

    return `
      <article class="theater-stop" data-gallery='${escapeHtml(JSON.stringify(galleryIds))}'>
        <div class="theater-progress" role="tablist" aria-label="Zastávky">${ticks}</div>
        <div class="theater-hero">
          ${heroBody}
          <div class="theater-hero-overlay">
            <div class="theater-hero-step">Zastávka ${stopNum} / ${total}</div>
            <h2 class="theater-hero-title">${escapeHtml(title)}</h2>
            ${stop.name && stop.name !== title ? `<div class="theater-hero-place">${escapeHtml(stop.name)}</div>` : ''}
          </div>
        </div>
        ${thumbStripHtml}
        ${stop.why_here ? `<div class="theater-why">${escapeHtml(stop.why_here)}</div>` : ''}
        ${stop.narration ? `<div class="theater-narration">${escapeHtml(stop.narration)}</div>` : ''}
        ${renderWikipediaBlock(stop, { compact: false })}
        <div class="theater-meta">
          ${stop.fallback_level ? `<span class="meta-tag" title="${escapeHtml(fbLabel)}"><span class="fallback-dot ${escapeHtml(stop.fallback_level)}" aria-hidden="true"></span> ${escapeHtml(fbLabel)}</span>` : ''}
          ${llmTagHtml}
          ${typeof stop.lat === 'number' ? `<span class="meta-tag">${stop.lat.toFixed(4)}, ${stop.lon.toFixed(4)}</span>` : ''}
        </div>
        ${renderStopLinks(stop)}
        <div class="theater-nav-bottom">
          <button type="button" class="btn btn-secondary btn-sm" data-theater-nav="prev"${idx === 0 ? ' disabled' : ''}>← Předchozí</button>
          <button type="button" class="btn btn-sm" data-theater-nav="next"${idx === total - 1 ? ' disabled' : ''}>Další →</button>
        </div>
      </article>
    `;
  }

  function replaceHeroWithFallback(stage) {
    const heroEl = stage.querySelector('.theater-hero');
    if (!heroEl) return;
    const img = heroEl.querySelector('.theater-hero-img');
    if (!img) return;
    img.remove();
    const fallback = document.createElement('div');
    fallback.className = 'theater-hero-fallback';
    fallback.innerHTML = '<div class="theater-hero-fallback-text">Obrázek se nepodařilo načíst</div>';
    heroEl.insertBefore(fallback, heroEl.firstChild);
  }

  function renderTheaterStage() {
    const stage = document.getElementById('theater-stage');
    const counter = document.getElementById('theater-counter');
    if (!stage || !lastSortedStops.length) return;

    theaterIndex = Math.max(0, Math.min(theaterIndex, lastSortedStops.length - 1));
    const stop = lastSortedStops[theaterIndex];
    const total = lastSortedStops.length;

    stage.hidden = false;
    stage.innerHTML = renderTheaterStopCard(stop, theaterIndex, total);

    if (counter) counter.textContent = `${theaterIndex + 1} / ${total}`;

    stage.querySelectorAll('[data-theater-nav]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.getAttribute('data-theater-nav') === 'prev') theaterPrev();
        else theaterNext();
      });
    });

    stage.querySelectorAll('[data-tick-index]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const i = parseInt(btn.getAttribute('data-tick-index'), 10);
        if (Number.isFinite(i) && i !== theaterIndex) {
          theaterIndex = i;
          renderTheaterStage();
        }
      });
    });

    const heroImg = stage.querySelector('.theater-hero-img');
    if (heroImg) {
      heroImg.addEventListener('error', () => replaceHeroWithFallback(stage), { once: true });
    }

    bindGalleryControls(stage, stop);

    // Track which stop is "current" so j/k in theater stays in sync.
    currentActiveId = stop.id;

    // FlyTo the current stop on the map (smooth cinematic move).
    if (currentMapInstance && typeof stop.lat === 'number' && typeof stop.lon === 'number') {
      currentMapInstance.focusStop(stop.id, { duration: 1.4, openPopup: false, zoom: 12 });
    }

    // Speak the narration if TTS is enabled.  When autoplay is also on,
    // we hand the "advance" decision to TTS so a long narration finishes
    // before the next slide flies in.  Otherwise fall back to the timer.
    if (ttsEnabled) {
      speakStop(stop, autoplayActive ? () => {
        if (theaterActive && autoplayActive) theaterNext();
      } : null);
    } else if (autoplayActive) {
      scheduleAutoplay(stop);
    }

    stage.scrollTop = 0;
  }

  function enterTheater(startId) {
    if (!lastSortedStops.length) {
      toast('Žádné zastávky k přehrání.', { variant: 'danger' });
      return;
    }
    lastFocusedBeforeTheater = document.activeElement;
    theaterActive = true;
    document.body.classList.add('theater-active');
    document.getElementById('theater-controls').hidden = false;
    setChromeInert(true);

    const idx = startId ? orderedStopIds.indexOf(startId) : -1;
    theaterIndex = idx >= 0 ? idx : 0;

    // Restore the user's last theater preferences (autoplay / TTS).
    const prefs = loadPrefs();
    autoplayActive = !!prefs.autoplay;
    ttsEnabled = !!prefs.tts && 'speechSynthesis' in window;
    setAutoplayPressed(autoplayActive);
    setTTSPressed(ttsEnabled);

    renderTheaterStage();

    // Move focus into the controls so keyboard nav works without a click.
    const nextBtn = document.getElementById('theater-next');
    if (nextBtn && typeof nextBtn.focus === 'function') {
      nextBtn.focus({ preventScroll: true });
    }
  }

  function exitTheater() {
    if (!theaterActive) return;
    theaterActive = false;
    stopAutoplay();
    stopTTS();
    setChromeInert(false);
    document.body.classList.remove('theater-active');
    const controls = document.getElementById('theater-controls');
    if (controls) controls.hidden = true;
    const stage = document.getElementById('theater-stage');
    if (stage) {
      stage.hidden = true;
      stage.innerHTML = '';
    }
    // Keep visual state in sync but don't clear persisted prefs.
    setAutoplayPressed(autoplayActive);
    setTTSPressed(ttsEnabled);

    // Restore highlight on the same stop in the regular list view.
    if (currentActiveId) {
      activateStop(currentActiveId, { scroll: true, openMarker: false });
    }

    // Return focus to the trigger that opened theater (or the play button).
    const target = lastFocusedBeforeTheater && document.body.contains(lastFocusedBeforeTheater)
      ? lastFocusedBeforeTheater
      : document.getElementById('play-btn');
    if (target && typeof target.focus === 'function') {
      target.focus({ preventScroll: true });
    }
    lastFocusedBeforeTheater = null;
  }

  function theaterNext() {
    if (!lastSortedStops.length) return;
    if (theaterIndex >= lastSortedStops.length - 1) {
      // End of presentation — stop autoplay but stay on last slide.
      autoplayActive = false;
      stopAutoplay();
      setAutoplayPressed(false);
      return;
    }
    theaterIndex += 1;
    renderTheaterStage();
  }

  function theaterPrev() {
    if (!lastSortedStops.length) return;
    if (theaterIndex <= 0) return;
    theaterIndex -= 1;
    renderTheaterStage();
  }

  function setAutoplayPressed(on) {
    const btn = document.getElementById('theater-autoplay');
    if (!btn) return;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = on ? '⏸ Pauza' : '▶ Auto';
  }

  // Pick how long the current slide should stay on screen based on how much
  // text the user has to read (or have read aloud).
  function autoplayDelayFor(stop) {
    const text = `${stop.why_here || ''} ${stop.narration || ''}`.trim();
    const words = text ? text.split(/\s+/).length : 0;
    const ms = AUTOPLAY_BASE_MS + words * AUTOPLAY_PER_WORD_MS;
    return Math.min(AUTOPLAY_MAX_MS, ms);
  }

  function scheduleAutoplay(stop) {
    stopAutoplay(); // single timer at all times
    if (!autoplayActive) return;
    if (theaterIndex >= lastSortedStops.length - 1) return;
    autoplayTimer = setTimeout(() => theaterNext(), autoplayDelayFor(stop));
  }

  function stopAutoplay() {
    if (autoplayTimer) {
      clearTimeout(autoplayTimer);
      autoplayTimer = null;
    }
  }

  function toggleAutoplay() {
    autoplayActive = !autoplayActive;
    savePrefs({ autoplay: autoplayActive });
    setAutoplayPressed(autoplayActive);
    if (autoplayActive) {
      const stop = lastSortedStops[theaterIndex];
      if (stop) scheduleAutoplay(stop);
    } else {
      stopAutoplay();
    }
  }

  function setTTSPressed(on) {
    const btn = document.getElementById('theater-tts');
    if (!btn) return;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = on ? '🔇 Ticho' : '🔊 Číst';
  }

  // Monotonically increases — every call to speakStop() bumps it so an old
  // utterance's onEnd handler can detect that it's stale and bail out.
  let speechToken = 0;

  function speakStop(stop, onEnd) {
    const synth = window.speechSynthesis;
    if (!synth) {
      if (typeof onEnd === 'function') onEnd();
      return;
    }
    speechToken += 1;
    const myToken = speechToken;
    synth.cancel(); // cut whatever was playing before
    const parts = [
      stop.short_title || stop.name || '',
      stop.why_here || '',
      stop.narration || '',
    ].filter(Boolean).join('. ');
    if (!parts.trim()) {
      if (typeof onEnd === 'function') onEnd();
      return;
    }
    const utt = new SpeechSynthesisUtterance(parts);
    utt.lang = 'cs-CZ';
    utt.rate = 0.95;
    utt.pitch = 1.0;
    if (cachedVoices.length === 0) refreshVoices();
    if (cachedCsVoice) utt.voice = cachedCsVoice;
    if (typeof onEnd === 'function') {
      const guarded = () => {
        // Ignore the event if a newer slide already started speaking.
        if (myToken !== speechToken) return;
        onEnd();
      };
      utt.addEventListener('end', guarded);
      utt.addEventListener('error', guarded);
    }
    synth.speak(utt);
  }

  function stopTTS() {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function toggleTTS() {
    if (!('speechSynthesis' in window)) {
      toast('Čtení nahlas není v tomto prohlížeči podporováno.', { variant: 'danger' });
      return;
    }
    ttsEnabled = !ttsEnabled;
    savePrefs({ tts: ttsEnabled });
    setTTSPressed(ttsEnabled);
    if (ttsEnabled && lastSortedStops[theaterIndex]) {
      speakStop(lastSortedStops[theaterIndex]);
      if (cachedVoices.length > 0 && !cachedCsVoice) {
        toast('Český hlas není k dispozici, použije se výchozí.', {});
      }
    } else {
      stopTTS();
    }
  }

  function bindTheaterControls() {
    const exitBtn = document.getElementById('theater-exit');
    const prevBtn = document.getElementById('theater-prev');
    const nextBtn = document.getElementById('theater-next');
    const auto = document.getElementById('theater-autoplay');
    const tts = document.getElementById('theater-tts');
    if (exitBtn) exitBtn.addEventListener('click', exitTheater);
    if (prevBtn) prevBtn.addEventListener('click', theaterPrev);
    if (nextBtn) nextBtn.addEventListener('click', theaterNext);
    if (auto) auto.addEventListener('click', toggleAutoplay);
    if (tts) tts.addEventListener('click', toggleTTS);
  }

  function activateStop(stopId, opts = {}) {
    if (!stopId) return;
    document.querySelectorAll('.stop-card.active').forEach((el) => el.classList.remove('active'));
    const card = document.getElementById(`stop-${CSS.escape(stopId)}`);
    if (card) {
      card.classList.add('active');
      if (opts.scroll) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    currentActiveId = stopId;
    if (opts.openMarker && (opts.mapInstance || currentMapInstance)) {
      (opts.mapInstance || currentMapInstance).focusStop(stopId);
    }
  }

  function stepStop(delta) {
    if (orderedStopIds.length === 0) return;
    const idx = currentActiveId ? orderedStopIds.indexOf(currentActiveId) : -1;
    let next;
    if (idx === -1) next = delta > 0 ? 0 : orderedStopIds.length - 1;
    else next = (idx + delta + orderedStopIds.length) % orderedStopIds.length;
    activateStop(orderedStopIds[next], { scroll: true, openMarker: true });
  }

  function isTextInputFocused() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function bindHotkeys() {
    if (document._stopHotkeysBound) return;
    document._stopHotkeysBound = true;
    document.addEventListener('keydown', (ev) => {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (isTextInputFocused()) return;

      if (isLightboxOpen()) {
        switch (ev.key) {
          case 'Escape':
            ev.preventDefault();
            closeLightbox();
            return;
          case 'ArrowLeft':
            ev.preventDefault();
            stepLightbox(-1);
            return;
          case 'ArrowRight':
            ev.preventDefault();
            stepLightbox(+1);
            return;
          default:
            return;
        }
      }

      if (theaterActive) {
        switch (ev.key) {
          case 'ArrowRight':
          case 'j':
          case 'ArrowDown':
            ev.preventDefault();
            theaterNext();
            return;
          case 'ArrowLeft':
          case 'k':
          case 'ArrowUp':
            ev.preventDefault();
            theaterPrev();
            return;
          case ' ':
            ev.preventDefault();
            toggleAutoplay();
            return;
          case 't':
          case 'T':
            ev.preventDefault();
            toggleTTS();
            return;
          case 'Escape':
            ev.preventDefault();
            exitTheater();
            return;
          default:
            return;
        }
      }

      switch (ev.key) {
        case 'j':
        case 'ArrowDown':
          ev.preventDefault();
          stepStop(+1);
          break;
        case 'k':
        case 'ArrowUp':
          ev.preventDefault();
          stepStop(-1);
          break;
        case 'Escape':
          if (currentMapInstance && currentMapInstance.map) {
            currentMapInstance.map.closePopup();
          }
          document.querySelectorAll('.stop-card.active').forEach((el) => el.classList.remove('active'));
          currentActiveId = null;
          break;
        default:
          break;
      }
    });
  }

  function bindFooter(exp) {
    const copyBtn = document.getElementById('copy-json-btn');
    if (copyBtn) {
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(JSON.stringify(exp, null, 2));
          toast('JSON zkopírován do schránky', { variant: 'success' });
        } catch (err) {
          toast(`Kopírování selhalo: ${err.message}`, { variant: 'danger' });
        }
      };
    }

    const gpxBtn = document.getElementById('gpx-btn');
    if (gpxBtn) {
      const sampleSlug = getQueryParam('sample');
      const hasGeo = (exp.stops || []).some(
        (s) => typeof s.lat === 'number' && typeof s.lon === 'number',
      );
      let href = null;
      let filename = null;
      if (hasGeo && sampleSlug) {
        href = `${window.api.BASE_URL}/samples/${encodeURIComponent(sampleSlug)}/gpx`;
        filename = `sample-${sampleSlug}.gpx`;
      } else if (hasGeo && exp.id) {
        href = `${window.api.BASE_URL}/experiences/${encodeURIComponent(exp.id)}/gpx`;
        filename = `experience-${exp.id.slice(0, 8)}.gpx`;
      }
      if (href) {
        gpxBtn.href = href;
        gpxBtn.setAttribute('download', filename);
        gpxBtn.classList.remove('hidden');
      } else {
        gpxBtn.classList.add('hidden');
        gpxBtn.removeAttribute('href');
      }
    }
  }

  function setMetaContent(id, value) {
    const el = document.getElementById(id);
    if (el && value != null) el.setAttribute('content', value);
  }

  function updateMetaTags(exp) {
    const title = exp.prompt ? `${exp.prompt.slice(0, 80)} — Experience` : 'Experience — Detail';
    const stopsCount = (exp.stops || []).length;
    const stopsWord = pluralCz(stopsCount, 'zastávka', 'zastávky', 'zastávek');
    const region = exp.selected_region ? ` v regionu ${exp.selected_region}` : '';
    const desc = exp.summary
      ? exp.summary
      : `Trasa o ${stopsCount} ${stopsWord}${region} — kurátorovaný geo-prolog.`;
    setMetaContent('meta-description', desc);
    setMetaContent('meta-og-title', title);
    setMetaContent('meta-og-description', desc);
    setMetaContent('meta-twitter-title', title);
    setMetaContent('meta-twitter-description', desc);

    // Pick the first stop's primary or extra image as the share preview.
    const heroId = (() => {
      for (const s of (exp.stops || [])) {
        if (s.media_id) return s.media_id;
        if (s.extra_media && s.extra_media.length > 0) return s.extra_media[0];
      }
      return null;
    })();
    const heroUrl = heroId ? media.thumbUrl(heroId, 1200) : null;
    if (heroUrl) {
      setMetaContent('meta-og-image', heroUrl);
      setMetaContent('meta-twitter-image', heroUrl);
    }
  }

  function applySampleMode() {
    // Curated samples are read-only — hide the chrome that only makes
    // sense for live jobs (delete/copy/provider debug, GPX still works).
    document.body.classList.add('sample-mode');
    const copyBtn = document.getElementById('copy-json-btn');
    if (copyBtn) copyBtn.classList.add('hidden');
    const providerWrap = document.querySelector('.detail-footer details');
    if (providerWrap) providerWrap.style.display = 'none';
  }

  async function init() {
    const jobId = getQueryParam('id');
    const sampleSlug = getQueryParam('sample');
    const stopsList = document.getElementById('stops-list');
    const header = document.getElementById('detail-header');

    if (!jobId && !sampleSlug) {
      if (header) {
        header.innerHTML = `
          <div class="error-box" role="alert">
            <div class="error-body">
              Chybí parametr <code>id</code> v URL.
              <div class="error-action"><a href="index.html">← Zpět na hlavní stránku</a></div>
            </div>
          </div>
        `;
      }
      return;
    }

    if (stopsList) stopsList.innerHTML = renderSkeletonStops(3);

    bindHotkeys();
    bindTheaterControls();

    try {
      currentMapInstance = window.map_ui.initMap('map');
    } catch (err) {
      console.error('Map init failed:', err);
      renderMapFallback(err);
    }

    if (sampleSlug) {
      try {
        applySampleMode();
        const exp = await window.api.getSample(sampleSlug);
        renderExperience(exp, currentMapInstance);
        bindFooter(exp);
      } catch (err) {
        if (header) {
          header.innerHTML = `
            <div class="error-box" role="alert">
              <div class="error-body">
                Nepodařilo se načíst sample: ${escapeHtml(err.message)}
                <div class="error-action"><a href="index.html">← Zpět na hlavní stránku</a></div>
              </div>
            </div>
          `;
        }
        if (stopsList) stopsList.innerHTML = '';
      }
      return;
    }

    try {
      const exp = await window.api.getExperience(jobId);
      renderExperience(exp, currentMapInstance);
      bindFooter(exp);

      if (exp.job_status === 'pending' || exp.job_status === 'running') {
        window.api.pollUntilDone(jobId, (updated) => {
          renderExperience(updated, currentMapInstance);
          bindFooter(updated);
        }).then((final) => {
          renderExperience(final, currentMapInstance);
          bindFooter(final);
        }).catch((err) => {
          console.error('Polling error:', err);
          toast(`Chyba při obnově: ${err.message}`, { variant: 'danger' });
        });
      }
    } catch (err) {
      if (header) {
        header.innerHTML = `
          <div class="error-box" role="alert">
            <div class="error-body">
              Nepodařilo se načíst experience: ${escapeHtml(err.message)}
              <div class="error-action"><a href="index.html">← Zpět na hlavní stránku</a></div>
            </div>
          </div>
        `;
      }
      if (stopsList) stopsList.innerHTML = '';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
