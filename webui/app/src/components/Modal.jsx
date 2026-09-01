import './Modal.css'

// 全局弹窗：遮罩固定定位，任何容器（overflow 裁剪/滚动侧边栏）都无法裁剪；
// 与 ConfirmAction 弹窗同构（overlay + box + 边框阴影），用于表单类交互
export default function Modal({ title, onClose, children, footer, width }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={width ? { width } : undefined} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button type="button" className="modal-close" onClick={onClose} aria-label="close">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  )
}
