import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { createAgent, getAgents, probeAgent } from '../api/client'
import { useI18n } from '../i18n'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import Input from '../components/Input'
import './Agents.css'

function AgentCard({ agent, t }) {
  const capLabel = (key) => {
    const val = agent.capabilities?.[key]
    if (!val) return t('agents.unknown')
    return t('agents.capLabels')[val] || val
  }
  return (
    <Card className="agent-card">
      <div className="agent-card-header">
        <span className="agent-name">{agent.id}</span>
        <Badge>{agent.health}</Badge>
      </div>
      <div className="agent-props">
        <div className="agent-prop">
          <span className="ap-label">{t('agents.backend')}</span>
          <span className="ap-value">{agent.capabilities?.backend || t('agents.unknown')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.baseUrl')}</span>
          <span className="ap-value ap-mono">{agent.base_url || t('agents.unknown')}</span>
        </div>
        <div className="agent-prop">
          <span className="ap-label">{t('agents.iscsiServer')}</span>
          <span className="ap-value ap-mono">
            {agent.iscsi_server || agent.capabilities?.base_iqn
              ? `${agent.iscsi_server || agent.capabilities.base_iqn}${agent.iscsi_server && agent.capabilities?.base_iqn ? ` (${agent.capabilities.base_iqn})` : ''}`
              : t('agents.unknown')}
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

export default function Agents() {
  const { t } = useI18n()
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState(true)
  const [error, setError] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState(null)
  const [probing, setProbing] = useState(false)
  const [probeError, setProbeError] = useState(null)
  const [probe, setProbe] = useState(null)
  const [addForm, setAddForm] = useState({
    id: '',
    base_url: '',
    token: '',
    iscsi_server: '',
    role_disk: true,
    role_cd: false,
    tags: '',
  })

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

  const setField = (name) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setAddForm((prev) => ({ ...prev, [name]: value }))
    if (name === 'base_url') setProbe(null) // 地址变更后旧探测结果失效
  }

  const handleProbe = async (e) => {
    e.preventDefault()
    setProbing(true)
    setProbeError(null)
    setAddError(null)
    try {
      const result = await probeAgent({
        base_url: addForm.base_url.trim(),
        token: addForm.token.trim(),
      })
      setProbe(result)
      setAddForm((prev) => ({
        ...prev,
        role_disk: result.role.disk,
        role_cd: result.role.cd,
        iscsi_server: result.iscsi_server || prev.iscsi_server,
        tags: result.tags.join(', '),
      }))
    } catch (err) {
      setProbeError(err.message)
      setProbe(null)
    } finally {
      setProbing(false)
    }
  }

  const resetForm = () => {
    setAddForm({
      id: '',
      base_url: '',
      token: '',
      iscsi_server: '',
      role_disk: true,
      role_cd: false,
      tags: '',
    })
  }

  const handleAdd = async (e) => {
    e.preventDefault()
    if (!probe) return // 须先探测成功才允许注册
    setAdding(true)
    setAddError(null)
    const body = {
      id: addForm.id.trim(),
      base_url: addForm.base_url.trim(),
      token: addForm.token.trim(),
      role: { disk: addForm.role_disk, cd: addForm.role_cd },
    }
    if (addForm.iscsi_server.trim()) body.iscsi_server = addForm.iscsi_server.trim()
    const tags = addForm.tags.split(',').map((s) => s.trim()).filter(Boolean)
    if (tags.length) body.tags = tags
    try {
      await createAgent(body)
      setShowAdd(false)
      setProbe(null)
      resetForm()
      await fetch(live)
    } catch (err) {
      setAddError(err.message)
    } finally {
      setAdding(false)
    }
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
          <Button variant="primary" onClick={() => setShowAdd(!showAdd)}>
            {t('agents.add')}
          </Button>
          <Button
            variant={live ? 'secondary' : 'ghost'}
            onClick={() => setLive(!live)}
          >
            {t('agents.live')}: {live ? t('agents.on') : t('agents.off')}
          </Button>
        </div>
      </div>

      {showAdd && (
        <form className="create-form" onSubmit={handleAdd}>
          <div className="create-form-title">{t('agents.addTitle')}</div>
          <p className="create-hint">{t('agents.probeHint')}</p>
          <div className="create-form-grid">
            <Input
              label={t('agents.idLabel')}
              name="id"
              value={addForm.id}
              onChange={setField('id')}
              placeholder={t('agents.idPlaceholder')}
              required
            />
            <Input
              label={t('agents.baseUrl')}
              name="base_url"
              value={addForm.base_url}
              onChange={setField('base_url')}
              placeholder={t('agents.baseUrlPlaceholder')}
              required
            />
            <Input
              label={t('agents.tokenLabel')}
              name="token"
              value={addForm.token}
              onChange={setField('token')}
              placeholder={t('agents.tokenPlaceholder')}
            />
          </div>
          {probeError && <p className="create-error">{probeError}</p>}
          <div className="create-actions">
            <Button
              type="button"
              variant="primary"
              onClick={handleProbe}
              disabled={probing || !addForm.base_url.trim()}
            >
              {probing ? t('agents.probing') : t('agents.probe')}
            </Button>
            <Button variant="ghost" type="button" onClick={() => setShowAdd(false)}>
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
                {probe.base_iqn && (
                  <span className="agent-tag">{t('agents.probeBaseIqn')}: {probe.base_iqn}</span>
                )}
                {probe.clone && <span className="agent-tag">{probe.clone}</span>}
                {probe.empty_disk && <span className="agent-tag">{probe.empty_disk}</span>}
                {probe.persistent && <span className="agent-tag">{probe.persistent}</span>}
              </div>
              <p className="create-hint">{t('agents.probeMeta')}</p>
              <div className="create-form-grid">
                <Input
                  label={t('agents.iscsiServer')}
                  name="iscsi_server"
                  value={addForm.iscsi_server}
                  onChange={setField('iscsi_server')}
                  placeholder={t('agents.iscsiServerPlaceholder')}
                />
                <Input
                  label={t('agents.tagsInput')}
                  name="tags"
                  value={addForm.tags}
                  onChange={setField('tags')}
                  placeholder={t('agents.tagsPlaceholder')}
                />
              </div>
              <div className="agent-role-checks">
                <label className="agent-role-check">
                  <input
                    type="checkbox"
                    checked={addForm.role_disk}
                    onChange={setField('role_disk')}
                  />
                  {t('agents.roleDisk')}
                </label>
                <label className="agent-role-check">
                  <input
                    type="checkbox"
                    checked={addForm.role_cd}
                    onChange={setField('role_cd')}
                  />
                  {t('agents.roleCd')}
                </label>
              </div>
              {addError && <p className="create-error">{addError}</p>}
              <div className="create-actions">
                <Button type="submit" disabled={adding}>
                  {adding ? t('agents.adding') : t('agents.addBtn')}
                </Button>
                <Button variant="ghost" type="button" onClick={() => setShowAdd(false)}>
                  {t('agents.cancel')}
                </Button>
              </div>
            </div>
          )}
        </form>
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
              <AgentCard agent={agent} t={t} />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
