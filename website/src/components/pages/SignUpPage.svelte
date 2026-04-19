<script>
  import { onMount, tick } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick, trackFunnel } from '../../config/analytics'

  let {
    onSignUpSuccess = () => {},
    onGoToLogin = () => {},
    googleEnabled = false,
    googleClientId = '',
    onGoogleSignIn = () => {},
    initialIntent = 'crew',
  } = $props()

  // Initial value comes from the parent prop; afterwards the user can flip the toggle.
  let intent = $state('crew')
  $effect(() => { if (initialIntent === 'agency') intent = 'agency' })
  let fullName = $state('')
  let email = $state('')
  let agencyName = $state('')
  let password = $state('')
  let confirmPassword = $state('')
  let isSubmitting = $state(false)
  let errorMessage = $state('')
  let fieldErrors = $state({ fullName: '', email: '', agencyName: '', password: '', confirmPassword: '' })
  let isGoogleLoading = $state(false)
  let googleRenderError = $state('')
  const browserWindow = /** @type {any} */ (window)

  function loadGoogleScript() {
    return new Promise((resolve, reject) => {
      if (browserWindow.google?.accounts?.id) { resolve(); return }
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
    if (!googleEnabled || !googleClientId) return
    isGoogleLoading = true
    googleRenderError = ''
    try {
      await loadGoogleScript()
      await tick()
      const target = document.getElementById('google-signup-button')
      if (!target || !browserWindow.google?.accounts?.id) return
      browserWindow.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: async (response) => {
          if (!response?.credential) {
            errorMessage = 'Google sign-in did not return a credential.'
            return
          }
          onGoogleSignIn(response.credential)
        },
      })
      target.innerHTML = ''
      browserWindow.google.accounts.id.renderButton(target, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        text: 'signup_with',
        width: 280,
      })
    } catch {
      googleRenderError = 'Google sign-in unavailable right now.'
    } finally {
      isGoogleLoading = false
    }
  }

  onMount(() => { initGoogleButton() })

  function validateFields() {
    const errors = { fullName: '', email: '', agencyName: '', password: '', confirmPassword: '' }
    let valid = true

    if (!fullName.trim()) {
      errors.fullName = 'Full name is required.'
      valid = false
    }

    if (intent === 'agency' && !agencyName.trim()) {
      errors.agencyName = 'Agency name is required.'
      valid = false
    }

    const emailTrimmed = email.trim().toLowerCase()
    if (!emailTrimmed) {
      errors.email = 'Email is required.'
      valid = false
    } else if (!/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(emailTrimmed)) {
      errors.email = 'Please enter a valid email address.'
      valid = false
    }

    if (password.length < 8) {
      errors.password = 'Password must be at least 8 characters.'
      valid = false
    }

    if (password !== confirmPassword) {
      errors.confirmPassword = 'Passwords do not match.'
      valid = false
    }

    fieldErrors = errors
    return valid
  }

  async function handleSubmit(event) {
    event.preventDefault()
    errorMessage = ''

    if (!validateFields()) return

    isSubmitting = true
    trackClick(intent === 'agency' ? 'signup_submit_agency' : 'signup_submit')

    try {
      const endpoint = intent === 'agency' ? '/auth/signup-agency' : '/auth/signup'
      const body = intent === 'agency'
        ? {
            email: email.trim().toLowerCase(),
            full_name: fullName.trim(),
            agency_name: agencyName.trim(),
            password,
          }
        : {
            email: email.trim().toLowerCase(),
            full_name: fullName.trim(),
            password,
          }
      const response = await apiFetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        skipAuthHandling: true,
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        errorMessage = err.detail || 'Something went wrong. Please try again.'
        return
      }

      trackFunnel('signup_success', { label: intent })
      onSignUpSuccess({ intent })
    } catch {
      errorMessage = 'Could not reach the server. Please try again.'
    } finally {
      isSubmitting = false
    }
  }
</script>

<main class="relative mx-auto flex min-h-[100dvh] w-full max-w-md items-center px-4 py-10 sm:px-6">
  <div class="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
    <div class="signup-orb absolute -left-24 -top-24 h-72 w-72 rounded-full" style="background: radial-gradient(circle, rgba(34,211,238,0.14) 0%, transparent 65%); filter: blur(80px);"></div>
    <div class="signup-orb absolute -bottom-32 -right-24 h-80 w-80 rounded-full" style="background: radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 65%); filter: blur(90px);"></div>
  </div>

  <section class="relative w-full rounded-2xl border border-white/[0.08] bg-[#0a0e14]/95 p-6 shadow-[0_30px_120px_-40px_rgba(34,211,238,0.18)] backdrop-blur-sm sm:p-8">
    <div class="flex items-center gap-2">
      <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
      <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-400">Get started</p>
    </div>
    <h1 class="mt-3 font-display text-3xl font-light text-white sm:text-[2rem]">
      {intent === 'agency' ? 'Create an agency account' : 'Create your account'}
    </h1>
    <p class="mt-3 text-[14px] leading-relaxed text-slate-400">
      {intent === 'agency'
        ? 'Post jobs directly to the CARVER board and reach matched crew.'
        : 'Sign up to start matching with superyacht positions.'}
    </p>

    <div class="mt-5 inline-flex w-full rounded-xl border border-white/[0.08] bg-[#04070b] p-1 text-xs">
      <button
        type="button"
        class={`flex-1 rounded-lg px-3 py-2 font-medium transition ${intent === 'crew' ? 'bg-white/[0.08] text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}
        onclick={() => (intent = 'crew')}
      >
        I'm crew
      </button>
      <button
        type="button"
        class={`flex-1 rounded-lg px-3 py-2 font-medium transition ${intent === 'agency' ? 'bg-white/[0.08] text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}
        onclick={() => (intent = 'agency')}
      >
        I'm a yacht agency
      </button>
    </div>

    <form class="mt-6 grid gap-4" onsubmit={handleSubmit}>
      <label class="grid gap-1.5">
        <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Full name</span>
        <input
          class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
          type="text"
          bind:value={fullName}
          autocomplete="name"
          placeholder="e.g. James Carter"
          required
        />
        {#if fieldErrors.fullName}
          <p class="text-xs text-rose-400">{fieldErrors.fullName}</p>
        {/if}
      </label>

      {#if intent === 'agency'}
        <label class="grid gap-1.5">
          <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Agency name</span>
          <input
            class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
            type="text"
            bind:value={agencyName}
            autocomplete="organization"
            placeholder="e.g. Northrop & Johnson Crew"
            maxlength="160"
            required
          />
          {#if fieldErrors.agencyName}
            <p class="text-xs text-rose-400">{fieldErrors.agencyName}</p>
          {/if}
        </label>
      {/if}

      <label class="grid gap-1.5">
        <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Email</span>
        <input
          class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
          type="email"
          bind:value={email}
          autocomplete="email"
          placeholder="you@example.com"
          required
        />
        {#if fieldErrors.email}
          <p class="text-xs text-rose-400">{fieldErrors.email}</p>
        {/if}
      </label>

      <label class="grid gap-1.5">
        <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Password</span>
        <input
          class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
          type="password"
          bind:value={password}
          autocomplete="new-password"
          placeholder="Min. 8 characters"
          required
          minlength="8"
        />
        {#if fieldErrors.password}
          <p class="text-xs text-rose-400">{fieldErrors.password}</p>
        {/if}
      </label>

      <label class="grid gap-1.5">
        <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Confirm password</span>
        <input
          class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-[14px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
          type="password"
          bind:value={confirmPassword}
          autocomplete="new-password"
          placeholder="Repeat your password"
          required
          minlength="8"
        />
        {#if fieldErrors.confirmPassword}
          <p class="text-xs text-rose-400">{fieldErrors.confirmPassword}</p>
        {/if}
      </label>

      <button
        type="submit"
        disabled={isSubmitting}
        class="mt-2 inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-4 py-2.5 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting ? 'Creating account...' : 'Create account'}
      </button>

      <p class="mt-1 inline-flex items-center justify-center gap-1.5 text-center text-[11px] text-slate-500">
        <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        Passwords are hashed with bcrypt &middot; TLS encrypted
      </p>
    </form>

    {#if googleEnabled && googleClientId && intent === 'crew'}
      <div class="mt-6 border-t border-white/[0.06] pt-5">
        <div class="mb-3 flex items-center gap-3">
          <span class="hairline flex-1"></span>
          <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Or continue with</p>
          <span class="hairline flex-1"></span>
        </div>
        <div id="google-signup-button"></div>
        {#if isGoogleLoading}
          <p class="mt-2 text-xs text-slate-500">Loading Google sign-in...</p>
        {/if}
        {#if googleRenderError}
          <p class="mt-2 text-xs text-rose-300">{googleRenderError}</p>
        {/if}
      </div>
    {/if}

    {#if errorMessage}
      <p class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-[13px] text-rose-200">{errorMessage}</p>
    {/if}

    <div class="mt-6 border-t border-white/[0.06] pt-5">
      <p class="text-center text-[13px] text-slate-500">
        Already have an account?
        <button
          type="button"
          onclick={() => onGoToLogin()}
          class="ml-1 font-medium text-cyan-300 underline-offset-4 transition hover:text-cyan-200 hover:underline"
        >
          Sign in
        </button>
      </p>
    </div>

    <p class="mt-5 text-center text-[10.5px] leading-relaxed text-slate-600">
      By creating an account, you agree to our
      <a href="/terms" class="text-slate-400 hover:text-slate-200">Terms</a>
      and
      <a href="/privacy" class="text-slate-400 hover:text-slate-200">Privacy Policy</a>.
    </p>
  </section>
</main>
