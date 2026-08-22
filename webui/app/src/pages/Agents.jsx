import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { createAgent, getAgents, probeAgent, updateAgent } from '../api/client'
import { useI18n } from '../i18n'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import Input from '../components/Input'
import './Agents.css'

function AgentCard({ agent, t, onEdit }) {
  const capLabel = (key) => {
    const val = agent.capabilities?.[key]
    if (!val) return t('agents.unknown')
    const labels = t('agents.capLabels')
    // 前缀匹配：动态文案（如 full copy only (reflink unsupported on ext4)）归并到静态条目
    const hit = Object.keys(labels).find((k) => val.startsWith(k))
    return hit ? labels[hit] : val
  }
  return (
    <Card className="agent-card">
      <div className="agent-card-header">
        <span className="agent-name">{agent.id}</span>
        <div className="agent-card-actions">
          {!agent.enabled && <Badge>{t('agents.disabled')}</Badge>}
          {agent.health && <Badge>{agent.health}</Badge>}
          <Button
            variant="ghost"
            className="agent-edit-btn"
            title={t('agents.edit')}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onEdit(agent)
            }}
          >
            {t('agents.edit')}
          </Button>
        </div>
      </div>
      <div className="agent-props">
        <div className="agent-prop">
          <span className="ap-label">{t('agents.backend')}</span>
          <span className="ap-value">{agent.capabilities?.backend || t('agents.unknown')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.fsType')}</span>
          <span className="ap-value ap-mono">{agent.capabilities?.fs_type || t('agents.unknown')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.baseUrl')}</span>
          <span className="ap-value ap-mono">{agent.base_url || t('agents.unknown')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.baseNqn')}</span>
          <span className="ap-value ap-mono">
            {agent.capabilities?.base_nqn
              ? `${agent.capabilities.base_nqn}${agent.iscsi_server ? ` (${agent.iscsi_server})` : ''}`
              : (agent.iscsi_server || t('agents.unknown'))}
          </span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.cdSupport')}</span>
          <span className="ap-value">{agent.capabilities?.cd ? t('agents.yes') : t('agents.no')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.diskRole')}</span>
          <span className="ap-value">{agent.role?.disk ? t('agents.yes') : t('agents.no')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.clone')}</span>
          <span className="ap-value">{capLabel('clone')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.emptyDisk')}</span>
          <span className="ap-value">{capLabel('empty_disk')}</span>
        </div>
        {agent.tags && agent.tags.length > 0 && (
          <div className="agent-prop">
            <span className="ap-label">{t('agents.tags')}</span>
            <span className="ap-value">
              {agent.tags.map((tag) => (
                <span key={tag} className="agent-tag">{tag}</span>
              ))}
            </span>
          </div>
        )}
      </div>
    </Card>
  )
}

// 添加 / 编辑共用的两步表单：探测 → 确认 / 修改参数 → 提交
// edit 模式：id 只读（走路径参数），token 留空 = 保持不变（探测沿用注册表 token），可切换 enabled
function AgentForm({ mode, agentId, initial, onClose, onSaved }) {
  const { t } = useI18n()
  const isEdit = mode === 'edit'
  const [form, setForm] = useState(() => ({
    id: initial?.id || '',
    base_url: initial?.base_url || '',
    token: '',
    iscsi_server: initial?.iscsi_server || '',
    role_disk: initial?.role?.disk ?? true,
    role_cd: initial?.role?.cd ?? false,
    tags: (initial?.tags || []).join(', '),
    enabled: initial?.enabled ?? true,
  }))
  const [probe, setProbe] = useState(null)
  // iscsi_server 折叠框：默认折叠（编辑模式已有值时展开），探测成功后自动展开供确认/修改
  const [iscsiOpen, setIscsiOpen] = useState(() => Boolean(initial?.iscsi_server))
  const [probing, setProbing] = useState(false)
  const [probeError, setProbeError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  const setField = (name) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((prev) => ({ ...prev, [name]: value }))
    if (name === 'base_url') setProbe(null) // 地址变更后旧探测结果失效
  }

  const handleProbe = async (e) => {
    e.preventDefault()
    setProbing(true)
    setProbeError(null)
    setSaveError(null)
    try {
      const result = await probeAgent({
        base_url: form.base_url.trim(),
        token: form.token.trim(),
        ...(isEdit ? { agent_id: agentId } : {}),
      })
      setProbe(result)
      setIscsiOpen(true) // 探测推导了数据面地址（base_url 主机名），展开以便确认或改为 Worker 可达的局域网 IP
      setForm((prev) => ({
        ...prev,
        role_disk: result.role.disk,
        role_cd: result.role.cd,
        // 探测前已手填的数据面地址优先保留，未被探测推导值覆盖
        iscsi_server: prev.iscsi_server || result.iscsi_server,
        tags: result.tags.join(', '),
      }))
    } catch (err) {
      setProbeError(err.message)
      setProbe(null)
    } finally {
      setProbing(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!probe) return // 须先探测成功才允许注册 / 保存
    setSaving(true)
    setSaveError(null)
    const body = {
      base_url: form.base_url.trim(),
      token: form.token.trim(),
      role: { disk: form.role_disk, cd: form.role_cd },
      enabled: isEdit ? form.enabled : true,
    }
    if (form.iscsi_server.trim()) body.iscsi_server = form.iscsi_server.trim()
    const tags = form.tags.split(',').map((s) => s.trim()).filter(Boolean)
    if (tags.length) body.tags = tags
    try {
      if (isEdit) {
        await updateAgent(agentId, body)
      } else {
        await createAgent({ id: form.id.trim(), ...body })
      }
      onSaved()
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="create-form" onSubmit={handleSubmit}>
      <div className="create-form-title">{isEdit ? t('agents.editTitle') : t('agents.addTitle')}</div>
      <p className="create-hint">{t('agents.probeHint')}</p>
      <div className="create-form-grid">
        {isEdit ? (
          <Input label={t('agents.idLabel')} value={agentId} disabled />
        ) : (
          <Input
            label={t('agents.idLabel')}
            name="id"
            value={form.id}
            onChange={setField('id')}
            placeholder={t('agents.idPlaceholder')}
            required
          />
        )}
        <Input
          label={t('agents.baseUrl')}
          name="base_url"
          value={form.base_url}
          onChange={setField('base_url')}
          placeholder={t('agents.baseUrlPlaceholder')}
          required
        />
        <Input
          label={t('agents.tokenLabel')}
          name="token"
          value={form.token}
          onChange={setField('token')}
          placeholder={isEdit ? t('agents.tokenKeepPlaceholder') : t('agents.tokenPlaceholder')}
        />
      </div>
      <div className="iscsi-collapse">
        <button
          type="button"
          className={`iscsi-collapse-toggle${iscsiOpen ? ' open' : ''}`}
          onClick={() => setIscsiOpen((v) => !v)}
          aria-expanded={iscsiOpen}
        >
          <span className="iscsi-collapse-arrow">▶</span>
          {t('agents.iscsiCollapseLabel')}
        </button>
        {iscsiOpen && (
          <div className="iscsi-collapse-body">
            <Input
              label={t('agents.iscsiServer')}
              name="iscsi_server"
              value={form.iscsi_server}
              onChange={setField('iscsi_server')}
              placeholder={t('agents.iscsiServerPlaceholder')}
            />
          </div>
        )}
      </div>
      {probeError && <p className="create-error">{probeError}</p>}
      <div className="create-actions">
        <Button
          type="button"
          variant="primary"
          onClick={handleProbe}
          disabled={probing || !form.base_url.trim()}
        >
          {probing ? t('agents.probing') : t('agents.probe')}
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          {t('agents.cancel')}
        </Button>
      </div>

      {probe && (
        <div className="probe-result">
          <div className="probe-result-title">{t('agents.probeResult')}</div>
          <div className="probe-meta">
            {probe.backend && (
              <span className="agent-tag">{t('agents.probeBackend')}: {probe.backend}</span>
            )}
            {probe.fs_type && (
              <span className="agent-tag">{t('agents.fsType')}: {probe.fs_type}</span>
            )}
            {probe.base_nqn && (
              <span className="agent-tag">{t('agents.probeBaseNqn')}: {probe.base_nqn}</span>
            )}
            {probe.clone && <span className="agent-tag">{probe.clone}</span>}
            {probe.empty_disk && <span className="agent-tag">{probe.empty_disk}</span>}
            {probe.persistent && <span className="agent-tag">{probe.persistent}</span>}
          </div>
          <p className="create-hint">{t('agents.probeMeta')}</p>
          <div className="create-form-grid">
            <Input
              label={t('agents.tagsInput')}
              name="tags"
              value={form.tags}
              onChange={setField('tags')}
              placeholder={t('agents.tagsPlaceholder')}
            />
          </div>
          <div className="agent-role-checks">
            <label className="agent-role-check">
              <input
                type="checkbox"
                checked={form.role_disk}
                onChange={setField('role_disk')}
              />
              {t('agents.roleDisk')}
            </label>
            <label className="agent-role-check">
              <input
                type="checkbox"
                checked={form.role_cd}
                onChange={setField('role_cd')}
              />
              {t('agents.roleCd')}
            </label>
            {isEdit && (
              <label className="agent-role-check">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={setField('enabled')}
                />
                {t('agents.enabled')}
              </label>
            )}
          </div>
          {saveError && <p className="create-error">{saveError}</p>}
          <div className="create-actions">
            <Button type="submit" disabled={saving}>
              {saving
                ? (isEdit ? t('agents.saving') : t('agents.adding'))
                : (isEdit ? t('agents.saveBtn') : t('agents.addBtn'))}
            </Button>
            <Button variant="ghost" type="button" onClick={onClose}>
              {t('agents.cancel')}
            </Button>
          </div>
        </div>
      )}
    </form>
  )
}

export default function Agents() {
  const { t } = useI18n()
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState(true)
  const [error, setError] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [editAgent, setEditAgent] = useState(null)

  // ===== 页面介绍弹层 =====
  const [guideOpen, setGuideOpen] = useState(false)
  const toggleGuide = () => setGuideOpen(!guideOpen)

  const fetch = async (liveMode) => {
    setLoading(true)
    setError(null)
    try {
      const data = await getAgents(liveMode)
      setAgents(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetch(live)
  }, [live])

  const closeForms = () => {
    setShowAdd(false)
    setEditAgent(null)
  }

  const handleSaved = async () => {
    closeForms()
    await fetch(live)
  }

  const healthy = agents.filter((a) => a.health === 'ok').length

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{t('agents.title')}</h2>
        <div className="agents-toolbar">
          <span className="agents-meta">
            {live
              ? t('agents.count', { count: agents.length, healthy })
              : t('agents.countStatic', { count: agents.length })}
          </span>
          <Button variant="primary" onClick={() => {
            setShowAdd(!showAdd)
            if (!showAdd) setEditAgent(null)
          }}>
            {t('agents.add')}
          </Button>
          <Button
            variant={live ? 'secondary' : 'ghost'}
            onClick={() => setLive(!live)}
          >
            {t('agents.live')}: {live ? t('agents.on') : t('agents.off')}
          </Button>
          <Button variant="ghost" onClick={toggleGuide}>
            {t('agents.guide.btn')}
          </Button>
        </div>
      </div>

      {showAdd && (
        <AgentForm mode="add" onClose={() => setShowAdd(false)} onSaved={handleSaved} />
      )}
      {editAgent && (
        <div className="agent-modal-overlay" onClick={closeForms}>
          <div className="agent-modal" onClick={(e) => e.stopPropagation()}>
            <AgentForm
              mode="edit"
              agentId={editAgent.id}
              initial={editAgent}
              onClose={closeForms}
              onSaved={handleSaved}
            />
          </div>
        </div>
      )}

      {error && <p className="page-error">{error}</p>}

      {loading ? (
        <p className="page-loading">{t('common.loading')}</p>
      ) : agents.length === 0 ? (
        <EmptyState message={t('agents.noAgents')} />
      ) : (
        <div className="agents-grid">
          {agents.map((agent) => (
            <Link key={agent.id} to={`/agents/${agent.id}`} className="agent-card-link">
              <AgentCard agent={agent} t={t} onEdit={(a) => { setEditAgent(a); setShowAdd(false) }} />
            </Link>
          ))}
        </div>
      )}

      {guideOpen && (
        <div className="guide-overlay" onClick={toggleGuide}>
          <div className="guide-panel" onClick={(e) => e.stopPropagation()}>
            <div className="guide-panel-title">{t('agents.guide.title')}</div>
            {[
              ['toolbarTitle', 'toolbarBody'],
              ['cardTitle', 'cardBody'],
              ['rowTitle', 'rowBody'],
            ].map(([titleKey, bodyKey]) => (
              <div className="guide-section" key={titleKey}>
                <div className="guide-section-title">{t(`agents.guide.${titleKey}`)}</div>
                <p className="guide-section-body">{t(`agents.guide.${bodyKey}`)}</p>
              </div>
            ))}
            <div className="guide-actions">
              <Button variant="primary" onClick={toggleGuide}>
                {t('agents.guide.close')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
