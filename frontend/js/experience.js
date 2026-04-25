(function () {
  const { escapeHtml, statusLabel, fallbackLabel, pluralCz, toast } = window.ui;

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function parseWikimediaFilename(mediaId) {
    if (!mediaId) return null;
    if (!mediaId.startsWith('wikimedia:')) return null;
    let name = mediaId.slice('wikimedia:'.length).trim();
    if (!name) return null;
    if (name.toLowerCase().startsWith('file:')) name = name.slice(5);
    return name;
  }

  function wikimediaThumbUrl(mediaId, width = 400) {
    const fn = parseWikimediaFilename(mediaId);
    if (!fn) return null;
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(fn)}?width=${width}`;
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
    const thumb = wikimediaThumbUrl(stop.media_id);
    if (thumb) {
      mediaHtml = `<img class="stop-media" src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" onerror="this.style.display='none'"/>`;
    } else if (stop.fallback_level === 'NO_MEDIA') {
      mediaHtml = `<div class="stop-media-placeholder" aria-hidden="true">Bez média</div>`;
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
        ${warningHtml}
        <div class="stop-footer">
          <span title="Skóre"><span class="score-star" aria-hidden="true">★</span> ${score}</span>
          ${fallbackBadge}
          ${llmBadge}
        </div>
      </div>
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

    document.title = exp.prompt
      ? `${exp.prompt.slice(0, 60)} — Experience`
      : 'Experience — Detail';

    const badges = [
      `<span class="badge badge-${escapeHtml(exp.job_status)}">${escapeHtml(statusLabel(exp.job_status))}</span>`,
      exp.selected_region ? `<span class="badge badge-region">${escapeHtml(exp.selected_region)}</span>` : '',
    ].filter(Boolean).join('');

    const qualityFlags = (exp.quality_flags || [])
      .map((f) => `<span class="meta-tag">⚑ ${escapeHtml(f)}</span>`)
      .join('');

    header.innerHTML = `
      <h1>${escapeHtml(exp.prompt || '(bez promptu)')}</h1>
      <div class="detail-header-badges">${badges}</div>
      ${exp.summary ? `<div class="detail-summary">${escapeHtml(exp.summary)}</div>` : ''}
      ${qualityFlags ? `<div class="meta-tags">${qualityFlags}</div>` : ''}
    `;

    const qm = exp.quality_metrics || {};
    const meta = exp.generation_metadata || null;

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

    const sortedStops = (exp.stops || []).slice().sort(
      (a, b) => (a.stop_order ?? a.order ?? 0) - (b.stop_order ?? b.order ?? 0),
    );
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
  let ttsEnabled = false;
  let lastExperience = null;
  let lastSortedStops = [];

  const AUTOPLAY_INTERVAL_MS = 12000;

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

  function renderTheaterStopCard(stop, idx, total) {
    const stopNum = idx + 1;
    const title = stop.short_title || stop.name || `Zastávka ${stopNum}`;
    const thumb = wikimediaThumbUrl(stop.media_id, 1200);
    const heroInner = thumb
      ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" onerror="this.parentNode.innerHTML='<div class=\\'theater-hero-fallback\\'>Bez obrázku</div>'+this.parentNode.querySelector('.theater-hero-overlay').outerHTML"/>`
      : `<div class="theater-hero-fallback">Bez obrázku</div>`;

    const ticks = Array.from({ length: total }, (_, i) => {
      let cls = '';
      if (i < idx) cls = 'done';
      else if (i === idx) cls = 'current';
      return `<span class="theater-progress-tick ${cls}"></span>`;
    }).join('');

    const fbLabel = fallbackLabel(stop.fallback_level);
    const llmTagHtml = stop.used_llm_narration
      ? '<span class="meta-tag">🤖 AI narace</span>'
      : '';

    return `
      <article class="theater-stop">
        <div class="theater-progress" aria-hidden="true">${ticks}</div>
        <div class="theater-hero">
          ${heroInner}
          <div class="theater-hero-overlay">
            <div class="theater-hero-step">Zastávka ${stopNum} / ${total}</div>
            <h2 class="theater-hero-title">${escapeHtml(title)}</h2>
            ${stop.name && stop.name !== title ? `<div class="theater-hero-place">${escapeHtml(stop.name)}</div>` : ''}
          </div>
        </div>
        ${stop.why_here ? `<div class="theater-why">${escapeHtml(stop.why_here)}</div>` : ''}
        ${stop.narration ? `<div class="theater-narration">${escapeHtml(stop.narration)}</div>` : ''}
        <div class="theater-meta">
          ${stop.fallback_level ? `<span class="meta-tag" title="${escapeHtml(fbLabel)}"><span class="fallback-dot ${escapeHtml(stop.fallback_level)}" aria-hidden="true"></span> ${escapeHtml(fbLabel)}</span>` : ''}
          ${llmTagHtml}
          ${typeof stop.lat === 'number' ? `<span class="meta-tag">${stop.lat.toFixed(4)}, ${stop.lon.toFixed(4)}</span>` : ''}
        </div>
        <div class="theater-nav-bottom">
          <button type="button" class="btn btn-secondary btn-sm" data-theater-nav="prev"${idx === 0 ? ' disabled' : ''}>← Předchozí</button>
          <button type="button" class="btn btn-sm" data-theater-nav="next"${idx === total - 1 ? ' disabled' : ''}>Další →</button>
        </div>
      </article>
    `;
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

    // Track which stop is "current" so j/k in theater stays in sync.
    currentActiveId = stop.id;

    // FlyTo the current stop on the map (smooth cinematic move).
    if (currentMapInstance && typeof stop.lat === 'number' && typeof stop.lon === 'number') {
      currentMapInstance.focusStop(stop.id, { duration: 1.4, openPopup: false, zoom: 12 });
    }

    // Speak the narration if TTS is enabled.
    if (ttsEnabled) speakStop(stop);
  }

  function enterTheater(startId) {
    if (!lastSortedStops.length) {
      toast('Žádné zastávky k přehrání.', { variant: 'danger' });
      return;
    }
    theaterActive = true;
    document.body.classList.add('theater-active');
    document.getElementById('theater-controls').hidden = false;

    const idx = startId ? orderedStopIds.indexOf(startId) : -1;
    theaterIndex = idx >= 0 ? idx : 0;

    renderTheaterStage();
  }

  function exitTheater() {
    if (!theaterActive) return;
    theaterActive = false;
    stopAutoplay();
    stopTTS();
    document.body.classList.remove('theater-active');
    const controls = document.getElementById('theater-controls');
    if (controls) controls.hidden = true;
    const stage = document.getElementById('theater-stage');
    if (stage) {
      stage.hidden = true;
      stage.innerHTML = '';
    }
    // Keep autoplay button visual state in sync.
    setAutoplayPressed(false);
    setTTSPressed(false);

    // Restore highlight on the same stop in the regular list view.
    if (currentActiveId) {
      activateStop(currentActiveId, { scroll: true, openMarker: false });
    }
  }

  function theaterNext() {
    if (!lastSortedStops.length) return;
    if (theaterIndex >= lastSortedStops.length - 1) {
      // End of presentation — stop autoplay but stay on last slide.
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
    btn.textContent = on ? '⏸ Auto' : '▶ Auto';
  }

  function startAutoplay() {
    stopAutoplay();
    autoplayTimer = setInterval(() => {
      if (theaterIndex >= lastSortedStops.length - 1) {
        stopAutoplay();
        setAutoplayPressed(false);
        return;
      }
      theaterNext();
    }, AUTOPLAY_INTERVAL_MS);
  }

  function stopAutoplay() {
    if (autoplayTimer) {
      clearInterval(autoplayTimer);
      autoplayTimer = null;
    }
  }

  function toggleAutoplay() {
    if (autoplayTimer) {
      stopAutoplay();
      setAutoplayPressed(false);
    } else {
      startAutoplay();
      setAutoplayPressed(true);
    }
  }

  function setTTSPressed(on) {
    const btn = document.getElementById('theater-tts');
    if (!btn) return;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = on ? '🔇 Ticho' : '🔊 Číst';
  }

  function speakStop(stop) {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel(); // cut whatever was playing before
    const parts = [
      stop.short_title || stop.name || '',
      stop.why_here || '',
      stop.narration || '',
    ].filter(Boolean).join('. ');
    if (!parts.trim()) return;
    const utt = new SpeechSynthesisUtterance(parts);
    utt.lang = 'cs-CZ';
    utt.rate = 0.95;
    utt.pitch = 1.0;
    // Pick a Czech voice if one is available.
    const voices = synth.getVoices();
    const cz = voices.find((v) => /^cs/i.test(v.lang));
    if (cz) utt.voice = cz;
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
    setTTSPressed(ttsEnabled);
    if (ttsEnabled && lastSortedStops[theaterIndex]) {
      speakStop(lastSortedStops[theaterIndex]);
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
    if (!copyBtn) return;
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(JSON.stringify(exp, null, 2));
        toast('JSON zkopírován do schránky', { variant: 'success' });
      } catch (err) {
        toast(`Kopírování selhalo: ${err.message}`, { variant: 'danger' });
      }
    };
  }

  async function init() {
    const jobId = getQueryParam('id');
    const stopsList = document.getElementById('stops-list');
    const header = document.getElementById('detail-header');

    if (!jobId) {
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
