<script>
  /**
   * BridgeConsole — three "bridge instrument" cards.
   *
   * Card 1 — Compass: ambient decorative dial with a slowly drifting needle
   *          and a rotating list of common Med / Caribbean ports. No metrics.
   * Card 2 — How matching works: plain-language description of the matching
   *          loop. No fabricated counts or scan times.
   * Card 3 — Where listings come from: labelled list of source categories.
   *          No percentages, no fake "last 24h" totals.
   *
   * Rule: nothing in this component should look like product telemetry unless
   * it is actually wired to a real data source.
   */
  import { onDestroy, onMount } from 'svelte'

  /** @type {{ paused?: boolean }} */
  let { paused = false } = $props()

  const portRotation = [
    { name: 'Antibes',           coord: '43°34′N · 07°07′E' },
    { name: 'Palma de Mallorca', coord: '39°34′N · 02°39′E' },
    { name: 'Monaco',            coord: '43°44′N · 07°25′E' },
    { name: 'Genoa',             coord: '44°25′N · 08°56′E' },
    { name: 'Fort Lauderdale',   coord: '26°07′N · 80°08′W' },
    { name: 'Gustavia',          coord: '17°54′N · 62°51′W' },
    { name: 'Viareggio',         coord: '43°52′N · 10°15′E' },
  ]

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

  let portIdx = $state(0)
  let heading = $state(127)

  /** @type {ReturnType<typeof setInterval>[]} */
  let timers = []

  function start() {
    stop()
    timers.push(setInterval(() => { portIdx = (portIdx + 1) % portRotation.length }, 3200))
    timers.push(setInterval(() => {
      const drift = (Math.random() - 0.5) * 14
      heading = Math.max(60, Math.min(160, heading + drift))
    }, 1800))
  }

  function stop() {
    timers.forEach(clearInterval)
    timers = []
  }

  onMount(start)
  onDestroy(stop)

  $effect(() => {
    if (paused) stop()
    else if (timers.length === 0) start()
  })

  const port = $derived(portRotation[portIdx])
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
      <article class="instrument compass">
        <div class="instrument-head">
          <span class="engraved">Compass</span>
          <span class="readout text-sm">{Math.round(heading).toString().padStart(3, '0')}°</span>
        </div>

        <div class="compass-dial" aria-hidden="true">
          <svg viewBox="0 0 200 200">
            <g fill="none" stroke="currentColor" class="text-brass" opacity="0.65">
              <circle cx="100" cy="100" r="92" stroke-width="0.6"/>
              <circle cx="100" cy="100" r="74" stroke-width="0.4" stroke-dasharray="1 4"/>
              <circle cx="100" cy="100" r="58" stroke-width="0.4"/>
              {#each Array.from({ length: 36 }) as _, i}
                {@const a = (i * 10 * Math.PI) / 180}
                {@const x1 = 100 + 86 * Math.sin(a)}
                {@const y1 = 100 - 86 * Math.cos(a)}
                {@const x2 = 100 + (i % 9 === 0 ? 70 : 78) * Math.sin(a)}
                {@const y2 = 100 - (i % 9 === 0 ? 70 : 78) * Math.cos(a)}
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke-width={i % 9 === 0 ? 1.2 : 0.4}
                      opacity={i % 9 === 0 ? 1 : 0.55} />
              {/each}
            </g>
            <g class="text-brass" font-family="DM Mono, ui-monospace, monospace" font-size="9" letter-spacing="2">
              <text x="100" y="22"  text-anchor="middle" fill="currentColor">N</text>
              <text x="180" y="103" text-anchor="middle" fill="currentColor">E</text>
              <text x="100" y="184" text-anchor="middle" fill="currentColor">S</text>
              <text x="20"  y="103" text-anchor="middle" fill="currentColor">W</text>
            </g>
            <g style="transform: rotate({heading}deg); transform-origin: 100px 100px; transition: transform 1.6s ease;">
              <polygon points="100,18 104,100 100,104 96,100" fill="var(--radium)" opacity="0.9"/>
              <polygon points="100,182 104,100 100,96 96,100" fill="var(--brass-deep)" opacity="0.7"/>
              <circle cx="100" cy="100" r="5" fill="var(--brass-bright)"/>
              <circle cx="100" cy="100" r="2.2" fill="#0a0d12"/>
            </g>
            <g class="radar-sweep" style="transform-origin: 100px 100px;">
              <defs>
                <linearGradient id="sweep" x1="100" y1="100" x2="100" y2="20" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="var(--radium)" stop-opacity="0"/>
                  <stop offset="1" stop-color="var(--radium)" stop-opacity="0.45"/>
                </linearGradient>
              </defs>
              <path d="M100,100 L100,16 A84,84 0 0 1 168,72 Z" fill="url(#sweep)"/>
            </g>
          </svg>
        </div>

        <div class="compass-foot">
          <p class="engraved">Charter waypoint</p>
          {#key portIdx}
            <p class="port-name">{port.name}</p>
            <p class="port-coord readout">{port.coord}</p>
          {/key}
        </div>
      </article>

      <article class="instrument flow">
        <div class="instrument-head">
          <span class="engraved">How matching works</span>
        </div>

        <ol class="flow-list">
          {#each matchSteps as step, i}
            <li class="flow-step">
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

      <article class="instrument sources">
        <div class="instrument-head">
          <span class="engraved">Where listings come from</span>
        </div>

        <ul class="src-list">
          {#each sources as name}
            <li class="src-row">
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
    max-width: 1180px;
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
  @media (min-width: 900px) {
    .instruments {
      grid-template-columns: 1.05fr 1fr 0.95fr;
      gap: 1.5rem;
    }
  }

  .instrument {
    padding: 1.5rem 1.4rem 1.6rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
    color: var(--text-primary);
  }
  .instrument-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.18);
    padding-bottom: 0.65rem;
  }

  .compass-dial {
    aspect-ratio: 1 / 1;
    width: 70%;
    align-self: center;
    color: var(--brass);
  }
  .compass-foot {
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    padding-top: 0.85rem;
    text-align: center;
  }
  .port-name {
    margin: 0.4rem 0 0.15rem;
    font-family: var(--font-serif);
    font-style: italic;
    color: var(--ivory);
    font-size: 1.4rem;
    letter-spacing: -0.005em;
    animation: port-fade 0.5s ease-out;
  }
  .port-coord {
    margin: 0;
    font-size: 0.78rem;
    letter-spacing: 0.18em;
    animation: port-fade 0.5s ease-out;
  }
  @keyframes port-fade {
    from { opacity: 0; transform: translateY(2px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .flow-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .flow-step {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.85rem;
    align-items: start;
  }
  .flow-num {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    letter-spacing: 0.22em;
    color: var(--brass);
    padding-top: 0.1rem;
  }
  .flow-title {
    margin: 0;
    color: var(--ivory);
    font-family: var(--font-serif);
    font-size: 1.05rem;
    font-weight: 400;
    letter-spacing: -0.005em;
  }
  .flow-body {
    margin: 0.2rem 0 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
    line-height: 1.55;
  }
  .flow-foot {
    margin-top: auto;
    padding-top: 0.9rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    font-size: 0.78rem;
    color: var(--text-secondary);
    line-height: 1.55;
  }

  .src-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }
  .src-row {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.55rem 0.7rem;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.04);
    background: rgba(0, 0, 0, 0.18);
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
    font-size: 0.92rem;
    letter-spacing: -0.005em;
  }
  .sources-foot {
    margin-top: auto;
    padding-top: 0.9rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.18);
    font-size: 0.78rem;
    color: var(--text-secondary);
    line-height: 1.55;
  }
</style>
