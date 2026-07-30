import { createContext, useContext, useState, useCallback } from 'react'
import zh from './zh-CN'
import en from './en-US'

const LOCALE_MAP = { 'zh-CN': zh, 'en-US': en }
const STORAGE_KEY = 'cp_locale'

function detectLocale() {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && LOCALE_MAP[stored]) return stored
  const nav = navigator.language || ''
  if (nav.startsWith('zh')) return 'zh-CN'
  return 'en-US'
}

function resolve(path, obj) {
  return path.split('.').reduce((o, k) => (o || {})[k], obj)
}

const I18nContext = createContext()

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(detectLocale)

  const setLocale = useCallback((l) => {
    setLocaleState(l)
    localStorage.setItem(STORAGE_KEY, l)
  }, [])

  const t = useCallback(
    (path, vars) => {
      const bundles = LOCALE_MAP[locale] || en
      let value = resolve(path, bundles)
      if (value === undefined) {
        value = resolve(path, en)
      }
      if (value === undefined) return path
      if (vars && typeof value === 'string') {
        return value.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`))
      }
      return value
    },
    [locale]
  )

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
