<script>
  /**
   * MobileMarketingPage — the small-screen conversion ladder.
   *
   * Same beats as the desktop LandingPage (offer → demo → how → compare →
   * pricing → agencies → FAQ → finale) but stacked, with the live chat
   * right under the CTA and a sticky bottom bar that keeps "Start free"
   * one thumb-tap away for the whole scroll.
   *
   * The section components (TypingChat / BridgeConsole / RouteMap /
   * CompareSection / TokenPacksSection / AgencySection / FaqSection)
   * are shared with the desktop page; no logic is forked.
   */
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'
  import TypingChat from '../sections/TypingChat.svelte'
  import RoleTicker from '../sections/RoleTicker.svelte'
  import ScrollProgress from '../sections/ScrollProgress.svelte'
  import BridgeConsole from '../sections/BridgeConsole.svelte'
  import RouteMap from '../sections/RouteMap.svelte'
  import CompareSection from '../sections/CompareSection.svelte'
  import TokenPacksSection from '../sections/TokenPacksSection.svelte'
  import AgencySection from '../sections/AgencySection.svelte'
  import FaqSection from '../sections/FaqSection.svelte'
  import StickyCtaBar from '../sections/StickyCtaBar.svelte'

  // `onStartMatch` accepted for router compatibility; unused on this page.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  let { onSignIn = () => {}, onAgencySignup = () => {}, onStartMatch = () => {} } = $props()

  const startMessage = "Hi Carver — I'd like to start matching to yacht roles."

  let chatPaused = $state(false)
  /** @type {HTMLElement|null} */
  let chatHost = $state(null)

  onMount(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      document.querySelectorAll('[data-animate]').forEach((el) => {
        /** @type {HTMLElement} */ (el).dataset.visible = 'true'
      })
    }

    const reveal = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue
          const target = /** @type {HTMLElement} */ (e.target)
          target.dataset.visible = 'true'
          if (target.hasAttribute('data-stagger')) {
            target.querySelectorAll(':scope > *').forEach((child, idx) => {
              const c = /** @type {HTMLElement} */ (child)
              c.style.transitionDelay = `${idx * 80}ms`
              c.dataset.visible = 'true'
            })
          }
          reveal.unobserve(target)
        }
      },
      { threshold: 0.08, rootMargin: '0px 0px -4% 0px' },
    )
    if (!prefersReduced) {
      document.querySelectorAll('[data-animate]').forEach((el) => reveal.observe(el))
    }

    const visibility = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.target === chatHost) chatPaused = !e.isIntersecting
        }
      },
      { threshold: 0.1 },
    )
    if (chatHost) visibility.observe(chatHost)

    const depths = new Set()
    function onScroll() {
      const denom = document.body.scrollHeight || 1
      const pct = Math.round(((window.scrollY + window.innerHeight) / denom) * 100)
      for (const t of [25, 50, 75, 100]) {
        if (pct >= t && !depths.has(t)) {
          depths.add(t)
          trackEvent('scroll_depth', { page: 'landing-mobile', value: String(t) })
        }
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()

    return () => {
      reveal.disconnect()
      visibility.disconnect()
      window.removeEventListener('scroll', onScroll)
    }
  })
</script>

<div class="m-landing">
  <ScrollProgress />

  <!-- ── Mobile nav ─────────────────────────────────────────── -->
  <nav class="m-nav">
    <a href="/" class="m-brand">
      <span class="m-pip" aria-hidden="true"></span>
      <span class="wordmark text-[12px] text-ivory">CARVER</span>
      <span class="font-display italic text-[12px] text-brass">v3</span>
    </a>
    <div class="m-nav-right">
      <button type="button" onclick={() => onSignIn('mobile_nav')} class="m-nav-signin">Sign in</button>
      <a
        href={whatsapp.link(startMessage)}
        target="_blank"
        rel="noopener noreferrer"
        onclick={() => trackEvent('mobile_nav_whatsapp')}
        class="cta-wa m-nav-start"
      >
        <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
        Start free
      </a>
    </div>
  </nav>

  <!-- ── Hero ───────────────────────────────────────────────── -->
  <section class="m-hero">
    <div class="m-hero-bg" aria-hidden="true">
      <div class="m-hero-grid"></div>
      <div class="m-hero-glow"></div>
    </div>

    <p class="m-offer m-enter" style="--e:0">
      <span class="m-offer-dot" aria-hidden="true"></span>
      Free to start · 2 match runs on us
    </p>

    <h1 class="m-title">
      <span class="m-title-line"><span class="m-line-inner" style="--l:0">Every live</span></span>
      <span class="m-title-line"><span class="m-line-inner" style="--l:1">yacht job.</span></span>
      <span class="m-title-line"><span class="m-line-inner" style="--l:2">
        <span class="font-hand text-brass m-title-hand">One text:</span>
        <span class="m-title-mark">“match”</span>
      </span></span>
    </h1>

    <p class="m-lede m-enter" style="--e:1">
      Carver runs your whole superyacht job hunt inside WhatsApp.
      <strong class="text-ivory">Profile built in chat, every live role scanned on demand,
      application emails drafted for you</strong> — in about 25 seconds.
      No app, no forms, no card.
    </p>

    <div class="m-ctas m-enter" style="--e:2">
      <a
        href={whatsapp.link(startMessage)}
        target="_blank"
        rel="noopener noreferrer"
        onclick={() => trackEvent('mobile_hero_whatsapp')}
        class="cta-wa cta-shine cta-beacon m-cta-primary"
      >
        <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
          <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
        </svg>
        Start free on WhatsApp
      </a>
      <a
        href="/signup"
        onclick={() => trackEvent('mobile_hero_web_signup')}
        class="m-cta-secondary"
      >
        Prefer the website? Create a free account →
      </a>
    </div>

    <!-- Live chat directly under the CTA — proof before scrolling -->
    <div class="m-chat" bind:this={chatHost}>
      <p class="m-chat-tag">
        <span class="m-chat-tag-dot"></span>
        Live demo · real bot replies
      </p>
      <TypingChat paused={chatPaused} />
      <p class="m-chat-foot">
        What you see is what you get — script pulled from the production bot.
      </p>
    </div>

    <ul class="m-trust">
      <li>
        <span class="trust-seal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        </span>
        <span><strong>Applications written for you</strong> — review, send, done</span>
      </li>
      <li>
        <span class="trust-seal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
        </span>
        <span><strong>From R9 per match run</strong> — no subscription, ever</span>
      </li>
      <li>
        <span class="trust-seal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </span>
        <span>Encrypted · EU-hosted · real captains &amp; verified agencies</span>
      </li>
    </ul>
  </section>

  <!-- Ticker — roles & ports marquee -->
  <RoleTicker />

  <!-- Bridge -->
  <div data-animate>
    <BridgeConsole />
  </div>

  <!-- Route -->
  <div data-animate>
    <RouteMap />
  </div>

  <!-- Compare -->
  <div data-animate>
    <CompareSection />
  </div>

  <!-- Pricing -->
  <div data-animate>
    <TokenPacksSection source="landing-mobile" />
  </div>

  <!-- Agencies -->
  <div data-animate>
    <AgencySection {onAgencySignup} />
  </div>

  <!-- FAQ -->
  <div data-animate>
    <FaqSection />
  </div>

  <!-- Final CTA -->
  <section class="m-finale" data-animate>
    <p class="engraved text-radium">All hands</p>
    <h2 class="m-finale-title">
      Your next berth is one
      <span class="font-hand text-brass">message</span>
      away.
    </h2>
    <p class="m-finale-sub">
      Five free match runs. Bonus tokens with your first pack. Never a subscription.
      <strong class="m-finale-urgency">Somewhere right now a captain is reading applications —
      yours should be in the pile.</strong>
    </p>
    <a
      href={whatsapp.link(startMessage)}
      target="_blank"
      rel="noopener noreferrer"
      onclick={() => trackEvent('mobile_finale_whatsapp')}
      class="cta-wa cta-shine cta-beacon m-finale-cta"
    >
      <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
        <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
      </svg>
      Start free on WhatsApp
    </a>
    <a
      href="/signup"
      onclick={() => trackEvent('mobile_finale_web_signup')}
      class="m-finale-secondary"
    >
      Or create a free web account →
    </a>
  </section>

  <!-- Footer -->
  <footer class="m-foot">
    <span class="font-hand text-brass text-base">For the crew, by the crew.</span>
    <div class="m-foot-links">
      <a href="/pricing">Pricing</a>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/data-deletion">Delete data</a>
    </div>
    <p class="m-foot-meta">© {new Date().getFullYear()} Carver · made on the dock</p>
  </footer>

  <StickyCtaBar source="landing-mobile" />
</div>

<style>
  .m-landing {
    background: var(--bg-base);
    color: var(--text-primary);
    overflow-x: hidden;
    min-height: 100vh;
    /* leave room for the sticky CTA bar */
    padding-bottom: 4.5rem;
  }

  /* ── Nav ───────────────────────────────────────────────── */
  .m-nav {
    position: sticky;
    top: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.7rem 1rem max(0.7rem, env(safe-area-inset-top));
    background: rgba(4, 7, 11, 0.85);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  .m-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.45rem;
    text-decoration: none;
  }
  .m-pip {
    width: 5px;
    height: 5px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 6px rgba(201, 169, 110, 0.55);
    align-self: center;
  }
  .m-nav-right {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }
  .m-nav-signin {
    padding: 0.45rem 0.8rem;
    border-radius: 9999px;
    border: 1px solid rgba(243, 234, 216, 0.22);
    background: rgba(243, 234, 216, 0.04);
    color: var(--ivory);
    font-size: 11.5px;
    font-weight: 500;
    cursor: pointer;
  }
  .m-nav-start {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.85rem;
    border-radius: 9999px;
    font-size: 11.5px;
    font-weight: 600;
    text-decoration: none;
  }
  .m-nav-start svg { width: 12px; height: 12px; }

  /* ── Hero ──────────────────────────────────────────────── */
  .m-hero {
    position: relative;
    overflow: hidden;
    padding: 1.5rem 1rem 3rem;
  }
  .m-hero-bg {
    position: absolute; inset: 0; pointer-events: none;
  }
  .m-hero-grid {
    position: absolute; inset: 0;
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.022) 1px, transparent 1px);
    background-size: 48px 48px;
    mask-image: radial-gradient(ellipse 100% 60% at 50% 20%, black, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse 100% 60% at 50% 20%, black, transparent 80%);
  }
  .m-hero-glow {
    position: absolute;
    width: 400px;
    height: 280px;
    top: -100px;
    right: -120px;
    background: radial-gradient(closest-side, rgba(201, 169, 110, 0.1), transparent 70%);
    filter: blur(28px);
  }

  .m-offer {
    position: relative;
    margin: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.85rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.35);
    background: rgba(141, 240, 196, 0.07);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .m-offer-dot {
    width: 5px; height: 5px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
    animation: pip 2s ease-in-out infinite;
  }
  @keyframes pip {
    0%, 100% { opacity: 0.55; }
    50%      { opacity: 1; }
  }

  .m-title {
    position: relative;
    margin: 1.4rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2.3rem, 9.5vw, 3.6rem);
    line-height: 1;
    letter-spacing: -0.025em;
  }
  /* ── Hero entrance choreography (runs once on load) ────────────── */
  .m-enter {
    animation: m-enter 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
    animation-delay: calc(var(--e, 0) * 160ms + 550ms);
  }
  @keyframes m-enter {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .m-title-line {
    display: block;
    overflow: hidden;
    padding: 0.06em 0.1em 0.16em;
    margin: -0.06em -0.1em -0.16em;
  }
  .m-line-inner {
    display: block;
    animation: m-line-up 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
    animation-delay: calc(var(--l, 0) * 140ms + 120ms);
  }
  @keyframes m-line-up {
    from { transform: translateY(108%); opacity: 0.4; }
    to   { transform: translateY(0);    opacity: 1; }
  }
  .m-title-mark {
    display: inline-block;
    margin-top: 0.18rem;
    padding: 0 0.18em 0.05em;
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.32);
    border-radius: 0.4rem;
    font-style: italic;
    color: var(--brass-bright);
    text-shadow: 0 0 24px rgba(201, 169, 110, 0.35);
  }
  .m-title-hand {
    font-size: 0.65em;
    font-weight: 600;
    margin-right: 0.25em;
    vertical-align: 0.15em;
  }
  /* The pill stamps in after its line lands, then glows softly forever. */
  .m-title-mark {
    animation:
      m-mark-stamp 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) 700ms both,
      m-mark-glow 3.6s ease-in-out 1.4s infinite;
  }
  @keyframes m-mark-stamp {
    from { transform: scale(1.45) rotate(-4deg); opacity: 0; }
    to   { transform: scale(1) rotate(0deg);     opacity: 1; }
  }
  @keyframes m-mark-glow {
    0%, 100% { text-shadow: 0 0 24px rgba(201, 169, 110, 0.35); border-color: rgba(201, 169, 110, 0.32); }
    50%      { text-shadow: 0 0 34px rgba(230, 201, 140, 0.6);  border-color: rgba(230, 201, 140, 0.55); }
  }

  .m-lede {
    margin: 1.4rem 0 0;
    font-size: 15px;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .m-lede strong {
    font-weight: 500;
    color: var(--ivory);
  }

  .m-ctas {
    margin-top: 1.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
  }
  .m-cta-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 1rem 1.25rem;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
    text-decoration: none;
  }
  .m-cta-primary svg { width: 17px; height: 17px; }
  .m-cta-secondary {
    align-self: center;
    color: var(--text-secondary);
    font-size: 12.5px;
    text-decoration: none;
    border-bottom: 1px dashed rgba(243, 234, 216, 0.3);
    padding-bottom: 1px;
  }
  .m-cta-secondary:hover { color: var(--ivory); }

  .m-chat {
    margin-top: 2.25rem;
  }
  .m-chat-tag {
    margin: 0 0 0.6rem;
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.25rem 0.65rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.25);
    background: rgba(141, 240, 196, 0.05);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 9.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
  }
  .m-chat-tag-dot {
    width: 5px; height: 5px;
    border-radius: 9999px;
    background: var(--radium);
    animation: pip 2s ease-in-out infinite;
  }
  .m-chat-foot {
    margin: 0.7rem 0 0;
    color: var(--text-muted);
    font-size: 11.5px;
    line-height: 1.5;
  }

  .m-trust {
    list-style: none;
    margin: 2rem 0 0;
    padding: 1.25rem 0 0;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .m-trust li {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    color: var(--text-secondary);
    font-size: 12.5px;
  }
  .m-trust li strong { color: var(--ivory); font-weight: 500; }
  .m-trust svg { width: 11px; height: 11px; }

  /* ── Final CTA ────────────────────────────────────────── */
  .m-finale {
    padding: 5.5rem 1.25rem 6rem;
    text-align: center;
    background: var(--bg-base);
  }
  .m-finale .engraved { display: inline-block; }
  .m-finale-title {
    margin: 1rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 8vw, 3rem);
    line-height: 1.05;
    letter-spacing: -0.02em;
  }
  .m-finale-sub {
    margin: 1rem auto 1.75rem;
    max-width: 24rem;
    color: var(--text-secondary);
    font-size: 13.5px;
    line-height: 1.6;
  }
  .m-finale-urgency {
    display: block;
    margin-top: 0.5rem;
    color: var(--ivory);
    font-weight: 500;
  }
  .m-finale-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 1rem 1.5rem;
    border-radius: 9999px;
    font-size: 14px;
    font-weight: 700;
    text-decoration: none;
  }
  .m-finale-cta svg { width: 16px; height: 16px; }
  .m-finale-secondary {
    margin-top: 1rem;
    display: block;
    color: var(--text-secondary);
    font-size: 13px;
    text-decoration: underline;
    text-decoration-color: rgba(243, 234, 216, 0.25);
    text-underline-offset: 4px;
  }
  .m-finale-secondary:hover { color: var(--ivory); }

  /* ── Footer ───────────────────────────────────────────── */
  .m-foot {
    padding: 2rem 1.25rem 2.5rem;
    background: var(--bg-bridge);
    border-top: 1px solid rgba(201, 169, 110, 0.18);
    text-align: center;
  }
  .m-foot-links {
    margin-top: 0.85rem;
    display: inline-flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 1rem;
    font-size: 12px;
    color: var(--text-muted);
  }
  .m-foot-links a { color: var(--text-muted); text-decoration: none; }
  .m-foot-meta {
    margin: 0.85rem 0 0;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.06em;
  }

  [data-animate] {
    opacity: 0;
    transform: translateY(20px);
    transition:
      opacity 0.65s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.65s cubic-bezier(0.22, 1, 0.36, 1);
    will-change: opacity, transform;
  }
  :global([data-animate="right"]) { transform: translateX(20px); }
  :global([data-animate="left"])  { transform: translateX(-20px); }

  :global([data-stagger] > *) {
    opacity: 0;
    transform: translateY(14px);
    transition:
      opacity 0.55s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.55s cubic-bezier(0.22, 1, 0.36, 1);
  }

  :global([data-animate][data-visible='true']) {
    opacity: 1;
    transform: translateY(0) translateX(0);
  }
  :global([data-stagger] > [data-visible='true']) {
    opacity: 1;
    transform: translateY(0);
  }

  @media (prefers-reduced-motion: reduce) {
    :global([data-animate]),
    :global([data-stagger] > *) {
      opacity: 1 !important;
      transform: none !important;
      transition: none !important;
    }
  }
</style>
