(function () {
  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function statusLabel(s) {
    switch (s) {
      case 'pending': return 'čeká';
      case 'running': return 'běží';
      case 'completed': return 'hotovo';
      case 'completed_with_warnings': return 'hotovo (varování)';
      case 'failed': return 'chyba';
      default: return s || '';
    }
  }

  function fallbackLabel(fl) {
    switch (fl) {
      case 'FULL': return 'Plný kontext';
      case 'PARTIAL_MEDIA': return 'Částečná média';
      case 'NO_MEDIA': return 'Bez média';
      case 'LOW_CONTEXT': return 'Omezený kontext';
      case 'MINIMAL': return 'Minimální data';
      default: return fl || '';
    }
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

  function renderMetricBar(label, value) {
    const v = Math.max(0, Math.min(1, Number(value) || 0));
    const pct = Math.round(v * 100);
    let cls = 'low';
    if (v >= 0.7) cls = 'high';
    else if (v >= 0.4) cls = 'mid';
    return `
      <div class="metric">
        <div class="metric-label">
          <span>${escapeHtml(label)}</span>
          <span>${pct}%</span>
        </div>
        <div class="metric-bar">
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
      mediaHtml = `<div class="stop-media-placeholder">Bez média</div>`;
    }

    const warningHtml = narrationConf < 0.5
      ? `<div class="stop-warning">⚠️ Omezený kontext (confidence ${narrationConf.toFixed(2)})</div>`
      : '';

    const llmBadge = stop.used_llm_narration ? `<span class="llm-badge">AI</span>` : '';

    const fallbackBadge = `
      <span title="${escapeHtml(fallbackLabel(stop.fallback_level))}">
        <span class="fallback-dot ${escapeHtml(stop.fallback_level || 'MINIMAL')}"></span>
        ${escapeHtml(stop.fallback_level || '')}
      </span>
    `;

    return `
      <div class="stop-card" id="stop-${escapeHtml(stop.id)}" data-stop-id="${escapeHtml(stop.id)}" tabindex="0">
        ${mediaHtml}
        <h3>${stopNum}. ${escapeHtml(title)}</h3>
        <div class="stop-name">${escapeHtml(stop.name || '')}</div>
        ${stop.why_here ? `<div class="stop-why"><strong>Proč zde:</strong> ${escapeHtml(stop.why_here)}</div>` : ''}
        ${stop.narration ? `<div class="stop-narration">${escapeHtml(stop.narration)}</div>` : ''}
        ${warningHtml}
        <div class="stop-footer">
          <span class="score-star">★</span> <span>${score}</span>
          ${fallbackBadge}
          ${llmBadge}
        </div>
      </div>
    `;
  }

  function renderSkeletonStops(count = 3) {
    const one = `
      <div class="skeleton">
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
    if (entries.length === 0) return '<div style="color:var(--text-secondary);font-size:12px;">Žádná data.</div>';
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
    const providerDetails = document.getElementById('provider-details-body');
    if (!header || !metrics || !stopsList) return;

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

    metrics.innerHTML = `
      <div class="metrics-box">
        ${renderMetricBar('Kvalita narace', qm.narration_confidence)}
        ${renderMetricBar('Koherence trasy', qm.route_coherence_score)}
        ${renderMetricBar('Pokrytí médii', qm.imagery_coverage_ratio)}
        ${renderMetricBar('Diverzita míst', qm.diversity_score)}
        <div class="meta-tags">
          ${routeStyleTag(meta && meta.route_style_used)}
          ${llmTag(meta)}
        </div>
      </div>
    `;

    const sortedStops = (exp.stops || []).slice().sort(
      (a, b) => (a.stop_order ?? a.order ?? 0) - (b.stop_order ?? b.order ?? 0),
    );

    if (sortedStops.length === 0) {
      stopsList.innerHTML = `<div class="history-empty">Žádné zastávky${exp.error_message ? ` — ${escapeHtml(exp.error_message)}` : ''}.</div>`;
    } else {
      stopsList.innerHTML = sortedStops.map((s, i) => renderStopCard(s, i)).join('');
    }

    if (providerDetails) providerDetails.innerHTML = renderProviderTable(meta);

    // Map
    if (mapInstance) {
      mapInstance.setExperience(exp, {
        onMarkerClick: (stopId) => activateStop(stopId, { scroll: true, openMarker: false }),
      });
    }

    // Bind stop card interactions
    stopsList.querySelectorAll('.stop-card').forEach((card) => {
      const id = card.getAttribute('data-stop-id');
      const activate = () => activateStop(id, { scroll: false, openMarker: true, mapInstance });
      card.addEventListener('click', activate);
      card.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); }
      });
    });

    // Bind "Zobrazit detail" inside map popups (event delegation on map container)
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

  let currentActiveId = null;
  let currentMapInstance = null;

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

  function bindFooter(exp) {
    const copyBtn = document.getElementById('copy-json-btn');
    if (copyBtn) {
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(JSON.stringify(exp, null, 2));
          copyBtn.textContent = '✓ Zkopírováno';
          setTimeout(() => { copyBtn.textContent = '📋 Kopírovat JSON'; }, 2000);
        } catch (err) {
          alert('Nepodařilo se zkopírovat: ' + err.message);
        }
      };
    }
  }

  async function init() {
    const jobId = getQueryParam('id');
    const stopsList = document.getElementById('stops-list');
    const header = document.getElementById('detail-header');

    if (!jobId) {
      if (header) header.innerHTML = '<div class="error-box">Chybí parametr <code>id</code> v URL.</div>';
      return;
    }

    if (stopsList) stopsList.innerHTML = renderSkeletonStops(3);

    currentMapInstance = window.map_ui.initMap('map');

    try {
      const exp = await window.api.getExperience(jobId);
      renderExperience(exp, currentMapInstance);
      bindFooter(exp);

      // If the job is still running, keep polling to auto-refresh.
      if (exp.job_status === 'pending' || exp.job_status === 'running') {
        window.api.pollUntilDone(jobId, (updated) => {
          renderExperience(updated, currentMapInstance);
          bindFooter(updated);
        }).then((final) => {
          renderExperience(final, currentMapInstance);
          bindFooter(final);
        }).catch((err) => {
          console.error('Polling error:', err);
        });
      }
    } catch (err) {
      if (header) header.innerHTML = `<div class="error-box">Nepodařilo se načíst experience: ${escapeHtml(err.message)}</div>`;
      if (stopsList) stopsList.innerHTML = '';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
