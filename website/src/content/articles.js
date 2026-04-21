/**
 * Static SEO article content. Keep author-trusted only — these are rendered
 * as structured blocks (never as raw HTML) so we don't need to sanitise.
 *
 * To add a new article, append an entry with a URL-safe slug. Keep
 * `description` under ~160 characters so it works as a meta description.
 *
 * Block types:
 *   { type: 'p',  text: '...' }
 *   { type: 'h2', text: '...' }
 *   { type: 'ul', items: ['...', '...'] }
 */

/** @typedef {{ type: 'p'|'h2'|'ul', text?: string, items?: string[] }} Block */
/** @typedef {{
 *   slug: string,
 *   title: string,
 *   description: string,
 *   date: string,
 *   readMinutes: number,
 *   keywords: string[],
 *   body: Block[],
 * }} Article */

/** @type {Article[]} */
export const articles = []

/** @param {string} slug */
export function findArticle(slug) {
  return articles.find((a) => a.slug === slug) || null
}
