<script>
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'

  let { onSignIn = () => {}, onStartMatch = () => {}, onAgencySignup = () => {} } = $props()

  onMount(() => {
    const depths = new Set()

    function onScroll() {
      const body = document.body
      const denom = body?.scrollHeight || 1
      const pct = Math.round(((window.scrollY + window.innerHeight) / denom) * 100)

      for (const threshold of [25, 50, 75, 100]) {
        if (pct >= threshold && !depths.has(threshold)) {
          depths.add(threshold)
          trackEvent('scroll_depth', { page: 'landing', value: String(threshold) })
        }
      }
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    // Capture an initial scroll position (e.g. returning via back button).
    onScroll()

    return () => window.removeEventListener('scroll', onScroll)
  })

  const features = [
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>`,
      title: 'Auto-Apply Engine',
      desc: 'CARVER scans live listings and submits your application automatically.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>`,
      title: 'Smart Matching',
      desc: 'AI-powered compatibility scoring ensures you only apply where you fit.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
      title: 'Document Vault',
      desc: 'Upload your CV, STCW, ENG1, and passport once. We handle the rest.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
      title: 'Live Job Board',
      desc: 'Real-time superyacht vacancies aggregated and filtered for you.',
    },
  ]

  const steps = [
    { num: '01', title: 'Build your profile', desc: 'Upload your documents and set your experience.' },
    { num: '02', title: 'Set your criteria', desc: 'Tell CARVER what you’re looking for.' },
    { num: '03', title: 'Activate Auto-Apply', desc: 'CARVER matches and applies on your behalf.' },
    { num: '04', title: 'Track & respond', desc: 'Monitor your pipeline and respond to interview invites.' },
  ]
</script>

<div class="min-h-screen bg-[#04070b] text-slate-100 relative overflow-hidden">
  <nav class="sticky top-0 z-50 w-full border-b border-white/[0.06] bg-[#04070b]/90 backdrop-blur-xl">
    <div class="mx-auto flex max-w-7xl items-center justify-between px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
      <a href="/" class="flex items-center gap-2">
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        <span class="font-display text-[14px] tracking-[0.38em] text-ivory">CARVER</span>
      </a>
      <button
        type="button"
        onclick={() => onSignIn('nav')}
        class="rounded-full border border-white/15 bg-white/[0.04] px-4 py-1.5 text-[12px] font-medium text-slate-200 transition-all duration-200 hover:border-cyan-300/50 hover:text-white"
      >
        Sign in
      </button>
    </div>
  </nav>

  <div class="pointer-events-none absolute inset-0" aria-hidden="true">
    <div class="mobile-grid-bg absolute inset-0"></div>
    <div class="mobile-orb mobile-orb-1"></div>
    <div class="mobile-orb mobile-orb-2"></div>
    <div class="mobile-orb mobile-orb-3"></div>
  </div>

  <main class="relative z-10 mx-auto w-full max-w-3xl px-4 pb-10 pt-8">
    <section class="text-center">
      <div class="mx-auto inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/[0.025] px-4 py-1.5">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400 animate-pulse"></span>
        <span class="font-mono text-[10px] uppercase tracking-[0.22em] text-slate-300">Superyacht crew &middot; Beta</span>
      </div>

      <h1 class="mt-6 font-display text-[clamp(2.1rem,9.5vw,3.4rem)] font-light leading-[1.04] text-white">
        Every yacht job.<br />
        <em class="gradient-text font-light italic">One place.</em><br />
        Auto-matched.
      </h1>

      <p class="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-300/85">
        We aggregate listings from 50+ crew groups, agencies, and any source with a contact email —
        so you stop scrolling and start applying.
      </p>

      <div class="mt-8 flex flex-col items-center gap-3">
        <button
          type="button"
          onclick={() => onSignIn('hero')}
          class="cta-primary group w-full rounded-xl px-7 py-3.5 text-[13px] font-semibold text-[#04070b] transition-all duration-200"
        >
          Join the Beta · First 100 discount
        </button>
        <a
          href="#how-it-works"
          class="w-full rounded-xl border border-white/15 px-7 py-3.5 text-[13px] font-medium text-slate-300 transition-all duration-200 hover:border-white/30 hover:text-white text-center"
        >
          How it works →
        </a>
      </div>

      <div class="mt-7 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-[11px] text-slate-500">
        <span class="inline-flex items-center gap-1.5">
          <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          TLS encrypted
        </span>
        <span class="text-slate-700">·</span>
        <span>EU data residency</span>
        <span class="text-slate-700">·</span>
        <span>Used by crew in Med &amp; Caribbean</span>
      </div>
    </section>

    <section class="mt-14 text-center">
      <p class="eyebrow">Community-powered</p>
      <h2 class="mt-3 font-display text-3xl font-light text-white sm:text-4xl">See one we missed?</h2>
      <p class="mx-auto mt-4 max-w-md text-[14px] leading-relaxed text-slate-400">
        Saw a job in a crew group or social post? Submit it with a screenshot or pasted text — we add it to the board
        and you earn a token. Hiring managers can post positions directly too.
      </p>
    </section>

    <section class="mt-14">
      <div class="text-center">
        <p class="eyebrow">Features</p>
        <h2 class="mt-3 font-display text-3xl font-light text-white sm:text-4xl">Built for superyacht crew</h2>
        <p class="mx-auto mt-3 max-w-md text-[14px] leading-relaxed text-slate-400">
          Every feature is designed for working on the water: faster applications and smarter matching.
        </p>
      </div>

      <div class="mt-8 grid gap-3 sm:grid-cols-2">
        {#each features as feature}
          <article class="rounded-2xl border border-white/[0.07] bg-[#0a0e14] p-5">
            <div class="flex items-center gap-3">
              <div class="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-cyan-300">
                {@html feature.icon}
              </div>
              <h3 class="text-[15px] font-semibold text-white">{feature.title}</h3>
            </div>
            <p class="mt-3 text-[13.5px] leading-relaxed text-slate-400">{feature.desc}</p>
          </article>
        {/each}
      </div>
    </section>

    <section class="mt-14 rounded-3xl border border-white/[0.08] bg-[#0a0e14]/80 p-5">
      <div class="flex items-start gap-3">
        <span class="mt-1.5 h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
        <div>
          <p class="eyebrow">Matching Engine</p>
          <h3 class="mt-2 font-display text-2xl font-light text-white">Find your <em class="italic">best fit</em></h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-400">
            Sign in to run the matching engine against your profile. We’ll scan open positions and return the one that fits.
          </p>
        </div>
      </div>

      <div class="mt-5 grid grid-cols-3 gap-3">
        <div class="rounded-xl border border-white/6 bg-black/30 px-3 py-3 text-center">
          <p class="text-lg font-black text-cyan-300">All</p>
          <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Recent posts</p>
        </div>
        <div class="rounded-xl border border-white/6 bg-black/30 px-3 py-3 text-center">
          <p class="text-lg font-black text-cyan-300">~1s</p>
          <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Per job</p>
        </div>
        <div class="rounded-xl border border-white/6 bg-black/30 px-3 py-3 text-center">
          <p class="text-lg font-black text-cyan-300">6</p>
          <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Factors scored</p>
        </div>
      </div>

      <div class="mt-5 rounded-2xl border border-white/6 bg-black/20 p-4">
        <p class="text-[10px] font-bold uppercase tracking-wider text-slate-500">How it works</p>
        <div class="mt-3 space-y-2.5">
          <div class="flex items-start gap-3">
            <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">
              1
            </span>
            <p class="text-sm text-slate-300">Your profile is analysed: role, certs, location, salary range.</p>
          </div>
          <div class="flex items-start gap-3">
            <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">
              2
            </span>
            <p class="text-sm text-slate-300">Every open position is scored on compatibility factors.</p>
          </div>
          <div class="flex items-start gap-3">
            <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">
              3
            </span>
            <p class="text-sm text-slate-300">Your best match is returned with a personalised reason.</p>
          </div>
        </div>

        <button
          type="button"
          onclick={() => onStartMatch()}
          class="mt-6 w-full rounded-xl border border-cyan-300/35 bg-cyan-300/10 px-6 py-4 text-sm font-bold text-cyan-100 transition-all duration-200 hover:border-cyan-300/60 hover:bg-cyan-300/20 hover:text-white"
        >
          Start Matching Engine
        </button>
      </div>
    </section>

    <section id="how-it-works" class="mt-14">
      <div class="text-center">
        <p class="eyebrow">Process</p>
        <h2 class="mt-3 font-display text-3xl font-light text-white sm:text-4xl">
          Four steps to your <em class="italic">next berth</em>
        </h2>
      </div>

      <div class="mt-8 space-y-6">
        {#each steps as step}
          <div class="flex gap-4">
            <span class="mt-1 flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-xs font-black text-white">
              {step.num}
            </span>
            <div>
              <h3 class="font-semibold text-white">{step.title}</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-400">{step.desc}</p>
            </div>
          </div>
        {/each}
      </div>
    </section>

    <section class="mt-14 rounded-3xl border border-white/[0.08] bg-[#0a0e14]/80 p-6 text-center">
      <p class="eyebrow">Set sail</p>
      <h2 class="mt-3 font-display text-3xl font-light text-white sm:text-4xl">
        Ready to go <em class="italic">offshore?</em>
      </h2>
      <p class="mx-auto mt-3 max-w-md text-[14px] leading-relaxed text-slate-400">
        Let CARVER do the legwork. Your next superyacht position is closer than you think.
      </p>
      <button
        type="button"
        onclick={() => onSignIn('cta_bottom')}
        class="mt-6 inline-flex items-center gap-2 rounded-xl bg-ivory px-7 py-3.5 text-[13px] font-semibold text-[#04070b] transition-all duration-200 hover:shadow-[0_0_60px_rgba(243,234,216,0.18)]"
        style="background: var(--ivory);"
      >
        Join the Beta · First 100 discount
      </button>
      <p class="mt-4 inline-flex items-center gap-2 text-[11px] text-slate-500">
        <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        No card required &middot; cancel anytime
      </p>
    </section>

    <section class="mt-10 rounded-2xl border border-white/10 bg-white/[0.025] p-6 text-left">
      <p class="eyebrow">For agencies</p>
      <h3 class="mt-2 font-display text-2xl font-light text-white sm:text-3xl">
        Are you a yachting agency?
      </h3>
      <p class="mt-3 text-[14px] leading-relaxed text-slate-400">
        Post jobs straight to qualified crew in seconds. Free during beta.
      </p>
      <button
        type="button"
        onclick={() => onAgencySignup('agency_strip')}
        class="mt-5 w-full rounded-xl border border-white/15 bg-white/[0.03] px-6 py-3 text-[13px] font-semibold text-white transition-all duration-200 hover:border-white/30 hover:bg-white/[0.07]"
      >
        Post a job →
      </button>
    </section>
  </main>

  <footer class="border-t border-white/[0.06] px-4 py-7">
    <div class="mx-auto flex max-w-7xl flex-col items-center gap-2 text-[11px] text-slate-500">
      <div class="flex items-center gap-2">
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        <span class="font-display tracking-[0.42em] text-slate-300">CARVER</span>
      </div>
      <span>© {new Date().getFullYear()} Carver &middot; TLS encrypted &middot; EU data residency</span>
    </div>
  </footer>
</div>

<style>
  .gradient-text {
    background: linear-gradient(130deg, #22d3ee 0%, #38bdf8 40%, #818cf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .cta-primary {
    background: linear-gradient(135deg, #67e8f9 0%, #38bdf8 55%, #818cf8 100%);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.4) inset,
      0 14px 32px -14px rgba(34, 211, 238, 0.45);
  }

  .mobile-grid-bg {
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.028) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.028) 1px, transparent 1px);
    background-size: 60px 60px;
    opacity: 0.45;
  }

  .mobile-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(90px);
    opacity: 0.7;
    pointer-events: none;
  }

  .mobile-orb-1 {
    width: 520px;
    height: 520px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.14) 0%, transparent 65%);
    top: -240px;
    left: -180px;
  }

  .mobile-orb-2 {
    width: 420px;
    height: 420px;
    background: radial-gradient(circle, rgba(14, 165, 233, 0.12) 0%, transparent 65%);
    bottom: -220px;
    right: -170px;
  }

  .mobile-orb-3 {
    width: 320px;
    height: 320px;
    background: radial-gradient(circle, rgba(129, 140, 248, 0.10) 0%, transparent 65%);
    top: 40%;
    left: 55%;
  }

  @media (prefers-reduced-motion: reduce) {
    .mobile-orb {
      filter: blur(70px);
    }
  }
</style>

