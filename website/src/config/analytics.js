import { API_BASE_URL } from './api'
import { capture as mpCapture, capturePageView as mpCapturePageView } from './mixpanel'

const FLUSH_INTERVAL_MS = 15_000
const MAX_BATCH = 50
const ENDPOINT = `${API_BASE_URL}/admin/analytics`
/** `value` is a VARCHAR(200) server-side — truncate before it gets there. */
const MAX_VALUE_LEN = 190

let _queue = []
let _timer = null

function _now() {
  return new Date().toISOString()
}

function _getSessionId() {
  try {
    let id = sessionStorage.getItem('carver_analytics_sid')
    if (!id) {
      id = crypto.randomUUID().replace(/-/g, '').slice(0, 16)
      sessionStorage.setItem('carver_analytics_sid', id)
    }
    return id
  } catch {
    return 'unknown'
  }
}

const _sessionId = _getSessionId()

export function trackEvent(type, data = {}) {
  _queue.push({ type, session_id: _sessionId, ...data, ts: _now() })
  if (_queue.length >= MAX_BATCH) flush()
  mpCapture(type, data)
}

export function trackPageView(page) {
  _queue.push({ type: 'page_view', session_id: _sessionId, page, ts: _now() })
  if (_queue.length >= MAX_BATCH) flush()
  mpCapturePageView(page)
}

export function trackClick(label) {
  trackEvent('click', { label })
}

/**
 * Track a click that immediately hands the browser to another app or page
 * (wa.me deep links, Yoco redirects) and push the queue out *before* the
 * navigation happens.
 *
 * Why: a `target="_blank"` wa.me tap on Android/iOS switches apps without
 * ever firing `beforeunload`, and the 15s timer never gets another tick —
 * so the click was simply lost (19 recorded hero taps vs 25 real signups
 * in the 22 Sep 2026 review). `flush()` is beacon-based and returns
 * synchronously, so calling it in the handler is safe.
 */
export function trackOutboundClick(type, data = {}) {
  trackEvent(type, data)
  flush()
}

export function trackChat(direction) {
  trackEvent(direction === 'send' ? 'chat_send' : 'chat_receive')
}

export function trackFunnel(name, data = {}) {
  trackEvent('funnel', { label: name, ...data })
}

/**
 * Record a JS error.
 *
 * The ingest schema (app/routes/admin.py::AnalyticsEventSchema) forbids
 * extra keys, so the stack cannot travel in a field of its own — message
 * and the top stack frames share `value`, newlines collapsed so the row
 * stays greppable.
 *
 * @param {string} kind
 * @param {unknown} message
 * @param {{ page?: string, stack?: unknown }} [extra]
 */
export function trackError(kind, message, extra = {}) {
  const { stack, ...rest } = extra
  const head = String(message ?? '')
  const tail = stack ? ` @ ${String(stack).replace(/\s*\n\s*/g, ' | ')}` : ''
  trackEvent('js_error', {
    label: kind,
    value: `${head}${tail}`.slice(0, MAX_VALUE_LEN),
    ...rest,
  })
  flush()
}

export function trackSessionStart() {
  trackEvent('session_start', {
    value: String(window.innerWidth),
    label: window.innerWidth < 768 ? 'mobile' : 'desktop',
  })
}

/**
 * Ship the queued events.
 *
 * Synchronous on purpose: `navigator.sendBeacon` hands the request to the
 * browser process and returns immediately, so the batch survives an
 * app-switch, a tab close or a bfcache freeze. `fetch(..., keepalive)` is
 * the fallback for the handful of engines without sendBeacon.
 *
 * POST /admin/analytics is CSRF-exempt (app/csrf.py::_EXEMPT_PATHS), so no
 * token header is needed and we can skip apiFetch's async CSRF seeding —
 * which is what made the old implementation impossible to call inline.
 */
export function flush() {
  // Drain, not just one batch: on pagehide there is no second chance.
  while (_queue.length) _send(_queue.splice(0, MAX_BATCH))
}

/** @param {object[]} batch */
function _send(batch) {
  const payload = JSON.stringify({ events: batch })

  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      const blob = new Blob([payload], { type: 'application/json' })
      if (navigator.sendBeacon(ENDPOINT, blob)) return
    }
  } catch {
    /* fall through to fetch */
  }

  try {
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true,
      credentials: 'include',
    }).catch(() => {})
  } catch {
    /* Silently drop analytics on failure -- never block the user. */
  }
}

// Page-lifecycle flushes. `visibilitychange → hidden` is the only event a
// mobile browser reliably fires when the user leaves for another app;
// `pagehide` covers bfcache entry and real unloads. Both are registered at
// module load so they are in place even on routes that never call
// startAutoFlush() (e.g. the pre-launch public pages).
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
  window.addEventListener('pagehide', flush)
}

export function startAutoFlush() {
  if (_timer) return
  _timer = setInterval(flush, FLUSH_INTERVAL_MS)
}

export function stopAutoFlush() {
  if (_timer) {
    clearInterval(_timer)
    _timer = null
  }
  flush()
}
