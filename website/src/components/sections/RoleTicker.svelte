<script>
  /**
   * RoleTicker — an AIS-style marquee of crew roles and ports that scrolls
   * under the hero. Purely decorative (aria-hidden, no "live" claim): it
   * paints the world Carver operates in — deck to galley, Med to Caribbean —
   * and keeps the page feeling alive between the hero and the bridge.
   *
   * Uses the shared .marquee keyframes from app.css (translateX(-50%) over
   * a duplicated track = seamless loop). Pauses on hover; the global
   * reduced-motion rule freezes it entirely.
   */
  const stops = [
    ['Deckhand', 'Antibes'],
    ['Chief Stew', 'Palma'],
    ['2nd Engineer', 'Monaco'],
    ['Sole Chef', 'Nassau'],
    ['Bosun', 'Fort Lauderdale'],
    ['3rd Officer', 'Genoa'],
    ['Stew / Masseuse', 'Ibiza'],
    ['ETO', 'Barcelona'],
    ['Chase Boat Captain', 'St Tropez'],
    ['Junior Stew', 'Split'],
    ['Chief Officer', 'San Remo'],
    ['Cook / Stew', 'Tortola'],
  ]
  // Track rendered twice for the seamless -50% loop.
  const track = [...stops, ...stops]
</script>

<div class="ticker" aria-hidden="true">
  <div class="marquee ticker-track">
    {#each track as [role, port]}
      <span class="ticker-item">
        <span class="ticker-pip"></span>
        <strong>{role}</strong>
        <span class="ticker-port">{port}</span>
      </span>
    {/each}
  </div>
</div>

<style>
  .ticker {
    position: relative;
    overflow: hidden;
    padding: 0.85rem 0;
    border-top: 1px dashed rgba(201, 169, 110, 0.2);
    border-bottom: 1px dashed rgba(201, 169, 110, 0.2);
    background: rgba(201, 169, 110, 0.02);
    /* fade the edges so the loop never shows a hard cut */
    mask-image: linear-gradient(90deg, transparent, black 8%, black 92%, transparent);
    -webkit-mask-image: linear-gradient(90deg, transparent, black 8%, black 92%, transparent);
  }
  .ticker:hover .ticker-track { animation-play-state: paused; }

  .ticker-track { gap: 2.4rem; }

  .ticker-item {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .ticker-item strong {
    color: var(--ivory);
    font-weight: 500;
  }
  .ticker-port { color: var(--brass); }
  .ticker-pip {
    width: 4px;
    height: 4px;
    border-radius: 9999px;
    background: var(--brass-deep);
    box-shadow: 0 0 6px rgba(201, 169, 110, 0.4);
  }
</style>
