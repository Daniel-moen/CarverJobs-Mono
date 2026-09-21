/** Shown on legal pages; override with VITE_SUPPORT_EMAIL when needed. */
export const supportEmail =
  typeof import.meta !== 'undefined' && import.meta.env?.VITE_SUPPORT_EMAIL
    ? String(import.meta.env.VITE_SUPPORT_EMAIL)
    : 'support@jobcarver.co'

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

/**
 * Free match runs granted at signup. Single source of truth for marketing
 * copy — the number changed once already (2 → 5 on 3 Aug 2026) and the old
 * value survived in five different hand-written strings. Import this instead
 * of typing a digit.
 */
export const FREE_MATCH_RUNS = 5

/**
 * Roughly how many live yacht roles the matcher scans. Deliberately a
 * rounded "at least" figure so it stays honest as the board moves.
 */
export const LIVE_JOBS_BLURB = '250+ live yacht jobs'

/**
 * Source tags appended to every wa.me prefill so the WhatsApp backend can
 * attribute a signup to the surface that produced it. The tag is always the
 * trailing token of the prefilled message, separated by a space.
 *
 * Keep these strings byte-stable — the backend matches on them exactly.
 */
export const WA_TAGS = {
  /** Anything on the small-screen marketing page (nav, hero, finale). */
  mobileHero: '· m-hero',
  /** The sticky bottom CTA bar. */
  sticky: '· sticky',
  /** Pricing page + the shared token-packs section. */
  pricing: '· pricing',
  /** Anything on the desktop landing page. */
  hero: '· hero',
  /** CTAs inside a server-rendered SEO article. */
  article: '· article',
}

/** The standard "start matching" prefill, untagged. */
export const WA_START_MESSAGE = "Hi Carver — I'd like to start matching to yacht roles."

/**
 * Build a source-tagged prefill.
 * @param {string} tag one of WA_TAGS
 * @param {string} [message] base text; defaults to the start-matching prefill
 */
export function waMessage(tag, message = WA_START_MESSAGE) {
  return tag ? `${message} ${tag}` : message
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
