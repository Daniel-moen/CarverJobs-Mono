/** Shown on legal pages; override with VITE_SUPPORT_EMAIL in production. */
export const supportEmail =
  typeof import.meta !== 'undefined' && import.meta.env?.VITE_SUPPORT_EMAIL
    ? String(import.meta.env.VITE_SUPPORT_EMAIL)
    : 'support@example.com'

export const site = {
  name: 'CARVER v3',
  tagline: 'Automated superyacht job applications.',
  description:
    'CARVER helps crew discover, match, and auto-apply to superyacht opportunities with a streamlined workflow.',
  nav: [
    { key: 'auto-apply', label: 'Auto Apply', hideForAgency: true },
    { key: 'job-board', label: 'Job Board' },
    { key: 'profile', label: 'Profile', hideForAgency: true },
    { key: 'status', label: 'Status', hideForAgency: true },
    { key: 'subscription', label: 'Buy Tokens', hideForAgency: true },
    { key: 'agency-dashboard', label: 'My Jobs', agencyOnly: true },
    { key: 'agency-submit', label: 'Post a Job', agencyOnly: true },
    { key: 'dashboard', label: 'Dashboard', adminOnly: true },
    { key: 'admin-job-ingest', label: 'Job Ingest', adminOnly: true },
  ],
}
