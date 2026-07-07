<script>
  /**
   * CompareSection — "the old hunt vs Carver", side by side.
   *
   * Conversion job: make the visitor *feel* the pain of the current job
   * hunt, then show the same outcome collapsing to one text message.
   * Every Carver claim maps to a real product behaviour — no invented
   * telemetry, no fake counts.
   */
  import { trackEvent } from '../../config/analytics'
  import { whatsapp } from '../../config/site'

  const oldWay = [
    'Walk the docks in the sun, handing out printed CVs',
    'Refresh a dozen Facebook groups and crew pages all day',
    'Email agencies into the void — most never reply',
    'Rewrite your CV and cover letter for every single role',
    'Miss the good berths because someone saw them first',
  ]

  const carverWay = [
    { lead: 'Text “match”', rest: ' — every live role scanned in about 25 seconds' },
    { lead: 'Ranked for you', rest: ' by certs, visa, salary band and availability' },
    { lead: 'Applications drafted', rest: ' — a tailored intro email per match. Review, send.' },
    { lead: 'Works where you are', rest: ' — dock, crew house, crossing. It’s just WhatsApp.' },
    { lead: 'Earn free tokens', rest: ' by sharing job posts you spot in your groups' },
  ]
</script>

<section class="compare" aria-labelledby="compare-title">
  <div class="compare-inner">
    <header class="compare-head">
      <p class="engraved">Two ways to find a berth</p>
      <h2 id="compare-title" class="compare-title">
        The dock walk, <span class="serif-accent">retired.</span>
      </h2>
      <span class="head-rule" aria-hidden="true"></span>
    </header>

    <div class="compare-grid">
      <div class="compare-col compare-old">
        <p class="compare-col-tag">The old hunt</p>
        <ul>
          {#each oldWay as item, i}
            <li style="--i:{i}">
              <span class="compare-x" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </span>
              {item}
            </li>
          {/each}
        </ul>
      </div>

      <div class="compare-vs" aria-hidden="true">
        <span>vs</span>
      </div>

      <div class="compare-col compare-new instrument">
        <p class="compare-col-tag compare-col-tag-new">With Carver</p>
        <ul>
          {#each carverWay as item, i}
            <li style="--i:{i}">
              <span class="compare-check" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              </span>
              <span><strong>{item.lead}</strong>{item.rest}</span>
            </li>
          {/each}
        </ul>
        <a
          href={whatsapp.link("Hi Carver — I'd like to start matching to yacht roles.")}
          target="_blank"
          rel="noopener noreferrer"
          class="cta-wa cta-shine compare-cta"
          onclick={() => trackEvent('compare_whatsapp_cta')}
        >
          <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
          Start free — 2 match runs on us
        </a>
      </div>
    </div>
  </div>
</section>

<style>
  .compare {
    padding: 5.5rem 1rem 5rem;
    background: var(--bg-base);
  }
  @media (min-width: 768px) { .compare { padding: 7rem 1.5rem 6rem; } }

  .compare-inner { max-width: 1100px; margin: 0 auto; }

  .compare-head { text-align: center; }
  .compare-title {
    margin: 1rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 5vw, 3.4rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }

  .head-rule {
    display: block;
    width: 76px;
    height: 2px;
    margin: 1.2rem auto 0;
    background: linear-gradient(90deg, transparent, var(--brass), transparent);
    transform: scaleX(0);
  }
  :global([data-visible='true']) .head-rule {
    animation: rule-draw 0.9s cubic-bezier(0.22, 1, 0.36, 1) 0.35s forwards;
  }
  @keyframes rule-draw {
    to { transform: scaleX(1); }
  }

  .compare-grid {
    margin-top: 3rem;
    display: grid;
    grid-template-columns: 1fr;
    gap: 1.25rem;
    align-items: stretch;
  }
  @media (min-width: 900px) {
    .compare-grid {
      grid-template-columns: 1fr auto 1.15fr;
      gap: 1.5rem;
    }
  }

  .compare-col { border-radius: 0.75rem; padding: 1.75rem 1.6rem; }

  .compare-old {
    border: 1px dashed rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.015);
  }
  .compare-col-tag {
    margin: 0 0 1.2rem;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .compare-col-tag-new { color: var(--radium); opacity: 0.9; }

  .compare-col ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.9rem;
  }
  .compare-col li {
    display: flex;
    gap: 0.7rem;
    align-items: flex-start;
    font-size: 14px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .compare-old li { color: var(--text-muted); }

  .compare-new li strong { color: var(--ivory); font-weight: 500; }

  /* Rows cascade in once the section's reveal wrapper flips visible.
     Default state stays visible so the section works unwrapped too. */
  :global([data-visible='true']) .compare-col li {
    animation: compare-row-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--i, 0) * 80ms + 180ms);
  }
  :global([data-visible='true']) .compare-new li {
    animation-delay: calc(var(--i, 0) * 80ms + 420ms);
  }
  @keyframes compare-row-in {
    from { opacity: 0; transform: translateX(-10px); }
    to   { opacity: 1; transform: translateX(0); }
  }
  /* Checks pop just after their row lands. */
  :global([data-visible='true']) .compare-check {
    animation: compare-check-pop 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) backwards;
    animation-delay: calc(var(--i, 0) * 80ms + 620ms);
  }
  @keyframes compare-check-pop {
    from { transform: scale(0); }
    to   { transform: scale(1); }
  }

  .compare-x,
  .compare-check {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.15rem;
    height: 1.15rem;
    flex: none;
    margin-top: 0.12rem;
    border-radius: 9999px;
  }
  .compare-x {
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: rgba(255, 255, 255, 0.35);
  }
  .compare-x svg { width: 9px; height: 9px; }
  .compare-check {
    border: 1px solid rgba(141, 240, 196, 0.4);
    background: rgba(141, 240, 196, 0.08);
    color: var(--radium);
  }
  .compare-check svg { width: 10px; height: 10px; }

  .compare-vs {
    display: none;
    align-items: center;
    justify-content: center;
  }
  @media (min-width: 900px) { .compare-vs { display: flex; } }
  .compare-vs span {
    font-family: var(--font-hand);
    font-size: 1.5rem;
    color: var(--brass);
    transform: rotate(-8deg);
  }

  .compare-new { padding-bottom: 1.6rem; }
  .compare-cta {
    margin-top: 1.5rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    width: 100%;
    padding: 0.9rem 1.2rem;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 600;
    text-decoration: none;
  }
  .compare-cta svg { width: 16px; height: 16px; }
</style>
