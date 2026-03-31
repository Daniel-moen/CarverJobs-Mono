export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3001'

const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const CSRF_EXEMPT_PATHS = ['/auth/login', '/auth/google', '/auth/signup', '/auth/waitlist']

let _csrfToken = ''
let _seedingPromise = null
let _lastUnauthorizedEventMs = 0

let _waSessionToken = ''
export function setWaSessionToken(token) { _waSessionToken = token }
export function getWaSessionToken() { return _waSessionToken }

async function _seedCsrfToken() {
  if (_csrfToken) return
  if (_seedingPromise) return _seedingPromise
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 4000)
  _seedingPromise = fetch(`${API_BASE_URL}/auth/providers`, {
    credentials: 'include',
    signal: controller.signal,
  })
    .then((r) => {
      const t = r.headers.get(CSRF_HEADER)
      if (t) _csrfToken = t
    })
    .catch(() => {})
    .finally(() => { clearTimeout(timer); _seedingPromise = null })
  return _seedingPromise
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
