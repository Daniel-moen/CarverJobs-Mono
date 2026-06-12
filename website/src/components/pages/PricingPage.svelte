<script>
  import { onMount } from 'svelte'
  import { DEFAULT_FIRST_PURCHASE_BONUS, defaultTokenPackages, formatTokenPrice, packSavings } from '../../config/subscriptionCheckout'

  let mounted = $state(false)
  const packages = defaultTokenPackages()
  const firstPurchaseBonus = DEFAULT_FIRST_PURCHASE_BONUS

  function perToken(pkg) {
    const v = pkg.price_per_token || (pkg.tokens ? (parseFloat(pkg.price) / pkg.tokens).toFixed(2) : pkg.price)
    return formatTokenPrice(v)
  }

  onMount(() => requestAnimationFrame(() => (mounted = true)))
</script>

<div class="min-h-screen bg-black text-slate-100">
  <main class="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6">
    <a href="/" class="text-sm text-slate-400 transition hover:text-slate-200">← Home</a>

    <!-- Hero -->
    <header class="mt-8 text-center">
      <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Pricing</p>
      <h1 class="mt-3 text-3xl font-black tracking-tight text-white sm:text-4xl">Simple, pay-as-you-go tokens</h1>
      <p class="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
        No subscriptions, no lock-in. Buy a pack of tokens and spend them whenever you need to.
        One token runs one job-matching session. Tokens never expire.
      </p>
      {#if firstPurchaseBonus > 0}
        <p class="mx-auto mt-4 inline-flex items-center gap-2 rounded-full border border-amber-300/25 bg-amber-300/10 px-4 py-1.5 text-xs font-semibold text-amber-100">
          🎁 New here? Get +{firstPurchaseBonus} bonus tokens free with your first purchase.
        </p>
      {/if}
    </header>

    <!-- Token packs -->
    <div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {#each packages as pkg, i}
        {@const isPopular = pkg.highlight || pkg.badge === 'Best Value'}
        {@const savings = packSavings(pkg, packages)}
        <article
          class="price-card group relative overflow-hidden rounded-2xl border p-6 transition-all duration-300 hover:-translate-y-0.5 {isPopular
            ? 'border-cyan-400/22 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-fuchsia-950/40'
            : 'border-white/8 bg-zinc-950 hover:border-white/15'}"
          class:visible={mounted}
          style="--delay:{80 + i * 70}ms;"
        >
          <div class="relative z-10">
            <div class="flex items-center gap-2.5">
              <p class="text-[10px] font-bold uppercase tracking-[0.28em] {isPopular ? 'text-cyan-300/70' : 'text-slate-500'}">
                {pkg.label || `${pkg.tokens} Token Pack`}
              </p>
              {#if pkg.badge}
                <span class="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-200">
                  {pkg.badge}
                </span>
              {/if}
            </div>

            <div class="mt-3 flex items-end gap-2">
              <span class="text-4xl font-black text-white">{formatTokenPrice(pkg.price)}</span>
              {#if savings}
                <span class="mb-1 text-sm text-slate-500 line-through">{formatTokenPrice(savings.anchor)}</span>
              {/if}
            </div>
            <p class="mt-1 text-sm {isPopular ? 'text-slate-300' : 'text-slate-500'}">
              {pkg.tokens} tokens · {perToken(pkg)} each
              {#if savings}
                <span class="ml-1 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300">Save {formatTokenPrice(savings.savings)}</span>
              {/if}
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
                <span class="{isPopular ? 'text-slate-200' : 'text-slate-300'}">Buy more anytime</span>
              </li>
            </ul>

            <a
              href="/signup"
              class="mt-6 block w-full rounded-xl border py-3 text-center text-sm font-bold transition-all active:scale-95 {isPopular
                ? 'border-cyan-300/30 bg-cyan-300/10 text-cyan-100 hover:border-cyan-300/50 hover:bg-cyan-300/18 hover:text-white'
                : 'border-white/12 bg-white/5 text-slate-200 hover:border-white/25 hover:bg-white/10 hover:text-white'}"
            >
              Get started
            </a>
          </div>
        </article>
      {/each}
    </div>

    <!-- Recruiters / agencies -->
    <section class="price-card mt-6 rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:flex sm:items-center sm:justify-between sm:gap-6" class:visible={mounted} style="--delay:440ms;">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">For agencies &amp; recruiters</p>
        <h2 class="mt-2 text-lg font-bold text-white">Pay only for the crew you want to reach</h2>
        <p class="mt-1.5 max-w-xl text-sm text-slate-400">
          Browse matched candidates for free. Spend 5 tokens to unlock a candidate's contact details —
          once unlocked, they stay open for you to revisit at no extra cost.
        </p>
        <p class="mt-2 max-w-xl text-xs text-slate-500">
          In recruiter terms: Starter ≈ 1 unlock · Standard ≈ 4 unlocks · Premium ≈ 15 unlocks.
        </p>
      </div>
      <a
        href="/signup/agency"
        class="mt-4 inline-block shrink-0 rounded-xl border border-white/12 bg-white/5 px-5 py-3 text-center text-sm font-bold text-slate-200 transition-all hover:border-white/25 hover:bg-white/10 hover:text-white active:scale-95 sm:mt-0"
      >
        Create an agency account
      </a>
    </section>

    <!-- Refund / trust note -->
    <p class="mt-8 text-center text-sm text-slate-500">
      Secure payment via Yoco · No recurring charges · Prices in ZAR.<br class="hidden sm:block" />
      Changed your mind? Unused tokens are refundable within 14 days — see our
      <a href="/refund-policy" class="text-cyan-400 underline-offset-4 transition hover:text-cyan-300 hover:underline">Refund Policy</a>.
    </p>

    <nav class="mt-10 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[12px] text-slate-500" aria-label="Legal">
      <a href="/refund-policy" class="transition hover:text-white">Refund Policy</a>
      <a href="/terms" class="transition hover:text-white">Terms</a>
      <a href="/privacy" class="transition hover:text-white">Privacy</a>
    </nav>
  </main>
</div>

<style>
  .price-card {
    opacity: 0;
    transform: translateY(14px);
    transition: opacity 0.45s ease, transform 0.45s ease, border-color 0.25s, box-shadow 0.25s, translate 0.2s;
    transition-delay: var(--delay, 0ms);
  }
  .price-card.visible {
    opacity: 1;
    transform: translateY(0);
  }
</style>
