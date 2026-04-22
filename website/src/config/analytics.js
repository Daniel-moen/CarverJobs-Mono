import { API_BASE_URL, apiFetch } from './api'
import { capture as phCapture, capturePageView as phCapturePageView } from './posthog'

const FLUSH_INTERVAL_MS = 15_000
const MAX_BATCH = 50

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
  phCapture(type, data)
}

export function trackPageView(page) {
  _queue.push({ type: 'page_view', session_id: _sessionId, page, ts: _now() })
  if (_queue.length >= MAX_BATCH) flush()
  phCapturePageView(page)
}

export function trackClick(label) {
  trackEvent('click', { label })
}

export function trackChat(direction) {
  trackEvent(direction === 'send' ? 'chat_send' : 'chat_receive')
}

export function trackFunnel(name, data = {}) {
  trackEvent('funnel', { label: name, ...data })
}

export function trackError(kind, message, extra = {}) {
  trackEvent('js_error', { label: kind, value: String(message ?? '').slice(0, 190), ...extra })
  flush()
}

export function trackSessionStart() {
  trackEvent('session_start', {
    value: String(window.innerWidth),
    label: window.innerWidth < 768 ? 'mobile' : 'desktop',
  })
}

export async function flush() {
  if (!_queue.length) return
  const batch = _queue.splice(0, MAX_BATCH)
  try {
    await apiFetch(`${API_BASE_URL}/admin/analytics`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: batch }),
    })
  } catch {
    /* Silently drop analytics on failure -- never block the user. */
  }
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
