<script>
  import { onMount, tick, onDestroy } from 'svelte'
  import SiteHeader from './components/layout/SiteHeader.svelte'
  import SiteFooter from './components/layout/SiteFooter.svelte'
  import AutoApplyPage from './components/pages/AutoApplyPage.svelte'
  import DashboardPage from './components/pages/DashboardPage.svelte'
  import JobBoardPage from './components/pages/JobBoardPage.svelte'
  import ProfilePage from './components/pages/ProfilePage.svelte'
  import StatusPage from './components/pages/StatusPage.svelte'
  import SubscriptionPage from './components/pages/SubscriptionPage.svelte'
  import OnboardingFlow from './components/onboarding/OnboardingFlow.svelte'
  import LandingPage from './components/pages/LandingPage.svelte'
  import MobileMarketingPage from './components/pages/MobileMarketingPage.svelte'
  import PublicProfilePage from './components/pages/PublicProfilePage.svelte'
  import WhatsAppAuthPage from './components/pages/WhatsAppAuthPage.svelte'
  import MatchSessionPage from './components/pages/MatchSessionPage.svelte'
  import LaunchSignupPage from './components/pages/LaunchSignupPage.svelte'
  import SignUpPage from './components/pages/SignUpPage.svelte'
  import AdminJobIngestPage from './components/pages/AdminJobIngestPage.svelte'
  import PrivacyPolicyPage from './components/pages/PrivacyPolicyPage.svelte'
  import TermsOfServicePage from './components/pages/TermsOfServicePage.svelte'
  import DataDeletionPage from './components/pages/DataDeletionPage.svelte'
  import { API_BASE_URL, apiFetch } from './config/api'
  import { trackPageView, trackClick, trackFunnel, trackError, trackSessionStart, startAutoFlush, stopAutoFlush, flush } from './config/analytics'

  // ── URL routing ──────────────────────────────────────────────────────────────
  // Map URL pathnames → page keys and back.  No router library needed —
  // nginx already falls back to index.html for every path.
  const PATH_TO_PAGE = {
    '/launch':       'launch-signup',
    '/signup':       'signup',
    '/':             'auto-apply',
    '/jobs':         'job-board',
    '/profile':      'profile',
    '/status':       'status',
    '/dashboard':    'dashboard',
    '/dashboard/job-ingest': 'admin-job-ingest',
    '/subscription': 'subscription',
    '/privacy':      'privacy',
    '/terms':        'terms',
    '/data-deletion': 'data-deletion',
  }
  const PAGE_TO_PATH = Object.fromEntries(
    Object.entries(PATH_TO_PAGE).map(([p, k]) => [k, p])
  )

  function extractCrewSlug(pathname) {
    const match = pathname.match(/^\/crew\/([a-zA-Z0-9_-]+)$/)
    return match ? match[1] : ''
  }

  function extractWaToken(pathname) {
    const match = pathname.match(/^\/wa\/([a-zA-Z0-9_-]+)$/)
    return match ? match[1] : ''
  }

  function extractMatchSessionId(pathname) {
    const match = pathname.match(/^\/matches\/(\d+)$/)
    return match ? parseInt(match[1], 10) : 0
  }

  function isLegalDocumentPage(key) {
    return key === 'privacy' || key === 'terms' || key === 'data-deletion'
  }

  function pageFromPath(pathname) {
    if (pathname === '/privacy') return 'privacy'
    if (pathname === '/terms') return 'terms'
    if (pathname === '/data-deletion') return 'data-deletion'
    if (!SITE_LAUNCHED) return 'launch-signup'
    if (pathname.startsWith('/crew/')) return 'public-profile'
    if (pathname.startsWith('/wa/')) return 'whatsapp-auth'
    if (pathname.startsWith('/matches/')) return 'match-session'
    if (pathname === '/signup') return 'signup'
    return PATH_TO_PAGE[pathname] ?? 'auto-apply'
  }

  function navigate(pageKey) {
    if (!SITE_LAUNCHED && !isLegalDocumentPage(pageKey)) return
    if (currentPage === pageKey) return
    currentPage = pageKey
    publicSlug = ''
    const path = PAGE_TO_PATH[pageKey] ?? '/'
    history.pushState({ page: pageKey }, '', path)
    trackPageView(pageKey)
  }

  function enforceAdminOnlyPageAccess() {
    if (currentPage === 'admin-job-ingest' && userRole !== 'admin') {
      currentPage = 'auto-apply'
      history.replaceState({ page: 'auto-apply' }, '', '/')
    }
  }

  const SITE_LAUNCHED = String(import.meta.env.VITE_SITE_LAUNCHED ?? 'true').toLowerCase() === 'true'

  let publicSlug = SITE_LAUNCHED ? extractCrewSlug(window.location.pathname) : ''
  let waToken = SITE_LAUNCHED ? extractWaToken(window.location.pathname) : ''
  let matchSessionId = SITE_LAUNCHED ? extractMatchSessionId(window.location.pathname) : 0
  let currentPage = pageFromPath(window.location.pathname)
  let isCheckingSession = true
  let isAuthenticated = false
  let hasActiveSession = false
  let userRole = ''
  let isSubscribed = false
  let creditsBalance = 0
  let showOnboarding = false
  let showDocsReminder = false
  let showLogin = false
  let showSignup = false
  let autoStartMatch = false
  let authError = ''
  let loginUsername = ''
  let loginPassword = ''
  let isSubmittingLogin = false
  let googleEnabled = false
  let googleClientId = ''
  let googleRenderError = ''
  let isGoogleLoading = false
  const browserWindow = /** @type {any} */ (window)
  const mobileMediaQuery = browserWindow.matchMedia('(max-width: 768px)')
  let isMobileViewport = mobileMediaQuery.matches

  function handleMobileViewportChange(e) {
    isMobileViewport = e.matches
  }

  function handleUnauthorizedEvent() {
    // Ignore 401s on public pages before any successful login/session.
    if (!isAuthenticated || !hasActiveSession) return
    isAuthenticated = false
    hasActiveSession = false
    userRole = ''
    isSubscribed = false
    creditsBalance = 0
    showOnboarding = false
    showDocsReminder = false
    showLogin = true
    authError = 'Your session expired. Please sign in again.'
  }

  onDestroy(() => {
    try { mobileMediaQuery.removeEventListener('change', handleMobileViewportChange) } catch { /* ignore */ }
    window.removeEventListener('carver:unauthorized', handleUnauthorizedEvent)
  })

  const appParticles = Array.from({ length: 8 }, () => ({
    x: Math.random() * 100,
    startY: 70 + Math.random() * 30,
    size: Math.random() * 1.8 + 0.6,
    dur: Math.random() * 28 + 20,
    delay: Math.random() * -50,
    opacity: Math.random() * 0.25 + 0.06,
  }))

  function checkOnboardingNeeded() {
    try {
      return localStorage.getItem('carver_onboarding_complete') !== 'true'
    } catch {
      return false
    }
  }

  function checkDocsReminder() {
    try {
      if (localStorage.getItem('carver_docs_reminder_dismissed') === 'true') return false
      const profile = JSON.parse(localStorage.getItem('carver_profile') || '{}')
      const docsComplete = profile.cvUploaded && profile.passportReady && profile.stcwReady && profile.eng1Ready
      return !docsComplete
    } catch {
      return false
    }
  }

  function dismissDocsReminder() {
    try { localStorage.setItem('carver_docs_reminder_dismissed', 'true') } catch { /* ignore */ }
    showDocsReminder = false
  }

  function handleOnboardingComplete() {
    showOnboarding = false
    showDocsReminder = checkDocsReminder()
  }

  const pageMap = {
    'auto-apply': AutoApplyPage,
    'job-board': JobBoardPage,
    'match-session': MatchSessionPage,
    profile: ProfilePage,
    status: StatusPage,
    dashboard: DashboardPage,
    'admin-job-ingest': AdminJobIngestPage,
    subscription: SubscriptionPage,
  }

  $: ActivePage = pageMap[currentPage] ?? AutoApplyPage

  // Retry a fetch on network failure (e.g. API still booting). Gives up after
  // maxAttempts, doubling the delay each time starting from initialDelayMs.
  async function fetchWithRetry(url, options, { maxAttempts = 3, initialDelayMs = 800 } = {}) {
    let delay = initialDelayMs
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        return await apiFetch(url, options)
      } catch (err) {
        if (attempt === maxAttempts) throw err
        await new Promise(r => setTimeout(r, delay))
        delay = Math.min(delay * 2, 5000)
      }
    }
  }

  async function checkSession() {
    isCheckingSession = true
    try {
      const response = await fetchWithRetry(`${API_BASE_URL}/auth/session`, {
        method: 'GET',
        credentials: 'include',
        skipAuthHandling: true,
        timeoutMs: 4000,
      }, { maxAttempts: 2, initialDelayMs: 1000 })
      let data = null
      try { data = response.ok ? await response.json() : null } catch { data = null }
      isAuthenticated = Boolean(data?.authenticated)
      if (isAuthenticated) {
        hasActiveSession = true
        userRole = data?.session?.role ?? ''
        isSubscribed = Boolean(data?.session?.is_subscribed)
        creditsBalance = Number(data?.session?.credits_balance ?? 0)
        // Keep the page that matches the current URL; don't override with a default.
        currentPage = pageFromPath(window.location.pathname)
        enforceAdminOnlyPageAccess()
        showOnboarding = checkOnboardingNeeded()
        if (!showOnboarding) showDocsReminder = checkDocsReminder()
      } else {
        hasActiveSession = false
        userRole = ''
        isSubscribed = false
        creditsBalance = 0
      }
    } catch (error) {
      isAuthenticated = false
      userRole = ''
      isSubscribed = false
      creditsBalance = 0
    } finally {
      isCheckingSession = false
    }
  }

  async function loadAuthProviders() {
    try {
      const response = await fetchWithRetry(`${API_BASE_URL}/auth/providers`, {
        method: 'GET',
        credentials: 'include',
        skipAuthHandling: true,
        timeoutMs: 4000,
      }, { maxAttempts: 2, initialDelayMs: 1000 })
      if (!response.ok) return
      const payload = await response.json()
      googleEnabled = Boolean(payload?.google?.enabled)
      googleClientId = typeof payload?.google?.client_id === 'string' ? payload.google.client_id : ''
    } catch {
      googleEnabled = false
      googleClientId = ''
    }
  }

  async function loginWithPassword(event) {
    event.preventDefault()
    isSubmittingLogin = true
    authError = ''
    trackClick('login_password')
    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        skipAuthHandling: true,
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        authError = err.detail || 'Invalid login details.'
        return
      }
      loginPassword = ''
      await checkSession()
      trackFunnel('login_success', { label: 'password' })
      showOnboarding = checkOnboardingNeeded()
      if (!showOnboarding) showDocsReminder = checkDocsReminder()
    } catch {
      authError = 'Could not reach API.'
    } finally {
      isSubmittingLogin = false
    }
  }

  async function loginWithGoogleToken(token) {
    authError = ''
    trackClick('login_google')
    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        skipAuthHandling: true,
        body: JSON.stringify({ id_token: token }),
      })
      if (!response.ok) {
        authError = 'Google sign-in failed or account is not allowed.'
        return
      }
      await checkSession()
      trackFunnel('login_success', { label: 'google' })
      showOnboarding = checkOnboardingNeeded()
      if (!showOnboarding) showDocsReminder = checkDocsReminder()
    } catch {
      authError = 'Could not reach API.'
    }
  }

  function loadGoogleScript() {
    return new Promise((resolve, reject) => {
      if (browserWindow.google?.accounts?.id) {
        resolve()
        return
      }
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.defer = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Failed to load Google script'))
      document.head.appendChild(script)
    })
  }

  async function initGoogleButton() {
    if (!googleEnabled || !googleClientId || isAuthenticated) return
    isGoogleLoading = true
    googleRenderError = ''
    try {
      await loadGoogleScript()
      await tick()
      const target = document.getElementById('google-signin-button')
      if (!target || !browserWindow.google?.accounts?.id) return
      browserWindow.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: async (response) => {
          if (!response?.credential) {
            authError = 'Google sign-in did not return a credential.'
            return
          }
          await loginWithGoogleToken(response.credential)
        },
      })
      target.innerHTML = ''
      browserWindow.google.accounts.id.renderButton(target, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        text: 'signin_with',
        width: 280,
      })
    } catch {
      googleRenderError = 'Google sign-in unavailable right now.'
    } finally {
      isGoogleLoading = false
    }
  }

  async function logout() {
    trackClick('logout')
    try {
      await apiFetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      /* Network failure is fine — clear local state regardless. */
    }
    isAuthenticated = false
    hasActiveSession = false
    userRole = ''
    isSubscribed = false
    creditsBalance = 0
    authError = ''
  }

  function enforceLaunchGate() {
    const path = window.location.pathname
    if (path === '/privacy' || path === '/terms' || path === '/data-deletion') {
      currentPage = pageFromPath(path)
      return
    }
    currentPage = 'launch-signup'
    publicSlug = ''
    waToken = ''
    if (path !== '/launch') {
      history.replaceState({ page: 'launch-signup' }, '', '/launch')
    }
  }

  onMount(async () => {
    try {
      mobileMediaQuery.addEventListener('change', handleMobileViewportChange)
    } catch {
      // Older browsers may use addListener/removeListener
      try { mobileMediaQuery.addListener(handleMobileViewportChange) } catch { /* ignore */ }
    }

    window.addEventListener('popstate', (e) => {
      if (!SITE_LAUNCHED) {
        const next = e.state?.page ?? pageFromPath(window.location.pathname)
        if (isLegalDocumentPage(next)) {
          currentPage = next
          trackPageView(next)
          return
        }
        enforceLaunchGate()
        trackPageView('launch-signup')
        return
      }
      publicSlug = extractCrewSlug(window.location.pathname)
      waToken = extractWaToken(window.location.pathname)
      matchSessionId = extractMatchSessionId(window.location.pathname)
      currentPage = e.state?.page ?? pageFromPath(window.location.pathname)
      enforceAdminOnlyPageAccess()
      showSignup = currentPage === 'signup'
      showLogin = false
      trackPageView(currentPage)
    })

    if (!SITE_LAUNCHED) {
      if (isLegalDocumentPage(currentPage)) {
        trackPageView(currentPage)
        return
      }
      enforceLaunchGate()
      trackPageView('launch-signup')
      return
    }

    history.replaceState({ page: currentPage }, '', window.location.pathname)
    startAutoFlush()
    trackSessionStart()
    trackPageView(currentPage)

    window.addEventListener('unhandledrejection', (e) => {
      trackError('unhandledrejection', e.reason?.message ?? String(e.reason), { page: currentPage })
    })
    window.onerror = (msg) => {
      trackError('uncaught', String(msg), { page: currentPage })
    }
    window.addEventListener('beforeunload', () => { flush(); stopAutoFlush() })
    window.addEventListener('carver:unauthorized', handleUnauthorizedEvent)

    await Promise.all([checkSession(), loadAuthProviders()])
    if (currentPage === 'signup' && !isAuthenticated) showSignup = true
    await initGoogleButton()
  })

  $: if (!isAuthenticated && showLogin && googleEnabled && googleClientId) {
    initGoogleButton()
  }
</script>

<div class="min-h-screen bg-black text-slate-100 relative">
  {#if currentPage === 'launch-signup'}
    <LaunchSignupPage />
  {:else if isLegalDocumentPage(currentPage)}
    {#if currentPage === 'privacy'}
      <PrivacyPolicyPage />
    {:else if currentPage === 'terms'}
      <TermsOfServicePage />
    {:else}
      <DataDeletionPage />
    {/if}
  {:else if waToken}
    <WhatsAppAuthPage token={waToken} />
  {:else if publicSlug}
    <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
      <PublicProfilePage slug={publicSlug} />
    </main>
  {:else if isCheckingSession}
    <main class="mx-auto flex min-h-[100dvh] w-full max-w-3xl items-center justify-center px-4 text-center sm:px-6">
      <p class="text-sm text-slate-400">Checking session...</p>
    </main>
  {:else if !isAuthenticated && showSignup}
    <SignUpPage
      {googleEnabled}
      {googleClientId}
      onGoogleSignIn={async (token) => {
        await loginWithGoogleToken(token)
        if (isAuthenticated) {
          showSignup = false
          trackFunnel('signup_complete', { label: 'google' })
          try { localStorage.removeItem('carver_onboarding_complete') } catch { /* ignore */ }
          showOnboarding = checkOnboardingNeeded()
          if (!showOnboarding) showDocsReminder = checkDocsReminder()
          currentPage = 'auto-apply'
          history.replaceState({ page: 'auto-apply' }, '', '/')
        }
      }}
      onSignUpSuccess={async () => {
        await checkSession()
        showSignup = false
        trackFunnel('signup_complete', { label: 'email' })
        try { localStorage.removeItem('carver_onboarding_complete') } catch { /* ignore */ }
        showOnboarding = checkOnboardingNeeded()
        if (!showOnboarding) showDocsReminder = checkDocsReminder()
        currentPage = 'auto-apply'
        history.replaceState({ page: 'auto-apply' }, '', '/')
      }}
      onGoToLogin={() => {
        showSignup = false
        showLogin = true
        history.pushState({ page: 'login' }, '', '/')
      }}
    />
  {:else if !isAuthenticated && !showLogin}
    {#if isMobileViewport}
      <MobileMarketingPage
        onSignIn={(source) => { authError = ''; showLogin = true; trackClick(source === 'hero' ? 'hero_cta_click' : 'nav_sign_in') }}
        onStartMatch={() => { authError = ''; autoStartMatch = true; showLogin = true; trackClick('landing_start_match') }}
      />
    {:else}
      <LandingPage
        onSignIn={(source) => { authError = ''; showLogin = true; trackClick(source === 'hero' ? 'hero_cta_click' : 'nav_sign_in') }}
        onStartMatch={() => { authError = ''; autoStartMatch = true; showLogin = true; trackClick('landing_start_match') }}
      />
    {/if}
  {:else if !isAuthenticated && showLogin}
    <main class="mx-auto flex min-h-[100dvh] w-full max-w-3xl items-center px-4 py-10 sm:px-6">
      <section class="w-full rounded-2xl border border-white/10 bg-zinc-950 p-6 sm:p-8">
        <button
          type="button"
          onclick={() => { showLogin = false; authError = '' }}
          class="mb-5 flex items-center gap-1.5 text-xs text-slate-500 transition hover:text-slate-300"
        >
          ← Back
        </button>
        <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Secure Access</p>
        <h1 class="mt-3 text-3xl font-semibold text-white">Sign in to CARVER</h1>
        <p class="mt-3 text-sm text-slate-300">
          Use Google sign-in or your email/password credentials.
        </p>

        <form class="mt-6 grid gap-3" onsubmit={loginWithPassword}>
          <label class="grid gap-1.5">
            <span class="text-xs text-slate-400">Email / Username</span>
            <input
              class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
              type="text"
              bind:value={loginUsername}
              autocomplete="username"
              required
            />
          </label>
          <label class="grid gap-1.5">
            <span class="text-xs text-slate-400">Password</span>
            <input
              class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
              type="password"
              bind:value={loginPassword}
              autocomplete="current-password"
              required
            />
          </label>
          <button
            type="submit"
            disabled={isSubmittingLogin}
            class="mt-1 rounded-md border border-cyan-200/50 bg-cyan-300/15 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmittingLogin ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        {#if googleEnabled && googleClientId}
          <div class="mt-6 border-t border-white/10 pt-5">
            <p class="mb-3 text-xs uppercase tracking-wide text-slate-500">Or continue with Google</p>
            <div id="google-signin-button"></div>
            {#if isGoogleLoading}
              <p class="mt-2 text-xs text-slate-500">Loading Google sign-in...</p>
            {/if}
            {#if googleRenderError}
              <p class="mt-2 text-xs text-rose-300">{googleRenderError}</p>
            {/if}
          </div>
        {/if}

        {#if authError}
          <p class="mt-4 text-sm text-rose-300">{authError}</p>
        {/if}

        <div class="mt-6 border-t border-white/10 pt-5">
          <p class="text-center text-sm text-slate-500">
            Don't have an account?
            <button
              type="button"
              onclick={() => { showLogin = false; showSignup = true; authError = ''; history.pushState({ page: 'signup' }, '', '/signup'); trackClick('goto_signup') }}
              class="font-medium text-cyan-400 transition hover:text-cyan-300"
            >
              Sign up
            </button>
          </p>
        </div>
      </section>
    </main>
  {:else if showOnboarding}
    <OnboardingFlow onComplete={handleOnboardingComplete} />
  {:else}
    <!-- Global animated app background -->
    <div class="app-bg" aria-hidden="true">
      <div class="app-grid-bg"></div>
      {#each appParticles as p}
        <div
          class="app-particle"
          style="left:{p.x}%; top:{p.startY}%; width:{p.size}px; height:{p.size}px; --op:{p.opacity}; animation-duration:{p.dur}s; animation-delay:{p.delay}s;"
        ></div>
      {/each}
      <div class="app-orb app-orb-1"></div>
      <div class="app-orb app-orb-2"></div>
      <div class="app-orb app-orb-3"></div>
      <div class="app-scan"></div>
    </div>

    <SiteHeader currentPage={currentPage} userRole={userRole} isSubscribed={isSubscribed} creditsBalance={creditsBalance} onNavigate={navigate} onLogout={logout} />

    {#if showDocsReminder}
      <div class="border-b border-amber-400/20 bg-amber-400/10 px-4 py-2.5 sm:px-6">
        <div class="mx-auto flex w-full max-w-7xl flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div class="flex items-start gap-2.5 text-sm text-amber-200">
            <span class="shrink-0 text-base">📋</span>
            <span>Your qualifications haven't been uploaded yet — add them to your profile to improve your match rate.</span>
          </div>
          <div class="flex items-center gap-3 self-end sm:flex-none sm:self-auto">
            <button
              onclick={() => (currentPage = 'profile')}
              class="rounded-lg border border-amber-300/40 bg-amber-300/15 px-3 py-1 text-xs font-medium text-amber-100 transition hover:bg-amber-300/25"
            >
              Go to Profile
            </button>
            <button
              onclick={() => dismissDocsReminder()}
              class="text-amber-400/60 transition hover:text-amber-300"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    {/if}

    <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
      <svelte:component this={ActivePage} isSubscribed={isSubscribed} creditsBalance={creditsBalance} onCreditsChanged={(value) => (creditsBalance = Math.max(0, Number(value) || 0))} onNavigate={navigate} autoStartMatch={autoStartMatch} onMatchStarted={() => (autoStartMatch = false)} sessionId={matchSessionId} />
    </main>
    <SiteFooter />
  {/if}
</div>

<style>
  /* ── Global animated background layer ── */
  .app-bg {
    position: fixed;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
    z-index: 0;
  }

  /* Pulsing line grid — reduced on mobile for performance */
  .app-grid-bg {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.022) 1px, transparent 1px);
    background-size: 60px 60px;
    animation: app-grid-pulse 6s ease-in-out infinite;
  }
  @media (max-width: 768px) {
    .app-grid-bg { animation: none; opacity: 0.6; }
  }
  @keyframes app-grid-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
  }

  /* Floating particles — fewer on mobile */
  .app-particle {
    position: absolute;
    border-radius: 50%;
    background: rgba(34, 211, 238, var(--op, 0.15));
    animation: app-float-up linear infinite;
  }
  @media (max-width: 768px) {
    .app-particle { display: none; }
  }
  @keyframes app-float-up {
    0%   { transform: translateY(0);      opacity: 0; }
    8%   { opacity: var(--op, 0.15); }
    85%  { opacity: var(--op, 0.15); }
    100% { transform: translateY(-110vh); opacity: 0; }
  }

  /* Orbs — static/low blur on mobile (blur is very expensive) */
  .app-orb {
    position: absolute;
    border-radius: 50%;
    animation: app-float 12s ease-in-out infinite;
  }
  .app-orb-1 {
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.07) 0%, transparent 65%);
    top: -120px; left: -100px;
    filter: blur(80px);
    animation-delay: 0s;
  }
  .app-orb-2 {
    width: 500px; height: 500px;
    background: radial-gradient(circle, rgba(99, 102, 241, 0.07) 0%, transparent 65%);
    bottom: 10%; right: -80px;
    filter: blur(90px);
    animation-delay: -5s;
    animation-direction: reverse;
  }
  .app-orb-3 {
    width: 360px; height: 360px;
    background: radial-gradient(circle, rgba(14, 165, 233, 0.06) 0%, transparent 65%);
    top: 40%; left: 50%;
    filter: blur(70px);
    animation-delay: -9s;
  }
  @media (max-width: 768px) {
    .app-orb { animation: none; filter: blur(40px); }
  }
  @keyframes app-float {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33%       { transform: translate(35px, -25px) scale(1.05); }
    66%       { transform: translate(-20px, 18px) scale(0.95); }
  }

  /* Horizontal scan line — disabled on mobile */
  .app-scan {
    position: absolute;
    top: -2px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, rgba(34, 211, 238, 0.2) 30%, rgba(34, 211, 238, 0.2) 70%, transparent 100%);
    animation: app-scan 18s linear infinite;
  }
  @media (max-width: 768px) {
    .app-scan { display: none; }
  }
  @keyframes app-scan {
    0%   { top: -2px;  opacity: 0; }
    4%   { opacity: 1; }
    96%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }
</style>
