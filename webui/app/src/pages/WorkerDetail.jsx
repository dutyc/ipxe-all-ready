import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { getWorker, getWorkerStatus, deleteWorker, bootVars } from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Divider from '../components/Divider'
import CodeBlock from '../components/CodeBlock'
import ConfirmAction from '../components/ConfirmAction'
import EmptyState from '../components/EmptyState'
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

        if (bv && Object.keys(bv).length > 0) {
          const lines = ['#!ipxe', `# boot vars for ${(w && w.hostname) || id}`]
          if (bv.base_iqn) lines.push(`set base-iqn ${bv.base_iqn}`)
          if (bv.iscsi_server) lines.push(`set iscsi-server ${bv.iscsi_server}`)
          if (bv.menu_default) lines.push(`set menu-default ${bv.menu_default}`)
          if (bv.menu_timeout !== undefined) lines.push(`set menu-timeout ${bv.menu_timeout}`)
          setBootVarsCode(lines.join('\n'))
        } else {
          setBootVarsCode('#!ipxe\n# no per-worker boot vars found')
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
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

  if (loading) return <p className="page-loading">{t('common.loading')}</p>
  if (error) return <p className="page-error">{error}</p>
  if (!worker) return <EmptyState message={t('workerDetail.notFoundMsg')} />

  const { disk, cd, mac } = worker

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
        <InfoRow label={t('workerDetail.os')} value={worker.os} />
        <InfoRow label={t('workerDetail.arch')} value={worker.arch} />
        <InfoRow label={t('workerDetail.state')} value={worker.state} />
      </Card>

      {/* Disk */}
      {disk && (
        <>
          <Divider>{t('workerDetail.disk')}</Divider>
          <Card className="detail-card">
            <InfoRow label={t('workerDetail.agent')} value={disk.agent} mono />
            <InfoRow label={t('workerDetail.iqn')} value={disk.iqn} mono />
            <InfoRow label={t('workerDetail.filename')} value={disk.filename} mono />
            <InfoRow label={t('workerDetail.backing')} value={disk.backing} mono />
            {disk.source && (
              <InfoRow
                label={t('workerDetail.source')}
                value={
                  disk.source.type === 'master'
                    ? `master: ${disk.source.name}`
                    : `empty: ${disk.source.size}`
                }
              />
            )}
          </Card>
        </>
      )}

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
          <InfoRow
            label={t('workerDetail.diskTarget')}
            value={status.actual?.disk?.exists ? t('workerDetail.exists') : t('workerDetail.notFound')}
          />
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
