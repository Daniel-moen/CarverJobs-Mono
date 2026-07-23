// ── Mixpanel product analytics ────────────────────────────────────────────────
// Inert when VITE_MIXPANEL_TOKEN is unset. Mirrors the dashboard snippet options:
// EU api_host, autocapture on, optional session replay sampling — all env-driven.
// SPA: manual Page View via capturePageView(); autocapture pageview stays off to avoid duplicates.
// Identify: only user id + role + subscription flag by default.
//
// mixpanel-browser (plus its session-replay recorder) is ~300 kB minified and
// was the largest module in the entry bundle. It is now loaded via dynamic
// import so first paint never waits on it; calls made before the SDK is ready
// are queued and flushed once init completes.

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

let _mp = null
let _ready = false
let _loading = false
/** Calls made before the SDK loads: [methodName, args]. */
let _queue = []

function _flushQueue() {
  const pending = _queue
  _queue = []
  for (const [method, args] of pending) {
    try { method(...args) } catch { /* ignore */ }
  }
}

export function initMixpanel() {
  if (_ready || _loading) return
  if (!TOKEN) {
    if (typeof window !== 'undefined') window.__mixpanel_status = 'no_token'
    return
  }
  _loading = true
  import('mixpanel-browser')
    .then(({ default: mixpanel }) => {
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
      _mp = mixpanel
      _ready = true
      if (typeof window !== 'undefined') {
        window.__mixpanel = mixpanel
        window.__mixpanel_status = 'ready'
      }
      _flushQueue()
    })
    .catch((err) => {
      _loading = false
      _queue = []
      if (typeof window !== 'undefined') window.__mixpanel_status = 'init_failed'
      // eslint-disable-next-line no-console
      console.warn('[mixpanel] init failed', err)
    })
}

export function isReady() {
  return _ready
}

/** Run fn now if the SDK is ready, otherwise queue it (only while loading). */
function _call(fn, args) {
  if (_ready) {
    try { fn(...args) } catch { /* ignore */ }
    return
  }
  if (_loading) _queue.push([fn, args])
}

export function capture(event, props = {}) {
  _call((e, p) => _mp.track(e, p), [event, props])
}

export function capturePageView(page) {
  _call((p, path, url) => _mp.track('Page View', { page: p, path, current_url: url }), [
    page,
    typeof window !== 'undefined' ? window.location.pathname : '',
    typeof window !== 'undefined' ? window.location.href : '',
  ])
}

export function identifyUser({ id, role, isSubscribed } = {}) {
  if (!id) return
  _call((uid, r, sub) => {
    _mp.identify(uid)
    _mp.people.set({ role: r, is_subscribed: sub })
  }, [String(id), role || 'unknown', Boolean(isSubscribed)])
}

export function resetUser() {
  if (!_ready) return
  try { _mp.reset() } catch { /* ignore */ }
}
