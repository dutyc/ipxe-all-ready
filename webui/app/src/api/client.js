const BASE = '/api/cp';

function getToken() {
  return import.meta.env.VITE_CP_TOKEN || localStorage.getItem('cp_token') || '';
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
      if (Array.isArray(err.detail)) {
        // FastAPI 422: detail 是字段校验错误数组
        detail = err.detail
          .map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`)
          .join('; ');
      } else {
        detail = err.detail || err.error || err.message || JSON.stringify(err);
      }
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

export function createAgent(data) {
  return request('/agents', { method: 'POST', body: data });
}

export function probeAgent(data) {
  return request('/agents/probe', { method: 'POST', body: data });
}

// ===== Agent LUNs =====
export function getAgentLuns(agentId) {
  return request(`/agents/${agentId}/luns`);
}

export function createAgentDiskLun(agentId, data) {
  return request(`/agents/${agentId}/luns/disk`, { method: 'POST', body: data });
}

export function createAgentCdLun(agentId, data) {
  return request(`/agents/${agentId}/luns/cd`, { method: 'POST', body: data });
}

export function deleteAgentLun(agentId, iqn, deleteFile = false) {
  return request(`/agents/${agentId}/luns`, {
    method: 'DELETE',
    params: { iqn, delete_file: deleteFile },
  });
}

export function scanAgentLuns(agentId) {
  return request(`/agents/${agentId}/luns/scan`, { method: 'POST' });
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

export function createWorkerDisk(workerId, data) {
  return request(`/workers/${workerId}/luns/disk`, { method: 'POST', body: data });
}

export function batchCreateWorkerDisks(data) {
  // 批量创建：{ type, os, name|size, targets: [{worker_id, agent}] }
  return request('/workers/luns/disk/batch', { method: 'POST', body: data });
}

export function deleteWorkerDisk(workerId, os, deleteFile = false, ignoreMissing = false) {
  return request(`/workers/${workerId}/luns/disk/${encodeURIComponent(os)}`, {
    method: 'DELETE',
    params: {
      delete_file: deleteFile,
      ignore_missing_target: ignoreMissing,
    },
  });
}

export function setWorkerDefaultBoot(workerId, data) {
  // os / menu_default / menu_timeout 可设可清；传 null 清除对应项
  return request(`/workers/${workerId}/default-os`, { method: 'PUT', body: data });
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

export function batchDeleteWorkers(workerIds, deleteDisk = false, ignoreMissing = true) {
  return request('/workers/delete/batch', {
    method: 'POST',
    body: {
      worker_ids: workerIds,
      delete_disk: deleteDisk,
      ignore_missing_target: ignoreMissing,
    },
  });
}

// ===== Operations =====
export function getOperations(since = 0, limit = 50) {
  return request('/operations', { params: { since, limit } });
}
