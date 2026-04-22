export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3001'

const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const CSRF_EXEMPT_PATHS = ['/auth/login', '/auth/google', '/auth/signup', '/auth/waitlist']

let _csrfToken = ''
/** In-flight or last single-flight GET /auth/providers (CSRF + Google config). */
let _providersBootstrapPromise = null
let _lastUnauthorizedEventMs = 0

let _waSessionToken = ''
export function setWaSessionToken(token) { _waSessionToken = token }
export function getWaSessionToken() { return _waSessionToken }

/**
 * One network GET /auth/providers at a time: sets CSRF from response headers
 * and returns parsed JSON (or null). Used by App bootstrap and CSRF seeding
 * so a racing POST does not duplicate the same request.
 */
export async function getAuthProviders() {
  if (_providersBootstrapPromise) return _providersBootstrapPromise
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 4000)
  _providersBootstrapPromise = (async () => {
    try {
      const r = await fetch(`${API_BASE_URL}/auth/providers`, {
        credentials: 'include',
        signal: controller.signal,
      })
      const t = r.headers.get(CSRF_HEADER)
      if (t) _csrfToken = t
      const json = r.ok ? await r.json().catch(() => null) : null
      return { ok: r.ok, json }
    } catch {
      return { ok: false, json: null }
    } finally {
      clearTimeout(timer)
      _providersBootstrapPromise = null
    }
  })()
  return _providersBootstrapPromise
}

async function _seedCsrfToken() {
  if (_csrfToken) return
  await getAuthProviders()
}

export async function apiFetch(url, options = {}) {
  const { skipAuthHandling = false, timeoutMs = 0, ...fetchOptions } = options
  const method = (fetchOptions.method ?? 'GET').toUpperCase()
  const headers = { ...(fetchOptions.headers ?? {}) }

  const isCsrfExempt = CSRF_EXEMPT_PATHS.some((p) => url.includes(p))

  if (!SAFE_METHODS.has(method) && !_csrfToken && !isCsrfExempt) {
    await _seedCsrfToken()
  }

  if (!SAFE_METHODS.has(method) && _csrfToken) {
    headers[CSRF_HEADER] = _csrfToken
  }

  if (_waSessionToken && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${_waSessionToken}`
  }

  let signal = fetchOptions.signal
  if (timeoutMs > 0 && typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    const timeoutSignal = AbortSignal.timeout(timeoutMs)
    signal = signal && typeof AbortSignal.any === 'function'
      ? AbortSignal.any([signal, timeoutSignal])
      : (signal ?? timeoutSignal)
  }

  const response = await fetch(url, { credentials: 'include', ...fetchOptions, headers, signal })

  const freshToken = response.headers.get(CSRF_HEADER)
  if (freshToken) _csrfToken = freshToken

  if (!skipAuthHandling && response.status === 401 && typeof window !== 'undefined') {
    const now = Date.now()
    if (now - _lastUnauthorizedEventMs > 1500) {
      _lastUnauthorizedEventMs = now
      window.dispatchEvent(new CustomEvent('carver:unauthorized'))
    }
  }

  return response
}
