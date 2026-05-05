<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch, setWaSessionToken } from '../../config/api'
  import { whatsapp } from '../../config/site'
  import MatchSessionPage from './MatchSessionPage.svelte'
  import ProfilePage from './ProfilePage.svelte'
  import JobBoardPage from './JobBoardPage.svelte'
  import StatusPage from './StatusPage.svelte'
  import WhatsAppSubscribePage from './WhatsAppSubscribePage.svelte'
  import FeedbackPrompt from '../feedback/FeedbackPrompt.svelte'

  export let token = ''

  let state = 'loading' // 'loading' | 'ready' | 'error'
  let errorMessage = ''
  let isExpired = false

  let targetPage = ''
  let matchSessionId = 0
  let isSubscribed = false
  let showFeedbackPrompt = false
  let creditsBalance = 0

  const PAGE_PATH = {
    'profile': '/profile',
    'job-board': '/jobs',
    'subscription': '/subscription',
    'status': '/status',
    'auto-apply': '/profile',
  }

  function navigate(pageKey) {
    const path = PAGE_PATH[pageKey] ?? '/profile'
    targetPage = pageKey
    history.replaceState({}, '', path)
  }

  onMount(async () => {
    if (!token) {
      state = 'error'
      errorMessage = 'Invalid link.'
      return
    }
    try {
      const response = await apiFetch(`${API_BASE_URL}/wa/auth/${token}`, {
        method: 'GET',
        credentials: 'include',
        skipAuthHandling: true,
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        errorMessage = data.detail || 'This link is invalid or has expired.'
        isExpired = response.status === 410
        state = 'error'
        return
      }
      const data = await response.json().catch(() => ({}))
      // Fallback: use ?r= query param if the API didn't return a redirect
      const urlR = new URLSearchParams(window.location.search).get('r') || ''
      const SAFE = new Set(['/profile', '/jobs', '/status', '/', '/subscription', '/?feedback=1'])
      const redirect = data.redirect || (SAFE.has(urlR) ? urlR : '') || '/profile'

      if (data.session_token) {
        setWaSessionToken(data.session_token)
      }

      // Fetch subscription status so child pages render correctly.
      try {
        const subRes = await apiFetch(`${API_BASE_URL}/subscription/status`, {
          method: 'GET',
          credentials: 'include',
        })
        if (subRes.ok) {
          const subData = await subRes.json()
          isSubscribed = Boolean(subData.subscribed)
          creditsBalance = Number(subData.balance ?? 0)
        }
      } catch { /* non-critical */ }

      const matchPath = redirect.match(/^\/matches\/(\d+)$/)
      if (matchPath) {
        targetPage = 'match-session'
        matchSessionId = parseInt(matchPath[1], 10)
      } else if (redirect === '/profile') {
        targetPage = 'profile'
      } else if (redirect === '/jobs') {
        targetPage = 'job-board'
      } else if (redirect === '/status') {
        targetPage = 'status'
      } else if (redirect === '/subscription') {
        targetPage = 'subscription'
      } else if (redirect === '/?feedback=1') {
        targetPage = 'profile'
        showFeedbackPrompt = true
      } else {
        targetPage = 'profile'
      }

      history.replaceState({}, '', redirect)
      state = 'ready'
    } catch {
      errorMessage = 'Could not reach the server. Please try again.'
      state = 'error'
    }
  })
</script>

{#if state === 'loading'}
  <main class="wa-state">
    <div class="wa-state-inner">
      <div class="wa-compass" aria-hidden="true">
        <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="24" cy="24" r="20"/>
          <circle cx="24" cy="24" r="14"/>
          <path d="M24 6v6M24 36v6M6 24h6M36 24h6"/>
          <path d="M24 10l4 14-4 14-4-14z" fill="currentColor" fill-opacity="0.18"/>
        </svg>
      </div>
      <p class="wa-eyebrow">
        <span class="wa-pip" aria-hidden="true"></span>
        Securing session
      </p>
      <p class="wa-state-sub">Verifying your WhatsApp magic link</p>
    </div>
  </main>

{:else if state === 'error'}
  <main class="wa-state">
    <div class="wa-state-inner wa-error-card">
      <div class="wa-state-icon" aria-hidden="true">
        {#if isExpired}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9"/>
            <path d="M12 7v5l3 2"/>
          </svg>
        {:else}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3L2 21h20L12 3z"/>
            <path d="M12 10v4M12 17.5v.01"/>
          </svg>
        {/if}
      </div>
      <p class="wa-eyebrow wa-eyebrow-brass">
        {isExpired ? 'Link expired' : 'Link unavailable'}
      </p>
      <h1 class="wa-error-title">
        {isExpired ? 'Your access link has timed out.' : 'This link can no longer be opened.'}
      </h1>
      <p class="wa-error-body">{errorMessage}</p>

      {#if whatsapp.configured}
        <a
          class="wa-error-cta"
          href={whatsapp.link('Hi Carver — I need a fresh access link.')}
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
            <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
          </svg>
          Request a new link
        </a>
      {/if}

      <p class="wa-error-foot">Send any message on WhatsApp to get a fresh link.</p>
    </div>
  </main>

{:else if state === 'ready'}
  <header class="wa-header">
    <div class="wa-header-inner">
      <a href="/" class="wa-brand">
        <span class="wa-brand-pip" aria-hidden="true"></span>
        <span class="wordmark wa-brand-word">CARVER</span>
        <span class="wa-brand-suffix">v3</span>
      </a>
      <nav class="wa-nav" aria-label="Primary">
        <button type="button" onclick={() => navigate('profile')}
          class="wa-nav-link" class:is-active={targetPage === 'profile'}>
          Profile
        </button>
        <button type="button" onclick={() => navigate('job-board')}
          class="wa-nav-link" class:is-active={targetPage === 'job-board'}>
          Jobs
        </button>
        <button type="button" onclick={() => navigate('subscription')}
          class="wa-nav-cta" class:is-active={targetPage === 'subscription'}>
          Tokens
        </button>
      </nav>
    </div>
  </header>

  <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
    {#if targetPage === 'match-session'}
      <MatchSessionPage sessionId={matchSessionId} />
    {:else if targetPage === 'profile'}
      <ProfilePage />
    {:else if targetPage === 'job-board'}
      <JobBoardPage />
    {:else if targetPage === 'status'}
      <StatusPage />
    {:else if targetPage === 'subscription'}
      <WhatsAppSubscribePage onNavigate={navigate} />
    {:else}
      <ProfilePage />
    {/if}
  </main>
  {#if showFeedbackPrompt}
    <FeedbackPrompt
      forceOpen={true}
      source="whatsapp_message"
      onRewarded={(value) => (creditsBalance = Math.max(0, Number(value) || 0))}
      onClose={() => {
        showFeedbackPrompt = false
        history.replaceState({}, '', '/profile')
      }}
    />
  {/if}
{/if}

<style>
  /* ── Full-bleed state screens (loading + error) ────────────────────── */
  .wa-state {
    min-height: 100dvh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
    background:
      radial-gradient(70% 50% at 50% 30%, rgba(201, 169, 110, 0.06), transparent 70%),
      var(--bg-base);
    position: relative;
  }
  .wa-state::before,
  .wa-state::after {
    content: "";
    position: absolute;
    left: 10%;
    right: 10%;
    height: 1px;
    background-image: linear-gradient(
      90deg, transparent, rgba(201, 169, 110, 0.28), transparent
    );
  }
  .wa-state::before { top: 0; }
  .wa-state::after { bottom: 0; }

  .wa-state-inner {
    width: 100%;
    max-width: 28rem;
    text-align: center;
    animation: waFadeUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  /* Loading compass */
  .wa-compass {
    width: 56px;
    height: 56px;
    margin: 0 auto 1.5rem;
    color: var(--brass);
    opacity: 0.85;
    animation: waCompassSpin 14s linear infinite;
  }
  @media (prefers-reduced-motion: reduce) {
    .wa-compass { animation: none; }
    .wa-state-inner { animation: none; }
  }
  @keyframes waCompassSpin {
    to { transform: rotate(360deg); }
  }

  .wa-eyebrow {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.32em;
    text-transform: uppercase;
    color: var(--radium);
    margin: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
  }
  .wa-eyebrow-brass {
    color: var(--brass);
  }
  .wa-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
    animation: waPip 2s ease-in-out infinite;
  }
  @keyframes waPip {
    0%, 100% { opacity: 0.55; }
    50%      { opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .wa-pip { animation: none; }
  }
  .wa-state-sub {
    margin: 0.85rem 0 0;
    font-size: 13px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
  }

  /* Error card */
  .wa-error-card {
    padding: 2.5rem 1.75rem 2rem;
    border-radius: 1rem;
    border: 1px solid rgba(201, 169, 110, 0.2);
    background:
      radial-gradient(80% 60% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      linear-gradient(180deg, #0a1015 0%, #050a0e 100%);
    box-shadow:
      inset 0 1px 0 rgba(201, 169, 110, 0.08),
      0 30px 80px -40px rgba(0, 0, 0, 0.7);
  }
  .wa-state-icon {
    width: 44px;
    height: 44px;
    margin: 0 auto 1.25rem;
    color: var(--brass);
    opacity: 0.85;
  }
  .wa-error-title {
    margin: 0.85rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    font-size: 1.55rem;
    line-height: 1.2;
    letter-spacing: -0.02em;
    color: var(--ivory);
  }
  .wa-error-body {
    margin: 0.75rem 0 0;
    font-size: 14px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .wa-error-cta {
    margin-top: 1.75rem;
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.75rem 1.2rem;
    border-radius: 9999px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    color: #06090d;
    background: linear-gradient(180deg, #fbf3df 0%, #ead7a7 100%);
    border: 1px solid rgba(216, 198, 154, 0.55);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.55) inset,
      0 16px 40px -18px rgba(216, 198, 154, 0.45);
    transition: transform 0.2s ease, filter 0.2s ease;
    min-height: 44px;
  }
  .wa-error-cta:hover {
    filter: brightness(1.04);
    transform: translateY(-1px);
  }
  .wa-error-cta svg { width: 14px; height: 14px; }

  .wa-error-foot {
    margin: 1.25rem 0 0;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  /* ── Header (authenticated shell) ─────────────────────────────────── */
  .wa-header {
    position: sticky;
    top: 0;
    z-index: 40;
    backdrop-filter: blur(14px);
    background: rgba(4, 7, 11, 0.72);
    border-bottom: 1px dashed rgba(201, 169, 110, 0.22);
  }
  .wa-header-inner {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0.85rem 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  @media (min-width: 768px) {
    .wa-header-inner { padding: 1rem 1.5rem; }
  }

  .wa-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.55rem;
    text-decoration: none;
  }
  .wa-brand-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 8px rgba(201, 169, 110, 0.55);
    align-self: center;
  }
  .wa-brand-word {
    font-size: 13px;
    color: var(--ivory);
  }
  .wa-brand-suffix {
    font-family: var(--font-serif);
    font-style: italic;
    font-size: 12px;
    color: var(--brass);
    letter-spacing: -0.02em;
  }

  .wa-nav {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
  }
  .wa-nav-link {
    padding: 0.5rem 0.85rem;
    border-radius: 9999px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid transparent;
    transition: color 0.18s ease, background 0.18s ease, border-color 0.18s ease;
    cursor: pointer;
    min-height: 36px;
  }
  .wa-nav-link:hover { color: var(--ivory); }
  .wa-nav-link.is-active {
    color: var(--ivory);
    background: rgba(243, 234, 216, 0.05);
    border-color: rgba(243, 234, 216, 0.14);
  }

  .wa-nav-cta {
    padding: 0.5rem 0.95rem;
    border-radius: 9999px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--brass-bright);
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.32);
    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
    cursor: pointer;
    min-height: 36px;
  }
  .wa-nav-cta:hover {
    background: rgba(201, 169, 110, 0.16);
    border-color: rgba(201, 169, 110, 0.5);
    color: var(--ivory);
  }
  .wa-nav-cta.is-active {
    background: rgba(201, 169, 110, 0.2);
    border-color: rgba(201, 169, 110, 0.55);
    color: var(--ivory);
  }

  @keyframes waFadeUp {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
