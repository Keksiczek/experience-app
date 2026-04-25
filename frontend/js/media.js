// Media adapter — translates a stop's `media_id` (e.g. "wikimedia:Foo.jpg",
// "mapillary:1234567890123456") into URLs we can render or link to.
//
// Inline rendering is only available for sources that support an unauthenticated
// thumbnail endpoint (currently: Wikimedia Commons).  For others we still
// expose an `externalUrl` so the caller can render a click-out.
(function () {
  function parseMediaId(id) {
    if (!id || typeof id !== 'string') return { type: 'none', raw: id || '' };
    const colon = id.indexOf(':');
    if (colon === -1) return { type: 'unknown', raw: id };
    const scheme = id.slice(0, colon).toLowerCase();
    const value = id.slice(colon + 1).trim();

    if (scheme === 'wikimedia') {
      let name = value;
      if (name.toLowerCase().startsWith('file:')) name = name.slice(5);
      if (!name) return { type: 'wikimedia', raw: id, name: '' };
      return { type: 'wikimedia', raw: id, name };
    }
    if (scheme === 'mapillary') {
      return { type: 'mapillary', raw: id, key: value };
    }
    return { type: 'unknown', raw: id, value };
  }

  // Returns a URL for an inline thumbnail at roughly `width` pixels, or null
  // if the source has no public thumbnail endpoint.
  function thumbUrl(id, width = 400) {
    const m = parseMediaId(id);
    if (m.type === 'wikimedia' && m.name) {
      return `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(m.name)}?width=${width}`;
    }
    return null;
  }

  // URL to open the original media in its source viewer.
  function externalUrl(id) {
    const m = parseMediaId(id);
    if (m.type === 'wikimedia' && m.name) {
      return `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(m.name)}`;
    }
    if (m.type === 'mapillary' && m.key) {
      return `https://www.mapillary.com/app/?focus=photo&pKey=${encodeURIComponent(m.key)}`;
    }
    return null;
  }

  function sourceLabel(id) {
    const m = parseMediaId(id);
    if (m.type === 'wikimedia') return 'Wikimedia Commons';
    if (m.type === 'mapillary') return 'Mapillary';
    return null;
  }

  // True when we can't render inline but a click-out exists (Mapillary).
  function isExternalOnly(id) {
    const m = parseMediaId(id);
    if (m.type === 'mapillary' && m.key) return true;
    return false;
  }

  window.media = {
    parseMediaId,
    thumbUrl,
    externalUrl,
    sourceLabel,
    isExternalOnly,
  };
})();
