(function () {
  const { escapeHtml, truncate, relativeTime, statusLabel, pluralCz } = window.ui;

  const MAX_PROMPT_LENGTH = 60;

  function renderCard(summary) {
    const rawPrompt = summary.prompt || '';
    const promptHtml = rawPrompt
      ? escapeHtml(truncate(rawPrompt, MAX_PROMPT_LENGTH))
      : '<span class="prompt-empty">(bez promptu)</span>';

    const status = escapeHtml(summary.job_status || 'pending');
    const stops = Number.isFinite(summary.stop_count) ? summary.stop_count : 0;
    const stopsWord = pluralCz(stops, 'zastávka', 'zastávky', 'zastávek');
    const when = relativeTime(summary.created_at);

    return `
      <div class="history-card"
           data-id="${escapeHtml(summary.job_id)}"
           role="button"
           tabindex="0"
           aria-label="Otevřít experience: ${escapeHtml(rawPrompt || 'bez promptu')}">
        <div class="prompt-text">${promptHtml}</div>
        <div class="meta-row">
          <span class="badge badge-${status}">${escapeHtml(statusLabel(status))}</span>
          <span>${stops} ${stopsWord}</span>
          ${when ? `<span>· ${escapeHtml(when)}</span>` : ''}
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
      container.innerHTML = `
        <div class="history-error" role="alert">
          Nepodařilo se načíst historii: ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  window.history_ui = { loadHistory };
})();
