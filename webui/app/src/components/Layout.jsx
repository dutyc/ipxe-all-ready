import { NavLink, Outlet } from 'react-router-dom'
import { hasToken, setToken, clearToken } from '../api/client'
import { useI18n } from '../i18n'
import { useState } from 'react'
import './Layout.css'

export default function Layout() {
  const { t, locale, setLocale } = useI18n()
  const [tokenInput, setTokenInput] = useState('')
  const [showToken, setShowToken] = useState(!hasToken())

  const handleSetToken = () => {
    if (tokenInput.trim()) {
      setToken(tokenInput.trim())
      setShowToken(false)
    }
  }

  const handleClearToken = () => {
    clearToken()
    setTokenInput('')
    setShowToken(true)
  }

  const NAV_ITEMS = [
    { to: '/', label: t('nav.dashboard'), exact: true },
    { to: '/workers', label: t('nav.workers') },
    { to: '/agents', label: t('nav.agents') },
    { to: '/operations', label: t('nav.operations') },
  ]

  return (
    <div className="layout">
      <nav className="nav">
        <div className="nav-inner">
          <span className="nav-brand">{t('nav.brand')}</span>
          <div className="nav-links">
            {NAV_ITEMS.map(({ to, label, exact }) => (
              <NavLink
                key={to}
                to={to}
                end={exact}
                className={({ isActive }) =>
                  `nav-link${isActive ? ' active' : ''}`
                }
              >
                {label}
              </NavLink>
            ))}
          </div>
          <div className="nav-right">
            <div className="lang-switch">
              <button
                className={`lang-btn${locale === 'zh-CN' ? ' lang-active' : ''}`}
                onClick={() => setLocale('zh-CN')}
              >
                中
              </button>
              <span className="lang-sep">/</span>
              <button
                className={`lang-btn${locale === 'en-US' ? ' lang-active' : ''}`}
                onClick={() => setLocale('en-US')}
              >
                EN
              </button>
            </div>
            <div className="nav-token">
              {showToken ? (
                <div className="token-form">
                  <input
                    type="password"
                    className="token-input"
                    placeholder={t('token.placeholder')}
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSetToken()}
                  />
                  <button className="token-btn" onClick={handleSetToken}>
                    {t('token.set')}
                  </button>
                </div>
              ) : (
                <button className="token-btn token-clear" onClick={handleClearToken}>
                  {t('token.clear')}
                </button>
              )}
            </div>
          </div>
        </div>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
