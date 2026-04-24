(function () {
  const MAX_PROMPT_LENGTH = 60;

  function truncate(text, max) {
    if (!text) return '';
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function relativeTime(isoString) {
    if (!isoString) return '';
    const then = new Date(isoString);
    if (Number.isNaN(then.getTime())) return '';
    const diffSec = Math.max(0, Math.round((Date.now() - then.getTime()) / 1000));
    if (diffSec < 60) return 'před chvílí';
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `před ${diffMin} min`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `před ${diffHr} h`;
    const diffDay = Math.round(diffHr / 24);
    if (diffDay < 7) return `před ${diffDay} d`;
    return then.toLocaleDateString('cs-CZ');
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

  function renderCard(summary) {
    const prompt = escapeHtml(truncate(summary.prompt || '', MAX_PROMPT_LENGTH));
    const status = escapeHtml(summary.job_status || 'pending');
    const stops = Number.isFinite(summary.stop_count) ? summary.stop_count : 0;
    const when = relativeTime(summary.created_at);

    return `
      <div class="history-card" data-id="${escapeHtml(summary.job_id)}" role="button" tabindex="0">
        <div class="prompt-text">${prompt || '<span style="color:var(--text-secondary)">(bez promptu)</span>'}</div>
        <div class="meta-row">
          <span class="badge badge-${status}">${escapeHtml(statusLabel(status))}</span>
          <span>${stops} ${stops === 1 ? 'zastávka' : (stops >= 2 && stops <= 4 ? 'zastávky' : 'zastávek')}</span>
          <span>· ${escapeHtml(when)}</span>
        </div>
      </div>
    `;
  }

  function attachClickHandlers(container) {
    container.querySelectorAll('.history-card').forEach((card) => {
      const id = card.getAttribute('data-id');
      const nav = () => { window.location.href = `experience.html?id=${encodeURIComponent(id)}`; };
      card.addEventListener('click', nav);
      card.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); nav(); }
      });
    });
  }

  async function loadHistory() {
    const container = document.getElementById('history-list');
    if (!container) return;

    try {
      const summaries = await window.api.listExperiences(10);
      if (!summaries || summaries.length === 0) {
        container.innerHTML = '<div class="history-empty">Zatím žádné experiences. Vygeneruj první!</div>';
        return;
      }
      container.innerHTML = summaries.map(renderCard).join('');
      attachClickHandlers(container);
    } catch (err) {
      container.innerHTML = `<div class="error-box">Nepodařilo se načíst historii: ${escapeHtml(err.message)}</div>`;
    }
  }

  window.history_ui = { loadHistory };
})();
