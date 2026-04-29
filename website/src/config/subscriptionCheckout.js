import { API_BASE_URL, apiFetch } from './api'

export const DEFAULT_TOKEN_PRICE = '10.00'
export const DEFAULT_TOKEN_PACKAGES = [
  { tokens: 10, price: '100.00' },
  { tokens: 20, price: '200.00' },
]

export function defaultTokenPackages() {
  return DEFAULT_TOKEN_PACKAGES.map((pkg) => ({ ...pkg }))
}

export function formatTokenPrice(amountStr) {
  const n = parseFloat(amountStr)
  if (isNaN(n)) return `R${amountStr}`
  return `R${Number.isInteger(n) ? n : n.toFixed(2)}`
}

export function readCheckoutReturnStatus() {
  const params = new URLSearchParams(window.location.search)
  const status = params.get('status')
  if (status !== 'success' && status !== 'cancelled' && status !== 'failed') return ''
  window.history.replaceState({}, '', window.location.pathname)
  return status
}

export async function loadSubscriptionStatus() {
  const res = await apiFetch(`${API_BASE_URL}/subscription/status`, {
    method: 'GET',
    credentials: 'include',
  })
  if (!res.ok) return null
  return res.json()
}

export async function startSubscriptionCheckout(tokens) {
  const response = await apiFetch(`${API_BASE_URL}/subscription/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ tokens }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    if (response.status === 403 && error.code === 'CRV-2006') {
      const retryResponse = await apiFetch(`${API_BASE_URL}/subscription/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ tokens }),
      })
      if (retryResponse.ok) return retryResponse.json()
      const retryError = await retryResponse.json().catch(() => ({}))
      throw new Error(retryError.detail || 'Could not start checkout. Please try again.')
    }
    throw new Error(error.detail || 'Could not start checkout. Please try again.')
  }
  return response.json()
}
