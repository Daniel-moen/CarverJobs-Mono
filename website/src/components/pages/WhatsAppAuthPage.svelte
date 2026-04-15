<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch, setWaSessionToken } from '../../config/api'
  import MatchSessionPage from './MatchSessionPage.svelte'
  import ProfilePage from './ProfilePage.svelte'
  import JobBoardPage from './JobBoardPage.svelte'
  import StatusPage from './StatusPage.svelte'
  import SubscriptionPage from './SubscriptionPage.svelte'

  export let token = ''

  let state = 'loading' // 'loading' | 'ready' | 'error'
  let errorMessage = ''
  let isExpired = false

  let targetPage = ''
  let matchSessionId = 0
  let isSubscribed = false

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
      const redirect = data.redirect || '/profile'

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
  <main class="mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-4 text-center">
    <div>
      <div class="mb-4 text-3xl">⚓</div>
      <p class="text-sm text-slate-400">Signing you in...</p>
    </div>
  </main>

{:else if state === 'error'}
  <main class="mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-4 text-center">
    <div class="rounded-2xl border border-white/10 bg-zinc-950 p-8">
      <div class="mb-4 text-3xl">{isExpired ? '⏳' : '⚠️'}</div>
      <h1 class="mb-2 text-lg font-semibold text-white">
        {isExpired ? 'Link expired' : 'Link unavailable'}
      </h1>
      <p class="text-sm text-slate-400">{errorMessage}</p>
      <p class="mt-4 text-xs text-slate-500">
        Send any message on WhatsApp to get a fresh link.
      </p>
    </div>
  </main>

{:else if state === 'ready'}
  <!-- Standalone header with minimal nav -->
  <header class="border-b border-white/8 bg-black/80 backdrop-blur-sm">
    <div class="mx-auto flex h-12 max-w-7xl items-center justify-between px-4 sm:px-6">
      <div class="flex items-center">
        <span class="text-sm font-bold tracking-widest text-white">CARVER</span>
        <span class="ml-2 text-[10px] text-slate-500">Superyacht Crew</span>
      </div>
      <nav class="flex items-center gap-1 sm:gap-2">
        <button type="button" onclick={() => navigate('profile')}
          class="rounded-md px-2 py-1 text-[11px] font-medium transition {targetPage === 'profile' ? 'text-white bg-white/8' : 'text-slate-500 hover:text-slate-300'}">
          Profile
        </button>
        <button type="button" onclick={() => navigate('job-board')}
          class="rounded-md px-2 py-1 text-[11px] font-medium transition {targetPage === 'job-board' ? 'text-white bg-white/8' : 'text-slate-500 hover:text-slate-300'}">
          Jobs
        </button>
        {#if !isSubscribed}
          <button type="button" onclick={() => navigate('subscription')}
            class="rounded-md px-2 py-1 text-[11px] font-medium transition {targetPage === 'subscription' ? 'text-cyan-200 bg-cyan-300/10 border border-cyan-300/25' : 'text-cyan-400 hover:text-cyan-300'}">
            Subscribe
          </button>
        {/if}
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
      <SubscriptionPage {isSubscribed} onNavigate={navigate} />
    {:else}
      <ProfilePage />
    {/if}
  </main>
{/if}
