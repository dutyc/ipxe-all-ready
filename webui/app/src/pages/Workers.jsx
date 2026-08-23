import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getWorkers, getAgents, createWorker, batchCreateWorkers, batchCreateWorkerDisks, batchDeleteWorkers, getMasters } from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Input from '../components/Input'
import Select from '../components/Select'
import Badge from '../components/Badge'
import ConfirmAction from '../components/ConfirmAction'
import EmptyState from '../components/EmptyState'
import './Workers.css'

const OS_OPTIONS = [
  { value: 'ubuntu', label: 'Ubuntu' },
  { value: 'debian', label: 'Debian' },
  { value: 'centos', label: 'CentOS' },
  { value: 'esxi', label: 'ESXi' },
  { value: 'windows', label: 'Windows' },
]

function useForm(initial) {
  const [values, setValues] = useState(initial)
  const update = (key) => (e) =>
    setValues((prev) => ({ ...prev, [key]: e.target.value }))
  const set = (key, val) => setValues((prev) => ({ ...prev, [key]: val }))
  const reset = () => setValues(initial)
  return { values, update, set, reset }
}

export default function Workers() {
  const { t } = useI18n()
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)

  // ===== 批量创建 Worker 模式（与批量系统盘/批量删除互斥） =====
  const [batchCreateMode, setBatchCreateMode] = useState(false)
  const [batchCreateForm, setBatchCreateForm] = useState({ count: '5', name_prefix: 'worker-', macs: '' })
  const [bcSubmitting, setBcSubmitting] = useState(false)
  const [bcError, setBcError] = useState(null)
  const [bcResult, setBcResult] = useState(null)

  // ===== 批量创建模式 =====
  const [batchMode, setBatchMode] = useState(false)
  // ===== 批量删除模式（与批量创建互斥） =====
  const [deleteMode, setDeleteMode] = useState(false)
  const [selected, setSelected] = useState([])
  const [anchor, setAnchor] = useState(null)
  const [storageAgents, setStorageAgents] = useState([])
  const [mastersData, setMastersData] = useState(null)
  const [assign, setAssign] = useState({})
  const [spreadIds, setSpreadIds] = useState([])
  const [batchForm, setBatchForm] = useState({ os: 'ubuntu', type: 'empty', name: '', size: '40G', master: '' })
  const [submitting, setSubmitting] = useState(false)
  const [batchError, setBatchError] = useState(null)
  const [batchResult, setBatchResult] = useState(null)
  const [dragAgent, setDragAgent] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)
  const [deleteResult, setDeleteResult] = useState(null)

  // ===== 页面介绍弹层 =====
  const [guideOpen, setGuideOpen] = useState(false)
  const toggleGuide = () => setGuideOpen(!guideOpen)

  const DISK_TYPE_OPTIONS = [
    { value: 'empty', label: t('workers.empty') },
    { value: 'master', label: t('workers.master') },
  ]

  // 聚合母盘清单按母盘名去重为纯名选项（不绑定节点）；均摊克隆时各参与节点须本地都有该母盘（提交时校验）
  const masterOptions = (mastersData?.agents || [])
    .flatMap((entry) => (entry.masters || []).map((m) => m.name))
    .filter((name, idx, arr) => arr.indexOf(name) === idx)
    .map((name) => ({ value: name, label: name }))

  const form = useForm({
    worker_id: '',
    mac: '',
    windows_iso: '',
  })

  const fetchWorkers = useCallback(async () => {
    try {
      const data = await getWorkers()
      setWorkers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const toggleCreate = () => {
    setShowCreate(!showCreate)
    setCreateError(null)
  }

  // 进入/退出批量创建模式：与批量系统盘/批量删除互斥
  const toggleBatchCreate = () => {
    const next = !batchCreateMode
    setBatchCreateMode(next)
    if (next) {
      setBatchMode(false)
      setDeleteMode(false)
    }
    setBcError(null)
    setBcResult(null)
  }

  // 批量创建 Worker：count + 命名规则；macs 可选（每行一个，行数须等于 count）
  const handleBatchCreateWorkers = async (e) => {
    e.preventDefault()
    const count = parseInt(batchCreateForm.count, 10)
    if (!count || count < 1 || count > 100) {
      setBcError(t('workers.batchCreate.countInvalid'))
      return
    }
    const macs = batchCreateForm.macs
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
    if (macs.length > 0 && macs.length !== count) {
      setBcError(t('workers.batchCreate.macsCountMismatch'))
      return
    }
    setBcSubmitting(true)
    setBcError(null)
    setBcResult(null)
    const body = { count, name_prefix: batchCreateForm.name_prefix.trim() }
    if (macs.length > 0) body.macs = macs
    try {
      const res = await batchCreateWorkers(body)
      setBcResult(res)
      await fetchWorkers()
    } catch (err) {
      setBcError(err.message)
    } finally {
      setBcSubmitting(false)
    }
  }

  // 进入/退出批量创建系统盘模式（与批量创建 Worker/批量删除互斥）
  const toggleBatch = async () => {
    const next = !batchMode
    setBatchMode(next)
    if (next) {
      setDeleteMode(false) // 与批量删除互斥
      setBatchCreateMode(false)
    }
    setBatchError(null)
    setBatchResult(null)
    if (next) {
      setSelected([])
      setAnchor(null)
      setAssign({})
      setSpreadIds([])
      setMastersData(null)
      try {
        const [agents, masters] = await Promise.all([getAgents(false), getMasters()])
        const diskAgents = (Array.isArray(agents) ? agents : []).filter(
          (a) => a.enabled && a.role?.disk
        )
        setStorageAgents(diskAgents)
        setMastersData(masters)
      } catch (e) {
        setBatchError(e.message)
      }
    }
  }

  // 进入/退出批量删除模式：与批量创建互斥，进入时清空勾选与上次结果
  const toggleDelete = () => {
    const next = !deleteMode
    setDeleteMode(next)
    if (next) {
      setBatchMode(false)
      setBatchCreateMode(false)
    }
    setSelected([])
    setAnchor(null)
    setDeleteError(null)
    setDeleteResult(null)
  }

  // 勾选：普通点击切换单个；Shift+点击以最近一次点击行为起点、当前行为终点，中间自动勾选
  const handleCheck = (e, w) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.shiftKey && anchor) {
      const idx1 = filtered.findIndex((x) => x.worker_id === anchor)
      const idx2 = filtered.findIndex((x) => x.worker_id === w.worker_id)
      if (idx1 >= 0 && idx2 >= 0) {
        const [lo, hi] = idx1 <= idx2 ? [idx1, idx2] : [idx2, idx1]
        const ids = filtered.slice(lo, hi + 1).map((x) => x.worker_id)
        setSelected((prev) => Array.from(new Set([...prev, ...ids])))
      }
    } else {
      setSelected((prev) =>
        prev.includes(w.worker_id)
          ? prev.filter((id) => id !== w.worker_id)
          : [...prev, w.worker_id]
      )
    }
    setAnchor(w.worker_id)
  }

  // 接管所选：所有已选 Worker 统一改派给该存储节点（覆盖之前的单独指定）
  const handleTakeover = (agentId) => {
    if (selected.length === 0) return
    setAssign((prev) => {
      const next = { ...prev }
      selected.forEach((id) => {
        next[id] = agentId
      })
      return next
    })
    setBatchError(null)
  }

  // 选择母盘：只记录母盘名（不再绑定/接管节点）；节点分配由均摊/接管/拖拽侧边栏决定
  const handleMasterSelect = (e) => {
    setBatchForm((prev) => ({ ...prev, master: e.target.value }))
    setBatchError(null)
  }

  // 均摊分配：已选 Worker 按参与节点轮流平均分配（覆盖之前分配），需 ≥2 个参与节点
  const handleSpread = () => {
    if (selected.length === 0 || spreadIds.length < 2) return
    setAssign((prev) => {
      const next = { ...prev }
      selected.forEach((id, i) => {
        next[id] = spreadIds[i % spreadIds.length]
      })
      return next
    })
    setBatchError(null)
  }

  const handleToggleSpread = (agentId) => {
    setSpreadIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    )
  }

  // 拖拽：节点标签放到某行 = 该 Worker 单独指定该存储节点
  const handleDrop = (w) => (e) => {
    e.preventDefault()
    const aid = e.dataTransfer.getData('text/plain')
    if (aid) {
      setAssign((prev) => ({ ...prev, [w.worker_id]: aid }))
      setBatchError(null)
    }
    setDragAgent(null)
  }

  const handleBatchCreate = async (e) => {
    e.preventDefault()
    if (selected.length === 0) {
      setBatchError(t('workers.batch.selectFirst'))
      return
    }
    const targets = selected
      .filter((id) => assign[id])
      .map((id) => ({ worker_id: id, agent: assign[id] }))
    if (targets.length === 0) {
      setBatchError(t('workers.batch.noAssign'))
      return
    }
    if (batchForm.type === 'master') {
      const masterName = batchForm.master.trim()
      // 母盘克隆在节点本地完成：均摊激活（≥2 节点参与）时检查参与均摊的节点，否则检查全部实际分配节点
      // ——每个待克隆节点都须本地存在该母盘，缺失则列出并阻止提交，由用户调整（移除勾选或先补母盘）
      const assignedAgents = [...new Set(targets.map((t) => t.agent))]
      const checkAgents =
        spreadIds.length >= 2 && spreadIds.some((a) => assignedAgents.includes(a))
          ? [...spreadIds]
          : assignedAgents
      const missing = checkAgents.filter((aid) => {
        const entry = (mastersData?.agents || []).find((e) => e.agent === aid)
        return !entry || !(entry.masters || []).some((m) => m.name === masterName)
      })
      if (missing.length > 0) {
        setBatchError(t('workers.batch.masterMissingOnNodes', { nodes: missing.join(', ') }))
        return
      }
    }
    setSubmitting(true)
    setBatchError(null)
    setBatchResult(null)
    const body = { type: batchForm.type, os: batchForm.os, targets }
    if (batchForm.type === 'master') {
      body.name = batchForm.master.trim()
    } else {
      body.size = batchForm.size.trim()
    }
    try {
      const res = await batchCreateWorkerDisks(body)
      setBatchResult(res)
      await fetchWorkers()
    } catch (err) {
      setBatchError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const assignedCount = (agentId) =>
    Object.values(assign).filter((a) => a === agentId).length

  // 批量删除：确认弹窗选项（delete_disk / ignore_missing）由 ConfirmAction extraFields 提供
  const handleBatchDelete = async (extra = {}) => {
    if (selected.length === 0) return
    setDeleting(true)
    setDeleteError(null)
    setDeleteResult(null)
    try {
      const res = await batchDeleteWorkers(selected, extra.delete_disk, extra.ignore_missing)
      setDeleteResult(res)
      setSelected([])
      setAnchor(null)
      await fetchWorkers()
    } catch (err) {
      setDeleteError(err.message)
    } finally {
      setDeleting(false)
    }
  }

  const hasDisk = (w) => Array.isArray(w.disks) && w.disks.length > 0

  useEffect(() => {
    fetchWorkers()
  }, [fetchWorkers])

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    setCreateError(null)

    const body = {
      worker_id: form.values.worker_id,
      mac: form.values.mac,
    }

    if (form.values.windows_iso.trim()) {
      body.windows_iso = form.values.windows_iso.trim()
    }

    try {
      await createWorker(body)
      form.reset()
      setShowCreate(false)
      await fetchWorkers()
    } catch (e) {
      setCreateError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const filtered = workers.filter((w) => {
    const term = filter.toLowerCase()
    return (
      (w.worker_id || '').toLowerCase().includes(term) ||
      (w.hostname || '').toLowerCase().includes(term) ||
      (w.bound_device || '').toLowerCase().includes(term) ||
      (w.disk?.os || '').toLowerCase().includes(term)
    )
  })

  if (loading) return <p className="page-loading">{t('common.loading')}</p>
  if (error) return <p className="page-error">{error}</p>

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{t('workers.title')}</h2>
        <div className="page-actions">
          <Button
            variant={batchCreateMode ? 'ghost' : 'primary'}
            onClick={toggleBatchCreate}
          >
            {batchCreateMode ? t('workers.batchCreate.exit') : t('workers.batchCreate.enter')}
          </Button>
          <Button
            variant={deleteMode ? 'ghost' : 'danger'}
            onClick={toggleDelete}
          >
            {deleteMode ? t('workers.bulkDelete.exit') : t('workers.bulkDelete.enter')}
          </Button>
          <Button
            variant={batchMode ? 'ghost' : 'primary'}
            onClick={toggleBatch}
          >
            {batchMode ? t('workers.batch.exit') : t('workers.batch.enter')}
          </Button>
          <Button
            variant={showCreate ? 'ghost' : 'primary'}
            onClick={toggleCreate}
          >
            {showCreate ? t('workers.cancel') : t('workers.create')}
          </Button>
        </div>
      </div>

      {showCreate && (
        <form className="create-form" onSubmit={handleCreate}>
          <div className="create-form-title">{t('workers.newWorker')}</div>
          <p className="create-hint">{t('workers.registerHint')}</p>

          <div className="create-form-grid">
            <Input
              label={t('workers.workerId')}
              name="worker_id"
              value={form.values.worker_id}
              onChange={form.update('worker_id')}
              placeholder={t('workers.workerIdPlaceholder')}
              required
            />
            <Input
              label={t('workers.mac')}
              name="mac"
              value={form.values.mac}
              onChange={form.update('mac')}
              placeholder={t('workers.macPlaceholder')}
            />
            <Input
              label={t('workers.windowsIso')}
              name="windows_iso"
              value={form.values.windows_iso}
              onChange={form.update('windows_iso')}
              placeholder={t('workers.windowsIsoPlaceholder')}
            />
          </div>

          {createError && <p className="create-error">{createError}</p>}

          <Button type="submit" disabled={creating}>
            {creating ? t('workers.creating') : t('workers.createBtn')}
          </Button>
        </form>
      )}

      {batchCreateMode && (
        <form className="create-form" onSubmit={handleBatchCreateWorkers}>
          <div className="create-form-title">{t('workers.batchCreate.title')}</div>
          <p className="create-hint">{t('workers.registerHint')}</p>

          <div className="create-form-grid">
            <Input
              label={t('workers.batchCreate.count')}
              name="count"
              value={batchCreateForm.count}
              onChange={(e) => setBatchCreateForm((p) => ({ ...p, count: e.target.value }))}
              placeholder={t('workers.batchCreate.countPlaceholder')}
              required
            />
            <Input
              label={t('workers.batchCreate.namePrefix')}
              name="name_prefix"
              value={batchCreateForm.name_prefix}
              onChange={(e) => setBatchCreateForm((p) => ({ ...p, name_prefix: e.target.value }))}
              placeholder={t('workers.batchCreate.namePrefixPlaceholder')}
              required
            />
          </div>
          <div className="create-form-grid">
            <div className="field">
              <label className="field-label">{t('workers.batchCreate.macs')}</label>
              <textarea
                className="batch-create-macs"
                value={batchCreateForm.macs}
                onChange={(e) => setBatchCreateForm((p) => ({ ...p, macs: e.target.value }))}
                placeholder={t('workers.batchCreate.macsPlaceholder')}
                rows={5}
              />
              <p className="batch-hint">{t('workers.batchCreate.macsHint')}</p>
            </div>
          </div>

          {bcError && <p className="create-error">{bcError}</p>}

          <Button type="submit" disabled={bcSubmitting}>
            {bcSubmitting ? t('workers.batchCreate.creating') : t('workers.batchCreate.create')}
          </Button>

          {bcResult && (
            <div className="batch-result">
              <div className="batch-result-title">{t('workers.batchCreate.resultTitle')}</div>
              <div className="batch-result-stats">
                <span className="br-ok">{t('workers.batchCreate.okCount', { n: bcResult.succeeded.length })}</span>
                <span className="br-skip">{t('workers.batchCreate.skipCount', { n: bcResult.skipped.length })}</span>
                <span className="br-fail">{t('workers.batchCreate.failCount', { n: bcResult.failed.length })}</span>
              </div>
              {bcResult.skipped.length > 0 && (
                <ul className="batch-result-list">
                  {bcResult.skipped.map((s) => (
                    <li key={s.worker_id}>
                      <b>{s.worker_id}</b>: {s.reason}
                    </li>
                  ))}
                </ul>
              )}
              {bcResult.failed.length > 0 && (
                <ul className="batch-result-list">
                  {bcResult.failed.map((f) => (
                    <li key={f.worker_id}>
                      <b>{f.worker_id}</b>: {f.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </form>
      )}

      <div className={batchMode || deleteMode ? 'workers-batch-layout' : ''}>
        {deleteMode && (
          <aside className="batch-sidebar batch-sidebar-left">
            <div className="batch-sidebar-title">{t('workers.bulkDelete.title')}</div>
            <p className="batch-sidebar-count">
              {t('workers.bulkDelete.selected', { count: selected.length })}
            </p>
            <p className="batch-hint">{t('workers.bulkDelete.hint')}</p>
            <p className="batch-hint">{t('workers.batch.rangeHint')}</p>

            <ConfirmAction
              trigger={
                <Button variant="danger" disabled={selected.length === 0}>
                  {deleting ? t('workers.bulkDelete.deleting') : t('workers.bulkDelete.delete')}
                </Button>
              }
              message={t('workers.bulkDelete.confirm', { count: selected.length })}
              onConfirm={(extra) => handleBatchDelete(extra)}
              extraFields={[
                { name: 'delete_disk', label: t('workerDetail.deleteDisk') },
                { name: 'ignore_missing', label: t('workerDetail.ignoreMissing') },
              ]}
            />
            {deleteError && <p className="batch-error">{deleteError}</p>}
            {deleteResult && (
              <div className="batch-result">
                <div className="batch-result-title">{t('workers.bulkDelete.result')}</div>
                <div className="batch-result-stats">
                  <span className="br-ok">
                    {t('workers.batch.okCount', { n: deleteResult.succeeded.length })}
                  </span>
                  <span className="br-fail">
                    {t('workers.batch.failCount', { n: deleteResult.failed.length })}
                  </span>
                </div>
                {deleteResult.failed.length > 0 && (
                  <ul className="batch-result-list">
                    {deleteResult.failed.map((f) => (
                      <li key={f.worker_id}>
                        <b>{f.worker_id}</b>: {f.error}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </aside>
        )}

        {batchMode && (
          <aside className="batch-sidebar batch-sidebar-left">
            <div className="batch-sidebar-title">{t('workers.batch.paramsTitle')}</div>
            <p className="batch-sidebar-count">
              {t('workers.batch.selected', { count: selected.length })}
            </p>
            <p className="batch-hint">{t('workers.batch.hasDiskHint')}</p>
            <p className="batch-hint">{t('workers.batch.autoDefaultHint')}</p>
            <p className="batch-hint">{t('workers.batch.rangeHint')}</p>

            <form className="batch-form" onSubmit={handleBatchCreate}>
              <Select
                label={t('workers.os')}
                name="os"
                value={batchForm.os}
                onChange={(e) => setBatchForm((prev) => ({ ...prev, os: e.target.value }))}
                options={OS_OPTIONS}
              />
              <Select
                label={t('workers.diskType')}
                name="type"
                value={batchForm.type}
                onChange={(e) => setBatchForm((prev) => ({ ...prev, type: e.target.value }))}
                options={DISK_TYPE_OPTIONS}
              />
              {batchForm.type === 'master' ? (
                <>
                  <Select
                    label={t('workers.masterName')}
                    name="disk_name"
                    value={batchForm.master}
                    onChange={handleMasterSelect}
                    options={masterOptions}
                    placeholder={masterOptions.length === 0 ? t('workers.noMasters') : t('workers.masterSelectPlaceholder')}
                    required
                  />
                  {masterOptions.length > 0 && (
                    <p className="batch-hint">{t('workers.batch.spreadMasterHint')}</p>
                  )}
                </>
              ) : (
                <Input
                  label={t('workers.diskSize')}
                  name="disk_size"
                  value={batchForm.size}
                  onChange={(e) => setBatchForm((prev) => ({ ...prev, size: e.target.value }))}
                  placeholder={t('workers.diskSizePlaceholder')}
                  required
                />
              )}

              {batchError && <p className="batch-error">{batchError}</p>}

              <Button type="submit" disabled={submitting}>
                {submitting ? t('workers.batch.creating') : t('workers.batch.create')}
              </Button>
            </form>

            {batchResult && (
              <div className="batch-result">
                <div className="batch-result-title">{t('workers.batch.resultTitle')}</div>
                <div className="batch-result-stats">
                  <span className="br-ok">
                    {t('workers.batch.okCount', { n: batchResult.succeeded.length })}
                  </span>
                  <span className="br-skip">
                    {t('workers.batch.skipCount', { n: batchResult.skipped.length })}
                  </span>
                  <span className="br-fail">
                    {t('workers.batch.failCount', { n: batchResult.failed.length })}
                  </span>
                </div>
                {batchResult.failed.length > 0 && (
                  <ul className="batch-result-list">
                    {batchResult.failed.map((f) => (
                      <li key={f.worker_id}>
                        <b>{f.worker_id}</b>: {f.error}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </aside>
        )}

        <div className="workers-main">
          <div className="workers-toolbar">
            <input
              className="workers-filter"
              placeholder={t('workers.filter')}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <span className="workers-count">
              {t('workers.count', { count: filtered.length })}
            </span>
            <Button variant="ghost" onClick={toggleGuide}>
              {t('workers.guide.btn')}
            </Button>
          </div>

          {filtered.length === 0 ? (
            <EmptyState message={filter ? t('workers.noMatch') : t('workers.noWorkers')} />
          ) : (
            <div className="workers-list">
              <div className={`workers-header ${batchMode || deleteMode ? 'workers-header-batch' : ''}`}>
                {(batchMode || deleteMode) && <span className="wh-check" />}
                <span className="wh-id">{t('workers.id')}</span>
                <span className="wh-host">{t('workers.hostname')}</span>
                <span className="wh-bound">{t('workers.bound')}</span>
                <span className="wh-os">{t('workers.os')}</span>
                <span className="wh-state">{t('workers.state')}</span>
                {batchMode && <span className="wh-assign">{t('workers.batch.nodesTitle')}</span>}
              </div>
              {filtered.map((w) => (
                <Link
                  key={w.worker_id}
                  to={`/workers/${w.worker_id}`}
                  className={`workers-row ${batchMode || deleteMode ? 'wr-batch' : ''} ${batchMode && hasDisk(w) ? 'wr-has-disk' : ''}`}
                  onDragOver={batchMode ? (e) => e.preventDefault() : undefined}
                  onDrop={batchMode ? handleDrop(w) : undefined}
                >
                  {(batchMode || deleteMode) && (
                    <span
                      className="wr-check"
                      title={t('workers.batch.rangeHint')}
                      onClick={(e) => handleCheck(e, w)}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(w.worker_id)}
                        readOnly
                      />
                    </span>
                  )}
                  <span className="wr-id">{w.worker_id}</span>
                  <span className="wr-host">{w.hostname}</span>
                  <span className="wr-bound">
                    <span className="wr-bound-mac">{w.bound_device || '—'}</span>
                    <Badge>{w.readiness || 'idle'}</Badge>
                  </span>
                  <span className="wr-os">{(w.disks || []).map((d) => d.os).join(', ') || '—'}</span>
                  <span className="wr-state">
                    <Badge>{w.state || 'unknown'}</Badge>
                  </span>
                  {batchMode && (
                    <span className="wr-assign">
                      {assign[w.worker_id] && (
                        <>
                          <span className="wr-assign-tag">{assign[w.worker_id]}</span>
                          <button
                            className="wr-assign-clear"
                            title={t('workers.batch.unassign')}
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setAssign((prev) => {
                                const next = { ...prev }
                                delete next[w.worker_id]
                                return next
                              })
                            }}
                          >
                            ×
                          </button>
                        </>
                      )}
                    </span>
                  )}
                </Link>
              ))}
            </div>
          )}
        </div>

        {batchMode && (
          <aside className="batch-sidebar batch-sidebar-right">
            <div className="batch-sidebar-title">{t('workers.batch.nodesTitle')}</div>
            <p className="batch-hint">{t('workers.batch.dragHint')}</p>
            {storageAgents.length === 0 ? (
              <p className="batch-empty">{t('workers.batch.noNodes')}</p>
            ) : (
              <>
                {storageAgents.map((a) => (
                <div
                  key={a.id}
                  className={`storage-tag ${dragAgent === a.id ? 'storage-tag-dragging' : ''}`}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('text/plain', a.id)
                    setDragAgent(a.id)
                  }}
                  onDragEnd={() => setDragAgent(null)}
                >
                  <div className="storage-tag-head">
                    <span className="storage-tag-name">{a.id}</span>
                    <span className="storage-tag-count">
                      {assignedCount(a.id)} {t('workers.batch.assigned')}
                    </span>
                  </div>
                  {a.storager_ip && (
                    <div className="storage-tag-addr">{a.storager_ip}</div>
                  )}
                  <div className="storage-tag-actions">
                    <label className="storage-tag-spread">
                      <input
                        type="checkbox"
                        checked={spreadIds.includes(a.id)}
                        onChange={() => handleToggleSpread(a.id)}
                      />
                      {t('workers.batch.spreadJoin')}
                    </label>
                    <Button
                      variant="ghost"
                      className="storage-tag-takeover"
                      disabled={selected.length === 0}
                      onClick={() => handleTakeover(a.id)}
                    >
                      {t('workers.batch.takeover')}
                    </Button>
                  </div>
                </div>
              ))}
              <div className="spread-bar">
                <Button
                  variant="primary"
                  className="spread-btn"
                  disabled={selected.length === 0 || spreadIds.length < 2}
                  onClick={handleSpread}
                >
                  {t('workers.batch.spread')}
                </Button>
                <p className="batch-hint">{t('workers.batch.spreadHint')}</p>
              </div>
              </>
            )}
          </aside>
        )}
      </div>

      {guideOpen && (
        <div className="guide-overlay" onClick={toggleGuide}>
          <div className="guide-panel" onClick={(e) => e.stopPropagation()}>
            <div className="guide-panel-title">{t('workers.guide.title')}</div>
            {[
              ['headerTitle', 'headerBody'],
              ['filterTitle', 'filterBody'],
              ['columnsTitle', 'columnsBody'],
              ['rowTitle', 'rowBody'],
            ].map(([titleKey, bodyKey]) => (
              <div className="guide-section" key={titleKey}>
                <div className="guide-section-title">{t(`workers.guide.${titleKey}`)}</div>
                <p className="guide-section-body">{t(`workers.guide.${bodyKey}`)}</p>
              </div>
            ))}
            <div className="guide-actions">
              <Button variant="primary" onClick={toggleGuide}>
                {t('workers.guide.close')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
