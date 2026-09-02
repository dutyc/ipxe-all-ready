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

// ===== Settings =====
export function getRegistrationWindow() {
  // 注册窗口状态: { open, opened_at, ttl_minutes, closes_at, remaining_seconds }（TTL 到期自动关闭，懒计算）
  return request('/settings/registration-window');
}

export function openRegistrationWindow(ttlMinutes) {
  // TTL 1-60 分钟硬上限（代码层不可配永久）；已开启返回 409（先关闭再开）
  return request('/settings/registration-window', { method: 'POST', body: { ttl_minutes: ttlMinutes } });
}

export function closeRegistrationWindow() {
  return request('/settings/registration-window', { method: 'DELETE' });
}

export function getEnforcement() {
  // 设备身份验签强制开关（过渡期兼容：关闭时无密钥设备照现状放行）
  return request('/settings/enforcement');
}

export function setEnforcement(enabled) {
  return request('/settings/enforcement', { method: 'PUT', body: { enabled } });
}

// ===== Agents =====
export function getAgents(live = true) {
  return request('/agents', { params: { live } });
}

export function updateAgent(agentId, data) {
  return request(`/agents/${agentId}`, { method: 'PUT', body: data });
}

export function issueBootstrapToken() {
  // 签发集群级通用 bootstrap token（kubeadm token create 同构）：不绑节点，每次新签
  return request('/pki/tokens', { method: 'POST' });
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

// ===== Masters =====
export function getMasters() {
  // 聚合列出全部启用磁盘角色 Agent 上的母盘: { agents: [{ agent, storager_ip, masters: [{name,size,mtime,os?,os_version?}] }] }
  return request('/masters');
}

export function setMasterTag(agentId, masterName, os, osVersion = '', remark = '') {
  // 登记母盘标签（控制面台账，备注性质）
  return request(`/agents/${agentId}/masters/${encodeURIComponent(masterName)}/tag`, {
    method: 'PUT',
    body: { os, os_version: osVersion, remark },
  });
}

export function clearMasterTag(agentId, masterName) {
  return request(`/agents/${agentId}/masters/${encodeURIComponent(masterName)}/tag`, {
    method: 'DELETE',
  });
}

// ===== Workers =====
export function createWorker(data) {
  return request('/workers', { method: 'POST', body: data });
}

export function batchCreateWorkers(data) {
  // 批量创建：{ count, name_prefix, arch?, macs? } → { succeeded, skipped, failed }
  return request('/workers/batch', { method: 'POST', body: data });
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

export function deleteWorkerDisk(workerId, osTag, deleteFile = false, ignoreMissing = false) {
  return request(`/workers/${workerId}/luns/disk/${encodeURIComponent(osTag)}`, {
    method: 'DELETE',
    params: {
      delete_file: deleteFile,
      ignore_missing_target: ignoreMissing,
    },
  });
}

export function setWorkerDefaultBoot(workerId, data) {
  // disk(os_tag) / menu_default / menu_timeout 可设可清；传 null 清除对应项
  return request(`/workers/${workerId}/default-disk`, { method: 'PUT', body: data });
}

export function updateWorkerMac(workerId, mac) {
  // 修改 MAC 绑定（hostname 不变），审计记录旧/新 MAC
  return request(`/workers/${workerId}/mac`, { method: 'PUT', body: { mac } });
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

// ===== Devices（设备池） =====
export function getDevices(state = 'all') {
  return request('/devices', { params: { state } });
}

export function getDevice(mac) {
  return request(`/devices/${encodeURIComponent(mac)}`);
}

export function createDevice(data) {
  return request('/devices', { method: 'POST', body: data });
}

export function importDevices(entries) {
  return request('/devices/import', { method: 'POST', body: { entries } });
}

export function bindDevice(mac, workerId, force = false) {
  return request(`/devices/${encodeURIComponent(mac)}/bind`, {
    method: 'POST',
    params: { worker_id: workerId, force },
  });
}

export function unbindDevice(mac) {
  return request(`/devices/${encodeURIComponent(mac)}/bind`, { method: 'DELETE' });
}

export function batchBindPreview(data) {
  return request('/devices/bind/batch/preview', { method: 'POST', body: data });
}

export function batchBind(data) {
  return request('/devices/bind/batch', { method: 'POST', body: data });
}

// ===== Operations =====
export function getOperations(since = 0, limit = 50, mac = null) {
  const params = mac ? { since, limit, mac } : { since, limit };
  return request('/operations', { params });
}
