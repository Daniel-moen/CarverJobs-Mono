<script>
  import { onMount } from 'svelte'
  import {
    DEFAULT_TOKEN_PRICE,
    defaultTokenPackages,
    formatTokenPrice,
    loadSubscriptionStatus,
    readCheckoutReturnStatus,
    startSubscriptionCheckout,
  } from '../../config/subscriptionCheckout'

  export let onNavigate = () => {}

  let mounted = false
  let isLoading = null
  let checkoutError = ''
  let returnStatus = ''
  let balance = 0
  let tokenPrice = DEFAULT_TOKEN_PRICE
  let packages = defaultTokenPackages()

  function formatPrice(amountStr) {
    return formatTokenPrice(amountStr)
  }

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    returnStatus = readCheckoutReturnStatus()
    try {
      const data = await loadSubscriptionStatus()
      if (data) {
        if (data.balance != null) balance = data.balance
        if (data.token_price) tokenPrice = data.token_price
        if (data.packages) packages = data.packages
      }
    } catch { /* fallback to defaults */ }
  })

  async function startCheckout(tokens) {
    isLoading = tokens
    checkoutError = ''
    try {
      const data = await startSubscriptionCheckout(tokens)
      if (data.redirect_url) {
        window.location.href = data.redirect_url
        return
      }
      checkoutError = 'Could not start checkout. Please try again.'
    } catch (error) {
      checkoutError = error?.message || 'Could not reach the server. Please try again.'
    } finally {
      isLoading = null
    }
  }
</script>

<section class="ws-root" class:visible={mounted}>
  {#if returnStatus === 'success'}
    <div class="ws-card ws-card-success">
      <div class="ws-state-icon ws-state-icon-success" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="9"/>
          <path d="M8 12.5l3 3 5-6"/>
        </svg>
      </div>
      <p class="ws-eyebrow ws-eyebrow-radium">
        <span class="ws-pip ws-pip-radium" aria-hidden="true"></span>
        Payment received
      </p>
      <h1 class="ws-title">Tokens added to your account</h1>
      <p class="ws-body">Your payment is being confirmed. Tokens will appear in your balance within a minute.</p>
      <button
        type="button"
        onclick={() => onNavigate('profile')}
        class="ws-cta-primary"
      >
        Go to profile
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M13 5l7 7-7 7"/></svg>
      </button>
      <p class="ws-foot">Send any message on WhatsApp to continue.</p>
    </div>

  {:else if returnStatus === 'cancelled'}
    <div class="ws-card">
      <div class="ws-state-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 14l-4-4 4-4"/>
          <path d="M5 10h9a6 6 0 0 1 0 12"/>
        </svg>
      </div>
      <p class="ws-eyebrow">Checkout cancelled</p>
      <h1 class="ws-title">No charge was made.</h1>
      <p class="ws-body">You can try again whenever you're ready.</p>
      <button
        type="button"
        onclick={() => (returnStatus = '')}
        class="ws-cta-primary"
      >
        Try again
      </button>
    </div>

  {:else if returnStatus === 'failed'}
    <div class="ws-card ws-card-failed">
      <div class="ws-state-icon ws-state-icon-garnet" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3L2 21h20L12 3z"/>
          <path d="M12 10v4M12 17.5v.01"/>
        </svg>
      </div>
      <p class="ws-eyebrow ws-eyebrow-garnet">Payment failed</p>
      <h1 class="ws-title">You were not charged.</h1>
      <p class="ws-body">Please try again or use a different payment method.</p>
      <button
        type="button"
        onclick={() => (returnStatus = '')}
        class="ws-cta-primary"
      >
        Try again
      </button>
    </div>

  {:else}
    <!-- Main buy-tokens card -->
    <div class="ws-card ws-card-main">
      <div class="ws-glow" aria-hidden="true"></div>

      <header class="ws-head">
        <p class="ws-eyebrow">
          <span class="ws-pip" aria-hidden="true"></span>
          Carver tokens
        </p>
        <h1 class="ws-title ws-title-lg">Buy tokens</h1>
        <p class="ws-price-line">
          <span class="ws-price-amount">{formatPrice(tokenPrice)}</span>
          <span class="ws-price-unit">per token</span>
          <span class="ws-price-dot" aria-hidden="true">·</span>
          <span class="ws-price-unit">no recurring charges</span>
        </p>

        <div class="ws-balance">
          <span class="ws-balance-label">Balance</span>
          <span class="ws-balance-num">{balance}</span>
          <span class="ws-balance-unit">{balance === 1 ? 'token' : 'tokens'}</span>
        </div>
      </header>

      {#if checkoutError}
        <p class="ws-error">{checkoutError}</p>
      {/if}

      <div class="ws-packages">
        {#each packages as pkg, i}
          {@const isPopular = i === 1}
          <button
            type="button"
            onclick={() => startCheckout(pkg.tokens)}
            disabled={isLoading !== null}
            class="ws-pkg"
            class:is-popular={isPopular}
          >
            {#if isPopular}
              <span class="ws-pkg-flag">Best value</span>
            {/if}
            <div class="ws-pkg-row">
              <div class="ws-pkg-lead">
                <span class="ws-pkg-tokens">{pkg.tokens}</span>
                <span class="ws-pkg-tokens-label">tokens</span>
              </div>
              <div class="ws-pkg-meta">
                <span class="ws-pkg-runs">{pkg.tokens} matching runs</span>
              </div>
              <div class="ws-pkg-price">
                {#if isLoading === pkg.tokens}
                  <span class="ws-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                {:else}
                  <span class="ws-pkg-price-amount">{formatPrice(pkg.price)}</span>
                {/if}
              </div>
            </div>
          </button>
        {/each}
      </div>

      <p class="ws-foot ws-foot-seal">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        Secure payment via Yoco · no recurring charges
      </p>
    </div>
  {/if}
</section>

<style>
  .ws-root {
    max-width: 32rem;
    margin: 0 auto;
    opacity: 0;
    transform: translateY(14px);
    transition:
      opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.45s cubic-bezier(0.22, 1, 0.36, 1);
  }
  .ws-root.visible { opacity: 1; transform: translateY(0); }

  @media (prefers-reduced-motion: reduce) {
    .ws-root { opacity: 1 !important; transform: none !important; transition: none !important; }
  }

  /* ── Card shell ────────────────────────────────────────────────── */
  .ws-card {
    position: relative;
    overflow: hidden;
    padding: 2rem 1.5rem;
    border-radius: 1rem;
    border: 1px solid rgba(201, 169, 110, 0.22);
    background:
      radial-gradient(80% 60% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      linear-gradient(180deg, #0a1015 0%, #050a0e 100%);
    box-shadow:
      inset 0 1px 0 rgba(201, 169, 110, 0.08),
      0 30px 80px -40px rgba(0, 0, 0, 0.7);
    text-align: center;
  }
  @media (min-width: 520px) { .ws-card { padding: 2.5rem 2rem; } }

  .ws-card-success { border-color: rgba(141, 240, 196, 0.35); }
  .ws-card-failed { border-color: rgba(190, 120, 100, 0.4); }

  .ws-glow {
    position: absolute;
    top: -100px;
    right: -80px;
    width: 280px;
    height: 280px;
    border-radius: 9999px;
    background: radial-gradient(closest-side, rgba(201, 169, 110, 0.12), transparent 70%);
    filter: blur(50px);
    pointer-events: none;
  }

  /* ── Shared typographic elements ──────────────────────────────── */
  .ws-eyebrow {
    margin: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
  }
  .ws-eyebrow-radium { color: var(--radium); }
  .ws-eyebrow-garnet { color: #e09286; }

  .ws-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 0 3px rgba(201, 169, 110, 0.18);
  }
  .ws-pip-radium {
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.2);
  }

  .ws-title {
    margin: 0.75rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    font-size: 1.65rem;
    line-height: 1.2;
    letter-spacing: -0.022em;
    color: var(--ivory);
  }
  .ws-title-lg {
    font-size: clamp(2.1rem, 6vw, 2.75rem);
    line-height: 1.05;
  }

  .ws-body {
    margin: 0.7rem 0 0;
    font-size: 14px;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  .ws-foot {
    margin: 1.25rem 0 0;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .ws-foot-seal {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--brass);
    opacity: 0.8;
  }
  .ws-foot-seal svg { width: 12px; height: 12px; }

  /* ── State icons (cancelled/failed/success) ───────────────────── */
  .ws-state-icon {
    width: 44px;
    height: 44px;
    margin: 0 auto 1rem;
    color: var(--brass);
    opacity: 0.85;
  }
  .ws-state-icon-success { color: var(--radium); }
  .ws-state-icon-garnet { color: #e09286; }

  /* ── Main card head ───────────────────────────────────────────── */
  .ws-head {
    position: relative;
    padding-bottom: 1.25rem;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.22);
  }

  .ws-price-line {
    margin: 0.9rem 0 0;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    color: var(--text-muted);
    text-transform: uppercase;
  }
  .ws-price-amount {
    color: var(--ivory);
    font-family: var(--font-serif);
    font-style: italic;
    font-weight: 400;
    font-size: 14px;
    letter-spacing: 0;
    text-transform: none;
  }
  .ws-price-unit { color: var(--text-muted); }
  .ws-price-dot { margin: 0 0.35rem; opacity: 0.5; }

  .ws-balance {
    margin-top: 1rem;
    display: inline-flex;
    align-items: baseline;
    gap: 0.45rem;
    padding: 0.5rem 0.9rem;
    border-radius: 9999px;
    background: rgba(243, 234, 216, 0.04);
    border: 1px solid rgba(201, 169, 110, 0.2);
  }
  .ws-balance-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
    opacity: 0.8;
  }
  .ws-balance-num {
    font-family: var(--font-serif);
    font-weight: 400;
    font-size: 1.5rem;
    color: var(--ivory);
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }
  .ws-balance-unit {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  /* ── Error banner ─────────────────────────────────────────────── */
  .ws-error {
    margin: 1.25rem 0 0;
    padding: 0.7rem 0.9rem;
    border-radius: 0.55rem;
    font-size: 13px;
    text-align: left;
    color: #ecb4a7;
    background: rgba(190, 90, 70, 0.08);
    border: 1px solid rgba(190, 90, 70, 0.3);
  }

  /* ── Package tiles ────────────────────────────────────────────── */
  .ws-packages {
    margin-top: 1.5rem;
    display: grid;
    gap: 0.7rem;
    text-align: left;
  }

  .ws-pkg {
    position: relative;
    width: 100%;
    padding: 1.1rem 1.1rem;
    border-radius: 0.75rem;
    border: 1px solid rgba(201, 169, 110, 0.2);
    background:
      radial-gradient(120% 80% at 100% 0%, rgba(201, 169, 110, 0.03), transparent 60%),
      rgba(243, 234, 216, 0.02);
    cursor: pointer;
    transition: border-color 0.18s ease, background 0.18s ease, transform 0.2s ease;
    text-align: left;
    min-height: 68px;
  }
  .ws-pkg:hover:not(:disabled) {
    border-color: rgba(201, 169, 110, 0.4);
    background: rgba(201, 169, 110, 0.05);
    transform: translateY(-1px);
  }
  .ws-pkg:disabled { opacity: 0.55; cursor: not-allowed; }

  .ws-pkg.is-popular {
    border-color: rgba(216, 198, 154, 0.45);
    background:
      radial-gradient(120% 80% at 100% 0%, rgba(216, 198, 154, 0.08), transparent 60%),
      rgba(216, 198, 154, 0.04);
  }
  .ws-pkg.is-popular:hover:not(:disabled) {
    border-color: rgba(216, 198, 154, 0.65);
  }

  .ws-pkg-flag {
    position: absolute;
    top: -9px;
    left: 1rem;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-family: var(--font-mono);
    font-size: 9px;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: #06090d;
    background: linear-gradient(180deg, #fbf3df 0%, #ead7a7 100%);
    border: 1px solid rgba(216, 198, 154, 0.55);
    box-shadow: 0 6px 18px -8px rgba(216, 198, 154, 0.45);
  }

  .ws-pkg-row {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.75rem;
  }

  .ws-pkg-lead {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    min-width: 60px;
  }
  .ws-pkg-tokens {
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    font-size: 2rem;
    line-height: 1;
    color: var(--ivory);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }
  .ws-pkg.is-popular .ws-pkg-tokens {
    color: var(--brass-bright);
    text-shadow: 0 0 22px rgba(201, 169, 110, 0.25);
  }
  .ws-pkg-tokens-label {
    margin-top: 0.15rem;
    font-family: var(--font-mono);
    font-size: 9px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
    opacity: 0.75;
  }

  .ws-pkg-meta { min-width: 0; }
  .ws-pkg-runs {
    font-size: 12.5px;
    color: var(--text-muted);
  }

  .ws-pkg-price {
    display: inline-flex;
    align-items: baseline;
  }
  .ws-pkg-price-amount {
    font-family: var(--font-serif);
    font-weight: 400;
    font-size: 1.35rem;
    color: var(--ivory);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .ws-pkg.is-popular .ws-pkg-price-amount { color: var(--brass-bright); }

  /* CTA (success/cancelled/failed states) */
  .ws-cta-primary {
    margin-top: 1.5rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.85rem 1.4rem;
    border-radius: 9999px;
    font-size: 13px;
    font-weight: 600;
    color: #06090d;
    background: linear-gradient(180deg, #fbf3df 0%, #ead7a7 100%);
    border: 1px solid rgba(216, 198, 154, 0.55);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.55) inset,
      0 16px 40px -18px rgba(216, 198, 154, 0.45);
    cursor: pointer;
    transition: transform 0.2s ease, filter 0.2s ease;
    min-height: 44px;
  }
  .ws-cta-primary:hover { filter: brightness(1.04); transform: translateY(-1px); }
  .ws-cta-primary svg { width: 13px; height: 13px; }

  /* Loading dots for in-progress checkout */
  .ws-dots {
    display: inline-flex;
    gap: 0.25rem;
  }
  .ws-dots i {
    width: 5px;
    height: 5px;
    border-radius: 9999px;
    background: var(--brass);
    opacity: 0.5;
    animation: wsDot 1.2s ease-in-out infinite;
  }
  .ws-dots i:nth-child(2) { animation-delay: 0.15s; }
  .ws-dots i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes wsDot {
    0%, 60%, 100% { opacity: 0.35; transform: translateY(0); }
    30%           { opacity: 1; transform: translateY(-2px); }
  }
  @media (prefers-reduced-motion: reduce) {
    .ws-dots i { animation: none; opacity: 0.7; }
  }
</style>
