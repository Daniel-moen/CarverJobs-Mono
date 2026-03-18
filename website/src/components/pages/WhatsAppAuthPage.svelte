<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  export let token = ''
  export let onAuthenticated = () => {}

  let state = 'loading' // 'loading' | 'error'
  let errorMessage = ''

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
        state = 'error'
        return
      }
      // Session cookie is now set — tell App.svelte we're authenticated
      onAuthenticated()
    } catch {
      errorMessage = 'Could not reach the server. Please try again.'
      state = 'error'
    }
  })
</script>

<main class="mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-4 text-center">
  {#if state === 'loading'}
    <div>
      <div class="mb-4 text-3xl">⚓</div>
      <p class="text-sm text-slate-400">Signing you in via WhatsApp...</p>
    </div>
  {:else}
    <div class="rounded-2xl border border-white/10 bg-zinc-950 p-8">
      <div class="mb-4 text-3xl">⚠️</div>
      <h1 class="mb-2 text-lg font-semibold text-white">Link unavailable</h1>
      <p class="text-sm text-slate-400">{errorMessage}</p>
      <p class="mt-4 text-xs text-slate-500">
        Send <span class="font-mono text-slate-300">edit</span> on WhatsApp to get a fresh link.
      </p>
    </div>
  {/if}
</main>
