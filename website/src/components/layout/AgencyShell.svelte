<script>
  import { onMount, onDestroy } from 'svelte'
  import AgencyDashboardPage from '../pages/AgencyDashboardPage.svelte'
  import AgencySubmitJobPage from '../pages/AgencySubmitJobPage.svelte'
  import RecruiterCandidatesPage from '../pages/RecruiterCandidatesPage.svelte'
  import SubscriptionPage from '../pages/SubscriptionPage.svelte'
  import { trackPageView } from '../../config/analytics'
  import { AGENCY_UNLOCK_PROMISE } from '../../config/site'

  let { agencyName = '', onLogout = () => {} } = $props()

  // Local routing — agency sub-pages live here.
  //
  // `/agency` is Find Crew, not My Jobs. Every agency arrives with zero jobs
  // posted, so the old default dropped them on an empty table and the crew
  // list — the only thing they can spend a token on — was a tab they had to
  // discover (22 Sep 2026 review: 2 agency accounts, 0 unlocks ever).
  // `/agency/crew` is kept as an alias so older links still resolve.
  const PATH_TO_PAGE = {
    '/agency': 'crew',
    '/agency/crew': 'crew',
    '/agency/jobs': 'dashboard',
    '/agency/submit': 'submit',
    '/agency/tokens': 'tokens',
  }
  const PAGE_TO_PATH = {
    crew: '/agency',
    dashboard: '/agency/jobs',
    submit: '/agency/submit',
    tokens: '/agency/tokens',
  }

  function pageFromPath(pathname) {
    // Yoco checkout return URLs land on /subscription?status=… — show the
    // tokens page so the agency sees the payment result instead of bouncing
    // to the crew list.
    if (pathname.startsWith('/subscription')) return 'tokens'
    return PATH_TO_PAGE[pathname] ?? 'crew'
  }

  function readWelcomeFlag() {
    try {
      return new URLSearchParams(window.location.search).get('welcome') === '1'
    } catch {
      return false
    }
  }

  let currentPage = $state(pageFromPath(window.location.pathname))
  let mobileOpen = $state(false)
  // Set by App.svelte immediately after an agency signup (?welcome=1).
  let showWelcome = $state(readWelcomeFlag())

  function dismissWelcome() {
    showWelcome = false
    if (readWelcomeFlag()) {
      history.replaceState(history.state, '', window.location.pathname)
    }
  }

  function navigate(pageKey) {
    if (currentPage === pageKey) {
      mobileOpen = false
      return
    }
    currentPage = pageKey
    const path = PAGE_TO_PATH[pageKey] ?? '/agency'
    history.pushState({ page: pageKey, scope: 'agency' }, '', path)
    trackPageView(`agency-${pageKey}`)
    mobileOpen = false
  }

  function onPopState() {
    currentPage = pageFromPath(window.location.pathname)
  }

  onMount(() => {
    // If we landed on a non-agency path (e.g. user typed /dashboard) snap back
    // to the agency home so the URL matches what's actually rendered.
    if (!window.location.pathname.startsWith('/agency')) {
      if (window.location.pathname.startsWith('/subscription')) {
        history.replaceState({ page: 'tokens', scope: 'agency' }, '', '/agency/tokens')
      } else {
        history.replaceState({ page: 'crew', scope: 'agency' }, '', '/agency')
        currentPage = 'crew'
      }
    }
    trackPageView(`agency-${currentPage}`)
    window.addEventListener('popstate', onPopState)
  })

  onDestroy(() => {
    window.removeEventListener('popstate', onPopState)
  })

  // Find Crew first: it is both the landing tab and the only tab that leads
  // to a token spend.
  const tabs = [
    { key: 'crew',      label: 'Find Crew' },
    { key: 'submit',    label: 'Post a Job' },
    { key: 'dashboard', label: 'My Jobs' },
    { key: 'tokens',    label: 'Buy Tokens' },
  ]
</script>

<div class="min-h-[100dvh] bg-black text-white">
  <header class="sticky top-0 z-10 border-b border-white/10 bg-black sm:bg-black/90 sm:backdrop-blur">
    <div class="mx-auto flex w-full max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6 md:px-8">
      <p class="text-sm font-semibold tracking-[0.2em] text-slate-100">CARVER</p>
      {#if agencyName}
        <p class="hidden truncate text-xs uppercase tracking-[0.18em] text-slate-400 sm:block">
          {agencyName}
        </p>
      {/if}
      <button
        type="button"
        class="rounded-md border border-white/15 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/30 hover:text-white"
        onclick={onLogout}
      >
        Logout
      </button>
    </div>

    <nav class="mx-auto flex w-full max-w-7xl gap-2 px-4 pb-3 text-sm sm:px-6 md:px-8">
      {#each tabs as tab}
        <button
          type="button"
          class={`rounded-md px-3 py-1.5 transition ${
            currentPage === tab.key
              ? 'bg-white/10 text-white'
              : 'text-slate-400 hover:bg-white/5 hover:text-white'
          }`}
          onclick={() => navigate(tab.key)}
        >
          {tab.label}
        </button>
      {/each}
    </nav>

    {#if agencyName}
      <p class="mx-auto block w-full max-w-7xl px-4 pb-2 text-[11px] uppercase tracking-[0.18em] text-slate-500 sm:hidden">
        {agencyName}
      </p>
    {/if}
  </header>

  {#if showWelcome}
    <div class="border-b border-emerald-400/20 bg-emerald-400/10 px-4 py-2.5 sm:px-6">
      <div class="mx-auto flex w-full max-w-7xl items-center justify-between gap-4">
        <p class="text-sm text-emerald-100">{AGENCY_UNLOCK_PROMISE}</p>
        <button
          type="button"
          onclick={dismissWelcome}
          class="shrink-0 text-emerald-300/60 transition hover:text-emerald-200"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
    </div>
  {/if}

  <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
    {#if currentPage === 'dashboard'}
      <AgencyDashboardPage onNavigate={(key) => navigate(key === 'agency-submit' ? 'submit' : key === 'agency-dashboard' ? 'dashboard' : key === 'crew' ? 'crew' : currentPage)} />
    {:else if currentPage === 'tokens'}
      <SubscriptionPage onNavigate={(key) => navigate(key === 'subscription' ? 'tokens' : key)} />
    {:else if currentPage === 'submit'}
      <AgencySubmitJobPage onNavigate={(key) => navigate(key === 'agency-dashboard' ? 'dashboard' : key === 'agency-submit' ? 'submit' : currentPage)} />
    {:else}
      <RecruiterCandidatesPage onNavigate={(key) => navigate(key === 'subscription' ? 'tokens' : key)} />
    {/if}
  </main>
</div>
