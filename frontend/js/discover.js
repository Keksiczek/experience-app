// Curated samples shown on the home page above the generator.
// Each card links to experience.html?sample=<slug> which renders the
// pre-baked Experience JSON read-only.
(function () {
  const { escapeHtml } = window.ui;

  function renderCard(s) {
    const cover = s.cover_image
      ? `<div class="discover-cover" style="background-image:url('${escapeHtml(s.cover_image)}');"></div>`
      : `<div class="discover-cover discover-cover-fallback"></div>`;
    const region = s.region ? `<span class="discover-region">${escapeHtml(s.region)}</span>` : '';
    const stops = Number.isFinite(s.stop_count) ? s.stop_count : 0;
    return `
      <a class="discover-card"
         href="experience.html?sample=${encodeURIComponent(s.slug)}"
         aria-label="Otevřít: ${escapeHtml(s.title)}">
        ${cover}
        <div class="discover-body">
          <h3 class="discover-title">${escapeHtml(s.title)}</h3>
          ${s.teaser ? `<p class="discover-teaser">${escapeHtml(s.teaser)}</p>` : ''}
          <div class="discover-meta">
            ${region}
            <span class="discover-stops">${stops} ${stops === 1 ? 'zastávka' : (stops >= 2 && stops <= 4 ? 'zastávky' : 'zastávek')}</span>
          </div>
        </div>
      </a>
    `;
  }

  async function loadDiscover() {
    const root = document.getElementById('discover-list');
    if (!root) return;
    try {
      const samples = await window.api.listSamples();
      if (!samples || samples.length === 0) {
        // Hide the whole panel rather than show an empty state — discover
        // is optional decoration, not a feature the user is waiting on.
        const panel = root.closest('.discover');
        if (panel) panel.classList.add('hidden');
        return;
      }
      root.innerHTML = samples.map(renderCard).join('');
    } catch (err) {
      // Fail quiet: hide the panel.  Generator + history still work even
      // when the samples endpoint is missing or returns an error.
      const panel = root.closest('.discover');
      if (panel) panel.classList.add('hidden');
      // eslint-disable-next-line no-console
      console.warn('Discover load failed:', err.message);
    }
  }

  window.discover_ui = { loadDiscover };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadDiscover);
  } else {
    loadDiscover();
  }
})();
