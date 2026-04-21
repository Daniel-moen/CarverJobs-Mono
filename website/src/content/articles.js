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
export const articles = [
  {
    slug: 'superyacht-crew-cv-essentials',
    title: 'The superyacht crew CV: what actually gets you hired',
    description:
      'A captain-first guide to writing a superyacht CV that lands interviews — the fields that matter, the ones to cut, and how to present sea time.',
    date: '2026-03-18',
    readMinutes: 4,
    keywords: [
      'superyacht cv',
      'yacht crew cv',
      'superyacht jobs',
      'yacht crew hiring',
    ],
    body: [
      {
        type: 'p',
        text: 'Most superyacht CVs are rejected in under ten seconds. Captains and agencies skim for a tight set of signals, and everything else is noise. This short guide walks through what to keep, what to cut, and how to make sea time speak for itself.',
      },
      { type: 'h2', text: 'Lead with the facts a captain needs first' },
      {
        type: 'p',
        text: 'The top quarter of the page should answer three questions without scrolling: which role you are applying for, your most recent vessel with tonnage and length, and whether your STCW, ENG1 and passport are current. Anything else is context, not headline.',
      },
      { type: 'h2', text: 'Show sea time, not job titles' },
      {
        type: 'p',
        text: 'A junior stew who has done a full Med season and an Atlantic crossing is more compelling than one with a loftier title and no miles. List vessel name, length, gross tonnage, guest type (private or charter), itinerary and dates — in that order.',
      },
      { type: 'h2', text: 'Cut the things that do not help' },
      {
        type: 'ul',
        items: [
          'Generic objectives ("seeking a challenging role where I can grow").',
          'Skills lists that repeat what the role already implies.',
          'Photos that are not a plain, well-lit headshot on a neutral background.',
          'References listed inline — "available on request" is fine.',
        ],
      },
      { type: 'h2', text: 'How Carver uses your CV' },
      {
        type: 'p',
        text: 'When you upload a CV to Carver, we extract structured fields — certifications, sea time, role history — and match them against live vacancies as they land. A clean, well-structured CV means better matches and fewer manual edits later.',
      },
    ],
  },
  {
    slug: 'how-whatsapp-job-matching-works',
    title: 'How WhatsApp job matching works for yacht crew',
    description:
      'Carver runs the full superyacht job hunt over WhatsApp — profile, matching and applications. Here is exactly how the loop works, end to end.',
    date: '2026-04-02',
    readMinutes: 3,
    keywords: [
      'whatsapp yacht jobs',
      'yacht crew matching',
      'superyacht job application',
    ],
    body: [
      {
        type: 'p',
        text: 'Carver treats WhatsApp as the control channel for finding work. You do not install an app, you do not keep a browser tab open — you send a short message and the bot does the rest.',
      },
      { type: 'h2', text: 'The loop in five messages' },
      {
        type: 'ul',
        items: [
          '"hi" — creates your profile and asks for a CV.',
          '"match" — pulls every live role that fits your certifications and sea time.',
          '"apply 3" — submits an application for the third match.',
          '"status" — shows what you have applied for and where each one sits.',
          '"pause" — stops notifications for a week without deleting anything.',
        ],
      },
      { type: 'h2', text: 'Why it works better than a job board' },
      {
        type: 'p',
        text: 'Listings move fast in the yachting world. By the time a role is public on a job board, the captain usually has a shortlist. WhatsApp lets Carver notify you the moment something matches — often before the role is listed publicly at all.',
      },
      { type: 'h2', text: 'Privacy and control' },
      {
        type: 'p',
        text: 'Your profile is encrypted at rest and only shared with an agency or captain when you explicitly apply. You can type "delete me" at any time and your data is removed within 24 hours.',
      },
    ],
  },
  {
    slug: 'sea-season-hiring-timeline',
    title: 'When to apply for the Med and Caribbean seasons',
    description:
      'A month-by-month hiring timeline for superyacht crew — when captains start shortlisting, when interviews happen, and when dayworking pays off.',
    date: '2026-04-15',
    readMinutes: 3,
    keywords: [
      'med season yacht jobs',
      'caribbean yacht season',
      'yacht crew hiring timeline',
    ],
    body: [
      {
        type: 'p',
        text: 'Timing is half the job hunt. Apply too early and captains have not opened the budget yet; apply too late and the shortlist is closed. Here is the rough rhythm that holds across most years.',
      },
      { type: 'h2', text: 'Mediterranean season' },
      {
        type: 'ul',
        items: [
          'January–February: permanent shortlists form. Strong time for green crew to start messaging.',
          'March–April: dayworking in Antibes, Palma and Barcelona converts into full-season contracts.',
          'May: last-minute replacements. Worth staying visible even if you did not land a boat in April.',
        ],
      },
      { type: 'h2', text: 'Caribbean season' },
      {
        type: 'ul',
        items: [
          'August–September: permanent hires start as yachts plan the crossing.',
          'October–November: Fort Lauderdale and Antigua dockwalking.',
          'December: charter-week reliefs and rotational spots.',
        ],
      },
      { type: 'h2', text: 'Staying match-ready off-season' },
      {
        type: 'p',
        text: 'The boring answer is the right one: keep your documents current, your CV up to date, and your availability accurate. Carver will not match you to a role your ENG1 has expired for — and a stale profile is the fastest way to miss the season you were waiting for.',
      },
    ],
  },
]

/** @param {string} slug */
export function findArticle(slug) {
  return articles.find((a) => a.slug === slug) || null
}
