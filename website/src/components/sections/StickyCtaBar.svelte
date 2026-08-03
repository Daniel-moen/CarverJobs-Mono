<script>
  /**
   * StickyCtaBar — full-width bottom bar for small screens.
   *
   * Appears once the visitor scrolls past the hero (they've seen the pitch)
   * and keeps the zero-friction WhatsApp action one thumb-tap away for the
   * whole page. Replaces the floating FAB on mobile marketing pages —
   * a full-width bar out-converts a corner bubble on touch.
   */
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'

  /** @type {{ showAfter?: number, source?: string }} */
  let { showAfter = 420, source = 'mobile' } = $props()

  let visible = $state(false)

  onMount(() => {
    function onScroll() {
      visible = window.scrollY > showAfter
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  })
</script>

{#if visible}
  <div class="bar" role="complementary" aria-label="Start free on WhatsApp">
    <div class="bar-copy">
      <p class="bar-title">5 free match runs</p>
      <p class="bar-sub">No card · no signup · just WhatsApp</p>
    </div>
    <a
      href={whatsapp.link("Hi Carver — I'd like to start matching to yacht roles.")}
      target="_blank"
      rel="noopener noreferrer"
      class="cta-wa cta-shine bar-cta"
      onclick={() => trackEvent('sticky_bar_whatsapp', { page: source })}
    >
      <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
      Start free
    </a>
  </div>
{/if}

<style>
  .bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.85rem;
    padding: 0.7rem 1rem calc(0.7rem + env(safe-area-inset-bottom));
    background: rgba(6, 10, 15, 0.92);
    backdrop-filter: blur(14px);
    border-top: 1px solid rgba(201, 169, 110, 0.25);
    box-shadow: 0 -18px 50px -20px rgba(0, 0, 0, 0.8);
    animation: bar-up 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  }
  @keyframes bar-up {
    from { transform: translateY(100%); }
    to   { transform: translateY(0); }
  }

  .bar-copy { min-width: 0; }
  .bar-title {
    margin: 0;
    color: var(--ivory);
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: 0.01em;
  }
  .bar-sub {
    margin: 1px 0 0;
    color: var(--text-muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .bar-cta {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    flex: none;
    padding: 0.75rem 1.2rem;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 700;
    text-decoration: none;
  }
  .bar-cta svg { width: 16px; height: 16px; }

  @media (prefers-reduced-motion: reduce) {
    .bar { animation: none; }
  }
</style>
