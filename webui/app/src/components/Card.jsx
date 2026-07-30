import './Card.css'

export default function Card({ children, className = '', hover = false, onClick, style }) {
  return (
    <div
      className={`card${hover ? ' card-hover' : ''} ${className}`}
      onClick={onClick}
      style={style}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  )
}
