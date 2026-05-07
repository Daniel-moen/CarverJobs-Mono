import mixpanel from 'mixpanel-browser'

// ── Mixpanel product analytics ────────────────────────────────────────────────
// Inert when VITE_MIXPANEL_TOKEN is unset. Manual pageviews for SPA routing.
// Identify sends only user id + role + subscription flag — no email by default.

const TOKEN = import.meta.env.VITE_MIXPANEL_TOKEN
const API_HOST = import.meta.env.VITE_MIXPANEL_API_HOST || 'https://api.mixpanel.com'

let _ready = false

export function initMixpanel() {
  if (_ready) return
  if (!TOKEN) {
    if (typeof window !== 'undefined') window.__mixpanel_status = 'no_token'
    return
  }
  try {
    mixpanel.init(TOKEN, {
      api_host: API_HOST,
      track_pageview: false,
      persistence: 'localStorage',
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
