import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getAgentLuns,
  getAgents,
  getWorkers,
  createAgentDiskLun,
  createAgentCdLun,
  deleteAgentLun,
  scanAgentLuns,
} from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Badge from '../components/Badge'
import Input from '../components/Input'
import Select from '../components/Select'
import ConfirmAction from '../components/ConfirmAction'
import EmptyState from '../components/EmptyState'
import './AgentLuns.css'

function flattenTargets(targets) {
  const rows = []
  for (const target of targets || []) {
    const luns =
      target.luns && target.luns.length ? target.luns : [{ lun: 1, backing: null }]
    for (const lun of luns) {
      rows.push({ iqn: target.iqn, backing: lun.backing || '', lun: lun.lun })
    }
  }
  return rows
}

function isCd(backing) {
  return /\.iso$/i.test(backing)
}

export default function AgentLuns() {
  const { t } = useI18n()
  const { id } = useParams()
  const [agent, setAgent] = useState(null)
  const [luns, setLuns] = useState([])
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showDiskForm, setShowDiskForm] = useState(false)
  const [showCdForm, setShowCdForm] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [diskForm, setDiskForm] = useState({ iqn: '', kind: 'empty', master: '', size: '40G' })
  const [cdForm, setCdForm] = useState({ iso: '', iqn: '' })

  const refresh = useCallback(async () => {
    const data = await getAgentLuns(id)
    setLuns(Array.isArray(data) ? data : [])
  }, [id])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [agents, lunsData, workersData] = await Promise.all([
          getAgents(false).catch(() => []),
          getAgentLuns(id),
          getWorkers().catch(() => []),
        ])
        if (cancelled) return
        setAgent((Array.isArray(agents) ? agents : []).find((a) => a.id === id) || null)
        setLuns(Array.isArray(lunsData) ? lunsData : [])
        setWorkers(Array.isArray(workersData) ? workersData : [])
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [id])

  // iqn -> 绑定的 Worker（系统盘 disk / 光驱 cd）
  const bindingByIqn = useMemo(() => {
    const map = {}
    for (const w of workers) {
      for (const d of w.disks || (w.disk ? [w.disk] : [])) {
        if (d.iqn) map[d.iqn] = { workerId: w.worker_id, kind: 'disk' }
      }
      if (w.cd?.iqn) map[w.cd.iqn] = { workerId: w.worker_id, kind: 'cd' }
    }
    return map
  }, [workers])

  const rows = flattenTargets(luns)
  const boundCount = rows.filter((r) => bindingByIqn[r.iqn]).length

  const update = (setter) => (key) => (e) =>
    setter((prev) => ({ ...prev, [key]: e.target.value }))

  const handleCreateDisk = async (e) => {
    e.preventDefault()
    setCreating(true)
    setCreateError(null)
    const body = { iqn: diskForm.iqn.trim() }
    if (diskForm.kind === 'master') {
      body.master = diskForm.master.trim()
    } else {
      body.size = diskForm.size.trim()
    }
    try {
      await createAgentDiskLun(id, body)
      setShowDiskForm(false)
      setDiskForm({ iqn: '', kind: 'empty', master: '', size: '40G' })
      await refresh()
    } catch (err) {
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  const handleCreateCd = async (e) => {
    e.preventDefault()
    setCreating(true)
    setCreateError(null)
    const body = { iso: cdForm.iso.trim() }
    if (cdForm.iqn.trim()) body.iqn = cdForm.iqn.trim()
    try {
      await createAgentCdLun(id, body)
      setShowCdForm(false)
      setCdForm({ iso: '', iqn: '' })
      await refresh()
    } catch (err) {
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  const handleScan = async () => {
    setScanning(true)
    try {
      const result = await scanAgentLuns(id)
      alert(
        t('agentLuns.scanResult', {
          created: result.created?.length || 0,
          skipped: result.skipped?.length || 0,
        })
      )
      await refresh()
    } catch (err) {
      alert(err.message)
    } finally {
      setScanning(false)
    }
  }

  const handleDelete = (iqn) => async (extra) => {
    try {
      await deleteAgentLun(id, iqn, extra.delete_file)
      await refresh()
    } catch (err) {
      alert(err.message)
    }
  }

  if (loading) return <p className="page-loading">{t('common.loading')}</p>
  if (error) return <p className="page-error">{error}</p>
  if (!agent) return <EmptyState message={t('agentLuns.notFound')} />

  return (
    <div>
      <div className="detail-nav">
        <Link to="/agents" className="back-link">
          {t('agentLuns.back')}
        </Link>
      </div>

      <div className="detail-header">
        <div className="detail-title-row">
          <h2 className="page-title" style={{ marginBottom: 0 }}>
            {agent.id}
          </h2>
          <Badge>{agent.health}</Badge>
        </div>
        <div className="luns-toolbar">
          <span className="luns-meta">
            {t('agentLuns.count', { count: rows.length })}
            {boundCount > 0 && ` · ${t('agentLuns.boundCount', { bound: boundCount })}`}
          </span>
          <Button variant="ghost" onClick={handleScan} disabled={scanning}>
            {scanning ? t('agentLuns.scanning') : t('agentLuns.scan')}
          </Button>
          <Button
            variant={showCdForm ? 'ghost' : 'secondary'}
            onClick={() => {
              setShowCdForm(!showCdForm)
              setShowDiskForm(false)
              setCreateError(null)
            }}
          >
            {showCdForm ? t('agentLuns.cancel') : t('agentLuns.createCd')}
          </Button>
          <Button
            variant={showDiskForm ? 'ghost' : 'primary'}
            onClick={() => {
              setShowDiskForm(!showDiskForm)
              setShowCdForm(false)
              setCreateError(null)
            }}
          >
            {showDiskForm ? t('agentLuns.cancel') : t('agentLuns.createDisk')}
          </Button>
        </div>
      </div>

      {showDiskForm && (
        <form className="create-form" onSubmit={handleCreateDisk}>
          <div className="create-form-title">{t('agentLuns.newDisk')}</div>
          <div className="create-form-grid">
            <Input
              label={t('agentLuns.iqnLabel')}
              name="iqn"
              value={diskForm.iqn}
              onChange={update(setDiskForm)('iqn')}
              placeholder={t('agentLuns.iqnPlaceholder')}
              required
            />
            <Select
              label={t('agentLuns.type')}
              name="kind"
              value={diskForm.kind}
              onChange={update(setDiskForm)('kind')}
              options={[
                { value: 'empty', label: t('agentLuns.empty') },
                { value: 'master', label: t('agentLuns.master') },
              ]}
            />
            {diskForm.kind === 'master' ? (
              <Input
                label={t('agentLuns.masterName')}
                name="master"
                value={diskForm.master}
                onChange={update(setDiskForm)('master')}
                placeholder={t('agentLuns.masterPlaceholder')}
                required
              />
            ) : (
              <Input
                label={t('agentLuns.diskSize')}
                name="size"
                value={diskForm.size}
                onChange={update(setDiskForm)('size')}
                placeholder={t('agentLuns.diskSizePlaceholder')}
                required
              />
            )}
          </div>
          {createError && <p className="create-error">{createError}</p>}
          <Button type="submit" disabled={creating}>
            {creating ? t('agentLuns.creating') : t('agentLuns.createBtn')}
          </Button>
        </form>
      )}

      {showCdForm && (
        <form className="create-form" onSubmit={handleCreateCd}>
          <div className="create-form-title">{t('agentLuns.newCd')}</div>
          <div className="create-form-grid">
            <Input
              label={t('agentLuns.iso')}
              name="iso"
              value={cdForm.iso}
              onChange={update(setCdForm)('iso')}
              placeholder={t('agentLuns.isoPlaceholder')}
              required
            />
            <Input
              label={t('agentLuns.iqnOptional')}
              name="cd_iqn"
              value={cdForm.iqn}
              onChange={update(setCdForm)('iqn')}
              placeholder={t('agentLuns.iqnPlaceholder')}
            />
          </div>
          {createError && <p className="create-error">{createError}</p>}
          <Button type="submit" disabled={creating}>
            {creating ? t('agentLuns.creating') : t('agentLuns.createBtn')}
          </Button>
        </form>
      )}

      {rows.length === 0 ? (
        <EmptyState message={t('agentLuns.noLuns')} />
      ) : (
        <div className="luns-list">
          <div className="luns-header">
            <span className="lh-iqn">{t('agentLuns.iqnLabel')}</span>
            <span className="lh-type">{t('agentLuns.type')}</span>
            <span className="lh-backing">{t('agentLuns.backing')}</span>
            <span className="lh-bound">{t('agentLuns.bound')}</span>
            <span className="lh-action" />
          </div>
          {rows.map((row) => {
            const binding = bindingByIqn[row.iqn]
            const cd = isCd(row.backing)
            const delMsg = binding
              ? t('agentLuns.deleteBoundConfirm', { iqn: row.iqn, worker: binding.workerId })
              : t('agentLuns.deleteConfirm', { iqn: row.iqn })
            return (
              <div key={`${row.iqn}-${row.lun}`} className="luns-row">
                <span className="lr-iqn">{row.iqn}</span>
                <span className="lr-type">
                  <Badge variant={cd ? 'installing' : 'ready'}>
                    {cd ? t('agentLuns.typeCd') : t('agentLuns.typeDisk')}
                  </Badge>
                </span>
                <span className="lr-backing">{row.backing || t('agentLuns.unknown')}</span>
                <span className="lr-bound">
                  {binding ? (
                    <Badge variant="installing">
                      {t('agentLuns.boundWorker', { worker: binding.workerId })}
                    </Badge>
                  ) : (
                    <span className="lr-unbound">{t('agentLuns.unbound')}</span>
                  )}
                </span>
                <span className="lr-action">
                  <ConfirmAction
                    trigger={<Button variant="danger">{t('agentLuns.delete')}</Button>}
                    message={delMsg}
                    onConfirm={handleDelete(row.iqn)}
                    extraFields={[{ name: 'delete_file', label: t('agentLuns.deleteFile') }]}
                  />
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
