<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { isSubscribed = false, onNavigate = () => {} } = $props()

  let mounted = $state(false)
  let isLoading = $state(false)
  let isCancelling = $state(false)
  let checkoutError = $state('')
  let returnStatus = $state('')
  let showCancelConfirm = $state(false)
  let monthlyAmount = $state('200.00')

  /** Format a decimal amount string like "200.00" → "R200" */
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
    // Fetch current price from the API so it always reflects the backend setting.
    try {
      const res = await apiFetch(`${API_BASE_URL}/subscription/status`, {
        method: 'GET',
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        if (data.monthly_amount) monthlyAmount = data.monthly_amount
      }
    } catch { /* non-critical — fallback to default */ }
  })

  const freeFeatures = ['25 Free Tokens / Month', 'Browse Job Board', 'Manage Profile', 'Upload Documents']
  const lockedFeatures = ['Unlimited Tokens', 'Priority Recommendations', 'Auto Apply']

  const proFeatures = [
    { label: 'Unlimited Tokens', desc: 'No cap on matching runs per month' },
    { label: 'Priority Recommendations', desc: 'Your profile surfaces first to employers' },
    { label: 'Auto Match', desc: 'AI matching against live listings' },
    { label: 'Auto Apply', desc: 'Automated applications to qualified roles' },
    { label: 'Priority Jobs', desc: 'First access to urgent hire postings' },
    { label: 'Match Insights', desc: 'Compatibility scores and gap analysis' },
    { label: 'Unlimited Applications', desc: 'No cap on monthly applications' },
    { label: 'Document Storage', desc: 'Secure CV, passport, STCW & ENG1 vault' },
  ]

  async function startCheckout(retried = false) {
    isLoading = true
    checkoutError = ''
    try {
      const response = await apiFetch(`${API_BASE_URL}/subscription/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        // CSRF token expired — apiFetch already refreshed _csrfToken from the
        // error response headers, so one silent retry will succeed.
        if (!retried && response.status === 403 && err.code === 'CRV-2006') {
          return startCheckout(true)
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
      isLoading = false
    }
  }

  async function cancelSubscription() {
    isCancelling = true
    checkoutError = ''
    try {
      const response = await apiFetch(`${API_BASE_URL}/subscription/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        checkoutError = err.detail || 'Could not cancel subscription.'
        return
      }
      window.location.reload()
    } catch {
      checkoutError = 'Could not reach the server. Please try again.'
    } finally {
      isCancelling = false
      showCancelConfirm = false
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
      <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">CARVER Pro</p>
      <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Unlock the full platform</h1>
      <p class="mt-1.5 max-w-xl text-sm text-slate-500">
        Auto Match, Auto Apply, and every tool to land your next superyacht position faster.
      </p>
    </div>
  </header>

  {#if returnStatus === 'success' && !isSubscribed}
    <div class="sub-card rounded-2xl border border-amber-400/22 bg-amber-950/30 p-5" class:visible={mounted} style="--delay:60ms;">
      <div class="flex items-start gap-3">
        <span class="mt-0.5 text-lg">&#9203;</span>
        <div>
          <p class="font-semibold text-amber-200">Payment processing</p>
          <p class="mt-1 text-sm text-slate-400">Your payment is being confirmed. This usually takes a few seconds. Refresh the page shortly to see your subscription activated.</p>
        </div>
      </div>
    </div>
  {/if}

  {#if returnStatus === 'cancelled'}
    <div class="sub-card rounded-2xl border border-slate-500/20 bg-zinc-900/60 p-5" class:visible={mounted} style="--delay:60ms;">
      <p class="text-sm text-slate-400">Checkout was cancelled. No charge was made. You can try again whenever you're ready.</p>
    </div>
  {/if}

  {#if returnStatus === 'failed'}
    <div class="sub-card rounded-2xl border border-rose-400/20 bg-rose-950/25 p-5" class:visible={mounted} style="--delay:60ms;">
      <p class="text-sm text-rose-200">Payment did not complete. You were not charged. You can try again when you're ready.</p>
    </div>
  {/if}

  {#if checkoutError}
    <div class="rounded-xl border border-rose-400/20 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
      {checkoutError}
    </div>
  {/if}

  {#if isSubscribed}
    <!-- Subscribed state -->
    <article class="sub-card relative overflow-hidden rounded-2xl border border-emerald-400/22 bg-gradient-to-br from-emerald-950/40 to-zinc-950 p-6" class:visible={mounted} style="--delay:80ms;">
      <div class="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full bg-emerald-400/10 blur-3xl animate-pulse"></div>
      <div class="relative flex items-start gap-4">
        <div class="flex h-10 w-10 flex-none items-center justify-center rounded-xl border border-emerald-400/25 bg-emerald-400/10">
          <svg class="h-5 w-5 text-emerald-300" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
          </svg>
        </div>
        <div>
          <p class="font-bold text-white">You're subscribed to CARVER Pro</p>
          <p class="mt-1 text-sm text-slate-400">Full access to all features is active on your account.</p>
          <div class="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onclick={() => onNavigate('auto-apply')}
              class="rounded-lg border border-emerald-300/30 bg-emerald-300/8 px-5 py-2 text-sm font-semibold text-emerald-200 transition-all hover:bg-emerald-300/18 hover:text-white active:scale-95"
            >
              Go to Auto Apply →
            </button>
            {#if !showCancelConfirm}
              <button
                type="button"
                onclick={() => (showCancelConfirm = true)}
                class="text-xs text-slate-600 transition hover:text-slate-400"
              >
                Cancel subscription
              </button>
            {/if}
          </div>

          {#if showCancelConfirm}
            <div class="mt-4 rounded-lg border border-rose-400/15 bg-rose-950/20 p-4">
              <p class="text-sm text-slate-300">Are you sure you want to cancel your Pro subscription?</p>
              <div class="mt-3 flex items-center gap-3">
                <button
                  type="button"
                  onclick={cancelSubscription}
                  disabled={isCancelling}
                  class="rounded-lg border border-rose-400/30 bg-rose-400/10 px-4 py-1.5 text-xs font-medium text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-50"
                >
                  {isCancelling ? 'Cancelling...' : 'Yes, cancel'}
                </button>
                <button
                  type="button"
                  onclick={() => (showCancelConfirm = false)}
                  class="text-xs text-slate-500 transition hover:text-slate-300"
                >
                  Keep subscription
                </button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    </article>

  {:else}
    <!-- Pricing cards -->
    <div class="grid gap-4 lg:grid-cols-2">
      <!-- Free tier -->
      <article class="sub-card rounded-2xl border border-white/8 bg-zinc-950 p-6" class:visible={mounted} style="--delay:80ms;">
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Free</p>
        <div class="mt-3 flex items-end gap-1">
          <span class="text-4xl font-black text-white">R0</span>
          <span class="mb-1 text-sm text-slate-600">/ month</span>
        </div>
        <p class="mt-2 text-sm text-slate-500">Browse listings, manage your profile, and get 25 free tokens every month.</p>

        <ul class="mt-5 space-y-2.5">
          {#each freeFeatures as item}
            <li class="flex items-center gap-2.5 text-sm">
              <span class="flex h-4 w-4 flex-none items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-[10px] text-slate-500">✓</span>
              <span class="text-slate-300">{item}</span>
            </li>
          {/each}
          {#each lockedFeatures as item}
            <li class="flex items-center gap-2.5 text-sm opacity-35">
              <span class="flex h-4 w-4 flex-none items-center justify-center rounded-full border border-slate-800 bg-slate-900 text-[10px] text-slate-700">✗</span>
              <span class="text-slate-600 line-through">{item}</span>
            </li>
          {/each}
        </ul>

        <div class="mt-7">
          <span class="rounded-lg border border-white/8 bg-white/4 px-4 py-2 text-xs font-medium text-slate-600">
            Current plan
          </span>
        </div>
      </article>

      <!-- Pro tier -->
      <article
        class="sub-card group relative overflow-hidden rounded-2xl border border-cyan-400/22 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-fuchsia-950/40 p-6 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_24px_60px_-20px_rgba(34,211,238,0.35)]"
        class:visible={mounted}
        style="--delay:160ms;"
      >
        <div class="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-cyan-400/12 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite;"></div>
        <div class="pointer-events-none absolute -bottom-14 -left-10 h-40 w-40 rounded-full bg-fuchsia-400/12 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite; animation-delay:-2s;"></div>

        <div class="relative z-10">
          <div class="flex items-center gap-2.5">
            <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-300/70">Pro</p>
            <span class="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-200">
              Recommended
            </span>
          </div>
          <div class="mt-3 flex items-end gap-1">
            <span class="text-4xl font-black text-white">{formatPrice(monthlyAmount)}</span>
            <span class="mb-1 text-sm text-slate-400">/ month</span>
          </div>
          <p class="mt-2 text-sm text-slate-300">Everything you need to land your next position.</p>

          <ul class="mt-5 space-y-2.5">
            {#each proFeatures as f}
              <li class="flex items-start gap-2.5 text-sm">
                <span class="mt-0.5 flex h-4 w-4 flex-none items-center justify-center rounded-full border border-cyan-400/30 bg-cyan-400/10 text-[10px] text-cyan-400">✓</span>
                <span class="text-slate-200">
                  <span class="font-semibold text-white">{f.label}</span>
                  <span class="text-slate-400"> — {f.desc}</span>
                </span>
              </li>
            {/each}
          </ul>

          <button
            type="button"
            onclick={startCheckout}
            disabled={isLoading}
            class="mt-7 w-full rounded-xl border border-cyan-300/30 bg-cyan-300/10 py-3 text-sm font-bold text-cyan-100 transition-all hover:border-cyan-300/50 hover:bg-cyan-300/18 hover:text-white active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? 'Redirecting to Yoco...' : 'Get CARVER Pro →'}
          </button>
          <p class="mt-2.5 text-center text-[10px] text-slate-600">
            Secure payment via Yoco. Cancel anytime.
          </p>
        </div>
      </article>
    </div>
  {/if}
</section>

<style>
  /* Header scan line */
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
