<script>
  /**
   * FaqSection — objection handling, one accordion per objection.
   *
   * Every answer states a real product fact (free runs, token pricing,
   * job-post rewards, refund window, data handling). FAQPage JSON-LD is
   * injected for rich results in search.
   */
  import { trackEvent } from '../../config/analytics'

  const faqs = [
    {
      q: 'How much does it cost?',
      a: 'Starting is free — your first 2 match runs are on us, no card needed. After that you buy tokens: one token runs one full matching session and costs between R9 and R13 depending on pack size. There is no subscription and tokens never expire.',
    },
    {
      q: 'What exactly does one token buy?',
      a: 'One complete matching run: Carver scans every live superyacht role, ranks the ones that fit your certs, visa, salary band and availability, and drafts a tailored application email for each match. You review and hit send.',
    },
    {
      q: 'Can I earn tokens without paying?',
      a: 'Yes. Spot a crew job in a WhatsApp group or on a noticeboard? Send Carver a screenshot. If it is a real yacht role we post it to the board and credit you a free token — up to 5 per month.',
    },
    {
      q: 'Do I need to install anything?',
      a: 'No. Carver runs entirely inside WhatsApp — the app you already use. Prefer a bigger screen? Everything also works on the website with the same account.',
    },
    {
      q: 'Where do the jobs come from?',
      a: 'Captains hiring directly, verified crew agencies, crew WhatsApp groups, and public job boards — pulled together in one place so you never miss a berth because you were watching the wrong group.',
    },
    {
      q: 'What if I buy tokens and change my mind?',
      a: 'Unused tokens are refundable within 14 days of purchase. Payments are processed securely by Yoco and there are no recurring charges — you only ever pay when you choose to top up.',
    },
    {
      q: 'Is my data safe?',
      a: 'Yes. Your profile and documents are encrypted in transit and at rest, hosted in the EU, and handled GDPR-first. You can ask Carver to delete everything at any time.',
    },
  ]

  let open = $state(0)

  function toggle(i) {
    open = open === i ? -1 : i
    if (open === i) trackEvent('faq_open', { value: String(i) })
  }

  const faqJsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map((f) => ({
      '@type': 'Question',
      name: f.q,
      acceptedAnswer: { '@type': 'Answer', text: f.a },
    })),
  })
</script>

<svelte:head>
  {@html `<script type="application/ld+json">${faqJsonLd}<\/script>`}
</svelte:head>

<section id="faq" class="faq" aria-labelledby="faq-title">
  <div class="faq-inner">
    <header class="faq-head">
      <p class="engraved">Before you cast off</p>
      <h2 id="faq-title" class="faq-title">Fair <span class="serif-accent">questions.</span></h2>
      <span class="head-rule" aria-hidden="true"></span>
    </header>

    <div class="faq-list">
      {#each faqs as f, i}
        <div class="faq-item" class:faq-item-open={open === i} style="--i:{i}">
          <button
            type="button"
            class="faq-q"
            aria-expanded={open === i}
            aria-controls={"faq-a-" + i}
            onclick={() => toggle(i)}
          >
            <span>{f.q}</span>
            <span class="faq-chevron" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </span>
          </button>
          {#if open === i}
            <p class="faq-a" id={"faq-a-" + i}>{f.a}</p>
          {/if}
        </div>
      {/each}
    </div>
  </div>
</section>

<style>
  .faq {
    padding: 5.5rem 1rem 5rem;
    background: var(--bg-base);
  }
  @media (min-width: 768px) { .faq { padding: 6.5rem 1.5rem 6rem; } }

  .faq-inner { max-width: 760px; margin: 0 auto; }

  .faq-head { text-align: center; }
  .faq-title {
    margin: 1rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 5vw, 3.2rem);
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
  /* Outside a reveal wrapper (the /pricing page) the rule is simply drawn. */
  :global(.pricing) .head-rule { transform: scaleX(1); }

  .faq-list {
    margin-top: 2.75rem;
    display: grid;
    gap: 0.6rem;
  }
  /* Items cascade in behind the reveal wrapper. */
  :global([data-visible='true']) .faq-item {
    animation: faq-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--i, 0) * 65ms + 200ms);
  }
  @keyframes faq-in {
    from { opacity: 0; transform: translateY(14px); }
  }

  .faq-item {
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.015);
    transition: border-color 0.2s ease, background 0.2s ease;
  }
  .faq-item:hover { border-color: rgba(201, 169, 110, 0.28); }
  .faq-item-open {
    border-color: rgba(201, 169, 110, 0.35);
    background:
      radial-gradient(80% 60% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      rgba(255, 255, 255, 0.02);
  }

  .faq-q {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1.05rem 1.25rem;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--ivory);
    font-size: 15px;
    font-weight: 500;
    font-family: var(--font-sans);
  }

  .faq-chevron {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    flex: none;
    border-radius: 9999px;
    border: 1px solid rgba(201, 169, 110, 0.3);
    color: var(--brass);
    transition: transform 0.25s ease;
  }
  .faq-chevron svg { width: 12px; height: 12px; }
  .faq-item-open .faq-chevron { transform: rotate(180deg); }

  .faq-a {
    margin: 0;
    padding: 0 1.25rem 1.2rem;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.65;
  }
</style>
