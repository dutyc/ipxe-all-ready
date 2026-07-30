import './Badge.css'

const VARIANT_MAP = {
  ok: 'badge-ok',
  ready: 'badge-ok',
  healthy: 'badge-ok',
  error: 'badge-error',
  installing: 'badge-warn',
  started: 'badge-warn',
  failed: 'badge-error',
}

export default function Badge({ children, variant = 'default' }) {
  const cls = VARIANT_MAP[children?.toLowerCase()] || VARIANT_MAP[variant] || 'badge-default'
  return <span className={`badge ${cls}`}>{children ?? variant}</span>
}
