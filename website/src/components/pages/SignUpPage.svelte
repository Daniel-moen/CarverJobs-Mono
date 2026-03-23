<script>
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick, trackFunnel } from '../../config/analytics'

  let { onSignUpSuccess = () => {}, onGoToLogin = () => {} } = $props()

  let fullName = $state('')
  let email = $state('')
  let password = $state('')
  let confirmPassword = $state('')
  let isSubmitting = $state(false)
  let errorMessage = $state('')
  let fieldErrors = $state({ fullName: '', email: '', password: '', confirmPassword: '' })

  function validateFields() {
    const errors = { fullName: '', email: '', password: '', confirmPassword: '' }
    let valid = true

    if (!fullName.trim()) {
      errors.fullName = 'Full name is required.'
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
    trackClick('signup_submit')

    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        skipAuthHandling: true,
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          full_name: fullName.trim(),
          password,
        }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        errorMessage = err.detail || 'Something went wrong. Please try again.'
        return
      }

      trackFunnel('signup_success', { label: 'email' })
      onSignUpSuccess()
    } catch {
      errorMessage = 'Could not reach the server. Please try again.'
    } finally {
      isSubmitting = false
    }
  }
</script>

<main class="mx-auto flex min-h-[100dvh] w-full max-w-md items-center px-4 py-10 sm:px-6">
  <section class="w-full rounded-2xl border border-white/10 bg-zinc-950 p-6 sm:p-8">
    <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Get Started</p>
    <h1 class="mt-3 text-3xl font-semibold text-white">Create your account</h1>
    <p class="mt-3 text-sm text-slate-400">
      Sign up to start matching with superyacht positions.
    </p>

    <form class="mt-6 grid gap-4" onsubmit={handleSubmit}>
      <label class="grid gap-1.5">
        <span class="text-xs text-slate-400">Full Name</span>
        <input
          class="rounded-md border border-white/15 bg-black px-3 py-2.5 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
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

      <label class="grid gap-1.5">
        <span class="text-xs text-slate-400">Email</span>
        <input
          class="rounded-md border border-white/15 bg-black px-3 py-2.5 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
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
        <span class="text-xs text-slate-400">Password</span>
        <input
          class="rounded-md border border-white/15 bg-black px-3 py-2.5 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
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
        <span class="text-xs text-slate-400">Confirm Password</span>
        <input
          class="rounded-md border border-white/15 bg-black px-3 py-2.5 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
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
        class="mt-2 rounded-md border border-cyan-200/50 bg-cyan-300/15 px-4 py-2.5 text-sm font-medium text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting ? 'Creating account...' : 'Create Account'}
      </button>
    </form>

    {#if errorMessage}
      <p class="mt-4 text-sm text-rose-300">{errorMessage}</p>
    {/if}

    <div class="mt-6 border-t border-white/10 pt-5">
      <p class="text-center text-sm text-slate-500">
        Already have an account?
        <button
          type="button"
          onclick={() => onGoToLogin()}
          class="font-medium text-cyan-400 transition hover:text-cyan-300"
        >
          Sign in
        </button>
      </p>
    </div>
  </section>
</main>
