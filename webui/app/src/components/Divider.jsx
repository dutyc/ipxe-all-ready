import './Divider.css'

export default function Divider({ children }) {
  return (
    <div className="divider">
      <span className="divider-text">{children}</span>
    </div>
  )
}
