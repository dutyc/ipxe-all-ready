import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getWorkers, createWorker } from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Input from '../components/Input'
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
      (w.disk?.os || '').toLowerCase().includes(term)
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
          onClick={toggleCreate}
        >
          {showCreate ? t('workers.cancel') : t('workers.create')}
        </Button>
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
              required
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
              <span className="wr-os">{(w.disks || []).map((d) => d.os).join(', ') || '—'}</span>
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
