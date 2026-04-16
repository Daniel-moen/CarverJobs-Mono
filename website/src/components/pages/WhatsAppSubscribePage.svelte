<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  export let onNavigate = () => {}

  let mounted = false
  let isLoading = null
  let checkoutError = ''
  let returnStatus = ''
  let balance = 0
  let tokenPrice = '10.00'
  let packages = [
    { tokens: 10, price: '100.00' },
    { tokens: 20, price: '200.00' },
  ]

  function formatPrice(amountStr) {
    const n = parseFloat(amountStr)
    if (isNaN(n)) return `R${amountStr}`
    return `R${Number.isInteger(n) ? n : n.toFixed(2)}`
  }

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    const params = new URLSearchParams(window.location.search)
    const status = params.get('status')
    if (status === 'success' || status === 'cancelled' || status === 'failed') {
      returnStatus = status
      window.history.replaceState({}, '', window.location.pathname)
    }
    try {
      const res = await apiFetch(`${API_BASE_URL}/subscription/status`, {
        method: 'GET',
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        if (data.balance != null) balance = data.balance
        if (data.token_price) tokenPrice = data.token_price
        if (data.packages) packages = data.packages
      }
    } catch { /* fallback to defaults */ }
  })

  async function startCheckout(tokens, retried = false) {
    isLoading = tokens
    checkoutError = ''
    try {
      const response = await apiFetch(`${API_BASE_URL}/subscription/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ tokens }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        if (!retried && response.status === 403 && err.code === 'CRV-2006') {
          return startCheckout(tokens, true)
        }
        checkoutError = err.detail || 'Could not start checkout. Please try again.'
        return
      }
      const data = await response.json()
      if (data.redirect_url) {
        window.location.href = data.redirect_url
        return
      }
      checkoutError = 'Could not start checkout. Please try again.'
    } catch {
      checkoutError = 'Could not reach the server. Please try again.'
    } finally {
      isLoading = null
    }
  }
</script>

<section class="mx-auto w-full max-w-lg">
  {#if returnStatus === 'success'}
    <div class="wa-sub-card rounded-2xl border border-emerald-400/22 bg-gradient-to-br from-emerald-950/40 to-zinc-950 p-8 text-center" class:visible={mounted}>
      <div class="mb-4 text-5xl">🎉</div>
      <h1 class="text-2xl font-black text-white">Tokens Added!</h1>
      <p class="mt-3 text-sm text-slate-400">Your payment is being confirmed. Your tokens will appear in your balance shortly.</p>
      <button
        type="button"
        onclick={() => onNavigate('profile')}
        class="mt-6 w-full rounded-xl border border-emerald-300/30 bg-emerald-300/10 py-3 text-sm font-bold text-emerald-200 transition hover:bg-emerald-300/20 hover:text-white active:scale-95"
      >
        Go to Profile →
      </button>
      <p class="mt-3 text-xs text-slate-600">Send any message on WhatsApp to continue.</p>
    </div>

  {:else if returnStatus === 'cancelled'}
    <div class="wa-sub-card rounded-2xl border border-white/8 bg-zinc-950 p-8 text-center" class:visible={mounted}>
      <div class="mb-4 text-4xl">↩️</div>
      <h1 class="text-xl font-bold text-white">Checkout cancelled</h1>
      <p class="mt-2 text-sm text-slate-400">No charge was made. You can try again whenever you're ready.</p>
      <button
        type="button"
        onclick={() => (returnStatus = '')}
        class="mt-6 w-full rounded-xl border border-cyan-300/30 bg-cyan-300/10 py-3 text-sm font-bold text-cyan-100 transition hover:bg-cyan-300/20 hover:text-white active:scale-95"
      >
        Try again
      </button>
    </div>

  {:else if returnStatus === 'failed'}
    <div class="wa-sub-card rounded-2xl border border-rose-400/20 bg-rose-950/25 p-8 text-center" class:visible={mounted}>
      <div class="mb-4 text-4xl">⚠️</div>
      <h1 class="text-xl font-bold text-white">Payment failed</h1>
      <p class="mt-2 text-sm text-rose-200">You were not charged. Please try again or use a different payment method.</p>
      <button
        type="button"
        onclick={() => (returnStatus = '')}
        class="mt-6 w-full rounded-xl border border-cyan-300/30 bg-cyan-300/10 py-3 text-sm font-bold text-cyan-100 transition hover:bg-cyan-300/20 hover:text-white active:scale-95"
      >
        Try again
      </button>
    </div>

  {:else}
    <!-- Main buy-tokens card -->
    <div
      class="wa-sub-card relative overflow-hidden rounded-2xl border border-cyan-400/22 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-fuchsia-950/40 p-8"
      class:visible={mounted}
    >
      <div class="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-cyan-400/12 blur-3xl" style="animation: waPulse 4s ease-in-out infinite;"></div>
      <div class="pointer-events-none absolute -bottom-14 -left-10 h-40 w-40 rounded-full bg-fuchsia-400/10 blur-3xl" style="animation: waPulse 4s ease-in-out infinite; animation-delay:-2s;"></div>

      <div class="relative z-10">
        <div class="text-center">
          <span class="inline-block rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-200">
            CARVER Tokens
          </span>
          <h1 class="mt-4 text-3xl font-black tracking-tight text-white">
            Buy Tokens
          </h1>
          <p class="mt-2 text-sm text-slate-400">
            {formatPrice(tokenPrice)} per token · Buy tokens anytime
          </p>

          <!-- Balance -->
          <div class="mx-auto mt-4 inline-flex items-center gap-2 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-2">
            <span class="text-xs text-slate-500">Balance:</span>
            <span class="text-lg font-black text-white">{balance}</span>
            <span class="text-xs text-slate-500">{balance === 1 ? 'token' : 'tokens'}</span>
          </div>
        </div>

        {#if checkoutError}
          <div class="mt-5 rounded-xl border border-rose-400/20 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
            {checkoutError}
          </div>
        {/if}

        <div class="mt-6 space-y-3">
          {#each packages as pkg, i}
            {@const isPopular = i === 1}
            <button
              type="button"
              onclick={() => startCheckout(pkg.tokens)}
              disabled={isLoading !== null}
              class="w-full rounded-xl border py-4 text-left transition-all active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 {isPopular
                ? 'border-cyan-300/30 bg-cyan-300/12 hover:border-cyan-300/50 hover:bg-cyan-300/20'
                : 'border-white/10 bg-white/[0.04] hover:border-white/20 hover:bg-white/[0.08]'}"
            >
              <div class="flex items-center justify-between px-5">
                <div>
                  <div class="flex items-center gap-2">
                    <span class="text-base font-bold text-white">{pkg.tokens} Tokens</span>
                    {#if isPopular}
                      <span class="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-200">Best Value</span>
                    {/if}
                  </div>
                  <p class="mt-0.5 text-xs text-slate-500">{pkg.tokens} matching runs</p>
                </div>
                <span class="text-xl font-black {isPopular ? 'text-cyan-100' : 'text-white'}">
                  {isLoading === pkg.tokens ? '...' : formatPrice(pkg.price)}
                </span>
              </div>
            </button>
          {/each}
        </div>

        <p class="mt-4 text-center text-[10px] text-slate-600">
          Secure payment via Yoco · No recurring charges
        </p>
      </div>
    </div>
  {/if}
</section>

<style>
  .wa-sub-card {
    opacity: 0;
    transform: translateY(14px);
    transition: opacity 0.45s ease, transform 0.45s ease;
  }
  .wa-sub-card.visible {
    opacity: 1;
    transform: translateY(0);
  }

  @keyframes waPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.12); }
  }
</style>
