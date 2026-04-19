<script>
  /**
   * AgencySection — pitch for crew agencies & captains hiring directly.
   *
   * No metrics, no fake testimonials. Three plain value props + a single
   * primary CTA wired to the existing /signup/agency flow.
   */
  let { onAgencySignup = () => {} } = $props()

  const points = [
    {
      title: 'Post a role in under a minute',
      body:
        'Paste the position, set role and salary, done. Carver writes the listing and pushes it to every active candidate that matches.',
    },
    {
      title: 'Only relevant applicants',
      body:
        'Candidates are filtered by role, certs, visa, salary band and availability before they ever reach your inbox.',
    },
    {
      title: 'Free during private beta',
      body:
        'No contract, no per-placement fee, no card on file. Cancel any time — the listing comes down within minutes.',
    },
  ]
</script>

<section id="agencies" class="agencies" aria-labelledby="agencies-title" data-animate>
  <div class="agencies-inner">
    <header class="agencies-head">
      <p class="engraved text-brass">For captains &amp; crew agencies</p>
      <h2 id="agencies-title" class="agencies-title">
        Hiring crew?
        <span class="font-hand text-brass">Post the role, we&rsquo;ll do the legwork.</span>
      </h2>
      <p class="agencies-sub">
        Carver routes your position to candidates whose profile actually fits — not the
        whole inbox. You get a short list, they get a real shot.
      </p>
    </header>

    <ul class="agencies-points">
      {#each points as p, i}
        <li class="point">
          <span class="point-num">0{i + 1}</span>
          <h3 class="point-title">{p.title}</h3>
          <p class="point-body">{p.body}</p>
        </li>
      {/each}
    </ul>

    <div class="agencies-cta-row">
      <button
        type="button"
        onclick={() => onAgencySignup('agency_section')}
        class="agencies-cta"
      >
        Post a position
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </button>
      <p class="agencies-cta-foot">
        Takes about a minute · no payment details required
      </p>
    </div>
  </div>
</section>

<style>
  .agencies {
    background:
      radial-gradient(60% 50% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      var(--bg-bridge);
    padding: 6rem 1rem 7rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    border-bottom: 1px dashed rgba(201, 169, 110, 0.18);
  }
  @media (min-width: 768px) { .agencies { padding: 8rem 1.5rem 9rem; } }

  .agencies-inner {
    max-width: 1080px;
    margin: 0 auto;
  }

  .agencies-head {
    max-width: 720px;
    margin: 0 auto 3.5rem;
    text-align: center;
  }
  .agencies-head .engraved {
    display: inline-block;
    margin-bottom: 1rem;
  }
  .agencies-title {
    margin: 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2.2rem, 5vw, 3.4rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }
  .agencies-sub {
    margin: 1.25rem auto 0;
    max-width: 540px;
    color: var(--text-secondary);
    font-size: 15px;
    line-height: 1.6;
  }

  .agencies-points {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: 1fr;
    gap: 1.25rem;
  }
  @media (min-width: 760px) {
    .agencies-points { grid-template-columns: repeat(3, 1fr); gap: 1.5rem; }
  }

  .point {
    padding: 1.5rem 1.4rem 1.6rem;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    background:
      radial-gradient(80% 80% at 50% 0%, rgba(255, 255, 255, 0.025), transparent 70%),
      #0a1015;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .point-num {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.22em;
    color: var(--brass);
  }
  .point-title {
    margin: 0;
    font-family: var(--font-serif);
    font-weight: 400;
    color: var(--ivory);
    font-size: 1.15rem;
    letter-spacing: -0.005em;
  }
  .point-body {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.92rem;
    line-height: 1.55;
  }

  .agencies-cta-row {
    margin-top: 3rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
  }
  .agencies-cta {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 1rem 1.6rem;
    border-radius: 9999px;
    background: rgba(243, 234, 216, 0.06);
    border: 1px solid rgba(243, 234, 216, 0.3);
    color: var(--ivory);
    font-size: 13.5px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
  }
  .agencies-cta:hover {
    background: rgba(243, 234, 216, 0.13);
    border-color: rgba(243, 234, 216, 0.45);
    transform: translateY(-1px);
  }
  .agencies-cta:focus-visible {
    outline: 2px solid var(--brass-bright);
    outline-offset: 3px;
  }
  .agencies-cta svg { width: 14px; height: 14px; }
  .agencies-cta-foot {
    margin: 0;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.06em;
  }
</style>
