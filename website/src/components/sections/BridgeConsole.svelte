<script>
  /**
   * BridgeConsole — two plain-language cards explaining what Carver does.
   *
   * Card 1 — How matching works: 3-step description of the matching loop.
   * Card 2 — Where listings come from: labelled list of source categories.
   *
   * Rule: nothing in this component should look like product telemetry
   * unless it is wired to a real data source.
   */

  const sources = [
    'Captains hiring directly',
    'Verified crew agencies',
    'Crew WhatsApp groups',
    'Public job boards',
  ]

  const matchSteps = [
    {
      title: 'You text “match”',
      body: 'Carver pulls every active listing and your latest profile.',
    },
    {
      title: 'Filter, then rank',
      body: 'Role, certs, visa, salary band and availability — in that order.',
    },
    {
      title: 'We draft the email',
      body: 'Each match arrives with an introduction email Carver wrote for you. Tap “Open in Mail”, review, send.',
    },
  ]
</script>

<section class="bridge" aria-labelledby="bridge-title">
  <div class="bridge-inner">
    <header class="bridge-head">
      <p class="engraved">On the bridge</p>
      <h2 id="bridge-title" class="font-display text-4xl font-light leading-[1.05] text-white sm:text-5xl">
        A quiet first officer,
        <span class="font-hand text-radium">always watching.</span>
      </h2>
      <p class="bridge-sub">
        Carver runs in the background — scanning crew channels, captains' posts and agency
        feeds, then bringing the roles that actually fit your profile straight to your chat.
      </p>
    </header>

    <div class="instruments">
      <article class="instrument flow" style="--c:0">
        <div class="instrument-head">
          <span class="engraved">How matching works</span>
        </div>

        <ol class="flow-list">
          {#each matchSteps as step, i}
            <li class="flow-step" style="--i:{i}">
              <span class="flow-num">{String(i + 1).padStart(2, '0')}</span>
              <div>
                <p class="flow-title">{step.title}</p>
                <p class="flow-body">{step.body}</p>
              </div>
            </li>
          {/each}
        </ol>

        <p class="flow-foot">
          <span class="font-hand text-brass text-lg">No spray-and-pray.</span>
          <br/>
          You only see roles where the captain or agent is actually open to a profile like yours.
        </p>
      </article>

      <article class="instrument sources" style="--c:1">
        <div class="instrument-head">
          <span class="engraved">Where listings come from</span>
        </div>

        <ul class="src-list">
          {#each sources as name, i}
            <li class="src-row" style="--i:{i}">
              <span class="src-marker" aria-hidden="true"></span>
              <span class="src-name">{name}</span>
            </li>
          {/each}
        </ul>

        <p class="sources-foot">
          <span class="font-hand text-brass text-lg">No scraping ghosts.</span>
          <br/>
          Real captains, real groups, real listings — every entry is reviewed before it
          hits your match feed.
        </p>
      </article>
    </div>
  </div>
</section>

<style>
  .bridge {
    position: relative;
    background:
      radial-gradient(60% 50% at 50% 0%, rgba(201, 169, 110, 0.06), transparent 70%),
      var(--bg-bridge);
    padding: 6rem 1rem 7rem;
  }
  @media (min-width: 768px) { .bridge { padding: 8rem 1.5rem 9rem; } }

  .bridge-inner {
    max-width: 1080px;
    margin: 0 auto;
  }
  .bridge-head {
    max-width: 720px;
    margin: 0 auto 4rem;
    text-align: center;
  }
  .bridge-head .engraved {
    color: var(--brass);
    margin-bottom: 1rem;
    display: inline-block;
  }
  .bridge-sub {
    color: var(--text-secondary);
    font-size: 15px;
    line-height: 1.6;
    margin: 1.25rem auto 0;
    max-width: 540px;
  }

  .instruments {
    display: grid;
    grid-template-columns: 1fr;
    gap: 1.25rem;
  }
  @media (min-width: 820px) {
    .instruments {
      grid-template-columns: 1.05fr 0.95fr;
      gap: 1.75rem;
    }
  }

  .instrument {
    padding: 1.75rem 1.6rem 1.85rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    color: var(--text-primary);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 16px;
    background:
      radial-gradient(80% 80% at 50% 0%, rgba(255, 255, 255, 0.02), transparent 70%),
      rgba(10, 13, 18, 0.5);
  }
  .instrument-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.18);
    padding-bottom: 0.75rem;
  }

  /* Cards, steps and source rows cascade in behind the reveal wrapper. */
  :global([data-visible='true']) .instrument {
    animation: card-in 0.65s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--c, 0) * 160ms + 120ms);
  }
  @keyframes card-in {
    from { opacity: 0; transform: translateY(24px); }
  }
  :global([data-visible='true']) .flow-step,
  :global([data-visible='true']) .src-row {
    animation: row-slide 0.5s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--i, 0) * 110ms + var(--c, 0) * 160ms + 420ms);
  }
  @keyframes row-slide {
    from { opacity: 0; transform: translateX(-12px); }
  }

  .flow-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }
  .flow-step {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.95rem;
    align-items: start;
  }
  .flow-num {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    letter-spacing: 0.22em;
    color: var(--brass);
    padding-top: 0.15rem;
  }
  .flow-title {
    margin: 0;
    color: var(--ivory);
    font-family: var(--font-serif);
    font-size: 1.1rem;
    font-weight: 400;
    letter-spacing: -0.005em;
  }
  .flow-body {
    margin: 0.25rem 0 0;
    color: var(--text-secondary);
    font-size: 0.9rem;
    line-height: 1.55;
  }
  .flow-foot {
    margin-top: auto;
    padding-top: 1rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    font-size: 0.82rem;
    color: var(--text-secondary);
    line-height: 1.55;
  }

  .src-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .src-row {
    display: inline-flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.65rem 0.8rem;
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.04);
    background: rgba(0, 0, 0, 0.18);
    transition: border-color 0.2s ease, background 0.2s ease;
  }
  .src-row:hover {
    border-color: rgba(201, 169, 110, 0.3);
    background: rgba(201, 169, 110, 0.04);
  }
  .src-marker {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass);
    box-shadow: 0 0 6px rgba(201, 169, 110, 0.45);
  }
  .src-name {
    color: var(--ivory);
    font-size: 0.95rem;
    letter-spacing: -0.005em;
  }
  .sources-foot {
    margin-top: auto;
    padding-top: 1rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    font-size: 0.82rem;
    color: var(--text-secondary);
    line-height: 1.55;
  }
</style>
