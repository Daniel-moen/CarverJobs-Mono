import { API_BASE_URL, apiFetch } from './api'

export const DEFAULT_TOKEN_PRICE = '11.00'
export const DEFAULT_TOKEN_PACKAGES = [
  { tokens: 5, price: '65.00', label: 'Starter', badge: null, highlight: false, price_per_token: '13.00' },
  { tokens: 20, price: '220.00', label: 'Standard', badge: 'Most Popular', highlight: false, price_per_token: '11.00' },
  { tokens: 50, price: '600.00', label: 'Plus', badge: null, highlight: false, price_per_token: '12.00' },
  { tokens: 75, price: '675.00', label: 'Premium', badge: 'Best Value', highlight: true, price_per_token: '9.00' },
]

export const DEFAULT_FIRST_PURCHASE_BONUS = 5

export function defaultTokenPackages() {
  return DEFAULT_TOKEN_PACKAGES.map((pkg) => ({ ...pkg }))
}

// Savings vs the most expensive per-token rate in the lineup (the Starter
// rate), so bigger packs can show "Save RX" and a strikethrough anchor price.
export function packSavings(pkg, packages) {
  const rate = (p) => parseFloat(p.price_per_token || parseFloat(p.price) / p.tokens)
  const baseRate = Math.max(...packages.map(rate).filter((r) => !isNaN(r)))
  if (!baseRate || !pkg.tokens) return null
  const anchor = Math.round(baseRate * pkg.tokens)
  const savings = Math.round(anchor - parseFloat(pkg.price))
  if (!(savings >= 5)) return null
  return { anchor: String(anchor), savings: String(savings) }
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
