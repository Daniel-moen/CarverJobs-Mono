<script>
  /**
   * LandingPage — "The Bridge", rebuilt as a conversion ladder.
   *
   * Every section is one rung from "stranger" to "buyer":
   *
   *   1. Hero          — offer chip + outcome headline + one dominant
   *                      WhatsApp CTA, live bot demo alongside.
   *   2. Bridge        — how matching works & where listings come from.
   *   3. Route         — "from signal to berth" journey.
   *   4. Compare       — the old dock-walk hunt vs one text (pain → relief).
   *   5. Pricing       — token packs with anchors, savings and the
   *                      first-purchase bonus. The buy-tokens pitch.
   *   6. Agencies      — captains/agencies post a role.
   *   7. FAQ           — objection handling + FAQPage JSON-LD.
   *   8. Final CTA     — offer restated, both paths.
   *
   * Rule carried over from the original build: no invented telemetry, no
   * fake user counts, no fabricated testimonials. Every claim is a real
   * product behaviour (2 free runs, +5 first-purchase bonus, job-post
   * rewards, 14-day refund).
   *
   * Animation budget stays tight — heavy effects only run while the
   * section is on screen, driven by an IntersectionObserver.
   */
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'
  import { DEFAULT_FIRST_PURCHASE_BONUS } from '../../config/subscriptionCheckout'
  import TypingChat from '../sections/TypingChat.svelte'
  import RoleTicker from '../sections/RoleTicker.svelte'
  import ScrollProgress from '../sections/ScrollProgress.svelte'
  import BridgeConsole from '../sections/BridgeConsole.svelte'
  import RouteMap from '../sections/RouteMap.svelte'
  import CompareSection from '../sections/CompareSection.svelte'
  import TokenPacksSection from '../sections/TokenPacksSection.svelte'
  import AgencySection from '../sections/AgencySection.svelte'
  import FaqSection from '../sections/FaqSection.svelte'
  import WhatsAppFab from '../sections/WhatsAppFab.svelte'

  // `onStartMatch` is accepted for API compatibility with the router but
  // intentionally ignored: the design routes everyone through WhatsApp
  // or sign-in instead of jumping straight to the matching engine.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  let { onSignIn = () => {}, onAgencySignup = () => {}, onStartMatch = () => {} } = $props()

  const startMessage = "Hi Carver — I'd like to start matching to yacht roles."

  // Pause the typing chat when it scrolls out of view.
  let chatPaused = $state(false)
  /** @type {HTMLElement|null} */
  let chatHost = $state(null)

  // Parallax layers in the hero + the "see how it works" cue.
  /** @type {HTMLElement|null} */
  let glowEl = $state(null)
  /** @type {HTMLElement|null} */
  let gridBgEl = $state(null)
  let cueHidden = $state(false)

  // Live clock for the status bar — locale-aware, 24h.
  let nowText = $state(currentTime())
  function currentTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  onMount(() => {
    // Respect users who prefer reduced motion: reveal everything immediately.
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      document.querySelectorAll('[data-animate]').forEach((el) => {
        /** @type {HTMLElement} */ (el).dataset.visible = 'true'
      })
    }

    // Reveal-on-scroll. Honours `data-stagger` for child sequencing and
    // `data-animate="left|right|up|scale"` for direction; default is "up".
    const reveal = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const target = /** @type {HTMLElement} */ (entry.target)
          target.dataset.visible = 'true'
          if (target.hasAttribute('data-stagger')) {
            const children = target.querySelectorAll(':scope > *')
            children.forEach((child, idx) => {
              const c = /** @type {HTMLElement} */ (child)
              c.style.transitionDelay = `${idx * 90}ms`
              c.dataset.visible = 'true'
            })
          }
          reveal.unobserve(target)
        }
      },
      { threshold: 0.12, rootMargin: '0px 0px -6% 0px' },
    )
    if (!prefersReduced) {
      document.querySelectorAll('[data-animate]').forEach((el) => reveal.observe(el))
    }

    // Pause/resume the typing chat based on visibility
    const visibilityObs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.target === chatHost) chatPaused = !entry.isIntersecting
        }
      },
      { threshold: 0.15 },
    )
    if (chatHost) visibilityObs.observe(chatHost)

    // Live clock + scroll depth analytics + hero parallax
    const clockTimer = setInterval(() => { nowText = currentTime() }, 30_000)
    const depths = new Set()
    const parallaxOn = !prefersReduced && window.matchMedia('(pointer: fine)').matches
    let parallaxTick = false
    function onScroll() {
      const y = window.scrollY
      cueHidden = y > 140
      const denom = document.body.scrollHeight || 1
      const pct = Math.round(((y + window.innerHeight) / denom) * 100)
      for (const t of [25, 50, 75, 100]) {
        if (pct >= t && !depths.has(t)) {
          depths.add(t)
          trackEvent('scroll_depth', { page: 'landing', value: String(t) })
        }
      }
      // Depth: the glow drifts up faster than the grid as the hero scrolls away.
      if (parallaxOn && !parallaxTick && y < window.innerHeight * 1.5) {
        parallaxTick = true
        requestAnimationFrame(() => {
          parallaxTick = false
          if (glowEl)   glowEl.style.transform   = `translateY(${y * 0.22}px)`
          if (gridBgEl) gridBgEl.style.transform = `translateY(${y * 0.08}px)`
        })
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      reveal.disconnect()
      visibilityObs.disconnect()
      clearInterval(clockTimer)
      window.removeEventListener('scroll', onScroll)
    }
  })
</script>

<div class="landing">
  <ScrollProgress />

  <!-- ── NAV ─────────────────────────────────────────────────────────── -->
  <nav class="nav">
    <div class="nav-inner">
      <a href="/" class="nav-brand">
        <span class="brand-pip" aria-hidden="true"></span>
        <span class="wordmark text-[14px] text-ivory">CARVER</span>
        <span class="brand-suffix font-display italic text-[13px] text-brass">v3</span>
      </a>
      <div class="nav-links">
        <a href="#route" class="nav-link">How it works</a>
        <a href="#pricing" class="nav-link" onclick={() => trackEvent('nav_pricing')}>Pricing</a>
        <a href="#agencies" class="nav-link">For agencies</a>
        <a href="/articles" class="nav-link" onclick={() => trackEvent('nav_articles')}>Articles</a>
        <button onclick={() => onSignIn('nav')} class="nav-signin">Sign in</button>
        <a
          href={whatsapp.link(startMessage)}
          target="_blank"
          rel="noopener noreferrer"
          onclick={() => trackEvent('nav_whatsapp_cta')}
          class="cta-wa nav-start"
        >
          <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
          Start free
        </a>
      </div>
    </div>
  </nav>

  <!-- ── HERO ────────────────────────────────────────────────────────── -->
  <section class="hero" role="banner">
    <!-- Decorative background — quiet, no neon -->
    <div class="hero-bg" aria-hidden="true">
      <div class="hero-grid" bind:this={gridBgEl}></div>
      <div class="hero-glow" bind:this={glowEl}></div>
    </div>

    <div class="hero-inner">
      <!-- Slim status line — live clock + beta pip -->
      <div class="hero-status">
        <span class="hero-status-cell">
          <span class="status-dot" aria-hidden="true"></span>
          <span class="engraved">UTC · {nowText}</span>
        </span>
        <span class="hero-status-cell ml-auto">
          <span class="engraved text-brass">superyacht crew · deck to galley</span>
        </span>
      </div>

      <!-- Two-column hero: editorial copy left, live chat right -->
      <div class="hero-grid-cols">
        <div class="hero-copy" data-animate data-stagger>
          <p class="hero-offer">
            <span class="hero-offer-dot" aria-hidden="true"></span>
            Free to start — your first 2 match runs are on us
          </p>

          <h1 class="hero-title">
            <span class="hero-title-line"><span class="line-inner" style="--l:0">Every live</span></span>
            <span class="hero-title-line"><span class="line-inner" style="--l:1">yacht job.</span></span>
            <span class="hero-title-line"><span class="line-inner" style="--l:2">
              <span class="font-hand text-brass hero-title-hand">One text:</span>
              <span class="hero-title-mark">“match”</span>
            </span></span>
          </h1>

          <p class="hero-lede">
            Carver runs your whole superyacht job hunt inside WhatsApp.
            <strong class="text-ivory">It builds your profile in chat, scans every live role the moment you ask,
            and drafts the application email for each match</strong> — in about 25 seconds.
            No app to install, no forms, no inbox to sort.
          </p>

          <div class="hero-ctas">
            <a
              href={whatsapp.link(startMessage)}
              target="_blank"
              rel="noopener noreferrer"
              onclick={() => trackEvent('hero_whatsapp_cta')}
              class="cta-wa cta-shine cta-beacon hero-cta-primary"
            >
              <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
                <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
              </svg>
              <span>Start free on WhatsApp</span>
              <span class="hero-cta-meta">no card · no signup</span>
            </a>
          </div>
          <p class="hero-alt">
            Prefer a bigger screen?
            <a
              href="/signup"
              class="hero-alt-link"
              onclick={() => trackEvent('hero_web_signup')}
            >Create a free web account →</a>
          </p>

          <!-- Value pips — real product facts, no invented numbers -->
          <ul class="hero-trust">
            <li>
              <span class="trust-seal">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              </span>
              <p><strong>Applications written for you</strong> — a tailored intro email per match</p>
            </li>
            <li>
              <span class="trust-seal">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
              </span>
              <p><strong>From R9 per match run</strong> — no subscription, tokens never expire</p>
            </li>
            <li>
              <span class="trust-seal">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              </span>
              <p>Encrypted &amp; EU-hosted · real listings from captains and verified agencies</p>
            </li>
          </ul>
        </div>

        <!-- The live chat — real bot script types itself out here -->
        <aside class="hero-chat" data-animate="right" bind:this={chatHost}>
          <p class="hero-chat-tag">
            <span class="hero-chat-tag-dot"></span>
            Live demo · real bot replies
          </p>
          <TypingChat paused={chatPaused} />
          <p class="hero-chat-foot">
            What you see is what you get — script pulled directly from the
            production bot. <a class="hero-chat-link" href={whatsapp.link('match')} target="_blank" rel="noopener noreferrer">Try “match” yourself →</a>
          </p>
        </aside>
      </div>

      <!-- Scroll cue — fades once the visitor commits to scrolling -->
      <a href="#route" class="hero-cue" class:hero-cue-hidden={cueHidden}>
        <span>See how it works</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </a>
    </div>

  </section>

  <!-- ── TICKER — roles & ports marquee ──────────────────────────────── -->
  <RoleTicker />

  <!-- ── BRIDGE — how it works ──────────────────────────────────────── -->
  <div data-animate>
    <BridgeConsole />
  </div>

  <!-- ── ROUTE — from signal to berth ────────────────────────────────── -->
  <div id="route" data-animate>
    <RouteMap />
  </div>

  <!-- ── COMPARE — the old hunt vs one text ──────────────────────────── -->
  <div data-animate>
    <CompareSection />
  </div>

  <!-- ── PRICING — token packs ───────────────────────────────────────── -->
  <div data-animate>
    <TokenPacksSection source="landing" />
  </div>

  <!-- ── AGENCIES — post a role ──────────────────────────────────────── -->
  <div data-animate>
    <AgencySection {onAgencySignup} />
  </div>

  <!-- ── FAQ — objection handling ────────────────────────────────────── -->
  <div data-animate>
    <FaqSection />
  </div>

  <!-- ── FINAL CTA ───────────────────────────────────────────────────── -->
  <section class="finale" data-animate>
    <div class="finale-inner">
      <p class="engraved text-radium">All hands</p>
      <h2 class="finale-title">
        Your next berth is one
        <span class="font-hand text-brass">message</span>
        away.
      </h2>
      <p class="finale-sub">
        Five free match runs, an extra {DEFAULT_FIRST_PURCHASE_BONUS} bonus tokens with your first pack,
        and never a subscription.
        <strong class="finale-urgency">Somewhere right now a captain is reading applications —
        yours should be in the pile.</strong>
      </p>
      <div class="finale-ctas">
        <a
          href={whatsapp.link(startMessage)}
          target="_blank"
          rel="noopener noreferrer"
          onclick={() => trackEvent('finale_whatsapp_cta')}
          class="cta-wa cta-shine cta-beacon finale-primary"
        >
          <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
            <path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/>
          </svg>
          Start free on WhatsApp
        </a>
        <span class="finale-or" aria-hidden="true">or</span>
        <a
          href="/signup"
          onclick={() => trackEvent('finale_web_signup')}
          class="cta-ivory finale-secondary"
        >
          Create a web account
        </a>
      </div>
      <p class="finale-foot">
        no card required · cancel nothing, there's nothing recurring · {whatsapp.configured ? whatsapp.display : 'WhatsApp number live in production'}
      </p>
    </div>
  </section>

  <!-- ── FOOTER — the engraved brass plate ──────────────────────────── -->
  <footer class="foot">
    <div class="foot-inner">
      <div class="foot-brand">
        <span class="brand-pip" aria-hidden="true"></span>
        <span class="wordmark text-[12px] text-ivory">CARVER</span>
        <span class="font-display italic text-[12px] text-brass">v3</span>
      </div>
      <p class="foot-tag font-hand text-brass text-lg">For the crew, by the crew.</p>
      <div class="foot-links">
        <a href="/pricing">Pricing</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
        <a href="/refund-policy">Refunds</a>
        <a href="/data-deletion">Delete data</a>
      </div>
      <p class="foot-meta">
        © {new Date().getFullYear()} Carver · made on the dock
      </p>
    </div>
  </footer>

  <!-- Sticky WhatsApp action — shows on every section -->
  <WhatsAppFab />
</div>

<style>
  .landing {
    background: var(--bg-base);
    color: var(--text-primary);
    overflow-x: hidden;
    min-height: 100vh;
  }

  /* ── Nav ────────────────────────────────────────────────────────── */
  .nav {
    position: sticky;
    top: 0;
    z-index: 50;
    backdrop-filter: blur(14px);
    background: rgba(4, 7, 11, 0.62);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  .nav-inner {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0.85rem 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  @media (min-width: 768px) { .nav-inner { padding: 1rem 1.5rem; } }

  .nav-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.55rem;
    text-decoration: none;
  }
  .brand-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 8px rgba(201, 169, 110, 0.55);
    align-self: center;
  }
  .brand-suffix { letter-spacing: -0.02em; }

  .nav-links {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
  }
  .nav-link {
    display: none;
    color: var(--text-secondary);
    font-size: 12.5px;
    padding: 0.5rem 0.85rem;
    border-radius: 9999px;
    text-decoration: none;
    transition: color 0.18s ease;
  }
  .nav-link:hover { color: var(--ivory); }
  @media (min-width: 768px) { .nav-link { display: inline-flex; } }

  .nav-start {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.55rem 1.05rem;
    border-radius: 9999px;
    font-size: 12.5px;
    font-weight: 600;
    text-decoration: none;
  }
  .nav-start svg { width: 14px; height: 14px; }

  .nav-signin {
    display: none;
    padding: 0.5rem 1rem;
    border-radius: 9999px;
    border: 1px solid rgba(243, 234, 216, 0.22);
    background: rgba(243, 234, 216, 0.04);
    color: var(--ivory);
    font-size: 12px;
    font-weight: 500;
    transition: background 0.2s ease, border-color 0.2s ease;
    cursor: pointer;
  }
  @media (min-width: 640px) { .nav-signin { display: inline-flex; } }
  .nav-signin:hover {
    background: rgba(243, 234, 216, 0.1);
    border-color: rgba(243, 234, 216, 0.35);
  }

  /* ── Hero ───────────────────────────────────────────────────────── */
  .hero {
    position: relative;
    overflow: hidden;
    background: var(--bg-base);
    padding-bottom: 0;
  }
  .hero-bg {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .hero-grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.022) 1px, transparent 1px);
    background-size: 64px 64px;
    mask-image: radial-gradient(ellipse 80% 60% at 50% 30%, black, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 30%, black, transparent 80%);
  }
  .hero-glow {
    position: absolute;
    width: 900px;
    height: 600px;
    top: -180px;
    right: -200px;
    background: radial-gradient(closest-side, rgba(201, 169, 110, 0.08), transparent 70%);
    filter: blur(40px);
  }
  @media (max-width: 900px) {
    .hero-glow { width: 500px; height: 400px; right: -100px; filter: blur(28px); }
  }

  .hero-inner {
    position: relative;
    z-index: 1;
    max-width: 1280px;
    margin: 0 auto;
    padding: 1.5rem 1rem 4rem;
  }
  @media (min-width: 768px) { .hero-inner { padding: 2.5rem 1.5rem 6rem; } }

  /* Status strip */
  .hero-status {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    padding: 0.6rem 0.5rem;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.18);
    flex-wrap: wrap;
  }
  .hero-status-cell {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
  }
  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
    animation: pip 2s ease-in-out infinite;
  }
  @keyframes pip {
    0%, 100% { opacity: 0.55; }
    50%      { opacity: 1; }
  }

  /* Two-column layout */
  .hero-grid-cols {
    margin-top: 2.5rem;
    display: grid;
    grid-template-columns: 1fr;
    gap: 2.5rem;
    align-items: start;
  }
  @media (min-width: 1024px) {
    .hero-grid-cols {
      grid-template-columns: 1.1fr 0.9fr;
      gap: 4rem;
      margin-top: 3.5rem;
      align-items: center;
    }
  }

  /* Offer chip — first thing read, states the free offer */
  .hero-offer {
    margin: 0 0 1.6rem;
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.45rem 1rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.35);
    background: rgba(141, 240, 196, 0.07);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .hero-offer-dot {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
    animation: pip 2s ease-in-out infinite;
  }

  /* Title — calm, editorial, no excess gradient */
  .hero-title {
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2.6rem, 7vw, 5.2rem);
    line-height: 0.98;
    letter-spacing: -0.028em;
    margin: 0;
  }
  /* Each headline line slides up out of its own clip window. Padding /
     negative margin keep descenders (y, j) and the pill's glow unclipped. */
  .hero-title-line {
    display: block;
    overflow: hidden;
    padding: 0.06em 0.1em 0.16em;
    margin: -0.06em -0.1em -0.16em;
  }
  .line-inner {
    display: block;
  }
  :global(.hero-title[data-visible='true']) .line-inner {
    animation: line-up 0.85s cubic-bezier(0.22, 1, 0.36, 1) both;
    animation-delay: calc(var(--l, 0) * 150ms + 80ms);
  }
  @keyframes line-up {
    from { transform: translateY(108%); opacity: 0.4; }
    to   { transform: translateY(0);    opacity: 1; }
  }
  .hero-title-mark {
    display: inline-block;
    padding: 0 0.18em 0.05em;
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.32);
    border-radius: 0.4rem;
    font-style: italic;
    color: var(--brass-bright);
    text-shadow: 0 0 24px rgba(201, 169, 110, 0.35);
  }
  /* The pill stamps in after its line lands, then glows softly forever. */
  :global(.hero-title[data-visible='true']) .hero-title-mark {
    animation:
      mark-stamp 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) 700ms both,
      mark-glow 3.6s ease-in-out 1.4s infinite;
  }
  @keyframes mark-stamp {
    from { transform: scale(1.45) rotate(-4deg); opacity: 0; }
    to   { transform: scale(1) rotate(0deg);     opacity: 1; }
  }
  @keyframes mark-glow {
    0%, 100% { text-shadow: 0 0 24px rgba(201, 169, 110, 0.35); border-color: rgba(201, 169, 110, 0.32); }
    50%      { text-shadow: 0 0 34px rgba(230, 201, 140, 0.6);  border-color: rgba(230, 201, 140, 0.55); }
  }
  .hero-title-hand {
    font-size: 0.65em;
    font-weight: 600;
    margin-right: 0.25em;
    vertical-align: 0.15em;
  }

  .hero-lede {
    margin: 1.85rem 0 0;
    max-width: 36rem;
    font-size: 1.05rem;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .hero-lede strong {
    font-weight: 500;
    color: var(--ivory);
  }

  /* CTAs */
  .hero-ctas {
    margin-top: 2.4rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
  }
  .hero-cta-primary {
    display: inline-flex;
    align-items: center;
    gap: 0.65rem;
    padding: 1.05rem 1.5rem;
    border-radius: 9999px;
    font-size: 14.5px;
    font-weight: 600;
    text-decoration: none;
  }
  .hero-cta-primary svg { width: 17px; height: 17px; }
  .hero-cta-meta {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    opacity: 0.7;
    margin-left: 0.35rem;
    padding-left: 0.65rem;
    border-left: 1px solid rgba(0, 0, 0, 0.18);
  }
  .hero-alt {
    margin: 1rem 0 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .hero-alt-link {
    color: var(--text-secondary);
    text-decoration: none;
    border-bottom: 1px dashed rgba(243, 234, 216, 0.35);
    transition: color 0.18s ease, border-color 0.18s ease;
  }
  .hero-alt-link:hover { color: var(--ivory); border-bottom-color: rgba(243, 234, 216, 0.7); }

  /* Value pips */
  .hero-trust {
    list-style: none;
    margin: 2.5rem 0 0;
    padding: 0;
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.9rem;
    max-width: 32rem;
  }
  .hero-trust li {
    display: flex;
    align-items: center;
    gap: 0.7rem;
  }
  .hero-trust p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
  }
  .hero-trust p strong { color: var(--ivory); font-weight: 500; }
  .hero-trust svg {
    width: 12px;
    height: 12px;
  }

  /* Right column — chat */
  .hero-chat {
    position: relative;
  }
  .hero-chat-tag {
    margin: 0 0 0.75rem;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0.7rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.25);
    background: rgba(141, 240, 196, 0.05);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
  }
  .hero-chat-tag-dot {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
    animation: pip 2s ease-in-out infinite;
  }
  .hero-chat-foot {
    margin: 0.85rem 0 0;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.55;
  }
  .hero-chat-link {
    color: var(--radium);
    text-decoration: none;
    border-bottom: 1px dashed rgba(141, 240, 196, 0.4);
  }
  .hero-chat-link:hover { color: #b9f5d6; border-bottom-color: rgba(141, 240, 196, 0.7); }

  /* Scroll cue */
  .hero-cue {
    margin: 3.5rem auto 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.3rem;
    width: max-content;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.26em;
    text-transform: uppercase;
    text-decoration: none;
    opacity: 1;
    transition: opacity 0.4s ease, color 0.2s ease;
  }
  .hero-cue:hover { color: var(--brass); }
  .hero-cue svg {
    width: 15px;
    height: 15px;
    animation: cue-bob 1.8s ease-in-out infinite;
  }
  @keyframes cue-bob {
    0%, 100% { transform: translateY(0);   opacity: 0.5; }
    50%      { transform: translateY(5px); opacity: 1; }
  }
  .hero-cue-hidden { opacity: 0; pointer-events: none; }

  /* ── Final CTA ────────────────────────────────────────────────── */
  .finale {
    position: relative;
    padding: 7rem 1rem 8rem;
    text-align: center;
    background:
      radial-gradient(70% 60% at 50% 50%, rgba(201, 169, 110, 0.06), transparent 70%),
      var(--bg-base);
    overflow: hidden;
  }
  @media (min-width: 768px) { .finale { padding: 9rem 1.5rem 10rem; } }
  .finale::before, .finale::after {
    content: "";
    position: absolute;
    height: 1px;
    left: 10%;
    right: 10%;
    background-image: linear-gradient(
      90deg, transparent, rgba(201, 169, 110, 0.5), transparent
    );
  }
  .finale::before { top: 0; }
  .finale::after  { bottom: 0; }

  .finale-inner { max-width: 760px; margin: 0 auto; }
  .finale-title {
    margin: 1.25rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2.4rem, 5.8vw, 4.4rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }
  .finale-sub {
    margin: 1.4rem auto 0;
    max-width: 34rem;
    color: var(--text-secondary);
    font-size: 15px;
    line-height: 1.65;
  }
  .finale-urgency {
    display: block;
    margin-top: 0.6rem;
    color: var(--ivory);
    font-weight: 500;
  }
  .finale-ctas {
    margin-top: 2.5rem;
    display: inline-flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.85rem;
  }
  .finale-or {
    display: inline-flex;
    align-items: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    padding: 0 0.25rem;
    align-self: center;
  }
  .finale-primary,
  .finale-secondary {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    padding: 1rem 1.6rem;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
  }
  .finale-primary svg { width: 16px; height: 16px; }
  .finale-foot {
    margin-top: 1.75rem;
    color: var(--text-muted);
    font-size: 12px;
    font-family: var(--font-mono);
    letter-spacing: 0.06em;
  }

  /* ── Footer ───────────────────────────────────────────────────── */
  .foot {
    background: var(--bg-bridge);
    border-top: 1px solid rgba(201, 169, 110, 0.18);
    padding: 2.5rem 1rem 3rem;
  }
  .foot-inner {
    max-width: 1280px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: 1fr;
    gap: 1.25rem;
    align-items: center;
    justify-items: center;
    text-align: center;
  }
  @media (min-width: 768px) {
    .foot-inner {
      grid-template-columns: auto 1fr auto auto;
      gap: 2rem;
      justify-items: start;
      text-align: left;
    }
  }
  .foot-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.55rem;
  }
  .foot-tag {
    color: var(--brass);
  }
  .foot-links {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 1.25rem;
    font-size: 12px;
    color: var(--text-muted);
  }
  .foot-links a {
    color: var(--text-muted);
    text-decoration: none;
    transition: color 0.18s ease;
  }
  .foot-links a:hover { color: var(--ivory); }
  .foot-meta {
    color: var(--text-muted);
    font-size: 11px;
    font-family: var(--font-mono);
    letter-spacing: 0.06em;
    margin: 0;
  }

  /* ── Reveal-on-scroll ─────────────────────────────────────────── */
  [data-animate] {
    opacity: 0;
    transform: translateY(24px);
    transition:
      opacity 0.75s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.75s cubic-bezier(0.22, 1, 0.36, 1);
    will-change: opacity, transform;
  }
  [data-animate="right"] { transform: translateX(28px); }
  :global([data-animate="left"])  { transform: translateX(-28px); }
  :global([data-animate="scale"]) { transform: scale(0.96); }

  /* Children of a stagger container start hidden too — the observer
     hands them their own visible flag with a per-index transition delay. */
  [data-stagger] > * {
    opacity: 0;
    transform: translateY(16px);
    transition:
      opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  }

  :global([data-animate][data-visible='true']) {
    opacity: 1;
    transform: translateY(0) translateX(0) scale(1);
  }
  :global([data-stagger] > [data-visible='true']) {
    opacity: 1;
    transform: translateY(0);
  }

  @media (prefers-reduced-motion: reduce) {
    [data-animate],
    [data-stagger] > * {
      opacity: 1 !important;
      transform: none !important;
      transition: none !important;
    }
  }
</style>
