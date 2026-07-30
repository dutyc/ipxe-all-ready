const BASE = '/api/cp';

function getToken() {
  return localStorage.getItem('cp_token') || '';
}

export function setToken(token) {
  localStorage.setItem('cp_token', token);
}

export function clearToken() {
  localStorage.removeItem('cp_token');
}

export function hasToken() {
  return !!getToken();
}

async function request(path, options = {}) {
  const { method = 'GET', body, params } = options;

  let url = `${BASE}${path}`;
  if (params) {
    const sp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') sp.append(k, v);
    });
    const qs = sp.toString();
    if (qs) url += `?${qs}`;
  }

  const headers = {};

  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (body) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = '';
    try {
      const err = await res.json();
      detail = err.detail || err.error || err.message || JSON.stringify(err);
    } catch {
      detail = res.statusText;
    }
    const error = new Error(detail || `HTTP ${res.status}`);
    error.status = res.status;
    throw error;
  }

  return res.json();
}

// ===== Health =====
export function healthz() {
  return request('/healthz');
}

// ===== Boot Vars =====
export function bootVars(params) {
  return request('/boot-vars', { params });
}

// ===== Agents =====
export function getAgents(live = true) {
  return request('/agents', { params: { live } });
}

// ===== Workers =====
export function createWorker(data) {
  return request('/workers', { method: 'POST', body: data });
}

export function getWorkers() {
  return request('/workers');
}

export function getWorker(workerId) {
  return request(`/workers/${workerId}`);
}

export function getWorkerStatus(workerId) {
  return request(`/workers/${workerId}/status`);
}

export function deleteWorker(workerId, deleteDisk = false, ignoreMissing = false) {
  return request(`/workers/${workerId}`, {
    method: 'DELETE',
    params: {
      delete_disk: deleteDisk,
      ignore_missing_target: ignoreMissing,
    },
  });
}

// ===== Operations =====
export function getOperations(since = 0, limit = 50) {
  return request('/operations', { params: { since, limit } });
}
