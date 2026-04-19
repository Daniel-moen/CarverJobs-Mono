<script>
  /**
   * RouteMap — a stylised four-stop charter route showing how a candidate
   * moves from "first text" to "next berth".  Each stop is anchored on a
   * curved nautical course drawn in SVG, with brass dots and cardinal
   * coordinates beneath.
   *
   * The shape of the path is a hand-tuned cubic that flows L→R across the
   * panel; markers are positioned by `getPointAtLength` after mount so the
   * dots always sit exactly on the line, regardless of viewport width.
   */
  import { onMount } from 'svelte'

  const stops = [
    {
      label: 'Open WhatsApp',
      coord: 'departure',
      detail: 'Text “help” to Carver. The bot greets you and walks through onboarding right in chat — name, role, certs, salary range.',
      eyebrow: '01 · Departure',
    },
    {
      label: 'Text "match"',
      coord: 'at sea',
      detail: 'Carver scans every live yacht position against your profile and brings back the roles that actually fit — filtered by certs, visa, salary band and availability.',
      eyebrow: '02 · At sea',
    },
    {
      label: 'We draft the email',
      coord: 'open in mail',
      detail: 'For every match, Carver writes the introduction email tailored to the role. Tap “Open in Mail” and it opens in your own mail app — review it, hit send, gone in seconds.',
      eyebrow: '03 · Approach',
    },
    {
      label: 'Onto your next berth',
      coord: 'arrival',
      detail: 'Captain replies straight to your inbox, you keep the thread. Carver stays out of the way once the introduction is made.',
      eyebrow: '04 · Berth',
    },
  ]

  /** @type {SVGPathElement|null} */
  let pathEl = null
  /** Marker positions in SVG units, set after mount. */
  let positions = $state(/** @type {{ x: number; y: number }[]} */ ([]))

  onMount(() => {
    if (!pathEl) return
    const total = pathEl.getTotalLength()
    // Place each stop at evenly spaced fractions, with small padding from the ends.
    const fractions = stops.map((_, i) => {
      const inset = 0.04
      if (stops.length === 1) return 0.5
      return inset + (i * (1 - inset * 2)) / (stops.length - 1)
    })
    positions = fractions.map((f) => {
      const p = pathEl.getPointAtLength(total * f)
      return { x: p.x, y: p.y }
    })
  })
</script>

<section class="route-section" aria-labelledby="route-title">
  <header class="route-head">
    <p class="engraved text-radium">Route</p>
    <h2 id="route-title" class="font-display text-4xl font-light leading-[1.05] text-white sm:text-5xl">
      From signal to berth,
      <span class="font-hand text-brass">in four stops.</span>
    </h2>
    <p class="route-sub">
      Carver isn't a job board you scroll. It's a quiet first officer that runs the search,
      brings you the shortlist, and hands you the captain's introduction.
    </p>
  </header>

  <!-- Curved course diagram (sm+ only — replaced by a vertical timeline on mobile) -->
  <div class="route-canvas" aria-hidden="true">
    <svg viewBox="0 0 1200 240" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="route-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0"   stop-color="var(--brass-deep)" stop-opacity="0.05"/>
          <stop offset="0.15" stop-color="var(--brass)"      stop-opacity="0.65"/>
          <stop offset="0.85" stop-color="var(--brass)"      stop-opacity="0.65"/>
          <stop offset="1"   stop-color="var(--brass-deep)" stop-opacity="0.05"/>
        </linearGradient>
      </defs>

      <g stroke="rgba(255,255,255,0.04)" stroke-width="0.4">
        {#each Array.from({ length: 7 }) as _, i}
          <line x1={i * 200} y1="0" x2={i * 200} y2="240" />
        {/each}
        <line x1="0" y1="80" x2="1200" y2="80" />
        <line x1="0" y1="160" x2="1200" y2="160" />
      </g>

      <!-- the course itself — a gentle wave, like a nautical chart -->
      <path
        bind:this={pathEl}
        d="M 40 160 C 220 40, 420 220, 600 120 S 980 40, 1160 140"
        fill="none"
        stroke="url(#route-line)"
        stroke-width="1.4"
        stroke-dasharray="4 6"
      />

      <!-- glowing markers, positioned after mount -->
      {#each positions as pos, i}
        <g class="marker" transform={`translate(${pos.x} ${pos.y})`} style="animation-delay: {i * 200}ms">
          <circle r="14" fill="rgba(201, 169, 110, 0.08)" />
          <circle r="6"  fill="var(--brass-bright)" />
          <circle r="3"  fill="#0a0d12" />
        </g>
      {/each}
    </svg>
  </div>

  <!-- Stops grid — sits underneath the chart on desktop, stacks on mobile -->
  <ol class="route-stops">
    {#each stops as stop, i}
      <li class="stop">
        <div class="stop-marker" aria-hidden="true">
          <span class="stop-dot"></span>
          <span class="stop-num">{String(i + 1).padStart(2, '0')}</span>
        </div>
        <div class="stop-body">
          <p class="engraved">{stop.eyebrow}</p>
          <h3 class="stop-label">{stop.label}</h3>
          <p class="stop-coord">{stop.coord}</p>
          <p class="stop-detail">{stop.detail}</p>
          {#if i === 2}
            <span class="stop-chip" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="5" width="18" height="14" rx="2"/>
                <path d="m3 7 9 6 9-6"/>
              </svg>
              Open in Mail
              <span class="stop-chip-arrow">↗</span>
            </span>
          {/if}
        </div>
      </li>
    {/each}
  </ol>
</section>

<style>
  .route-section {
    background:
      radial-gradient(60% 50% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      var(--bg-bridge);
    padding: 6rem 1rem 7rem;
  }
  @media (min-width: 768px) { .route-section { padding: 8rem 1.5rem 9rem; } }

  .route-head {
    max-width: 720px;
    margin: 0 auto 3rem;
    text-align: center;
  }
  .route-head .engraved { display: inline-block; margin-bottom: 1rem; }
  .route-sub {
    color: var(--text-secondary);
    font-size: 15px;
    line-height: 1.6;
    margin: 1.25rem auto 0;
    max-width: 540px;
  }

  /* ── Course canvas ── */
  .route-canvas {
    max-width: 1180px;
    margin: 1.5rem auto 0;
    aspect-ratio: 1200 / 240;
    overflow: hidden;
  }
  .route-canvas svg {
    width: 100%;
    height: 100%;
    display: block;
  }
  @media (max-width: 720px) { .route-canvas { display: none; } }

  .marker {
    opacity: 0;
    animation: marker-in 0.6s ease-out forwards;
  }
  @keyframes marker-in {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* ── Stops grid ── */
  .route-stops {
    list-style: none;
    margin: 0 auto;
    padding: 0;
    max-width: 1180px;
    display: grid;
    grid-template-columns: 1fr;
    gap: 2rem;
  }
  @media (min-width: 720px) {
    .route-stops {
      grid-template-columns: repeat(4, 1fr);
      gap: 1.4rem;
      margin-top: -0.5rem;
    }
  }

  .stop {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 1rem;
    align-items: start;
  }
  @media (min-width: 720px) {
    .stop {
      grid-template-columns: 1fr;
      gap: 1rem;
      text-align: left;
    }
  }

  .stop-marker {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.45rem 0.65rem;
    border-radius: 9999px;
    border: 1px solid rgba(201, 169, 110, 0.25);
    background: rgba(201, 169, 110, 0.06);
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--brass);
    width: max-content;
  }
  .stop-dot {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright);
    box-shadow: 0 0 8px rgba(201, 169, 110, 0.55);
  }
  .stop-num { color: var(--brass-bright); }

  .stop-body { min-width: 0; }
  .stop-label {
    margin: 0.65rem 0 0.3rem;
    font-family: var(--font-serif);
    font-style: italic;
    font-weight: 400;
    color: var(--ivory);
    font-size: 1.4rem;
    line-height: 1.2;
  }
  .stop-coord {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-muted);
    letter-spacing: 0.12em;
  }
  .stop-detail {
    margin: 0.85rem 0 0;
    font-size: 13.5px;
    line-height: 1.6;
    color: var(--text-secondary);
  }

  .stop-chip {
    margin-top: 0.85rem;
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.45rem 0.75rem;
    border-radius: 9999px;
    border: 1px solid rgba(141, 240, 196, 0.35);
    background: rgba(141, 240, 196, 0.06);
    color: var(--radium);
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .stop-chip svg { width: 13px; height: 13px; }
  .stop-chip-arrow {
    color: var(--radium);
    opacity: 0.75;
    margin-left: 0.1rem;
  }
</style>
