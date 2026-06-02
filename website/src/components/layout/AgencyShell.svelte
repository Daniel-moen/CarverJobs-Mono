<script>
  import { onMount, onDestroy } from 'svelte'
  import AgencyDashboardPage from '../pages/AgencyDashboardPage.svelte'
  import AgencySubmitJobPage from '../pages/AgencySubmitJobPage.svelte'
  import RecruiterCandidatesPage from '../pages/RecruiterCandidatesPage.svelte'
  import { trackPageView } from '../../config/analytics'

  let { agencyName = '', onLogout = () => {} } = $props()

  // Local routing — agency sub-pages live here.
  const PATH_TO_PAGE = {
    '/agency': 'dashboard',
    '/agency/submit': 'submit',
    '/agency/crew': 'crew',
  }
  const PAGE_TO_PATH = {
    dashboard: '/agency',
    submit: '/agency/submit',
    crew: '/agency/crew',
  }

  function pageFromPath(pathname) {
    return PATH_TO_PAGE[pathname] ?? 'dashboard'
  }

  let currentPage = $state(pageFromPath(window.location.pathname))
  let mobileOpen = $state(false)

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
    // to the agency dashboard so the URL matches what's actually rendered.
    if (!window.location.pathname.startsWith('/agency')) {
      history.replaceState({ page: 'dashboard', scope: 'agency' }, '', '/agency')
      currentPage = 'dashboard'
    }
    trackPageView(`agency-${currentPage}`)
    window.addEventListener('popstate', onPopState)
  })

  onDestroy(() => {
    window.removeEventListener('popstate', onPopState)
  })

  const tabs = [
    { key: 'dashboard', label: 'My Jobs' },
    { key: 'submit',    label: 'Post a Job' },
    { key: 'crew',      label: 'Find Crew' },
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

  <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
    {#if currentPage === 'crew'}
      <RecruiterCandidatesPage />
    {:else if currentPage === 'submit'}
      <AgencySubmitJobPage onNavigate={(key) => navigate(key === 'agency-dashboard' ? 'dashboard' : key === 'agency-submit' ? 'submit' : currentPage)} />
    {:else}
      <AgencyDashboardPage onNavigate={(key) => navigate(key === 'agency-submit' ? 'submit' : key === 'agency-dashboard' ? 'dashboard' : currentPage)} />
    {/if}
  </main>
</div>
