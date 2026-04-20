let currentTheme = 'dark'

function systemPrefersLight() {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches
  } catch {
    return false
  }
}

export function getTheme() {
  return currentTheme
}

export function applyTheme(theme) {
  const next = theme === 'light' ? 'light' : 'dark'
  currentTheme = next
  try {
    const root = document.documentElement
    root.classList.toggle('light', next === 'light')
    root.style.colorScheme = next
  } catch {
    /* SSR / no-DOM safe */
  }
}

export function initTheme() {
  let stored = null
  try { stored = localStorage.getItem('carver_theme') } catch { /* ignore */ }
  const initial = stored === 'light' || stored === 'dark'
    ? stored
    : (systemPrefersLight() ? 'light' : 'dark')
  applyTheme(initial)
  return initial
}

export function setTheme(theme) {
  const next = theme === 'light' ? 'light' : 'dark'
  applyTheme(next)
  try { localStorage.setItem('carver_theme', next) } catch { /* ignore */ }
  return next
}

export function toggleTheme() {
  return setTheme(currentTheme === 'light' ? 'dark' : 'light')
}
