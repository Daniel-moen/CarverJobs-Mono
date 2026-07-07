<script>
  /**
   * PricingPage — public /pricing route, rebuilt on the Bridge design
   * language and sharing TokenPacksSection + FaqSection with the landing
   * pages so prices and objection-handling never drift between surfaces.
   */
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'
  import TokenPacksSection from '../sections/TokenPacksSection.svelte'
  import FaqSection from '../sections/FaqSection.svelte'
  import ScrollProgress from '../sections/ScrollProgress.svelte'
  import WhatsAppFab from '../sections/WhatsAppFab.svelte'

  const startMessage = "Hi Carver — I'd like to start matching to yacht roles."
</script>

<div class="pricing">
  <ScrollProgress />

  <nav class="p-nav">
    <a href="/" class="p-brand">
      <span class="p-pip" aria-hidden="true"></span>
      <span class="wordmark text-[13px] text-ivory">CARVER</span>
      <span class="font-display italic text-[12px] text-brass">v3</span>
    </a>
    <a
      href={whatsapp.link(startMessage)}
      target="_blank"
      rel="noopener noreferrer"
      onclick={() => trackEvent('pricing_nav_whatsapp')}
      class="cta-wa p-nav-start"
    >
      <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
      Start free
    </a>
  </nav>

  <!-- The token packs section doubles as the page hero -->
  <TokenPacksSection source="pricing" />

  <!-- Recruiters / agencies -->
  <section class="p-recruiter">
    <div class="p-recruiter-inner instrument">
      <div>
        <p class="engraved">For agencies &amp; recruiters</p>
        <h2 class="p-recruiter-title">Pay only for the crew you want to reach.</h2>
        <p class="p-recruiter-body">
          Post roles and browse matched candidates for free. Spend 5 tokens to unlock a
          candidate's contact details — once unlocked, they stay open for you at no extra cost.
        </p>
        <p class="p-recruiter-note">
          In recruiter terms: Starter ≈ 1 unlock · Standard ≈ 4 unlocks · Premium ≈ 15 unlocks.
        </p>
      </div>
      <a
        href="/signup/agency"
        class="cta-ivory p-recruiter-cta"
        onclick={() => trackEvent('pricing_agency_signup')}
      >
        Create an agency account
      </a>
    </div>
  </section>

  <FaqSection />

  <footer class="p-foot">
    <nav class="p-foot-links" aria-label="Legal">
      <a href="/refund-policy">Refund Policy</a>
      <a href="/terms">Terms</a>
      <a href="/privacy">Privacy</a>
    </nav>
    <p class="p-foot-meta">© {new Date().getFullYear()} Carver · made on the dock</p>
  </footer>

  <WhatsAppFab />
</div>

<style>
  .pricing {
    min-height: 100vh;
    background: var(--bg-base);
    color: var(--text-primary);
    overflow-x: hidden;
  }

  .p-nav {
    position: sticky;
    top: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.85rem 1rem;
    background: rgba(4, 7, 11, 0.72);
    backdrop-filter: blur(14px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  @media (min-width: 768px) { .p-nav { padding: 0.95rem 1.5rem; } }

  .p-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.5rem;
    text-decoration: none;
  }
  .p-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 8px rgba(201, 169, 110, 0.55);
    align-self: center;
  }
  .p-nav-start {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.5rem 1rem;
    border-radius: 9999px;
    font-size: 12.5px;
    font-weight: 600;
    text-decoration: none;
  }
  .p-nav-start svg { width: 14px; height: 14px; }

  .p-recruiter {
    padding: 0 1rem 3rem;
    background: var(--bg-bridge);
  }
  @media (min-width: 768px) { .p-recruiter { padding: 0 1.5rem 4rem; } }
  .p-recruiter-inner {
    max-width: 1000px;
    margin: 0 auto;
    padding: 2rem 1.75rem;
    display: grid;
    gap: 1.5rem;
    align-items: center;
  }
  @media (min-width: 860px) {
    .p-recruiter-inner {
      grid-template-columns: 1fr auto;
      gap: 2.5rem;
    }
  }
  .p-recruiter-title {
    margin: 0.75rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(1.5rem, 3.4vw, 2.1rem);
    line-height: 1.1;
    letter-spacing: -0.02em;
  }
  .p-recruiter-body {
    margin: 0.9rem 0 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.65;
    max-width: 36rem;
  }
  .p-recruiter-note {
    margin: 0.65rem 0 0;
    color: var(--text-muted);
    font-size: 12px;
  }
  .p-recruiter-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.9rem 1.5rem;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;
  }

  .p-foot {
    padding: 2rem 1.25rem 2.75rem;
    background: var(--bg-bridge);
    border-top: 1px solid rgba(201, 169, 110, 0.18);
    text-align: center;
  }
  .p-foot-links {
    display: inline-flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 1.25rem;
    font-size: 12px;
  }
  .p-foot-links a {
    color: var(--text-muted);
    text-decoration: none;
    transition: color 0.18s ease;
  }
  .p-foot-links a:hover { color: var(--ivory); }
  .p-foot-meta {
    margin: 0.9rem 0 0;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.06em;
  }
</style>
