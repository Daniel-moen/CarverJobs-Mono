/** Shown on legal pages; override with VITE_SUPPORT_EMAIL in production. */
export const supportEmail =
  typeof import.meta !== 'undefined' && import.meta.env?.VITE_SUPPORT_EMAIL
    ? String(import.meta.env.VITE_SUPPORT_EMAIL)
    : 'support@example.com'

/**
 * WhatsApp control channel. Crew can run every Carver function over text:
 * `match`, `apply <n>`, `jobs <role>`, `status`, `cv`, `pause`, etc.
 *
 * Override VITE_WHATSAPP_NUMBER in production with the live business number
 * in E.164 format **without** the leading `+` (e.g. 447000000000).
 * The placeholder below renders the UI but `wa.me/` links won't open until
 * you swap it for the real number — keep it short to make it obvious.
 */
const _waRaw = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_WHATSAPP_NUMBER)
  ? String(import.meta.env.VITE_WHATSAPP_NUMBER).replace(/[^0-9]/g, '')
  : '27688516141'

export const whatsapp = {
  /** E.164 digits, no plus. Used to build wa.me/ links. */
  number: _waRaw,
  /**
   * Pretty display, e.g. "+27 68 851 6141".
   * Formats SA mobile numbers nicely; falls back to a sane default for others.
   */
  display: _waRaw
    ? (_waRaw.startsWith('27') && _waRaw.length === 11
        ? '+27 ' + _waRaw.slice(2, 4) + ' ' + _waRaw.slice(4, 7) + ' ' + _waRaw.slice(7)
        : '+' + _waRaw.replace(/^(\d{1,3})(\d{3,4})(\d+)$/, '$1 $2 $3'))
    : '',
  /** Build a wa.me link with an optional pre-filled message. */
  link(message = '') {
    const base = `https://wa.me/${_waRaw}`
    if (!message) return base
    return `${base}?text=${encodeURIComponent(message)}`
  },
  /** True only when a real number is configured (not the obvious placeholder). */
  configured: _waRaw !== '447000000000' && _waRaw.length >= 8,
}

export const site = {
  name: 'CARVER v3',
  tagline: 'Automated superyacht job applications.',
  description:
    'CARVER helps crew discover, match, and auto-apply to superyacht opportunities with a streamlined workflow.',
  nav: [
    { key: 'auto-apply', label: 'Auto Apply' },
    { key: 'job-board', label: 'Job Board' },
    { key: 'profile', label: 'Profile' },
    { key: 'status', label: 'Status' },
    { key: 'subscription', label: 'Buy Tokens' },
    { key: 'dashboard', label: 'Dashboard', adminOnly: true },
    { key: 'admin-job-ingest', label: 'Job Ingest', adminOnly: true },
  ],
}
