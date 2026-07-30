import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getWorkers, createWorker } from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Input from '../components/Input'
import Select from '../components/Select'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import './Workers.css'

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

  const form = useForm({
    worker_id: '',
    mac: '',
    os: 'ubuntu',
    disk_type: 'empty',
    disk_name: '',
    disk_size: '40G',
    windows_iso: '',
  })

  const OS_OPTIONS = [
    { value: 'ubuntu', label: 'Ubuntu' },
    { value: 'debian', label: 'Debian' },
    { value: 'windows', label: 'Windows' },
  ]

  const DISK_TYPE_OPTIONS = [
    { value: 'empty', label: t('workers.empty') },
    { value: 'master', label: t('workers.master') },
  ]

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

  useEffect(() => {
    fetchWorkers()
  }, [fetchWorkers])

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    setCreateError(null)

    const disk =
      form.values.disk_type === 'master'
        ? { type: 'master', name: form.values.disk_name }
        : { type: 'empty', size: form.values.disk_size }

    const body = {
      worker_id: form.values.worker_id,
      mac: form.values.mac,
      os: form.values.os,
      disk,
    }

    if (form.values.os === 'windows' && form.values.windows_iso.trim()) {
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
      (w.os || '').toLowerCase().includes(term)
    )
  })

  if (loading) return <p className="page-loading">{t('common.loading')}</p>
  if (error) return <p className="page-error">{error}</p>

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{t('workers.title')}</h2>
        <Button
          variant={showCreate ? 'ghost' : 'primary'}
          onClick={() => {
            setShowCreate(!showCreate)
            setCreateError(null)
          }}
        >
          {showCreate ? t('workers.cancel') : t('workers.create')}
        </Button>
      </div>

      {showCreate && (
        <form className="create-form" onSubmit={handleCreate}>
          <div className="create-form-title">{t('workers.newWorker')}</div>

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
              required
            />
            <Select
              label={t('workers.os')}
              name="os"
              value={form.values.os}
              onChange={(e) => { form.set('os', e.target.value) }}
              options={OS_OPTIONS}
            />
            <Select
              label={t('workers.diskType')}
              name="disk_type"
              value={form.values.disk_type}
              onChange={(e) => { form.set('disk_type', e.target.value) }}
              options={DISK_TYPE_OPTIONS}
            />
            {form.values.disk_type === 'master' && (
              <Input
                label={t('workers.masterName')}
                name="disk_name"
                value={form.values.disk_name}
                onChange={form.update('disk_name')}
                placeholder={t('workers.masterNamePlaceholder')}
                required
              />
            )}
            {form.values.disk_type === 'empty' && (
              <Input
                label={t('workers.diskSize')}
                name="disk_size"
                value={form.values.disk_size}
                onChange={form.update('disk_size')}
                placeholder={t('workers.diskSizePlaceholder')}
                required
              />
            )}
            {form.values.os === 'windows' && (
              <Input
                label={t('workers.windowsIso')}
                name="windows_iso"
                value={form.values.windows_iso}
                onChange={form.update('windows_iso')}
                placeholder={t('workers.windowsIsoPlaceholder')}
              />
            )}
          </div>

          {createError && <p className="create-error">{createError}</p>}

          <Button type="submit" disabled={creating}>
            {creating ? t('workers.creating') : t('workers.createBtn')}
          </Button>
        </form>
      )}

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
      </div>

      {filtered.length === 0 ? (
        <EmptyState message={filter ? t('workers.noMatch') : t('workers.noWorkers')} />
      ) : (
        <div className="workers-list">
          <div className="workers-header">
            <span className="wh-id">{t('workers.id')}</span>
            <span className="wh-host">{t('workers.hostname')}</span>
            <span className="wh-os">{t('workers.os')}</span>
            <span className="wh-state">{t('workers.state')}</span>
          </div>
          {filtered.map((w) => (
            <Link
              key={w.worker_id}
              to={`/workers/${w.worker_id}`}
              className="workers-row"
            >
              <span className="wr-id">{w.worker_id}</span>
              <span className="wr-host">{w.hostname}</span>
              <span className="wr-os">{w.os}</span>
              <span className="wr-state">
                <Badge>{w.state || 'unknown'}</Badge>
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
