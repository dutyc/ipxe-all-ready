import { NavLink, Outlet } from 'react-router-dom'
import { useI18n } from '../i18n'
import './Layout.css'

export default function Layout() {
  const { t, locale, setLocale } = useI18n()

  const NAV_ITEMS = [
    { to: '/', label: t('nav.dashboard'), exact: true },
    { to: '/workers', label: t('nav.workers') },
    { to: '/devices', label: t('nav.devices') },
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
          </div>
        </div>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
