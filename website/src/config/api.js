export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3001'

const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

let _csrfToken = ''
let _seedingPromise = null
let _lastUnauthorizedEventMs = 0

function debugLog(payload) {
  if (typeof window === 'undefined') return
  const host = window.location.hostname
  if (host !== 'localhost' && host !== '127.0.0.1') return
  fetch('http://127.0.0.1:7242/ingest/6976b566-a777-43de-856a-ff88f09927de', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {})
}

/**
 * Seed the CSRF token by making a lightweight GET request.
 * Deduplicates concurrent calls so only one request is in-flight at a time.
 */
async function _seedCsrfToken() {
  if (_csrfToken) return
  if (_seedingPromise) return _seedingPromise
  _seedingPromise = fetch(`${API_BASE_URL}/auth/providers`, { credentials: 'include' })
    .then((r) => {
      const t = r.headers.get(CSRF_HEADER)
      if (t) _csrfToken = t
    })
    .catch(() => {})
    .finally(() => { _seedingPromise = null })
  return _seedingPromise
}

/**
 * Drop-in replacement for fetch() that automatically attaches the CSRF token
 * header on every mutating request and captures fresh tokens from responses.
 *
 * If no token is cached when a mutating request is about to be sent, it
 * fetches one first so the request never fails with "CSRF token missing".
 */
export async function apiFetch(url, options = {}) {
  const { skipAuthHandling = false, timeoutMs = 0, ...fetchOptions } = options
  const method = (fetchOptions.method ?? 'GET').toUpperCase()
  const headers = { ...(fetchOptions.headers ?? {}) }

  if (!SAFE_METHODS.has(method) && !_csrfToken) {
    await _seedCsrfToken()
  }

  if (!SAFE_METHODS.has(method) && _csrfToken) {
    headers[CSRF_HEADER] = _csrfToken
  }

  let signal = fetchOptions.signal
  if (timeoutMs > 0 && typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    const timeoutSignal = AbortSignal.timeout(timeoutMs)
    signal = signal && typeof AbortSignal.any === 'function'
      ? AbortSignal.any([signal, timeoutSignal])
      : (signal ?? timeoutSignal)
  }

  // #region agent log
  debugLog({ runId: 'initial', hypothesisId: 'H1', location: 'website/src/config/api.js:64', message: 'apiFetch request start', data: { url, method, skipAuthHandling, hasCsrfToken: Boolean(_csrfToken), timeoutMs }, timestamp: Date.now() })
  // #endregion
  let response
  try {
    response = await fetch(url, { credentials: 'include', ...fetchOptions, headers, signal })
  } catch (error) {
    // #region agent log
    debugLog({ runId: 'initial', hypothesisId: 'H2', location: 'website/src/config/api.js:71', message: 'apiFetch request threw', data: { url, method, timeoutMs, error: error instanceof Error ? error.message : String(error) }, timestamp: Date.now() })
    // #endregion
    throw error
  }

  // #region agent log
  debugLog({ runId: 'initial', hypothesisId: 'H3', location: 'website/src/config/api.js:77', message: 'apiFetch response received', data: { url, method, status: response.status, ok: response.ok, timeoutMs }, timestamp: Date.now() })
  // #endregion

  const freshToken = response.headers.get(CSRF_HEADER)
  if (freshToken) _csrfToken = freshToken

  if (!skipAuthHandling && response.status === 401 && typeof window !== 'undefined') {
    const now = Date.now()
    // Throttle to avoid a flood when multiple requests fail at once.
    if (now - _lastUnauthorizedEventMs > 1500) {
      _lastUnauthorizedEventMs = now
      window.dispatchEvent(new CustomEvent('carver:unauthorized'))
    }
  }

  return response
}
