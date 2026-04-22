import posthog from 'posthog-js'

// ── PostHog product analytics ─────────────────────────────────────────────────
// Thin wrapper around posthog-js that stays inert unless a project key is
// provided via env. Project (publishable) keys are safe to ship to the browser
// — but we still load the key from env so it can be swapped per environment
// and kept out of the repo. Defaults are chosen to minimise PII exposure:
//   • session recording is OFF unless explicitly enabled
//   • we control pageview capture manually (SPA routing)
//   • Do-Not-Track is respected
//   • only user id + role are attached on identify; no email by default
// ──────────────────────────────────────────────────────────────────────────────

const KEY = import.meta.env.VITE_POSTHOG_KEY
const HOST = import.meta.env.VITE_POSTHOG_HOST || 'https://us.i.posthog.com'
const SESSION_RECORDING =
  String(import.meta.env.VITE_POSTHOG_SESSION_RECORDING ?? 'false').toLowerCase() === 'true'

let _ready = false

export function initPostHog() {
  if (_ready) return
  if (!KEY) {
    if (typeof window !== 'undefined') window.__posthog_status = 'no_key'
    return
  }
  try {
    posthog.init(KEY, {
      api_host: HOST,
      capture_pageview: false,
      capture_pageleave: true,
      autocapture: true,
      persistence: 'localStorage+cookie',
      disable_session_recording: !SESSION_RECORDING,
      // respect_dnt intentionally left off: Brave/Safari/Firefox-strict send
      // DNT by default and would silently drop *everything* — producing the
      // "no events in PostHog" experience. PostHog's own opt-out UI can still
      // be wired later if we need per-user consent.
      mask_all_text: !SESSION_RECORDING,
      mask_all_element_attributes: !SESSION_RECORDING,
      loaded: (ph) => {
        if (typeof window !== 'undefined') {
          window.__posthog = ph
          window.__posthog_status = 'ready'
        }
      },
    })
    _ready = true
  } catch (err) {
    _ready = false
    if (typeof window !== 'undefined') window.__posthog_status = 'init_failed'
    // eslint-disable-next-line no-console
    console.warn('[posthog] init failed', err)
  }
}

export function isReady() {
  return _ready
}

export function capture(event, props = {}) {
  if (!_ready) return
  try { posthog.capture(event, props) } catch { /* ignore */ }
}

export function capturePageView(page) {
  if (!_ready) return
  try {
    posthog.capture('$pageview', {
      page,
      $current_url: window.location.href,
      path: window.location.pathname,
    })
  } catch { /* ignore */ }
}

export function identifyUser({ id, role, isSubscribed } = {}) {
  if (!_ready || !id) return
  try {
    posthog.identify(String(id), {
      role: role || 'unknown',
      is_subscribed: Boolean(isSubscribed),
    })
  } catch { /* ignore */ }
}

export function resetUser() {
  if (!_ready) return
  try { posthog.reset() } catch { /* ignore */ }
}

export { posthog }
