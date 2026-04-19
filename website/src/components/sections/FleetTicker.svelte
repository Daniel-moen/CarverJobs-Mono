<script>
  /**
   * FleetTicker — an AIS-style horizontal marquee of vessels in transit.
   *
   * Each item shows: vessel name, length, hull type, last port → next port.
   * Names are deliberately fictional but plausible — never use a real yacht
   * unless the owner has approved.  Lengths cluster around the realistic
   * 30–80m superyacht range, and the colour-coded "tier" badge maps to the
   * radium / brass / ivory accent palette so the strip feels lived-in.
   */

  /** Variant — "wide" (full bleed marquee) is default; "compact" for mobile heroes. */
  let { variant = 'wide' } = $props()

  const vessels = [
    { name: 'M/Y Lupus',     len: '62 m', type: 'M/Y', from: 'Antibes',   to: 'Palma',          tier: 'a' },
    { name: 'M/Y Astra',     len: '48 m', type: 'M/Y', from: 'Palma',     to: 'Ibiza',          tier: 'b' },
    { name: 'S/Y Hera',      len: '39 m', type: 'S/Y', from: 'Genoa',     to: 'Olbia',          tier: 'c' },
    { name: 'M/Y Polaris',   len: '55 m', type: 'M/Y', from: 'Monaco',    to: 'St. Tropez',     tier: 'a' },
    { name: 'M/Y Anatolia',  len: '71 m', type: 'M/Y', from: 'Marmaris',  to: 'Bodrum',         tier: 'b' },
    { name: 'S/Y Helios',    len: '45 m', type: 'S/Y', from: 'Viareggio', to: 'Naples',         tier: 'c' },
    { name: 'M/Y Northstar', len: '58 m', type: 'M/Y', from: 'Ft. Laud.', to: 'Gustavia',       tier: 'a' },
    { name: 'M/Y Mistral',   len: '42 m', type: 'M/Y', from: 'Cannes',    to: 'Porto Cervo',    tier: 'b' },
    { name: 'M/Y Atlantis',  len: '85 m', type: 'M/Y', from: 'Auckland',  to: 'Fiji',           tier: 'c' },
    { name: 'S/Y Aurora',    len: '37 m', type: 'S/Y', from: 'Split',     to: 'Dubrovnik',      tier: 'a' },
    { name: 'M/Y Capricorn', len: '50 m', type: 'M/Y', from: 'Mykonos',   to: 'Athens',         tier: 'b' },
    { name: 'M/Y Sabine',    len: '64 m', type: 'M/Y', from: 'Antibes',   to: 'Monte Carlo',    tier: 'c' },
  ]

  // Duplicate list so the CSS marquee loops seamlessly.
  const stream = [...vessels, ...vessels]
</script>

<div class="ticker" class:ticker-compact={variant === 'compact'}>
  <div class="ticker-mask">
    <div class="marquee">
      {#each stream as v, i}
        <span class="vessel" data-tier={v.tier} aria-hidden={i >= vessels.length}>
          <span class="vessel-tag">{v.type}</span>
          <span class="vessel-name">{v.name}</span>
          <span class="vessel-len">{v.len}</span>
          <span class="vessel-route">
            <span class="vessel-port">{v.from}</span>
            <svg class="vessel-arrow" viewBox="0 0 24 12" aria-hidden="true">
              <path d="M0 6 H20 M14 1 L20 6 L14 11" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="vessel-port">{v.to}</span>
          </span>
        </span>
      {/each}
    </div>
  </div>
</div>

<style>
  .ticker {
    width: 100%;
    border-top: 1px solid rgba(201, 169, 110, 0.16);
    border-bottom: 1px solid rgba(201, 169, 110, 0.16);
    background:
      linear-gradient(180deg, rgba(201, 169, 110, 0.025), transparent 40%, rgba(201, 169, 110, 0.025)),
      var(--bg-bridge);
    padding: 0.85rem 0;
  }
  .ticker-compact { padding: 0.55rem 0; }

  .ticker-mask {
    overflow: hidden;
    mask-image: linear-gradient(90deg, transparent 0%, black 6%, black 94%, transparent 100%);
    -webkit-mask-image: linear-gradient(90deg, transparent 0%, black 6%, black 94%, transparent 100%);
  }

  .vessel {
    display: inline-flex;
    align-items: center;
    gap: 0.85rem;
    padding-right: 3rem;
    border-right: 1px dashed rgba(201, 169, 110, 0.14);
    font-family: var(--font-mono);
    font-size: 12px;
    letter-spacing: 0.06em;
    white-space: nowrap;
    color: var(--text-secondary);
  }
  .ticker-compact .vessel {
    font-size: 10.5px;
    padding-right: 2rem;
    gap: 0.6rem;
  }

  .vessel-tag {
    font-size: 0.62rem;
    letter-spacing: 0.18em;
    color: var(--brass);
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.22);
    border-radius: 4px;
    padding: 0.05rem 0.35rem;
    text-transform: uppercase;
  }
  .vessel-name {
    font-family: var(--font-serif);
    font-style: italic;
    font-size: 14.5px;
    color: var(--ivory);
    letter-spacing: -0.005em;
  }
  .ticker-compact .vessel-name { font-size: 12.5px; }
  .vessel-len {
    color: var(--brass-bright);
    text-shadow: 0 0 12px rgba(201, 169, 110, 0.3);
  }
  .vessel-route {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: 0.66rem;
    letter-spacing: 0.18em;
  }
  .vessel-arrow {
    width: 22px;
    height: 10px;
    color: var(--brass-deep);
  }
  .vessel-port { color: var(--ivory-soft); }

  /* Tier accent — a small dot to the left of each vessel name */
  .vessel-tag::before {
    content: "";
    display: inline-block;
    width: 5px;
    height: 5px;
    margin-right: 0.4rem;
    border-radius: 9999px;
    background: var(--brass);
    box-shadow: 0 0 6px rgba(201, 169, 110, 0.45);
    vertical-align: middle;
  }
  .vessel[data-tier="a"] .vessel-tag::before {
    background: var(--radium);
    box-shadow: 0 0 6px rgba(141, 240, 196, 0.5);
  }
  .vessel[data-tier="c"] .vessel-tag::before {
    background: var(--ivory);
    box-shadow: 0 0 6px rgba(243, 234, 216, 0.4);
  }
</style>
