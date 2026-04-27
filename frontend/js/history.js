(function () {
  const { escapeHtml, truncate, relativeTime, statusLabel, pluralCz, toast } = window.ui;

  const MAX_PROMPT_LENGTH = 60;
  const container = () => document.getElementById('history-list');

  // Optimistic cards keyed by job_id — visible immediately after POST,
  // replaced on next server fetch.
  const optimistic = new Map();

  function renderCard(summary, { optimistic: isOptimistic = false } = {}) {
    const rawPrompt = summary.prompt || '';
    const promptHtml = rawPrompt
      ? escapeHtml(truncate(rawPrompt, MAX_PROMPT_LENGTH))
      : '<span class="prompt-empty">(bez promptu)</span>';

    const status = summary.job_status || 'pending';
    const stops = Number.isFinite(summary.stop_count) ? summary.stop_count : 0;
    const stopsWord = pluralCz(stops, 'zastávka', 'zastávky', 'zastávek');
    const when = isOptimistic ? 'právě teď' : relativeTime(summary.created_at);
    const final = status === 'completed' || status === 'completed_with_warnings' || status === 'failed';

    const deleteBtn = final && !isOptimistic
      ? `<button type="button"
                 class="history-delete"
                 data-delete-id="${escapeHtml(summary.job_id)}"
                 aria-label="Smazat experience"
                 title="Smazat">×</button>`
      : '';

    return `
      <div class="history-card ${isOptimistic ? 'is-optimistic' : ''}"
           data-id="${escapeHtml(summary.job_id)}"
           role="button"
           tabindex="0"
           aria-label="Otevřít experience: ${escapeHtml(rawPrompt || 'bez promptu')}">
        ${deleteBtn}
        <div class="prompt-text">${promptHtml}</div>
        <div class="meta-row">
          <span class="badge badge-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>
          <span>${stops} ${stopsWord}</span>
          ${when ? `<span>· ${escapeHtml(when)}</span>` : ''}
        </div>
      </div>
    `;
  }

  function renderEmpty() {
    return `
      <div class="history-empty">
        Zatím žádné experiences.
        <button type="button" class="chip empty-cta" id="empty-cta">Vygeneruj první →</button>
      </div>
    `;
  }

  function attachHandlers(root) {
    root.querySelectorAll('.history-card').forEach((card) => {
      const id = card.getAttribute('data-id');
      const nav = () => { window.location.href = `experience.html?id=${encodeURIComponent(id)}`; };
      card.addEventListener('click', (ev) => {
        if (ev.target.closest('[data-delete-id]')) return;
        nav();
      });
      card.addEventListener('keydown', (ev) => {
        if (ev.target.closest('[data-delete-id]')) return;
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); nav(); }
      });
    });

    root.querySelectorAll('[data-delete-id]').forEach((btn) => {
      btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const id = btn.getAttribute('data-delete-id');
        if (!id) return;
        if (!window.confirm('Smazat tuto experience?')) return;
        btn.disabled = true;
        try {
          await window.api.deleteExperience(id);
          toast('Experience smazána', { variant: 'success' });
          loadHistory();
        } catch (err) {
          btn.disabled = false;
          toast(`Mazání selhalo: ${err.message}`, { variant: 'danger' });
        }
      });
    });

    const cta = root.querySelector('#empty-cta');
    if (cta) {
      cta.addEventListener('click', () => {
        const textarea = document.getElementById('prompt-input');
        if (textarea) {
          textarea.focus();
          textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      });
    }
  }

  function render(summaries) {
    const root = container();
    if (!root) return;

    const serverIds = new Set(summaries.map((s) => s.job_id));
    // Drop optimistic entries that the server already knows about.
    for (const id of Array.from(optimistic.keys())) {
      if (serverIds.has(id)) optimistic.delete(id);
    }

    const combined = [
      ...Array.from(optimistic.values()).map((opt) =>
        renderCard(opt, { optimistic: true })
      ),
      ...summaries.map((s) => renderCard(s)),
    ];

    if (combined.length === 0) {
      root.innerHTML = renderEmpty();
    } else {
      root.innerHTML = combined.join('');
    }
    attachHandlers(root);
  }

  async function loadHistory() {
    const root = container();
    if (!root) return;

    try {
      const summaries = await window.api.listExperiences(10);
      render(summaries || []);
    } catch (err) {
      root.innerHTML = `
        <div class="history-error" role="alert">
          Nepodařilo se načíst historii: ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  // Called by generator right after POST succeeds — shows a pending card
  // immediately so the user sees feedback in the history panel.
  function addOptimistic({ job_id, prompt }) {
    if (!job_id) return;
    optimistic.set(job_id, {
      job_id,
      prompt: prompt || '',
      job_status: 'pending',
      stop_count: 0,
      created_at: new Date().toISOString(),
    });
    // Re-render using the last known list; if we have none cached, just fetch.
    loadHistory();
  }

  window.history_ui = { loadHistory, addOptimistic };
})();
