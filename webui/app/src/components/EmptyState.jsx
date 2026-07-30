import './EmptyState.css'

export default function EmptyState({ message = 'No data found.' }) {
  return (
    <div className="empty-state">
      <p>{message}</p>
    </div>
  )
}
