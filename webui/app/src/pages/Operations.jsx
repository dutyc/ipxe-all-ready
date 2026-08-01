import { useState, useEffect, useCallback } from 'react'
import { getOperations } from '../api/client'
import { useI18n } from '../i18n'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import './Operations.css'

export default function Operations() {
  const { t } = useI18n()
  const [entries, setEntries] = useState([])
  const [cursor, setCursor] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async (since = 0, append = false) => {
    setLoading(true)
    setError(null)
    try {
      const data = await getOperations(since, 50)
      const newEntries = data.entries || []
      const reversed = [...newEntries].reverse()
      if (append) {
        setEntries((prev) => [...reversed, ...prev])
      } else {
        setEntries(reversed)
      }
      const nextCursor = data.next_cursor ?? since + newEntries.length
      setCursor(nextCursor)
      setHasMore(newEntries.length === 50)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(0)
  }, [load])

  const loadMore = () => {
    if (cursor > 0) load(cursor, true)
  }

  const renderValue = (val) => {
    if (val === null || val === undefined) return '—'
    if (typeof val === 'object') return JSON.stringify(val)
    return String(val)
  }

  const EXCLUDE_KEYS = ['id', 'ts', 'op', 'status', 'client']

  return (
    <div>
      <h2 className="page-title">{t('operations.title')}</h2>

      {error && <p className="page-error">{error}</p>}

      {loading && entries.length === 0 ? (
        <p className="page-loading">{t('common.loading')}</p>
      ) : entries.length === 0 ? (
        <EmptyState message={t('operations.noOps')} />
      ) : (
        <div className="ops-list">
          {entries.map((op) => {
            const detailKeys = Object.keys(op).filter(
              (k) => !EXCLUDE_KEYS.includes(k)
            )
            return (
              <div key={op.id} className="ops-entry">
                <div className="ops-entry-header">
                  <span className="oe-id">#{op.id}</span>
                  <span className="oe-ts">{op.ts}</span>
                  <span className="oe-op">{op.op}</span>
                  <Badge>{op.status}</Badge>
                  <span className="oe-client">{op.client}</span>
                </div>
                {detailKeys.length > 0 && (
                  <div className="ops-entry-detail">
                    {detailKeys.map((k) => (
                      <span key={k} className="oed-item">
                        <span className="oed-key">{k}</span>
                        <span className="oed-val">{renderValue(op[k])}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {hasMore && entries.length > 0 && (
        <div className="ops-load-more">
          <Button variant="ghost" onClick={loadMore} disabled={loading}>
            {loading ? t('operations.loading') : t('operations.loadMore')}
          </Button>
          <span className="ops-cursor">cursor={cursor}</span>
        </div>
      )}
    </div>
  )
}
