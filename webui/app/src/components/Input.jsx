import './Input.css'

export default function Input({ label, value, onChange, placeholder, type = 'text', required, disabled, error, name, style }) {
  return (
    <div className="field" style={style}>
      {label && (
        <label className="field-label" htmlFor={name}>
          {label}
          {required && <span className="field-required"> *</span>}
        </label>
      )}
      <input
        id={name}
        name={name}
        type={type}
        className={`field-input${error ? ' field-input-error' : ''}`}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        disabled={disabled}
        autoComplete="off"
      />
      {error && <span className="field-error">{error}</span>}
    </div>
  )
}
