<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { onNavigate = () => {} } = $props()

  let mounted = $state(false)
  let isLoading = $state(null)
  let checkoutError = $state('')
  let returnStatus = $state('')
  let balance = $state(0)
  let tokenPrice = $state('10.00')
  let packages = $state([
    { tokens: 10, price: '100.00' },
    { tokens: 20, price: '200.00' },
  ])

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

<section class="grid gap-4">
  <!-- Header -->
  <header class="relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-5 page-header" class:visible={mounted}>
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-violet-400/10 blur-3xl" style="animation: pulseOrb 4.5s ease-in-out infinite;"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-indigo-400/7 blur-2xl" style="animation: pulseOrb 4.5s ease-in-out infinite; animation-delay:-2.1s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative">
      <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">CARVER Tokens</p>
      <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Buy Tokens</h1>
      <p class="mt-1.5 max-w-xl text-sm text-slate-500">
        Each matching run uses 1 token. Top up whenever you need more.
      </p>
    </div>
  </header>

  <!-- Balance -->
  <div class="sub-card rounded-2xl border border-white/8 bg-zinc-950 p-5 text-center" class:visible={mounted} style="--delay:40ms;">
    <p class="text-xs font-bold uppercase tracking-[0.28em] text-slate-500">Your Balance</p>
    <p class="mt-2 text-4xl font-black text-white">{balance}</p>
    <p class="mt-1 text-sm text-slate-500">{balance === 1 ? 'token' : 'tokens'} remaining</p>
  </div>

  {#if returnStatus === 'success'}
    <div class="sub-card rounded-2xl border border-emerald-400/22 bg-emerald-950/30 p-5" class:visible={mounted} style="--delay:60ms;">
      <div class="flex items-start gap-3">
        <span class="mt-0.5 text-lg">🎉</span>
        <div>
          <p class="font-semibold text-emerald-200">Payment received!</p>
          <p class="mt-1 text-sm text-slate-400">Your tokens are being added. This usually takes a few seconds — refresh the page shortly to see your updated balance.</p>
        </div>
      </div>
    </div>
  {/if}

  {#if returnStatus === 'cancelled'}
    <div class="sub-card rounded-2xl border border-slate-500/20 bg-zinc-900/60 p-5" class:visible={mounted} style="--delay:60ms;">
      <p class="text-sm text-slate-400">Checkout was cancelled. No charge was made.</p>
    </div>
  {/if}

  {#if returnStatus === 'failed'}
    <div class="sub-card rounded-2xl border border-rose-400/20 bg-rose-950/25 p-5" class:visible={mounted} style="--delay:60ms;">
      <p class="text-sm text-rose-200">Payment did not complete. You were not charged. Please try again.</p>
    </div>
  {/if}

  {#if checkoutError}
    <div class="rounded-xl border border-rose-400/20 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
      {checkoutError}
    </div>
  {/if}

  <!-- Token packages -->
  <div class="grid gap-4 sm:grid-cols-2">
    {#each packages as pkg, i}
      {@const isPopular = i === 1}
      <article
        class="sub-card group relative overflow-hidden rounded-2xl border p-6 transition-all duration-300 hover:-translate-y-0.5 {isPopular
          ? 'border-cyan-400/22 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-fuchsia-950/40 hover:shadow-[0_24px_60px_-20px_rgba(34,211,238,0.35)]'
          : 'border-white/8 bg-zinc-950 hover:border-white/15'}"
        class:visible={mounted}
        style="--delay:{80 + i * 80}ms;"
      >
        {#if isPopular}
          <div class="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-cyan-400/12 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite;"></div>
          <div class="pointer-events-none absolute -bottom-14 -left-10 h-40 w-40 rounded-full bg-fuchsia-400/12 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite; animation-delay:-2s;"></div>
        {/if}

        <div class="relative z-10">
          <div class="flex items-center gap-2.5">
            <p class="text-[10px] font-bold uppercase tracking-[0.28em] {isPopular ? 'text-cyan-300/70' : 'text-slate-500'}">
              {pkg.tokens} Token Pack
            </p>
            {#if isPopular}
              <span class="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-200">
                Best Value
              </span>
            {/if}
          </div>

          <div class="mt-3 flex items-end gap-1">
            <span class="text-4xl font-black text-white">{formatPrice(pkg.price)}</span>
          </div>
          <p class="mt-1 text-sm {isPopular ? 'text-slate-300' : 'text-slate-500'}">
            {pkg.tokens} tokens at {formatPrice(tokenPrice)} each
          </p>

          <ul class="mt-5 space-y-2 text-sm">
            <li class="flex items-center gap-2.5">
              <span class="flex h-4 w-4 flex-none items-center justify-center rounded-full border {isPopular ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-400' : 'border-slate-700 bg-slate-800 text-slate-500'} text-[10px]">✓</span>
              <span class="{isPopular ? 'text-slate-200' : 'text-slate-300'}">{pkg.tokens} matching runs</span>
            </li>
            <li class="flex items-center gap-2.5">
              <span class="flex h-4 w-4 flex-none items-center justify-center rounded-full border {isPopular ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-400' : 'border-slate-700 bg-slate-800 text-slate-500'} text-[10px]">✓</span>
              <span class="{isPopular ? 'text-slate-200' : 'text-slate-300'}">Tokens never expire</span>
            </li>
            <li class="flex items-center gap-2.5">
              <span class="flex h-4 w-4 flex-none items-center justify-center rounded-full border {isPopular ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-400' : 'border-slate-700 bg-slate-800 text-slate-500'} text-[10px]">✓</span>
              <span class="{isPopular ? 'text-slate-200' : 'text-slate-300'}">Buy tokens anytime</span>
            </li>
          </ul>

          <button
            type="button"
            onclick={() => startCheckout(pkg.tokens)}
            disabled={isLoading !== null}
            class="mt-6 w-full rounded-xl border py-3 text-sm font-bold transition-all active:scale-95 disabled:cursor-not-allowed disabled:opacity-60 {isPopular
              ? 'border-cyan-300/30 bg-cyan-300/10 text-cyan-100 hover:border-cyan-300/50 hover:bg-cyan-300/18 hover:text-white'
              : 'border-white/12 bg-white/5 text-slate-200 hover:border-white/25 hover:bg-white/10 hover:text-white'}"
          >
            {isLoading === pkg.tokens ? 'Redirecting to Yoco...' : `Buy ${pkg.tokens} Tokens — ${formatPrice(pkg.price)}`}
          </button>
        </div>
      </article>
    {/each}
  </div>

  <p class="text-center text-[10px] text-slate-600">
    Secure payment via Yoco · No recurring charges
  </p>
</section>

<style>
  .header-scan-line {
    position: absolute;
    top: -1px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(167,139,250,0.28), transparent);
    animation: headerScan 8s linear infinite;
    pointer-events: none;
  }
  @keyframes headerScan {
    0%   { top: -1px; opacity: 0; }
    8%   { opacity: 1; }
    92%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }

  .page-header,
  .sub-card {
    opacity: 0;
    transform: translateY(14px);
    transition: opacity 0.45s ease, transform 0.45s ease, border-color 0.25s, box-shadow 0.25s, translate 0.2s;
    transition-delay: var(--delay, 0ms);
  }
  .page-header.visible,
  .sub-card.visible {
    opacity: 1;
    transform: translateY(0);
  }

  @keyframes pulseOrb {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.12); }
  }
</style>
