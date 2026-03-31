<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  export let token = ''
  export let onAuthenticated = (redirect) => {}

  let state = 'loading' // 'loading' | 'error'
  let errorMessage = ''
  let isExpired = false

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
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        errorMessage = data.detail || 'This link is invalid or has expired.'
        isExpired = response.status === 410
        state = 'error'
        return
      }
      const data = await response.json().catch(() => ({}))
      onAuthenticated(data.redirect || '/profile')
    } catch {
      errorMessage = 'Could not reach the server. Please try again.'
      state = 'error'
    }
  })

  function goHome() {
    window.location.href = '/'
  }
</script>

<main class="mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-4 text-center">
  {#if state === 'loading'}
    <div>
      <div class="mb-4 text-3xl">⚓</div>
      <p class="text-sm text-slate-400">Signing you in via WhatsApp...</p>
    </div>
  {:else}
    <div class="rounded-2xl border border-white/10 bg-zinc-950 p-8">
      <div class="mb-4 text-3xl">{isExpired ? '⏳' : '⚠️'}</div>
      <h1 class="mb-2 text-lg font-semibold text-white">
        {isExpired ? 'Link expired' : 'Link unavailable'}
      </h1>
      <p class="text-sm text-slate-400">{errorMessage}</p>
      <p class="mt-4 text-xs text-slate-500">
        Send any message on WhatsApp to get a fresh link.
      </p>
      <button
        type="button"
        onclick={goHome}
        class="mt-5 rounded-lg border border-cyan-300/30 bg-cyan-300/8 px-5 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white"
      >
        Go to CARVER
      </button>
    </div>
  {/if}
</main>
