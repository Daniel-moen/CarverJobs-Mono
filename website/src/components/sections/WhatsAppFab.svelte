<script>
  import { whatsapp } from '../../config/site'

  let { message = "Hi Carver — I'd like to try the WhatsApp matching." } = $props()
  const href = $derived(whatsapp.link(message))

  let dismissed = $state(false)
  let expanded = $state(false)
</script>

{#if !dismissed}
  <div class="wa-fab-root" aria-label="Chat with Carver on WhatsApp">
    {#if expanded}
      <div class="wa-pop">
        <div class="wa-pop-head">
          <span class="wa-dot"></span>
          <p class="wa-pop-title">Carver on WhatsApp</p>
          <button
            class="wa-pop-x"
            type="button"
            aria-label="Hide"
            onclick={() => { expanded = false; dismissed = true }}
          >×</button>
        </div>
        <p class="wa-pop-body">
          Run <span class="wa-mono">match</span>, <span class="wa-mono">apply 142</span>,
          <span class="wa-mono">status</span> — straight from your phone. No app, no install.
        </p>
        <a class="wa-pop-cta" href={href} target="_blank" rel="noopener noreferrer">
          Open in WhatsApp →
        </a>
        <p class="wa-pop-foot">{whatsapp.display}</p>
      </div>
    {/if}

    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      class="wa-fab"
      onmouseenter={() => (expanded = true)}
      onfocus={() => (expanded = true)}
      aria-label="Open Carver in WhatsApp"
    >
      <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
        <path d="M16.001 3C9.373 3 4 8.373 4 15c0 2.345.668 4.534 1.823 6.388L4 29l7.812-1.79A11.95 11.95 0 0 0 16.001 27c6.628 0 12-5.373 12-12S22.629 3 16.001 3Zm0 21.6c-1.836 0-3.55-.49-5.027-1.343l-.36-.213-4.638 1.063 1.085-4.524-.232-.371A9.567 9.567 0 0 1 6.4 15c0-5.292 4.31-9.6 9.602-9.6 5.293 0 9.601 4.308 9.601 9.6 0 5.293-4.308 9.6-9.601 9.6Zm5.276-7.18c-.289-.144-1.71-.842-1.974-.939-.265-.097-.458-.144-.65.144-.193.289-.748.939-.917 1.131-.169.193-.337.217-.626.072-.289-.144-1.22-.45-2.324-1.434-.86-.766-1.44-1.713-1.609-2.002-.169-.289-.018-.445.127-.589.131-.13.289-.337.434-.506.144-.169.193-.289.289-.482.097-.193.048-.361-.024-.506-.072-.144-.65-1.566-.89-2.144-.234-.563-.473-.486-.65-.495l-.553-.01c-.193 0-.506.072-.771.361-.265.289-1.012.989-1.012 2.411 0 1.422 1.036 2.797 1.18 2.99.144.193 2.04 3.116 4.94 4.367.69.298 1.228.475 1.648.608.692.22 1.322.189 1.821.115.555-.083 1.71-.699 1.951-1.374.241-.674.241-1.252.169-1.374-.072-.121-.265-.193-.554-.337Z"/>
      </svg>
      <span class="wa-fab-label">WhatsApp</span>
    </a>
  </div>
{/if}

<style>
  .wa-fab-root {
    position: fixed;
    right: clamp(0.75rem, 2vw, 1.5rem);
    bottom: clamp(0.75rem, 2vw, 1.5rem);
    z-index: 60;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.5rem;
    pointer-events: none;
  }

  .wa-fab {
    pointer-events: auto;
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.7rem 1rem 0.7rem 0.9rem;
    border-radius: 9999px;
    color: #04070b;
    background: linear-gradient(180deg, #25d366 0%, #1ebd5d 100%);
    border: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.4) inset,
      0 0 0 4px rgba(37, 211, 102, 0.15),
      0 18px 38px -16px rgba(37, 211, 102, 0.55);
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.01em;
    text-decoration: none;
    transition: transform 0.18s ease, box-shadow 0.25s ease, filter 0.18s ease;
  }
  .wa-fab svg { width: 18px; height: 18px; }
  .wa-fab:hover {
    transform: translateY(-2px);
    filter: brightness(1.05);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.4) inset,
      0 0 0 6px rgba(37, 211, 102, 0.2),
      0 22px 50px -16px rgba(37, 211, 102, 0.65);
  }
  .wa-fab::before {
    content: "";
    position: absolute;
    inset: -8px;
    border-radius: 9999px;
    background: rgba(37, 211, 102, 0.35);
    z-index: -1;
    animation: wa-pulse 2.6s ease-out infinite;
    pointer-events: none;
  }
  .wa-fab { position: relative; isolation: isolate; }

  @keyframes wa-pulse {
    0% { transform: scale(0.9); opacity: 0.65; }
    80%, 100% { transform: scale(1.45); opacity: 0; }
  }

  /* Hide the text on very small screens; keep just the icon */
  @media (max-width: 480px) {
    .wa-fab-label { display: none; }
    .wa-fab { padding: 0.7rem; }
  }

  /* Pop-over card */
  .wa-pop {
    pointer-events: auto;
    width: 280px;
    padding: 14px;
    border-radius: 16px;
    background:
      radial-gradient(120% 80% at 0% 0%, rgba(37, 211, 102, 0.06), transparent 55%),
      linear-gradient(180deg, #0c1117 0%, #080c11 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 0 30px 80px -30px rgba(0, 0, 0, 0.6);
    color: #f4f6f8;
    animation: wa-pop-in 0.22s ease-out;
  }
  @keyframes wa-pop-in {
    from { opacity: 0; transform: translateY(6px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  .wa-pop-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .wa-dot {
    width: 8px;
    height: 8px;
    border-radius: 9999px;
    background: #25d366;
    box-shadow: 0 0 0 4px rgba(37, 211, 102, 0.18);
  }
  .wa-pop-title {
    margin: 0;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: #f3ead8;
  }
  .wa-pop-x {
    margin-left: auto;
    width: 22px;
    height: 22px;
    border-radius: 9999px;
    background: rgba(255, 255, 255, 0.06);
    border: none;
    color: #a8b3bf;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
  }
  .wa-pop-x:hover { color: #fff; background: rgba(255, 255, 255, 0.12); }
  .wa-pop-body {
    margin: 10px 0 12px;
    font-size: 12.5px;
    line-height: 1.55;
    color: #a8b3bf;
  }
  .wa-mono {
    font-family: "Geist Mono", ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(37, 211, 102, 0.12);
    color: #a7f3c4;
    border: 1px solid rgba(37, 211, 102, 0.25);
  }
  .wa-pop-cta {
    display: block;
    text-align: center;
    padding: 10px 14px;
    border-radius: 10px;
    background: linear-gradient(180deg, #25d366 0%, #1ebd5d 100%);
    color: #04070b;
    font-size: 13px;
    font-weight: 700;
    text-decoration: none;
    border: 1px solid rgba(0, 0, 0, 0.12);
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.4) inset;
  }
  .wa-pop-foot {
    margin: 8px 0 0;
    text-align: center;
    font-family: "Geist Mono", ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 10px;
    letter-spacing: 0.18em;
    color: #6a7280;
    text-transform: uppercase;
  }

  @media (prefers-reduced-motion: reduce) {
    .wa-fab::before { animation: none; }
    .wa-pop { animation: none; }
  }
</style>
