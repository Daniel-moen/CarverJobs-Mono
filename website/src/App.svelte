<script>
  import { onMount, tick, onDestroy } from 'svelte'
  import SiteHeader from './components/layout/SiteHeader.svelte'
  import SiteFooter from './components/layout/SiteFooter.svelte'
  import RouteLoading from './components/layout/RouteLoading.svelte'
  import { API_BASE_URL, apiFetch, getAuthProviders } from './config/api'
  import { trackPageView, trackClick, trackFunnel, trackError, trackSessionStart, startAutoFlush, stopAutoFlush, flush } from './config/analytics'
  import { identifyUser, resetUser } from './config/posthog'

  // ── URL routing ──────────────────────────────────────────────────────────────
  // Map URL pathnames → page keys and back.  No router library needed —
  // nginx already falls back to index.html for every path.
  /** Cached dynamic imports — one chunk per key, reused on navigation. */
  const _pageChunkCache = new Map()
  /**
   * @param {string} key
   * @param {() => Promise<{ default: import('svelte').Component }>} loader
   */
  function pageChunk(key, loader) {
    let p = _pageChunkCache.get(key)
    if (!p) {
      p = loader()
      _pageChunkCache.set(key, p)
    }
    return p
  }

  const crewPageImports = {
    'auto-apply': () => import('./components/pages/AutoApplyPage.svelte'),
    'job-board': () => import('./components/pages/JobBoardPage.svelte'),
    'match-session': () => import('./components/pages/MatchSessionPage.svelte'),
    profile: () => import('./components/pages/ProfilePage.svelte'),
    status: () => import('./components/pages/StatusPage.svelte'),
    dashboard: () => import('./components/pages/DashboardPage.svelte'),
    'admin-job-ingest': () => import('./components/pages/AdminJobIngestPage.svelte'),
    subscription: () => import('./components/pages/SubscriptionPage.svelte'),
  }

  /** @param {string} page */
  function crewChunkKey(page) {
    return page in crewPageImports ? page : 'auto-apply'
  }

  const PATH_TO_PAGE = {
    '/launch':       'launch-signup',
    '/signup':       'signup',
    '/signup/agency': 'signup',
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
    '/articles':      'articles',
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

  function extractArticleSlug(pathname) {
    const match = pathname.match(/^\/articles\/([a-zA-Z0-9_-]+)$/)
    return match ? match[1] : ''
  }

  function isLegalDocumentPage(key) {
    return key === 'privacy' || key === 'terms' || key === 'data-deletion'
  }

  function isPublicContentPage(key) {
    return isLegalDocumentPage(key) || key === 'articles'
  }

  function pageFromPath(pathname) {
    if (pathname === '/privacy') return 'privacy'
    if (pathname === '/terms') return 'terms'
    if (pathname === '/data-deletion') return 'data-deletion'
    if (pathname === '/articles' || pathname.startsWith('/articles/')) return 'articles'
    if (!SITE_LAUNCHED) return 'launch-signup'
    if (pathname.startsWith('/crew/')) return 'public-profile'
    if (pathname.startsWith('/wa/')) return 'whatsapp-auth'
    if (pathname.startsWith('/matches/')) return 'match-session'
    if (pathname === '/signup') return 'signup'
    return PATH_TO_PAGE[pathname] ?? 'auto-apply'
  }

  function navigate(pageKey) {
    if (!SITE_LAUNCHED && !isPublicContentPage(pageKey)) return
    if (currentPage === pageKey) return
    currentPage = pageKey
    publicSlug = ''
    const path = PAGE_TO_PATH[pageKey] ?? '/'
    history.pushState({ page: pageKey }, '', path)
    trackPageView(pageKey)
  }

  function enforceRoleAccess() {
    if (currentPage === 'admin-job-ingest' && userRole !== 'admin') {
      currentPage = 'auto-apply'
      history.replaceState({ page: 'auto-apply' }, '', '/')
    }
    // Agency role is handled by AgencyShell — App.svelte never renders
    // crew pages for agencies, so no extra bouncing is needed here.
  }

  const SITE_LAUNCHED = String(import.meta.env.VITE_SITE_LAUNCHED ?? 'true').toLowerCase() === 'true'

  let publicSlug = SITE_LAUNCHED ? extractCrewSlug(window.location.pathname) : ''
  let waToken = SITE_LAUNCHED ? extractWaToken(window.location.pathname) : ''
  let matchSessionId = SITE_LAUNCHED ? extractMatchSessionId(window.location.pathname) : 0
  let articleSlug = extractArticleSlug(window.location.pathname)
  let currentPage = pageFromPath(window.location.pathname)
  let isCheckingSession = true
  let sessionCheckError = ''
  let isAuthenticated = false
  let hasActiveSession = false
  let userRole = ''
  let agencyName = ''
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
    agencyName = ''
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
    sessionCheckError = ''
    try {
      const response = await fetchWithRetry(`${API_BASE_URL}/auth/session`, {
        method: 'GET',
        credentials: 'include',
        skipAuthHandling: true,
        timeoutMs: 4000,
      }, { maxAttempts: 2, initialDelayMs: 1000 })
      if (!response.ok && response.status >= 500) {
        sessionCheckError = 'CARVER is having trouble connecting. Please retry in a moment.'
      }
      let data = null
      try { data = response.ok ? await response.json() : null } catch { data = null }
      isAuthenticated = Boolean(data?.authenticated)
      if (isAuthenticated) {
        hasActiveSession = true
        userRole = data?.session?.role ?? ''
        agencyName = String(data?.session?.agency_name ?? '')
        isSubscribed = Boolean(data?.session?.is_subscribed)
        creditsBalance = Number(data?.session?.credits_balance ?? 0)
        identifyUser({ id: data?.session?.sub, role: userRole, isSubscribed })
        if (userRole === 'agency') {
          // Agency users get a fully separate shell — no crew page resolution,
          // no onboarding, no docs reminders.
          showOnboarding = false
          showDocsReminder = false
          return
        }
        // Keep the page that matches the current URL; don't override with a default.
        currentPage = pageFromPath(window.location.pathname)
        enforceRoleAccess()
        showOnboarding = checkOnboardingNeeded()
        if (!showOnboarding) showDocsReminder = checkDocsReminder()
      } else {
        hasActiveSession = false
        userRole = ''
        agencyName = ''
        isSubscribed = false
        creditsBalance = 0
      }
    } catch (error) {
      sessionCheckError = 'CARVER is having trouble connecting. Please retry in a moment.'
      isAuthenticated = false
      userRole = ''
      agencyName = ''
      isSubscribed = false
      creditsBalance = 0
    } finally {
      isCheckingSession = false
    }
  }

  async function loadAuthProviders() {
    try {
      let payload = null
      for (let attempt = 1; attempt <= 2; attempt++) {
        const { ok, json } = await getAuthProviders()
        if (ok && json) {
          payload = json
          break
        }
        if (attempt < 2) await new Promise((r) => setTimeout(r, 1000))
      }
      if (!payload) return
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
      if (userRole === 'agency') {
        showLogin = false
        history.replaceState({}, '', '/agency')
        return
      }
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
      if (userRole === 'agency') {
        showLogin = false
        history.replaceState({}, '', '/agency')
        return
      }
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
    agencyName = ''
    isSubscribed = false
    creditsBalance = 0
    authError = ''
    resetUser()
  }

  function enforceLaunchGate() {
    const path = window.location.pathname
    if (
      path === '/privacy' ||
      path === '/terms' ||
      path === '/data-deletion' ||
      path === '/articles' ||
      path.startsWith('/articles/')
    ) {
      currentPage = pageFromPath(path)
      articleSlug = extractArticleSlug(path)
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
        if (isPublicContentPage(next)) {
          currentPage = next
          articleSlug = extractArticleSlug(window.location.pathname)
          trackPageView(next)
          return
        }
        enforceLaunchGate()
        trackPageView('launch-signup')
        return
      }
      // Agency users own their own routing inside AgencyShell.
      if (isAuthenticated && userRole === 'agency') return
      publicSlug = extractCrewSlug(window.location.pathname)
      waToken = extractWaToken(window.location.pathname)
      matchSessionId = extractMatchSessionId(window.location.pathname)
      articleSlug = extractArticleSlug(window.location.pathname)
      currentPage = e.state?.page ?? pageFromPath(window.location.pathname)
      enforceRoleAccess()
      showSignup = currentPage === 'signup'
      showLogin = false
      trackPageView(currentPage)
    })

    if (!SITE_LAUNCHED) {
      if (isPublicContentPage(currentPage)) {
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
  })

  $: if (!isAuthenticated && showLogin && googleEnabled && googleClientId) {
    initGoogleButton()
  }
</script>

<div class="min-h-screen bg-black text-slate-100 relative">
  {#if currentPage === 'launch-signup'}
    {#await pageChunk('launch-signup', () => import('./components/pages/LaunchSignupPage.svelte'))}
      <RouteLoading />
    {:then { default: LaunchSignupPage }}
      <LaunchSignupPage />
    {/await}
  {:else if currentPage === 'articles'}
    {#await pageChunk('articles', () => import('./components/pages/ArticlesPage.svelte'))}
      <RouteLoading />
    {:then { default: ArticlesPage }}
      <ArticlesPage
        slug={articleSlug}
        onBack={() => {
          articleSlug = ''
          currentPage = SITE_LAUNCHED ? 'auto-apply' : 'launch-signup'
          const path = SITE_LAUNCHED ? '/' : '/launch'
          history.pushState({ page: currentPage }, '', path)
        }}
      />
    {/await}
  {:else if isLegalDocumentPage(currentPage)}
    {#if currentPage === 'privacy'}
      {#await pageChunk('legal-privacy', () => import('./components/pages/PrivacyPolicyPage.svelte'))}
        <RouteLoading />
      {:then { default: PrivacyPolicyPage }}
        <PrivacyPolicyPage />
      {/await}
    {:else if currentPage === 'terms'}
      {#await pageChunk('legal-terms', () => import('./components/pages/TermsOfServicePage.svelte'))}
        <RouteLoading />
      {:then { default: TermsOfServicePage }}
        <TermsOfServicePage />
      {/await}
    {:else}
      {#await pageChunk('legal-data-deletion', () => import('./components/pages/DataDeletionPage.svelte'))}
        <RouteLoading />
      {:then { default: DataDeletionPage }}
        <DataDeletionPage />
      {/await}
    {/if}
  {:else if waToken}
    {#await pageChunk('whatsapp-auth', () => import('./components/pages/WhatsAppAuthPage.svelte'))}
      <RouteLoading />
    {:then { default: WhatsAppAuthPage }}
      <WhatsAppAuthPage token={waToken} />
    {/await}
  {:else if publicSlug}
    <main class="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-6 md:px-8">
      {#await pageChunk('public-profile', () => import('./components/pages/PublicProfilePage.svelte'))}
        <RouteLoading compact />
      {:then { default: PublicProfilePage }}
        <PublicProfilePage slug={publicSlug} />
      {/await}
    </main>
  {:else if isCheckingSession}
    <main class="mx-auto flex min-h-[100dvh] w-full max-w-3xl items-center justify-center px-4 text-center sm:px-6">
      <div class="flex flex-col items-center gap-3">
        <span class="relative flex h-2 w-2 items-center justify-center">
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/60"></span>
          <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        </span>
        <p class="font-mono text-[10px] uppercase tracking-[0.28em] text-slate-500">Securing session</p>
      </div>
    </main>
  {:else if sessionCheckError}
    <main class="mx-auto flex min-h-[100dvh] w-full max-w-md items-center justify-center px-4 text-center sm:px-6">
      <section class="rounded-2xl border border-amber-300/20 bg-zinc-950/90 p-6 shadow-2xl shadow-black/40">
        <p class="font-mono text-[10px] uppercase tracking-[0.28em] text-amber-300/80">Connection issue</p>
        <h1 class="mt-3 text-2xl font-black tracking-tight text-white">We could not verify your session.</h1>
        <p class="mt-2 text-sm leading-6 text-slate-400">{sessionCheckError}</p>
        <button
          type="button"
          onclick={checkSession}
          class="mt-5 inline-flex items-center justify-center rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/60 hover:bg-cyan-300/15"
        >
          Retry
        </button>
      </section>
    </main>
  {:else if !isAuthenticated && showSignup}
    {#await pageChunk('signup', () => import('./components/pages/SignUpPage.svelte'))}
      <RouteLoading />
    {:then { default: SignUpPage }}
      <SignUpPage
        {googleEnabled}
        {googleClientId}
        initialIntent={window.location.pathname === '/signup/agency' ? 'agency' : 'crew'}
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
        onSignUpSuccess={async (result) => {
          await checkSession()
          showSignup = false
          trackFunnel('signup_complete', { label: result?.intent === 'agency' ? 'agency' : 'email' })
          if (result?.intent === 'agency') {
            showOnboarding = false
            showDocsReminder = false
            history.replaceState({}, '', '/agency')
            return
          }
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
    {/await}
  {:else if !isAuthenticated && !showLogin}
    {#if isMobileViewport}
      {#await pageChunk('marketing-mobile', () => import('./components/pages/MobileMarketingPage.svelte'))}
        <RouteLoading />
      {:then { default: MobileMarketingPage }}
        <MobileMarketingPage
          onSignIn={(source) => { authError = ''; showLogin = true; trackClick(source === 'hero' ? 'hero_cta_click' : 'nav_sign_in') }}
          onStartMatch={() => { authError = ''; autoStartMatch = true; showLogin = true; trackClick('landing_start_match') }}
          onAgencySignup={() => { authError = ''; showLogin = false; showSignup = true; history.pushState({ page: 'signup' }, '', '/signup/agency'); trackClick('agency_signup_cta') }}
        />
      {/await}
    {:else}
      {#await pageChunk('marketing-desktop', () => import('./components/pages/LandingPage.svelte'))}
        <RouteLoading />
      {:then { default: LandingPage }}
        <LandingPage
          onSignIn={(source) => { authError = ''; showLogin = true; trackClick(source === 'hero' ? 'hero_cta_click' : 'nav_sign_in') }}
          onStartMatch={() => { authError = ''; autoStartMatch = true; showLogin = true; trackClick('landing_start_match') }}
          onAgencySignup={() => { authError = ''; showLogin = false; showSignup = true; history.pushState({ page: 'signup' }, '', '/signup/agency'); trackClick('agency_signup_cta') }}
        />
      {/await}
    {/if}
  {:else if !isAuthenticated && showLogin}
    <main class="relative mx-auto flex min-h-[100dvh] w-full max-w-md items-center px-4 py-10 sm:px-6">
      <div class="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div class="absolute -left-24 -top-24 h-72 w-72 rounded-full" style="background: radial-gradient(circle, rgba(34,211,238,0.14) 0%, transparent 65%); filter: blur(80px);"></div>
        <div class="absolute -bottom-32 -right-24 h-80 w-80 rounded-full" style="background: radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 65%); filter: blur(90px);"></div>
      </div>

      <section class="relative w-full rounded-2xl border border-white/[0.08] bg-[#0a0e14]/95 p-6 shadow-[0_30px_120px_-40px_rgba(34,211,238,0.18)] backdrop-blur-sm sm:p-8">
        <button
          type="button"
          onclick={() => { showLogin = false; authError = '' }}
          class="mb-5 inline-flex items-center gap-1.5 text-[12px] text-slate-500 transition hover:text-slate-200"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          Back
        </button>

        <div class="flex items-center gap-2">
          <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
          <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-400">Secure access</p>
        </div>
        <h1 class="mt-3 font-display text-3xl font-light text-white sm:text-[2rem]">Welcome back</h1>
        <p class="mt-3 text-[14px] leading-relaxed text-slate-400">
          Sign in with Google or your email and password.
        </p>

        <form class="mt-6 grid gap-3.5" onsubmit={loginWithPassword}>
          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Email or username</span>
            <input
              class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
              type="text"
              bind:value={loginUsername}
              autocomplete="username"
              required
            />
          </label>
          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Password</span>
            <input
              class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
              type="password"
              bind:value={loginPassword}
              autocomplete="current-password"
              required
            />
          </label>
          <button
            type="submit"
            disabled={isSubmittingLogin}
            class="mt-1 inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-4 py-2.5 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmittingLogin ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        {#if googleEnabled && googleClientId}
          <div class="mt-6">
            <div class="mb-3 flex items-center gap-3">
              <span class="hairline flex-1"></span>
              <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Or continue with</p>
              <span class="hairline flex-1"></span>
            </div>
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
          <p class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-[13px] text-rose-200">{authError}</p>
        {/if}

        <p class="mt-5 inline-flex items-center justify-center gap-1.5 text-center text-[11px] text-slate-500">
          <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          Encrypted session &middot; we never store your password in plaintext
        </p>

        <div class="mt-5 border-t border-white/[0.06] pt-5">
          <p class="text-center text-[13px] text-slate-500">
            Don't have an account?
            <button
              type="button"
              onclick={() => { showLogin = false; showSignup = true; authError = ''; history.pushState({ page: 'signup' }, '', '/signup'); trackClick('goto_signup') }}
              class="ml-1 font-medium text-cyan-300 underline-offset-4 transition hover:text-cyan-200 hover:underline"
            >
              Sign up
            </button>
          </p>
        </div>
      </section>
    </main>
  {:else if showOnboarding}
    {#await pageChunk('onboarding', () => import('./components/onboarding/OnboardingFlow.svelte'))}
      <RouteLoading />
    {:then { default: OnboardingFlow }}
      <OnboardingFlow onComplete={handleOnboardingComplete} />
    {/await}
  {:else if isAuthenticated && userRole === 'agency'}
    {#await pageChunk('agency-shell', () => import('./components/layout/AgencyShell.svelte'))}
      <RouteLoading />
    {:then { default: AgencyShell }}
      <AgencyShell agencyName={agencyName} onLogout={logout} />
    {/await}
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
              onclick={() => navigate('profile')}
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
      {#await pageChunk('crew-' + crewChunkKey(currentPage), () => crewPageImports[crewChunkKey(currentPage)]())}
        <RouteLoading compact />
      {:then { default: ActivePage }}
        <svelte:component this={ActivePage} isSubscribed={isSubscribed} creditsBalance={creditsBalance} onCreditsChanged={(value) => (creditsBalance = Math.max(0, Number(value) || 0))} onNavigate={navigate} autoStartMatch={autoStartMatch} onMatchStarted={() => (autoStartMatch = false)} sessionId={matchSessionId} />
      {/await}
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

  @media (prefers-reduced-motion: reduce) {
    .app-grid-bg,
    .app-particle,
    .app-orb,
    .app-scan {
      animation: none !important;
    }

    .app-particle,
    .app-scan {
      display: none;
    }

    .app-orb {
      transform: none;
    }
  }
</style>
