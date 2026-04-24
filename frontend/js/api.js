const BASE_URL = 'http://localhost:8000';

const FINAL_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed']);

async function _request(method, path, body) {
  const url = `${BASE_URL}${path}`;
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new Error(`Nelze se připojit k backendu (${url}): ${networkErr.message}`);
  }

  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail || data.message || JSON.stringify(data);
    } catch (_) {
      try { detail = await response.text(); } catch (_) { detail = ''; }
    }
    throw new Error(`HTTP ${response.status}: ${detail || response.statusText}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

async function createExperience(prompt) {
  if (!prompt || !prompt.trim()) {
    throw new Error('Prompt nesmí být prázdný');
  }
  return _request('POST', '/experiences', { prompt });
}

async function getExperience(jobId) {
  if (!jobId) throw new Error('jobId je povinné');
  return _request('GET', `/experiences/${encodeURIComponent(jobId)}`);
}

async function listExperiences(limit = 10) {
  return _request('GET', `/experiences?limit=${limit}`);
}

async function deleteExperience(jobId) {
  if (!jobId) throw new Error('jobId je povinné');
  return _request('DELETE', `/experiences/${encodeURIComponent(jobId)}`);
}

async function getHealth() {
  return _request('GET', '/health');
}

/**
 * Poll getExperience every 2s until job is in a final status or timeoutMs is reached.
 * Calls onUpdate(experience) on every successful fetch (even before final status).
 */
async function pollUntilDone(jobId, onUpdate, timeoutMs = 300000) {
  const startedAt = Date.now();
  const interval = 2000;

  while (true) {
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error(`Generování nedokončeno v rámci ${Math.round(timeoutMs / 1000)}s (timeout)`);
    }

    let exp;
    try {
      exp = await getExperience(jobId);
    } catch (err) {
      throw new Error(`Chyba při pollování experience: ${err.message}`);
    }

    if (typeof onUpdate === 'function') {
      try { onUpdate(exp); } catch (_) { /* callback errors must not stop polling */ }
    }

    if (FINAL_STATUSES.has(exp.job_status)) {
      return exp;
    }

    await new Promise((r) => setTimeout(r, interval));
  }
}

// Browser globals
window.api = {
  BASE_URL,
  createExperience,
  getExperience,
  listExperiences,
  deleteExperience,
  getHealth,
  pollUntilDone,
};
