import './Button.css'

export default function Button({ children, onClick, variant = 'primary', className = '', disabled, type = 'button', style }) {
  return (
    <button
      type={type}
      className={`btn btn-${variant} ${className}`}
      onClick={onClick}
      disabled={disabled}
      style={style}
    >
      {children}
    </button>
  )
}
