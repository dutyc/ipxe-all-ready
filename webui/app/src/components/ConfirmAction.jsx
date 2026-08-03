import { useState } from 'react'
import { useI18n } from '../i18n'
import Button from './Button'
import './ConfirmAction.css'

export default function ConfirmAction({
  trigger,
  message,
  onConfirm,
  extraFields,
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [extra, setExtra] = useState({})

  const handleConfirm = () => {
    onConfirm(extra)
    setOpen(false)
    setExtra({})
  }

  return (
    <div className="confirm-wrap">
      <span onClick={() => setOpen(true)} className="confirm-trigger">
        {trigger}
      </span>
      {open && (
        <div className="confirm-box">
          <p className="confirm-msg">{message}</p>
          {extraFields && (
            <div className="confirm-extra">
              {extraFields.map((f) => (
                <label key={f.name} className="confirm-check">
                  <input
                    type="checkbox"
                    checked={!!extra[f.name]}
                    onChange={(e) =>
                      setExtra((prev) => ({ ...prev, [f.name]: e.target.checked }))
                    }
                  />
                  <span>{f.label}</span>
                </label>
              ))}
            </div>
          )}
          <div className="confirm-actions">
            <Button variant="danger" onClick={handleConfirm}>
              {t('workerDetail.confirm')}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t('workers.cancel')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
