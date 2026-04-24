// Shared UI utilities used by history / generator / experience pages.
// Keep dependency-free so it can be included before any page-specific script.
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

  function truncate(text, max) {
    if (!text) return '';
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
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

  // Czech pluralization for counts (1, 2–4, 5+)
  function pluralCz(n, one, few, many) {
    const abs = Math.abs(n);
    if (abs === 1) return one;
    if (abs >= 2 && abs <= 4) return few;
    return many;
  }

  // Tiny global toast.  Single #toast element on the page; calls overwrite.
  let toastTimer = null;
  function toast(message, { variant = 'default', durationMs = 2200 } = {}) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('toast-success', 'toast-danger');
    if (variant === 'success') el.classList.add('toast-success');
    else if (variant === 'danger') el.classList.add('toast-danger');
    el.classList.add('visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove('visible');
    }, durationMs);
  }

  window.ui = {
    escapeHtml,
    truncate,
    relativeTime,
    statusLabel,
    fallbackLabel,
    pluralCz,
    toast,
  };
})();
