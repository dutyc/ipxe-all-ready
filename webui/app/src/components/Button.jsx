import './Button.css'

export default function Button({ children, onClick, variant = 'primary', className = '', disabled, type = 'button', style, ...rest }) {
  return (
    <button
      type={type}
      className={`btn btn-${variant} ${className}`}
      onClick={onClick}
      disabled={disabled}
      style={style}
      {...rest}
    >
      {children}
    </button>
  )
}
