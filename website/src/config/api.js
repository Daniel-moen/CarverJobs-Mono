export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3001'

const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

let _csrfToken = ''
let _seedingPromise = null

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
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = { ...(options.headers ?? {}) }

  if (!SAFE_METHODS.has(method) && !_csrfToken) {
    await _seedCsrfToken()
  }

  if (!SAFE_METHODS.has(method) && _csrfToken) {
    headers[CSRF_HEADER] = _csrfToken
  }

  const response = await fetch(url, { credentials: 'include', ...options, headers })

  const freshToken = response.headers.get(CSRF_HEADER)
  if (freshToken) _csrfToken = freshToken

  return response
}
