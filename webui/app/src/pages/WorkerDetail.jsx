import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  getWorker,
  getWorkerStatus,
  deleteWorker,
  bootVars,
  createWorkerDisk,
  deleteWorkerDisk,
  setWorkerDefaultBoot,
  getAgents,
  getMasters,
} from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Divider from '../components/Divider'
import CodeBlock from '../components/CodeBlock'
import ConfirmAction from '../components/ConfirmAction'
import EmptyState from '../components/EmptyState'
import Input from '../components/Input'
import Select from '../components/Select'
import './WorkerDetail.css'

function InfoRow({ label, value, mono = false }) {
  if (value === undefined || value === null) return null
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className={`info-value${mono ? ' info-mono' : ''}`}>{String(value)}</span>
    </div>
  )
}

export default function WorkerDetail() {
  const { t } = useI18n()
  const { id } = useParams()
  const navigate = useNavigate()
  const [worker, setWorker] = useState(null)
  const [status, setStatus] = useState(null)
  const [bootVarsCode, setBootVarsCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [agentsList, setAgentsList] = useState([])
  const [mastersData, setMastersData] = useState(null)
  const [diskForm, setDiskForm] = useState({ os: 'ubuntu', type: 'empty', name: '', size: '40G', disk_agent: '' })
  const [creatingDisk, setCreatingDisk] = useState(false)
  const [diskCreateError, setDiskCreateError] = useState(null)
  const [deletingDisk, setDeletingDisk] = useState(null)
  const [bootForm, setBootForm] = useState({ os: '', menu_default: '', menu_timeout: '', clear_timeout: false })
  const [savingBoot, setSavingBoot] = useState(false)
  const [bootSaveError, setBootSaveError] = useState(null)

  // menu.ipxe 主菜单 item ID（与后端 MENU_ITEMS 一致）
  const MENU_OPTIONS = [
    'windows', 'ubuntu', 'debian', 'centos', 'esxi',
    'menu-diag', 'menu-install', 'config', 'shell', 'reboot', 'exit',
  ].map((v) => ({ value: v, label: v }))
  const CLEAR_OPTION = { value: '__clear__', label: t('workerDetail.clear') }

  const OS_OPTIONS = [
    { value: 'ubuntu', label: 'Ubuntu' },
    { value: 'debian', label: 'Debian' },
    { value: 'centos', label: 'CentOS' },
    { value: 'esxi', label: 'ESXi' },
    { value: 'windows', label: 'Windows' },
  ]

  const DISK_TYPE_OPTIONS = [
    { value: 'empty', label: t('workers.empty') },
    { value: 'master', label: t('workers.master') },
  ]

  // 母盘清单按当前所选存储节点过滤（value 直接存母盘名，agent 已由 disk_agent 单独选择）
  const masterOptions = (mastersData?.agents || [])
    .filter((entry) => !diskForm.disk_agent || entry.agent === diskForm.disk_agent)
    .flatMap((entry) =>
      (entry.masters || []).map((m) => ({ value: m.name, label: m.name }))
    )

  const buildBootVarsCode = (bv, worker) => {
    if (bv && Object.keys(bv).length > 0) {
      const lines = ['#!ipxe', `# boot vars for ${(worker && worker.hostname) || id}`]
      if (bv.base_iqn) lines.push(`set base-iqn ${bv.base_iqn}`)
      if (bv.iscsi_server) lines.push(`set iscsi-server ${bv.iscsi_server}`)
      if (bv.iscsi_sep) lines.push(`set iscsi-sep ${bv.iscsi_sep}`)
      if (bv.menu_default) lines.push(`set menu-default ${bv.menu_default}`)
      if (bv.menu_timeout !== undefined) lines.push(`set menu-timeout ${bv.menu_timeout}`)
      return lines.join('\n')
    }
    return '#!ipxe\n# no per-worker boot vars found'
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [w, s, bv] = await Promise.all([
          getWorker(id),
          getWorkerStatus(id).catch(() => null),
          bootVars({ hostname: id, format: 'json' }).catch(() => null),
        ])
        if (cancelled) return
        setWorker(w)
        setStatus(s)
        setBootForm({
          os: w.default_os || '',
          menu_default: w.boot?.menu_default || w.boot?.['menu-default'] || '',
          menu_timeout: w.boot?.menu_timeout ?? w.boot?.['menu-timeout'] ?? '',
          clear_timeout: false,
        })
        setBootVarsCode(buildBootVarsCode(bv, w))
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [id])

  useEffect(() => {
    let cancelled = false
    async function loadDiskAgents() {
      try {
        const [agents, masters] = await Promise.all([
          getAgents(false),
          getMasters().catch(() => null), // 全部 Agent 失败时聚合端点 502，母盘下拉置空即可
        ])
        if (cancelled) return
        const diskAgents = (Array.isArray(agents) ? agents : []).filter(
          (a) => a.enabled && a.role?.disk
        )
        setAgentsList(diskAgents)
        setMastersData(masters)
        if (diskAgents.length > 0) {
          setDiskForm((prev) => ({ ...prev, disk_agent: prev.disk_agent || diskAgents[0].id }))
        }
      } catch {
        setAgentsList([])
        setMastersData(null)
      }
    }
    loadDiskAgents()
    return () => { cancelled = true }
  }, [id])

  const refreshStatus = async () => {
    setStatusLoading(true)
    try {
      const s = await getWorkerStatus(id)
      setStatus(s)
    } catch {
      // ignore
    } finally {
      setStatusLoading(false)
    }
  }

  const handleDelete = async (extra) => {
    try {
      await deleteWorker(id, extra.delete_disk, extra.ignore_missing)
      navigate('/workers')
    } catch (e) {
      alert(e.message)
    }
  }

  // 删除单个系统盘后刷新台账与默认启动表单（default_os / menu_default 可能被联动清除）
  const reloadWorkerAndBoot = async () => {
    const w = await getWorker(id)
    const bv = await bootVars({ hostname: id, format: 'json' }).catch(() => null)
    setWorker(w)
    setBootForm({
      os: w.default_os || '',
      menu_default: w.boot?.menu_default || w.boot?.['menu-default'] || '',
      menu_timeout: w.boot?.menu_timeout ?? w.boot?.['menu-timeout'] ?? '',
      clear_timeout: false,
    })
    setBootVarsCode(buildBootVarsCode(bv, w))
  }

  const handleDeleteDisk = async (os, extra) => {
    setDeletingDisk(os)
    try {
      await deleteWorkerDisk(id, os, extra.delete_file, extra.ignore_missing)
      await reloadWorkerAndBoot()
    } catch (e) {
      alert(e.message)
    } finally {
      setDeletingDisk(null)
    }
  }

  const handleCreateDisk = async (e) => {
    e.preventDefault()
    setCreatingDisk(true)
    setDiskCreateError(null)
    const body = { type: diskForm.type, os: diskForm.os }
    if (diskForm.type === 'master') {
      body.name = diskForm.name.trim()
    } else {
      body.size = diskForm.size.trim()
    }
    if (diskForm.disk_agent) {
      body.disk_agent = diskForm.disk_agent
    }
    try {
      await createWorkerDisk(id, body)
      const w = await getWorker(id)
      setWorker(w)
      setBootForm((prev) => ({ ...prev, os: w.default_os || prev.os }))
    } catch (err) {
      setDiskCreateError(err.message)
    } finally {
      setCreatingDisk(false)
    }
  }

  const handleSaveBoot = async (e) => {
    e.preventDefault()
    setSavingBoot(true)
    setBootSaveError(null)
    const body = {}
    if (bootForm.os === '__clear__') body.os = null
    else if (bootForm.os) body.os = bootForm.os
    if (bootForm.menu_default === '__clear__') body.menu_default = null
    else if (bootForm.menu_default) body.menu_default = bootForm.menu_default
    if (bootForm.clear_timeout) body.menu_timeout = null
    else if (bootForm.menu_timeout !== '' && bootForm.menu_timeout !== undefined) {
      body.menu_timeout = Number(bootForm.menu_timeout)
    }
    if (Object.keys(body).length === 0) {
      setBootSaveError(t('workerDetail.bootNothing'))
      setSavingBoot(false)
      return
    }
    try {
      await setWorkerDefaultBoot(id, body)
      const w = await getWorker(id)
      const bv = await bootVars({ hostname: id, format: 'json' }).catch(() => null)
      setWorker(w)
      setBootForm({
        os: w.default_os || '',
        menu_default: w.boot?.menu_default || w.boot?.['menu-default'] || '',
        menu_timeout: w.boot?.menu_timeout ?? w.boot?.['menu-timeout'] ?? '',
        clear_timeout: false,
      })
      setBootVarsCode(buildBootVarsCode(bv, w))
    } catch (err) {
      setBootSaveError(err.message)
    } finally {
      setSavingBoot(false)
    }
  }

  if (loading) return <p className="page-loading">{t('common.loading')}</p>
  if (error) return <p className="page-error">{error}</p>
  if (!worker) return <EmptyState message={t('workerDetail.notFoundMsg')} />

  const { disks = [], cd, mac } = worker

  return (
    <div>
      <div className="detail-nav">
        <Link to="/workers" className="back-link">
          {t('workerDetail.back')}
        </Link>
      </div>

      <div className="detail-header">
        <div className="detail-title-row">
          <h2 className="page-title" style={{ marginBottom: 0 }}>
            {worker.worker_id}
          </h2>
          <Badge>{worker.state || 'unknown'}</Badge>
        </div>
        <ConfirmAction
          trigger={<Button variant="danger">{t('workerDetail.delete')}</Button>}
          message={t('workerDetail.deleteConfirm', { id })}
          onConfirm={handleDelete}
          extraFields={[
            { name: 'delete_disk', label: t('workerDetail.deleteDisk') },
            { name: 'ignore_missing', label: t('workerDetail.ignoreMissing') },
          ]}
        />
      </div>

      {/* Identity */}
      <Divider>{t('workerDetail.identity')}</Divider>
      <Card className="detail-card">
        <InfoRow label={t('workerDetail.workerId')} value={worker.worker_id} mono />
        <InfoRow label={t('workerDetail.hostname')} value={worker.hostname} mono />
        <InfoRow label={t('workerDetail.mac')} value={mac} mono />
        <InfoRow
          label={t('workerDetail.os')}
          value={disks.map((d) => d.os).join(', ') || t('workerDetail.noDisk')}
        />
        <InfoRow label={t('workerDetail.arch')} value={worker.arch} />
        <InfoRow label={t('workerDetail.state')} value={worker.state} />
      </Card>

      {/* Create System Disk (step 2) */}
      <Divider>{t('workerDetail.createDisk')}</Divider>
      <form className="create-form" onSubmit={handleCreateDisk}>
        <div className="create-form-title">{t('workerDetail.createDiskTitle')}</div>
        <p className="create-hint">{t('workerDetail.createDiskHint')}</p>
        <div className="create-form-grid">
          <Select
            label={t('workers.os')}
            name="os"
            value={diskForm.os}
            onChange={(e) => { setDiskForm((prev) => ({ ...prev, os: e.target.value })) }}
            options={OS_OPTIONS}
          />
          <Select
            label={t('workers.diskType')}
            name="type"
            value={diskForm.type}
            onChange={(e) => { setDiskForm((prev) => ({ ...prev, type: e.target.value })) }}
            options={DISK_TYPE_OPTIONS}
          />
          {diskForm.type === 'master' ? (
            <Select
              label={t('workers.masterName')}
              name="disk_name"
              value={diskForm.name}
              onChange={(e) => { setDiskForm((prev) => ({ ...prev, name: e.target.value })) }}
              options={masterOptions}
              placeholder={masterOptions.length === 0 ? t('workers.noMasters') : t('workers.masterSelectPlaceholder')}
              required
            />
          ) : (
            <Input
              label={t('workers.diskSize')}
              name="disk_size"
              value={diskForm.size}
              onChange={(e) => { setDiskForm((prev) => ({ ...prev, size: e.target.value })) }}
              placeholder={t('workers.diskSizePlaceholder')}
              required
            />
          )}
          {agentsList.length > 0 && (
            <Select
              label={t('workers.diskAgent')}
              name="disk_agent"
              value={diskForm.disk_agent}
              onChange={(e) => {
                // 切换节点后母盘清单随之过滤，已选母盘不再有效则清空
                setDiskForm((prev) => ({ ...prev, disk_agent: e.target.value, name: '' }))
              }}
              options={agentsList.map((a) => ({
                value: a.id,
                label: `${a.id}${a.iscsi_server ? ` (${a.iscsi_server})` : ''}`,
              }))}
            />
          )}
        </div>
        {diskCreateError && <p className="create-error">{diskCreateError}</p>}
        <Button type="submit" disabled={creatingDisk}>
          {creatingDisk ? t('workers.creating') : t('workers.createBtn')}
        </Button>
      </form>

      {/* Disks */}
      {disks.length > 0 && (
        <>
          <Divider>{t('workerDetail.disks')}</Divider>
          {disks.map((d, i) => (
            <Card className="detail-card" key={d.iqn || `disk-${i}`}>
              <InfoRow label={t('workerDetail.os')} value={d.os} />
              <InfoRow label={t('workerDetail.agent')} value={d.agent} mono />
              <InfoRow label={t('workerDetail.iqn')} value={d.iqn} mono />
              <InfoRow label={t('workerDetail.filename')} value={d.filename} mono />
              <InfoRow label={t('workerDetail.backing')} value={d.backing} mono />
              {d.source && (
                <InfoRow
                  label={t('workerDetail.source')}
                  value={
                    d.source.type === 'master'
                      ? `master: ${d.source.name}`
                      : `empty: ${d.source.size}`
                  }
                />
              )}
              <div className="disk-card-actions">
                <ConfirmAction
                  trigger={
                    <Button variant="danger" disabled={deletingDisk !== null}>
                      {deletingDisk === d.os ? t('workerDetail.deletingDisk') : t('workerDetail.deleteSystemDisk')}
                    </Button>
                  }
                  message={t('workerDetail.deleteDiskConfirm', { id, os: d.os })}
                  onConfirm={(extra) => handleDeleteDisk(d.os, extra)}
                  extraFields={[
                    { name: 'delete_file', label: t('workerDetail.deleteDisk') },
                    { name: 'ignore_missing', label: t('workerDetail.ignoreMissing') },
                  ]}
                />
              </div>
            </Card>
          ))}
        </>
      )}

      {/* Default Boot */}
      <Divider>{t('workerDetail.defaultBoot')}</Divider>
      <Card className="detail-card">
        <InfoRow label={t('workerDetail.defaultOs')} value={worker.default_os || '—'} mono />
        <InfoRow
          label={t('workerDetail.menuDefault')}
          value={worker.boot?.menu_default || worker.boot?.['menu-default'] || '—'}
          mono
        />
        <InfoRow
          label={t('workerDetail.menuTimeout')}
          value={worker.boot?.menu_timeout ?? worker.boot?.['menu-timeout'] ?? '—'}
          mono
        />
      </Card>
      <form className="create-form" onSubmit={handleSaveBoot}>
        <p className="create-hint">{t('workerDetail.defaultBootHint')}</p>
        <div className="create-form-grid">
          <Select
            label={t('workerDetail.defaultOs')}
            name="boot_os"
            value={bootForm.os}
            onChange={(e) => { setBootForm((prev) => ({ ...prev, os: e.target.value })) }}
            options={[CLEAR_OPTION, ...disks.map((d) => ({ value: d.os, label: d.os }))]}
            disabled={disks.length === 0}
          />
          <Select
            label={t('workerDetail.menuDefault')}
            name="boot_menu_default"
            value={bootForm.menu_default}
            onChange={(e) => { setBootForm((prev) => ({ ...prev, menu_default: e.target.value })) }}
            options={[CLEAR_OPTION, ...MENU_OPTIONS]}
          />
          <Input
            label={t('workerDetail.menuTimeout')}
            name="boot_menu_timeout"
            type="number"
            min="0"
            value={bootForm.menu_timeout}
            onChange={(e) => { setBootForm((prev) => ({ ...prev, menu_timeout: e.target.value })) }}
            placeholder={t('workerDetail.menuTimeoutPlaceholder')}
          />
          <label className="boot-clear">
            <input
              type="checkbox"
              checked={bootForm.clear_timeout}
              onChange={(e) => { setBootForm((prev) => ({ ...prev, clear_timeout: e.target.checked })) }}
            />
            {t('workerDetail.clearTimeout')}
          </label>
        </div>
        {bootSaveError && <p className="create-error">{bootSaveError}</p>}
        <Button type="submit" disabled={savingBoot}>
          {savingBoot ? t('workerDetail.savingBoot') : t('workerDetail.saveBoot')}
        </Button>
      </form>

      {/* CD */}
      {cd && (
        <>
          <Divider>{t('workerDetail.cdrom')}</Divider>
          <Card className="detail-card">
            <InfoRow label={t('workerDetail.agent')} value={cd.agent} mono />
            <InfoRow label={t('workerDetail.iqn')} value={cd.iqn} mono />
            <InfoRow label={t('workerDetail.iso')} value={cd.iso} mono />
            <InfoRow label={t('workerDetail.backing')} value={cd.backing} mono />
          </Card>
        </>
      )}

      {/* Live Status */}
      <Divider>{t('workerDetail.liveStatus')}</Divider>
      {status ? (
        <Card className="detail-card">
          {status.actual?.dnsmasq && (
            <InfoRow
              label={t('workerDetail.dnsmasq')}
              value={`${status.actual.dnsmasq.hostname} \u2192 ${status.actual.dnsmasq.mac}`}
              mono
            />
          )}
          {(status.actual?.disks || []).map((d, i) => (
            <InfoRow
              key={d.os || `disk-${i}`}
              label={`${t('workerDetail.diskTarget')}${d.os ? ` (${d.os})` : ''}`}
              value={d?.exists ? t('workerDetail.exists') : t('workerDetail.notFound')}
            />
          ))}
          {status.actual?.cd !== null && (
            <InfoRow
              label={t('workerDetail.cdTarget')}
              value={status.actual?.cd?.exists ? t('workerDetail.exists') : t('workerDetail.notFound')}
            />
          )}
        </Card>
      ) : (
        <p className="page-muted">{t('workerDetail.statusUnavailable')}</p>
      )}
      <div style={{ marginTop: 12 }}>
        <Button variant="ghost" onClick={refreshStatus} disabled={statusLoading}>
          {statusLoading ? t('workerDetail.refreshing') : t('workerDetail.refresh')}
        </Button>
      </div>

      {/* Boot Vars */}
      <Divider>{t('workerDetail.bootVars')}</Divider>
      <CodeBlock code={bootVarsCode} language="ipxe" />
    </div>
  )
}
