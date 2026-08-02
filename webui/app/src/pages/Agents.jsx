import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getAgents } from '../api/client'
import { useI18n } from '../i18n'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
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
          <Button
            variant={live ? 'secondary' : 'ghost'}
            onClick={() => setLive(!live)}
          >
            {t('agents.live')}: {live ? t('agents.on') : t('agents.off')}
          </Button>
        </div>
      </div>

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
