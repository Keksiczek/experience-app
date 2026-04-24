(function () {
  const { escapeHtml, toast } = window.ui;

  const RUNNING_MESSAGES = [
    'Hledám místa…',
    'Skóruji kandidáty…',
    'Stahuju média…',
    'Generuji naraci…',
    'Skládám trasu…',
  ];

  const MAX_PROMPT_CHARS = 2000;
  const POLL_TIMEOUT_MS = 300000;

  let runningMessageTimer = null;

  function clearRunningMessageCycler() {
    if (runningMessageTimer) {
      clearInterval(runningMessageTimer);
      runningMessageTimer = null;
    }
  }

  function setStatus(html) {
    const box = document.getElementById('generator-status');
    if (!box) return;
    box.classList.remove('hidden');
    box.innerHTML = html;
  }

  function hideStatus() {
    const box = document.getElementById('generator-status');
    if (!box) return;
    box.classList.add('hidden');
    box.innerHTML = '';
  }

  function renderPending() {
    clearRunningMessageCycler();
    setStatus(`
      <div class="row">
        <span class="spinner" aria-hidden="true"></span>
        <span>Připravuji pipeline…</span>
      </div>
    `);
  }

  function renderRunning() {
    let idx = 0;
    const update = () => {
      setStatus(`
        <div class="row">
          <span class="spinner" aria-hidden="true"></span>
          <span id="running-text">${escapeHtml(RUNNING_MESSAGES[idx % RUNNING_MESSAGES.length])}</span>
        </div>
        <div class="progress-bar" aria-hidden="true"><div class="fill"></div></div>
      `);
      idx += 1;
    };
    clearRunningMessageCycler();
    update();
    runningMessageTimer = setInterval(update, 3000);
  }

  function renderCompleted(experience) {
    clearRunningMessageCycler();
    const warn = experience.job_status === 'completed_with_warnings';
    const icon = warn
      ? '<span class="status-icon warning" title="Dokončeno s varováním" aria-hidden="true">!</span>'
      : '<span class="status-icon success" title="Dokončeno" aria-hidden="true">✓</span>';
    const label = warn ? 'Dokončeno s varováním' : 'Experience vygenerována';
    const href = `experience.html?id=${encodeURIComponent(experience.id)}`;
    setStatus(`
      <div class="row">
        ${icon}
        <span>${escapeHtml(label)}</span>
        <a href="${href}">Zobrazit experience →</a>
      </div>
    `);
  }

  function renderFailed(experience, fallbackMessage) {
    clearRunningMessageCycler();
    const msg = (experience && experience.error_message) || fallbackMessage || 'Neznámá chyba';
    setStatus(`
      <div class="error-box" role="alert">
        <span class="status-icon danger" aria-hidden="true">✕</span>
        <div class="error-body"><strong>Chyba generování:</strong> ${escapeHtml(msg)}</div>
      </div>
    `);
  }

  function updateCharCount() {
    const textarea = document.getElementById('prompt-input');
    const counter = document.getElementById('char-count');
    if (!textarea || !counter) return;
    const n = textarea.value.length;
    counter.textContent = `${n} / ${MAX_PROMPT_CHARS}`;
    counter.classList.toggle('warn', n > MAX_PROMPT_CHARS * 0.9);
  }

  async function onGenerate() {
    const btn = document.getElementById('generate-btn');
    const textarea = document.getElementById('prompt-input');
    if (!btn || !textarea) return;

    const prompt = textarea.value.trim();
    if (!prompt) {
      setStatus(`
        <div class="error-box" role="alert">
          <div class="error-body">Zadej prompt — např. „Průmyslové ruiny v okolí Prahy".</div>
        </div>
      `);
      textarea.focus();
      return;
    }

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    textarea.readOnly = true;
    renderPending();

    try {
      const { job_id } = await window.api.createExperience(prompt);

      const finalExp = await window.api.pollUntilDone(
        job_id,
        (exp) => {
          if (exp.job_status === 'running') renderRunning();
          else if (exp.job_status === 'pending') renderPending();
        },
        POLL_TIMEOUT_MS,
      );

      if (finalExp.job_status === 'failed') {
        renderFailed(finalExp);
      } else {
        renderCompleted(finalExp);
      }

      if (window.history_ui && typeof window.history_ui.loadHistory === 'function') {
        window.history_ui.loadHistory();
      }
    } catch (err) {
      renderFailed(null, err.message);
    } finally {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      textarea.readOnly = false;
    }
  }

  function bindExampleChips() {
    document.querySelectorAll('#generator-examples [data-example]').forEach((el) => {
      el.addEventListener('click', () => {
        const textarea = document.getElementById('prompt-input');
        if (!textarea) return;
        textarea.value = el.getAttribute('data-example') || '';
        updateCharCount();
        hideStatus();
        textarea.focus();
      });
    });
  }

  async function checkHealth() {
    const dot = document.getElementById('health-dot');
    const text = document.getElementById('health-text');
    const ollamaInfo = document.getElementById('health-ollama');
    if (!dot || !text) return;

    try {
      const h = await window.api.getHealth();
      dot.className = 'health-dot ok';
      text.textContent = 'Backend OK';
      if (ollamaInfo) {
        if (h.ollama_model && h.providers && h.providers.ollama === 'ok') {
          ollamaInfo.textContent = `🤖 Ollama: ${h.ollama_model}`;
          ollamaInfo.classList.remove('hidden');
        } else {
          ollamaInfo.classList.add('hidden');
        }
      }
    } catch (_) {
      dot.className = 'health-dot down';
      text.textContent = 'Backend nedostupný';
      if (ollamaInfo) ollamaInfo.classList.add('hidden');
    }
  }

  function init() {
    const btn = document.getElementById('generate-btn');
    if (btn) btn.addEventListener('click', onGenerate);

    const textarea = document.getElementById('prompt-input');
    if (textarea) {
      textarea.addEventListener('input', updateCharCount);
      textarea.addEventListener('keydown', (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
          ev.preventDefault();
          onGenerate();
        }
      });
      updateCharCount();
    }

    bindExampleChips();

    if (window.history_ui) window.history_ui.loadHistory();
    checkHealth();
    setInterval(checkHealth, 30000);

    // Re-check health when tab comes back from background (fast feedback after
    // waking the laptop).
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkHealth();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
