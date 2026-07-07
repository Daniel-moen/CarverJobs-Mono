<script>
  /**
   * TokenPacksSection — the money section, shared by the landing pages and
   * the public /pricing page.
   *
   * Persuasion architecture:
   *  - "Free to start" is restated up top so price never reads as a gate.
   *  - Packs come from the same DEFAULT_TOKEN_PACKAGES the checkout uses,
   *    with strikethrough anchors + "Save RX" from packSavings() — display
   *    math only, prices unchanged.
   *  - The highlighted pack (Premium / Best Value) is visually dominant;
   *    the Plus pack is the decoy that makes it look obviously right.
   *  - First-purchase bonus (+5 tokens) is a real webhook-credited offer.
   *  - Two purchase paths: web signup, or "buy tokens" typed in WhatsApp
   *    (in-chat Yoco link, shipped Jul 2026).
   */
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'
  import {
    DEFAULT_FIRST_PURCHASE_BONUS,
    defaultTokenPackages,
    formatTokenPrice,
    packSavings,
  } from '../../config/subscriptionCheckout'

  /** @type {{ source?: string }} */
  let { source = 'landing' } = $props()

  const packages = defaultTokenPackages()
  const bonus = DEFAULT_FIRST_PURCHASE_BONUS

  function perToken(pkg) {
    const v = pkg.price_per_token || (pkg.tokens ? (parseFloat(pkg.price) / pkg.tokens).toFixed(2) : pkg.price)
    return formatTokenPrice(v)
  }

  // Count-up on the big prices the first time the grid scrolls into view.
  // Initialised at the true values so nothing is ever wrong if the observer
  // doesn't fire; the animation just replays 0 → value once, on sight.
  const priceTargets = packages.map((p) => Math.round(parseFloat(p.price)))
  let shownPrices = $state([...priceTargets])
  /** @type {HTMLElement|null} */
  let gridEl = $state(null)

  onMount(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let played = false
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting || played) continue
          played = true
          io.disconnect()
          const t0 = performance.now()
          const dur = 900
          const tick = (t) => {
            const k = Math.min(1, (t - t0) / dur)
            const ease = 1 - Math.pow(1 - k, 3)
            shownPrices = priceTargets.map((v) => Math.round(v * ease))
            if (k < 1) requestAnimationFrame(tick)
          }
          shownPrices = priceTargets.map(() => 0)
          requestAnimationFrame(tick)
        }
      },
      { threshold: 0.25 },
    )
    if (gridEl) io.observe(gridEl)
    return () => io.disconnect()
  })
</script>

<section id="pricing" class="packs" aria-labelledby="packs-title">
  <div class="packs-inner">
    <header class="packs-head">
      <p class="engraved">The ship's ledger</p>
      <h2 id="packs-title" class="packs-title">
        Pay per <span class="serif-accent">match</span>, not per month.
      </h2>
      <p class="packs-lede">
        Your first two match runs are free. After that, one token buys one full run —
        every live role scanned, ranked against your profile, application emails drafted.
        <strong>No subscription. Tokens never expire.</strong>
      </p>
      <span class="head-rule" aria-hidden="true"></span>
      {#if bonus > 0}
        <p class="packs-bonus">
          <span class="packs-bonus-gift" aria-hidden="true">🎁</span>
          First pack? We add <strong>+{bonus} bonus tokens</strong> — free, on any pack.
        </p>
      {/if}
    </header>

    <div class="packs-grid" bind:this={gridEl}>
      {#each packages as pkg, i (pkg.tokens)}
        {@const savings = packSavings(pkg, packages)}
        {@const hot = pkg.highlight || pkg.badge === 'Best Value'}
        <article class="pack instrument" class:pack-hot={hot} style="--i:{i}">
          {#if pkg.badge}
            <span class="pack-badge" class:pack-badge-hot={hot}>{pkg.badge}</span>
          {/if}
          <p class="pack-label engraved">{pkg.label}</p>
          <div class="pack-price">
            <span class="pack-amount readout">R{shownPrices[i]}</span>
            {#if savings}
              <span class="pack-anchor">{formatTokenPrice(savings.anchor)}</span>
            {/if}
          </div>
          <p class="pack-tokens">
            <strong>{pkg.tokens} tokens</strong> · {perToken(pkg)} per match run
            {#if savings}
              <span class="pack-save">Save {formatTokenPrice(savings.savings)}</span>
            {/if}
          </p>
          <ul class="pack-points">
            <li>{pkg.tokens} full matching runs</li>
            <li>Application emails drafted for you</li>
            <li>Never expires · buy more anytime</li>
          </ul>
          <a
            href="/signup"
            class="pack-cta {hot ? 'cta-brass cta-shine' : ''}"
            class:pack-cta-quiet={!hot}
            onclick={() => trackEvent('pack_cta_click', { page: source, value: String(pkg.tokens) })}
          >
            Get {pkg.tokens} tokens
          </a>
        </article>
      {/each}
    </div>

    <div class="packs-wa">
      <p>
        Already chatting with Carver? Just text
        <a
          href={whatsapp.link('buy tokens')}
          target="_blank"
          rel="noopener noreferrer"
          class="packs-wa-cmd"
          onclick={() => trackEvent('pricing_wa_buy_tokens', { page: source })}
        >buy tokens</a>
        in WhatsApp — pick a pack and pay right in the chat.
      </p>
    </div>

    <p class="packs-trust">
      Secure payment via Yoco · Prices in ZAR · No recurring charges ·
      Unused tokens refundable within 14 days — <a href="/refund-policy">refund policy</a>
    </p>
  </div>
</section>

<style>
  .packs {
    position: relative;
    padding: 5.5rem 1rem 5rem;
    background:
      radial-gradient(60% 45% at 50% 0%, rgba(201, 169, 110, 0.06), transparent 70%),
      var(--bg-bridge);
    border-top: 1px solid rgba(201, 169, 110, 0.14);
  }
  @media (min-width: 768px) { .packs { padding: 7rem 1.5rem 6rem; } }

  .packs-inner { max-width: 1200px; margin: 0 auto; }

  .packs-head { text-align: center; max-width: 46rem; margin: 0 auto; }
  .packs-title {
    margin: 1rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 5vw, 3.4rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }
  .packs-lede {
    margin: 1.25rem auto 0;
    color: var(--text-secondary);
    font-size: 0.98rem;
    line-height: 1.65;
    max-width: 38rem;
  }
  .packs-lede strong { color: var(--ivory); font-weight: 500; }

  .head-rule {
    display: block;
    width: 76px;
    height: 2px;
    margin: 1.3rem auto 0;
    background: linear-gradient(90deg, transparent, var(--brass), transparent);
    transform: scaleX(0);
  }
  :global([data-visible='true']) .head-rule {
    animation: rule-draw 0.9s cubic-bezier(0.22, 1, 0.36, 1) 0.35s forwards;
  }
  @keyframes rule-draw {
    to { transform: scaleX(1); }
  }
  /* Outside a reveal wrapper (the /pricing page) the rule is simply drawn. */
  :global(.pricing) .head-rule { transform: scaleX(1); }

  .packs-bonus {
    margin: 1.4rem auto 0;
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.55rem 1.1rem;
    border-radius: 9999px;
    border: 1px solid rgba(230, 201, 140, 0.4);
    background: rgba(201, 169, 110, 0.1);
    color: var(--brass-bright);
    font-size: 13px;
  }
  .packs-bonus strong { color: var(--ivory); }

  .packs-grid {
    margin-top: 3rem;
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
    align-items: stretch;
  }
  @media (min-width: 640px)  { .packs-grid { grid-template-columns: repeat(2, 1fr); } }
  @media (min-width: 1024px) { .packs-grid { grid-template-columns: repeat(4, 1fr); gap: 1.1rem; } }

  .pack {
    position: relative;
    display: flex;
    flex-direction: column;
    padding: 1.6rem 1.4rem 1.5rem;
    transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
  }
  .pack:hover { transform: translateY(-3px); border-color: rgba(201, 169, 110, 0.4); }

  /* Cards cascade in when the reveal wrapper flips visible. */
  :global([data-visible='true']) .pack {
    animation: pack-in 0.65s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--i, 0) * 110ms + 120ms);
  }
  @keyframes pack-in {
    from { opacity: 0; transform: translateY(26px); }
  }

  .pack-hot {
    border-color: rgba(230, 201, 140, 0.55);
    background:
      radial-gradient(90% 70% at 50% 0%, rgba(201, 169, 110, 0.14), transparent 70%),
      linear-gradient(180deg, #0d1116 0%, #060a0e 100%);
    box-shadow:
      inset 0 1px 0 rgba(201, 169, 110, 0.18),
      0 0 0 1px rgba(201, 169, 110, 0.12),
      0 34px 70px -38px rgba(201, 169, 110, 0.4);
  }
  @media (min-width: 1024px) {
    .pack-hot { transform: scale(1.04); }
    .pack-hot:hover { transform: scale(1.04) translateY(-3px); }
  }
  /* The Best Value card breathes — a slow brass glow, after it has entered. */
  :global([data-visible='true']) .pack-hot {
    animation:
      pack-in 0.65s cubic-bezier(0.22, 1, 0.36, 1) backwards,
      pack-breathe 4.5s ease-in-out 1.2s infinite;
    animation-delay: calc(var(--i, 0) * 110ms + 120ms), 1.2s;
  }
  @keyframes pack-breathe {
    0%, 100% {
      box-shadow:
        inset 0 1px 0 rgba(201, 169, 110, 0.18),
        0 0 0 1px rgba(201, 169, 110, 0.12),
        0 34px 70px -38px rgba(201, 169, 110, 0.4);
    }
    50% {
      box-shadow:
        inset 0 1px 0 rgba(201, 169, 110, 0.26),
        0 0 0 1px rgba(230, 201, 140, 0.28),
        0 34px 95px -34px rgba(201, 169, 110, 0.65);
    }
  }

  .pack-badge {
    position: absolute;
    top: -11px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
    padding: 0.25rem 0.8rem;
    border-radius: 9999px;
    font-family: var(--font-mono);
    font-size: 9.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    background: #10151c;
    border: 1px solid rgba(141, 240, 196, 0.4);
    color: var(--radium);
  }
  .pack-badge-hot {
    background: linear-gradient(180deg, #f0d59a 0%, #c9a96e 100%);
    border-color: rgba(230, 201, 140, 0.8);
    color: #1a1206;
    font-weight: 600;
  }

  .pack-label { display: block; margin: 0.35rem 0 0; }
  .pack-price {
    margin-top: 0.9rem;
    display: flex;
    align-items: baseline;
    gap: 0.55rem;
  }
  .pack-amount { font-size: 2.1rem; }
  .pack-anchor {
    color: var(--text-muted);
    font-size: 0.95rem;
    text-decoration: line-through;
    text-decoration-color: rgba(255, 255, 255, 0.35);
  }
  .pack-tokens {
    margin: 0.45rem 0 0;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.5;
  }
  .pack-tokens strong { color: var(--ivory); font-weight: 500; }
  .pack-save {
    display: inline-block;
    margin-left: 0.4rem;
    padding: 0.1rem 0.5rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.35);
    background: rgba(141, 240, 196, 0.08);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .pack-points {
    list-style: none;
    margin: 1.15rem 0 1.4rem;
    padding: 0.9rem 0 0;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    display: grid;
    gap: 0.5rem;
    flex: 1;
  }
  .pack-points li {
    position: relative;
    padding-left: 1.1rem;
    color: var(--text-secondary);
    font-size: 12.5px;
    line-height: 1.45;
  }
  .pack-points li::before {
    content: "✓";
    position: absolute;
    left: 0;
    color: var(--brass);
    font-size: 11px;
  }

  .pack-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.8rem 1rem;
    border-radius: 9999px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    text-align: center;
  }
  .pack-cta-quiet {
    color: var(--ivory);
    border: 1px solid rgba(243, 234, 216, 0.22);
    background: rgba(243, 234, 216, 0.05);
    transition: background 0.2s ease, border-color 0.2s ease;
  }
  .pack-cta-quiet:hover {
    background: rgba(243, 234, 216, 0.11);
    border-color: rgba(243, 234, 216, 0.38);
  }

  .packs-wa {
    margin: 2.4rem auto 0;
    max-width: 34rem;
    text-align: center;
    padding: 1rem 1.4rem;
    border-radius: 14px;
    border: 1px solid rgba(37, 211, 102, 0.25);
    background: rgba(37, 211, 102, 0.05);
  }
  .packs-wa p { margin: 0; color: var(--text-secondary); font-size: 13.5px; line-height: 1.6; }
  .packs-wa-cmd {
    font-family: var(--font-mono);
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 6px;
    background: rgba(37, 211, 102, 0.14);
    border: 1px solid rgba(37, 211, 102, 0.35);
    color: #a7f3c4;
    text-decoration: none;
    white-space: nowrap;
  }
  .packs-wa-cmd:hover { background: rgba(37, 211, 102, 0.22); }

  .packs-trust {
    margin: 1.75rem auto 0;
    text-align: center;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.7;
    max-width: 40rem;
  }
  .packs-trust a {
    color: var(--text-secondary);
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-color: rgba(255, 255, 255, 0.25);
  }
  .packs-trust a:hover { color: var(--ivory); }
</style>
