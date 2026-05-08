import mixpanel from 'mixpanel-browser'

// ── Mixpanel product analytics ────────────────────────────────────────────────
// Inert when VITE_MIXPANEL_TOKEN is unset. Mirrors the dashboard snippet options:
// EU api_host, autocapture on, optional session replay sampling — all env-driven.
// SPA: manual Page View via capturePageView(); autocapture pageview stays off to avoid duplicates.
// Identify: only user id + role + subscription flag by default.

const TOKEN = import.meta.env.VITE_MIXPANEL_TOKEN
const API_HOST = import.meta.env.VITE_MIXPANEL_API_HOST || 'https://api.mixpanel.com'

function envBool(name, fallback) {
  const raw = import.meta.env[name]
  if (raw === undefined || raw === '') return fallback
  return String(raw).toLowerCase() === 'true'
}

function envRecordPercent() {
  const raw = import.meta.env.VITE_MIXPANEL_SESSION_RECORD_PERCENT
  if (raw === undefined || raw === '') return 0
  const n = Number(raw)
  if (!Number.isFinite(n)) return 0
  return Math.min(100, Math.max(0, Math.round(n)))
}

let _ready = false

export function initMixpanel() {
  if (_ready) return
  if (!TOKEN) {
    if (typeof window !== 'undefined') window.__mixpanel_status = 'no_token'
    return
  }
  try {
    const autocaptureOn = envBool('VITE_MIXPANEL_AUTOCAPTURE', true)
    const recordPercent = envRecordPercent()

    mixpanel.init(TOKEN, {
      api_host: API_HOST,
      track_pageview: false,
      persistence: 'localStorage',
      autocapture: autocaptureOn
        ? {
            pageview: false,
            click: true,
            input: true,
            submit: true,
            scroll: true,
            rage_click: true,
            dead_click: true,
          }
        : false,
      record_sessions_percent: recordPercent,
      record_mask_all_text: true,
      record_mask_all_inputs: true,
    })
    _ready = true
    if (typeof window !== 'undefined') {
      window.__mixpanel = mixpanel
      window.__mixpanel_status = 'ready'
    }
  } catch (err) {
    _ready = false
    if (typeof window !== 'undefined') window.__mixpanel_status = 'init_failed'
    // eslint-disable-next-line no-console
    console.warn('[mixpanel] init failed', err)
  }
}

export function isReady() {
  return _ready
}

export function capture(event, props = {}) {
  if (!_ready) return
  try {
    mixpanel.track(event, props)
  } catch { /* ignore */ }
}

export function capturePageView(page) {
  if (!_ready) return
  try {
    mixpanel.track('Page View', {
      page,
      path: typeof window !== 'undefined' ? window.location.pathname : '',
      current_url: typeof window !== 'undefined' ? window.location.href : '',
    })
  } catch { /* ignore */ }
}

export function identifyUser({ id, role, isSubscribed } = {}) {
  if (!_ready || !id) return
  try {
    mixpanel.identify(String(id))
    mixpanel.people.set({
      role: role || 'unknown',
      is_subscribed: Boolean(isSubscribed),
    })
  } catch { /* ignore */ }
}

export function resetUser() {
  if (!_ready) return
  try {
    mixpanel.reset()
  } catch { /* ignore */ }
}

export { mixpanel }
