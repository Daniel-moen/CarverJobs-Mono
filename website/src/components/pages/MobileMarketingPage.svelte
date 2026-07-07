<script>
  /**
   * MobileMarketingPage — the small-screen reimagining.
   *
   * Same Bridge concept as the desktop LandingPage, but every section is
   * stacked vertically and the chat moves *above* the headline so the
   * first thing on screen is the live demo doing its thing.
   *
   * The same TypingChat / BridgeConsole / RouteMap / AgencySection
   * components are reused; no logic is forked between the two
   * marketing surfaces.
   */
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'
  import TypingChat from '../sections/TypingChat.svelte'
  import BridgeConsole from '../sections/BridgeConsole.svelte'
  import RouteMap from '../sections/RouteMap.svelte'
  import AgencySection from '../sections/AgencySection.svelte'
  import WhatsAppFab from '../sections/WhatsAppFab.svelte'

  // `onStartMatch` accepted for router compatibility; unused on this page.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  let { onSignIn = () => {}, onAgencySignup = () => {}, onStartMatch = () => {} } = $props()

  let chatPaused = $state(false)
  /** @type {HTMLElement|null} */
  let chatHost = $state(null)

  let nowText = $state(currentTime())
  function currentTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }

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

    const clockTimer = setInterval(() => { nowText = currentTime() }, 30_000)
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
      clearInterval(clockTimer)
      window.removeEventListener('scroll', onScroll)
    }
  })
</script>

<div class="m-landing">
  <!-- ── Mobile nav ─────────────────────────────────────────── -->
  <nav class="m-nav">
    <a href="/" class="m-brand">
      <span class="m-pip" aria-hidden="true"></span>
      <span class="wordmark text-[12px] text-ivory">CARVER</span>
      <span class="font-display italic text-[12px] text-brass">v3</span>
    </a>
    <div class="m-nav-right">
      <a
        href="/articles"
        onclick={() => trackEvent('mobile_nav_articles')}
        class="m-nav-articles"
      >Articles</a>
      <a
        href={whatsapp.link('help')}
        target="_blank"
        rel="noopener noreferrer"
        onclick={() => trackEvent('mobile_nav_whatsapp')}
        class="m-nav-wa"
      >
        <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
        Open chat
      </a>
    </div>
  </nav>

  <!-- ── Hero ───────────────────────────────────────────────── -->
  <section class="m-hero">
    <div class="m-hero-bg" aria-hidden="true">
      <div class="m-hero-grid"></div>
      <div class="m-hero-glow"></div>
    </div>

    <div class="m-status">
      <span class="m-status-cell">
        <span class="m-status-dot"></span>
        <span class="engraved">UTC · {nowText}</span>
      </span>
      <span class="m-status-cell">
        <span class="engraved text-brass">private beta</span>
      </span>
    </div>

    <h1 class="m-title">
      <span class="m-title-line">Text</span>
      <span class="m-title-mark">“match”</span>
      <span class="m-title-line">
        <span class="font-hand text-brass m-title-hand">— and</span>
        get the yacht.
      </span>
    </h1>

    <p class="m-lede">
      Carver runs the entire superyacht crew job hunt over WhatsApp.
      <strong class="text-ivory">Build your profile, match every live role, and apply</strong> —
      no app, no signup, and your first 2 match runs are free.
    </p>

    <div class="m-ctas">
      <a
        href={whatsapp.link("Hi Carver — I'd like to start matching to yacht roles.")}
        target="_blank"
        rel="noopener noreferrer"
        onclick={() => trackEvent('mobile_hero_whatsapp')}
        class="cta-wa m-cta-primary"
      >
        <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
          <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
        </svg>
        Open WhatsApp
      </a>
      <span class="m-cta-or" aria-hidden="true">or</span>
      <button
        type="button"
        onclick={() => onSignIn('mobile_hero')}
        class="cta-ivory m-cta-secondary"
      >
        Use the website
      </button>
    </div>

    <!-- Live chat is below the fold on mobile so the headline lands first -->
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
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </span>
        <span>Encrypted · TLS + at-rest</span>
      </li>
      <li>
        <span class="trust-seal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M2 12h20"/></svg>
        </span>
        <span>EU-hosted · GDPR by design</span>
      </li>
      <li>
        <span class="trust-seal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        </span>
        <span>Real captains, verified agencies</span>
      </li>
    </ul>
  </section>

  <!-- Bridge -->
  <div data-animate>
    <BridgeConsole />
  </div>

  <!-- Route -->
  <div data-animate>
    <RouteMap />
  </div>

  <!-- Agencies -->
  <div data-animate>
    <AgencySection {onAgencySignup} />
  </div>

  <!-- Final CTA -->
  <section class="m-finale" data-animate>
    <p class="engraved text-radium">All hands</p>
    <h2 class="m-finale-title">
      Your next berth is one
      <span class="font-hand text-brass">message</span>
      away.
    </h2>
    <a
      href={whatsapp.link("Hi Carver — I'd like to start matching to yacht roles.")}
      target="_blank"
      rel="noopener noreferrer"
      onclick={() => trackEvent('mobile_finale_whatsapp')}
      class="cta-wa m-finale-cta"
    >
      <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
        <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
      </svg>
      Open WhatsApp
    </a>
    <button
      type="button"
      onclick={() => onSignIn('mobile_finale')}
      class="m-finale-secondary"
    >
      Or use the website →
    </button>
  </section>

  <!-- Footer -->
  <footer class="m-foot">
    <span class="font-hand text-brass text-base">For the crew, by the crew.</span>
    <div class="m-foot-links">
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/data-deletion">Delete data</a>
    </div>
    <p class="m-foot-meta">© {new Date().getFullYear()} Carver · made on the dock</p>
  </footer>

  <WhatsAppFab />
</div>

<style>
  .m-landing {
    background: var(--bg-base);
    color: var(--text-primary);
    overflow-x: hidden;
    min-height: 100vh;
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
  .m-nav-wa {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.8rem;
    border-radius: 9999px;
    background: rgba(37, 211, 102, 0.12);
    border: 1px solid rgba(37, 211, 102, 0.4);
    color: #6ee7a8;
    font-size: 11.5px;
    font-weight: 500;
    text-decoration: none;
  }
  .m-nav-wa svg { width: 12px; height: 12px; }
  .m-nav-right {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }
  .m-nav-articles {
    padding: 0.4rem 0.7rem;
    border-radius: 9999px;
    border: 1px solid rgba(201, 169, 110, 0.28);
    background: rgba(201, 169, 110, 0.06);
    color: var(--ivory);
    font-size: 11.5px;
    font-weight: 500;
    text-decoration: none;
  }

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

  .m-status {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 0.65rem;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.18);
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  .m-status-cell { display: inline-flex; align-items: center; gap: 0.35rem; }
  .m-status-dot {
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
    margin: 1.6rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2.3rem, 9.5vw, 3.6rem);
    line-height: 1;
    letter-spacing: -0.025em;
  }
  .m-title-line { display: block; }
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
    font-size: 0.7em;
    font-weight: 600;
    margin-right: 0.25em;
    vertical-align: 0.15em;
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
    gap: 0.7rem;
  }
  .m-cta-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 0.95rem 1.25rem;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
  }
  .m-cta-primary svg { width: 16px; height: 16px; }
  .m-cta-or {
    align-self: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    padding: 0.1rem 0;
  }
  .m-cta-secondary {
    display: inline-flex;
    justify-content: center;
    align-items: center;
    padding: 0.85rem 1.25rem;
    border-radius: 12px;
    font-size: 13.5px;
    font-weight: 600;
  }

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
  .m-trust svg { width: 11px; height: 11px; }

  /* ── Final CTA ────────────────────────────────────────── */
  .m-finale {
    padding: 5.5rem 1.25rem 6rem;
    text-align: center;
    background: var(--bg-base);
  }
  .m-finale .engraved { display: inline-block; }
  .m-finale-title {
    margin: 1rem 0 1.75rem;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 8vw, 3rem);
    line-height: 1.05;
    letter-spacing: -0.02em;
  }
  .m-finale-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 1rem 1.5rem;
    border-radius: 9999px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
  }
  .m-finale-cta svg { width: 16px; height: 16px; }
  .m-finale-secondary {
    margin-top: 1rem;
    display: inline-block;
    color: var(--text-secondary);
    background: none;
    border: none;
    font-size: 13px;
    text-decoration: underline;
    text-decoration-color: rgba(243, 234, 216, 0.25);
    text-underline-offset: 4px;
    cursor: pointer;
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
