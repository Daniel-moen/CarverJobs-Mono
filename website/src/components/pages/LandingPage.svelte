<script>
  import { onMount } from 'svelte'
  import { trackEvent } from '../../config/analytics'

  let { onSignIn = () => {}, onStartMatch = () => {}, onAgencySignup = () => {} } = $props()
  const isFinePointer = window.matchMedia('(pointer:fine)').matches
  const isMobileViewport = window.matchMedia('(max-width: 768px)').matches

  // Hero mouse tracking — mousemove only (touch devices stay centered, no lag)
  let heroEl = $state(null)
  let mx = $state(50)
  let my = $state(50)

  function handleHeroMouseMove(e) {
    if (!isFinePointer || isMobileViewport) return
    if (!heroEl) return
    const rect = heroEl.getBoundingClientRect()
    mx = ((e.clientX - rect.left) / rect.width) * 100
    my = ((e.clientY - rect.top) / rect.height) * 100
  }

  onMount(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const target = /** @type {HTMLElement} */ (entry.target)
          if (entry.isIntersecting) {
            target.dataset.visible = 'true'
          }
        })
      },
      { threshold: 0.12 },
    )

    document.querySelectorAll('[data-animate]').forEach((el) => observer.observe(el))

    const depths = new Set()
    if (isMobileViewport) {
      return () => observer.disconnect()
    }
    function onScroll() {
      const pct = Math.round((window.scrollY + window.innerHeight) / document.body.scrollHeight * 100)
      for (const threshold of [25, 50, 75, 100]) {
        if (pct >= threshold && !depths.has(threshold)) {
          depths.add(threshold)
          trackEvent('scroll_depth', { page: 'landing', value: String(threshold) })
        }
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      observer.disconnect()
      window.removeEventListener('scroll', onScroll)
    }
  })

  const features = [
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>`,
      title: 'Auto-Apply Engine',
      desc: 'CARVER scans live listings and submits your application automatically — while you sleep.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>`,
      title: 'Smart Matching',
      desc: 'AI-powered compatibility scoring ensures you only apply where you genuinely fit the brief.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
      title: 'Document Vault',
      desc: 'Upload your CV, STCW, ENG1, and passport once. CARVER handles the rest every time.',
    },
    {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
      title: 'Live Job Board',
      desc: 'Real-time superyacht vacancies aggregated from top sources, filtered for your profile.',
    },
  ]

  const steps = [
    {
      num: '01',
      title: 'Build your profile',
      desc: 'Upload your documents and set your experience, certifications, and preferences.',
    },
    {
      num: '02',
      title: 'Set your criteria',
      desc: "Tell CARVER what you're looking for — vessel type, role, region, and salary range.",
    },
    {
      num: '03',
      title: 'Activate Auto-Apply',
      desc: 'CARVER matches and applies on your behalf to relevant openings in real time.',
    },
    {
      num: '04',
      title: 'Track & respond',
      desc: 'Monitor your application pipeline and respond to interview invites from your dashboard.',
    },
  ]

  const roles = [
    'Captain',
    'First Officer',
    'Chief Engineer',
    'Bosun',
    'Stewardess',
    'Head Chef',
    'Deckhand',
    'Second Engineer',
    'Purser',
    'Chief Steward/ess',
    'Mate',
    'ETO',
  ]

  const particles = Array.from({ length: 10 }, () => ({
    x: Math.random() * 100,
    startY: 75 + Math.random() * 25,
    size: Math.random() * 2 + 0.8,
    dur: Math.random() * 25 + 18,
    delay: Math.random() * -40,
    opacity: Math.random() * 0.35 + 0.08,
  }))
</script>

<div class="min-h-screen bg-[#04070b] text-slate-100">
  <!-- ── NAV ─────────────────────────────────────────────────────────── -->
  <nav class="fixed top-0 z-50 w-full border-b border-white/[0.06] bg-[#04070b]/70 backdrop-blur-xl supports-[backdrop-filter]:bg-[#04070b]/55">
    <div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
      <a href="/" class="flex items-center gap-2.5">
        <span class="relative flex h-2 w-2 items-center justify-center">
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/50 opacity-60"></span>
          <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        </span>
        <span class="font-display text-[15px] tracking-[0.42em] text-ivory">CARVER</span>
      </a>
      <div class="flex items-center gap-2 sm:gap-3">
        <a
          href="#how-it-works"
          class="hidden rounded-full px-3 py-2 text-[12px] font-medium text-slate-400 transition hover:text-white sm:inline-block"
        >
          How it works
        </a>
        <button
          onclick={() => onSignIn('nav')}
          class="rounded-full border border-white/15 bg-white/[0.03] px-5 py-2 text-[12px] font-medium text-slate-200 transition-all duration-200 hover:border-cyan-300/50 hover:bg-cyan-300/[0.06] hover:text-white"
        >
          Sign in
        </button>
      </div>
    </div>
  </nav>

  <!-- ── HERO ───────────────────────────────────────────────────────── -->
  <section
    bind:this={heroEl}
    class="relative flex min-h-[100svh] flex-col items-center justify-start overflow-hidden px-4 pb-10 pt-24 sm:min-h-screen sm:justify-center sm:px-6 sm:pb-0 sm:pt-20"
    onmousemove={handleHeroMouseMove}
    role="banner"
  >
    <!-- Background layers -->
    <div class="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <!-- Pulsing line grid -->
      <div class="grid-bg absolute inset-0"></div>

      <!-- Floating particles -->
      {#each particles as p}
        <div
          class="particle"
          style="left:{p.x}%; top:{p.startY}%; width:{p.size}px; height:{p.size}px; --op:{p.opacity}; animation-duration:{p.dur}s; animation-delay:{p.delay}s;"
        ></div>
      {/each}

      <!-- Orbs -->
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <div class="orb orb-4"></div>
      <div class="orb orb-5"></div>

      <!-- Horizontal scan line -->
      <div class="scan-line"></div>

      <!-- Mouse spotlight -->
      <div
        class="absolute inset-0 transition-[background] duration-100"
        style="background: radial-gradient(700px circle at {mx}% {my}%, rgba(34,211,238,0.06), transparent 60%);"
      ></div>
    </div>

    <div class="relative z-10 mx-auto max-w-5xl text-center">
      <!-- Pill badge -->
      <div
        class="mb-8 inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/[0.025] px-4 py-1.5"
      >
        <span class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-cyan-400"></span>
        <span class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-300 sm:text-[11px]">
          <span class="sm:hidden">Superyacht crew &middot; Beta</span>
          <span class="hidden sm:inline">Automated superyacht crew recruitment &middot; Beta</span>
        </span>
      </div>

      <!-- Headline -->
      <h1 class="font-display text-[clamp(2.4rem,11vw,6.4rem)] font-light leading-[1.02] text-white">
        Every yacht job.<br />
        <em class="gradient-text font-light italic">One place.</em><br />
        Auto-matched.
      </h1>

      <p class="mx-auto mt-8 max-w-2xl text-[15px] leading-relaxed text-slate-300/85 sm:text-[17px]">
        We aggregate listings from 50+ crew groups, agencies, and any source with a contact email —
        so you stop scrolling and start applying. Captains hiring? Post directly.
      </p>

      <!-- CTAs -->
      <div class="mt-10 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
        <button
          onclick={() => onSignIn('hero')}
          class="cta-primary group inline-flex items-center gap-2 rounded-full px-8 py-3.5 text-[13px] font-semibold text-[#04070b] transition-all duration-200"
        >
          Join the Beta
          <span class="font-mono text-[10px] uppercase tracking-[0.22em] text-[#04070b]/70 group-hover:text-[#04070b]">First 100 &middot; discount</span>
        </button>
        <a
          href="#how-it-works"
          class="rounded-full border border-white/15 px-8 py-3.5 text-[13px] font-medium text-slate-300 transition-all duration-200 hover:border-white/30 hover:text-white"
        >
          How it works →
        </a>
      </div>

      <!-- Trust strip -->
      <div class="mx-auto mt-10 flex max-w-2xl flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[11px] text-slate-500">
        <span class="inline-flex items-center gap-1.5">
          <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          TLS encrypted
        </span>
        <span class="text-slate-700">·</span>
        <span class="inline-flex items-center gap-1.5">
          <svg class="h-3.5 w-3.5 text-cyan-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M2 12h20M12 2a14 14 0 0 1 0 20M12 2a14 14 0 0 0 0 20"/></svg>
          EU data residency
        </span>
        <span class="text-slate-700">·</span>
        <span class="inline-flex items-center gap-1.5">
          <svg class="h-3.5 w-3.5 text-cyan-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
          Used by crew in Med &amp; Caribbean
        </span>
      </div>

      <!-- Role ticker -->
      <div class="mt-14 overflow-hidden">
        <p class="eyebrow mb-3 text-slate-500">Roles we cover</p>
        <div class="ticker-mask">
          <div class="ticker">
            {#each [...roles, ...roles] as role}
              <span class="ticker-item">{role}</span>
            {/each}
          </div>
        </div>
      </div>
    </div>

    <!-- Scroll arrow -->
    <div class="absolute bottom-10 left-1/2 hidden -translate-x-1/2 animate-bounce sm:block" aria-hidden="true">
      <svg class="h-5 w-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 9l-7 7-7-7" />
      </svg>
    </div>
  </section>

  <!-- ── SEE ONE WE MISSED? ─────────────────────────────────────────── -->
  <section class="px-4 py-16 sm:px-6 sm:py-28" data-animate>
    <div class="mx-auto max-w-3xl text-center">
      <p class="eyebrow">Community-powered</p>
      <h2 class="mt-3 font-display text-4xl font-light text-white sm:text-5xl">See one we missed?</h2>
      <p class="mx-auto mt-5 max-w-xl text-[15px] leading-relaxed text-slate-400">
        Saw a job in a crew group or social post? Submit it with a screenshot or pasted text — we add it to the board
        and you earn a token to match roles that fit your profile. Hiring managers can post positions directly too.
      </p>
    </div>
  </section>

  <!-- ── FEATURES ───────────────────────────────────────────────────── -->
  <section id="features" class="px-4 py-16 sm:px-6 sm:py-28">
    <div class="mx-auto max-w-7xl">
      <div class="mb-16 text-center" data-animate>
        <p class="eyebrow">Features</p>
        <h2 class="mt-3 font-display text-4xl font-light text-white sm:text-5xl">Built for superyacht crew</h2>
        <p class="mx-auto mt-4 max-w-lg text-[15px] leading-relaxed text-slate-400">
          Every feature designed around the realities of working on the water.
        </p>
      </div>

      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {#each features as feature, i}
          <article
            class="feature-card group relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-6 transition-all duration-300"
            style="--mx:50%; --my:50%; transition-delay: {i * 80}ms"
            data-animate
            onmousemove={(e) => {
              if (!isFinePointer || isMobileViewport) return
              const r = e.currentTarget.getBoundingClientRect()
              e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
              e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
            }}
            onmouseleave={(e) => {
              if (!isFinePointer || isMobileViewport) return
              e.currentTarget.style.setProperty('--mx', '50%')
              e.currentTarget.style.setProperty('--my', '50%')
            }}
          >
            <div
              class="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
              style="background: radial-gradient(180px circle at var(--mx) var(--my), rgba(34,211,238,0.12), transparent 70%);"
              aria-hidden="true"
            ></div>
            <div class="relative z-10">
              <div
                class="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-cyan-300"
              >
                {@html feature.icon}
              </div>
              <h3 class="font-semibold text-white">{feature.title}</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-400">{feature.desc}</p>
            </div>
          </article>
        {/each}
      </div>
    </div>
  </section>

  <!-- ── MATCHING ENGINE ─────────────────────────────────────────────── -->
  <section id="matching" class="relative overflow-hidden px-4 py-16 sm:px-6 sm:py-28">
    <div class="pointer-events-none absolute inset-0 matching-bg-glow" aria-hidden="true"></div>

    <div class="relative z-10 mx-auto max-w-5xl">
      <div class="mb-14 text-center" data-animate>
        <p class="eyebrow">Matching Engine</p>
        <h2 class="mt-3 font-display text-4xl font-light text-white sm:text-5xl">
          Job matching, in <em class="italic text-cyan-200/90">seconds.</em>
        </h2>
        <p class="mx-auto mt-4 max-w-lg text-[15px] leading-relaxed text-slate-400">
          The engine analyses your profile against every open position and returns the best fit, with the reasoning shown.
        </p>
      </div>

      <div class="mx-auto max-w-2xl" data-animate>
        <div class="match-demo group relative overflow-hidden rounded-2xl border border-cyan-400/20 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-cyan-950/40 p-4 sm:p-8">
          <div class="match-demo-orb match-demo-orb-1 pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-cyan-400/12 blur-3xl" style="animation: match-orb-pulse 4s ease-in-out infinite;" aria-hidden="true"></div>
          <div class="match-demo-orb match-demo-orb-2 pointer-events-none absolute -bottom-12 -left-12 h-36 w-36 rounded-full bg-indigo-400/8 blur-2xl" style="animation: match-orb-pulse 4s ease-in-out infinite; animation-delay:-2s;" aria-hidden="true"></div>

          <div class="relative z-10">
            <div class="flex items-center gap-2">
              <span class="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
              <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-300/60">Live Engine</p>
            </div>
            <h3 class="mt-3 text-2xl font-black text-white">Find Your Match</h3>
            <p class="mt-2 text-sm leading-relaxed text-slate-400">
              Sign in to run the matching engine against your crew profile. We'll scan every open position and find the one that fits you best.
            </p>

            <div class="mt-6 grid grid-cols-3 gap-3">
              <div class="rounded-xl border border-white/6 bg-black/30 px-4 py-3 text-center">
                <p class="text-lg font-black text-cyan-300">All</p>
                <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Recent posts</p>
              </div>
              <div class="rounded-xl border border-white/6 bg-black/30 px-4 py-3 text-center">
                <p class="text-lg font-black text-cyan-300">~1s</p>
                <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Per job</p>
              </div>
              <div class="rounded-xl border border-white/6 bg-black/30 px-4 py-3 text-center">
                <p class="text-lg font-black text-cyan-300">6</p>
                <p class="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">Factors scored</p>
              </div>
            </div>

            <div class="mt-6 rounded-xl border border-white/6 bg-black/20 p-4">
              <p class="text-[10px] font-bold uppercase tracking-wider text-slate-500">How it works</p>
              <div class="mt-3 space-y-2.5">
                <div class="flex items-center gap-3">
                  <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">1</span>
                  <p class="text-sm text-slate-300">Your profile is analysed — role, certs, location, salary range</p>
                </div>
                <div class="flex items-center gap-3">
                  <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">2</span>
                  <p class="text-sm text-slate-300">Every open position is scored on compatibility factors</p>
                </div>
                <div class="flex items-center gap-3">
                  <span class="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-[10px] font-bold text-cyan-300">3</span>
                  <p class="text-sm text-slate-300">Your best match is returned with a personalised reason</p>
                </div>
              </div>
            </div>

            <button
              type="button"
              onclick={() => onStartMatch()}
              class="mt-6 w-full relative overflow-hidden rounded-xl border border-cyan-300/35 bg-cyan-300/10 px-6 py-4 text-sm font-bold text-cyan-100 transition-all duration-200 hover:border-cyan-300/60 hover:bg-cyan-300/20 hover:text-white hover:shadow-[0_0_40px_rgba(34,211,238,0.2)] active:scale-[0.98]"
            >
              <span class="flex items-center justify-center gap-2.5">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                Start Matching Engine
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ── HOW IT WORKS ───────────────────────────────────────────────── -->
  <section id="how-it-works" class="bg-[#080c11] px-4 py-16 sm:px-6 sm:py-28">
    <div class="mx-auto max-w-5xl">
      <div class="mb-16 text-center" data-animate>
        <p class="eyebrow">Process</p>
        <h2 class="mt-3 font-display text-4xl font-light text-white sm:text-5xl">
          Four steps to your <em class="italic">next berth.</em>
        </h2>
      </div>

      <div class="grid gap-10 sm:grid-cols-2">
        {#each steps as step, i}
          <div class="group flex gap-6" data-animate style="transition-delay: {i * 100}ms">
            <div class="flex-none select-none pt-0.5">
              <span class="text-5xl font-black leading-none tracking-tighter text-white/8 transition duration-300 group-hover:text-cyan-400/20 sm:text-6xl"
                >{step.num}</span
              >
            </div>
            <div class="border-l border-white/8 pl-6 transition-colors duration-300 group-hover:border-cyan-400/20">
              <h3 class="font-semibold text-white">{step.title}</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-400">{step.desc}</p>
            </div>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <!-- ── CTA BANNER ─────────────────────────────────────────────────── -->
  <section class="relative overflow-hidden px-4 py-20 sm:px-6 sm:py-32">
    <div class="pointer-events-none absolute inset-0" aria-hidden="true">
      <div class="orb-cta"></div>
      <div
        class="absolute inset-0"
        style="background-image: radial-gradient(rgba(255,255,255,0.025) 1px, transparent 1px); background-size: 40px 40px;"
      ></div>
    </div>

    <div class="relative z-10 mx-auto max-w-2xl text-center" data-animate>
      <p class="eyebrow">Set sail</p>
      <h2 class="mt-3 font-display text-5xl font-light leading-[1.05] text-white sm:text-6xl">
        Ready to go <em class="italic">offshore?</em>
      </h2>
      <p class="mx-auto mt-5 max-w-md text-[15px] leading-relaxed text-slate-400">
        Let CARVER do the legwork. Your next superyacht position is closer than you think.
      </p>
      <button
        onclick={() => onSignIn('cta_bottom')}
        class="mt-8 inline-flex items-center gap-2 rounded-full bg-ivory px-9 py-3.5 text-[13px] font-semibold text-[#04070b] transition-all duration-200 hover:shadow-[0_0_60px_rgba(243,234,216,0.18)]"
        style="background: var(--ivory);"
      >
        Join the Beta
        <span class="font-mono text-[10px] uppercase tracking-[0.22em] text-[#04070b]/70">First 100 &middot; discount</span>
      </button>
      <p class="mx-auto mt-5 inline-flex items-center gap-2 text-[11px] text-slate-500">
        <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        No card required &middot; cancel anytime
      </p>
    </div>
  </section>

  <!-- ── AGENCY STRIP ───────────────────────────────────────────────── -->
  <section class="border-t border-white/[0.06] px-4 py-12 sm:px-6 sm:py-16">
    <div
      class="mx-auto flex max-w-5xl flex-col items-start justify-between gap-6 rounded-2xl border border-white/10 bg-white/[0.025] p-6 sm:flex-row sm:items-center sm:p-8"
      data-animate
    >
      <div class="max-w-xl">
        <p class="eyebrow">For agencies</p>
        <h3 class="mt-2 font-display text-3xl font-light text-white sm:text-4xl">
          Are you a yachting agency?
        </h3>
        <p class="mt-3 text-[14px] leading-relaxed text-slate-400">
          Post jobs straight to qualified crew in seconds. Free to use during beta — no tokens, no fees.
        </p>
      </div>
      <button
        type="button"
        onclick={() => onAgencySignup('agency_strip')}
        class="shrink-0 rounded-full border border-white/20 bg-white/[0.04] px-7 py-3 text-[13px] font-semibold text-white transition-all duration-200 hover:border-white/35 hover:bg-white/[0.08]"
      >
        Post a job →
      </button>
    </div>
  </section>

  <!-- ── FOOTER ─────────────────────────────────────────────────────── -->
  <footer class="border-t border-white/[0.06] px-4 py-8 sm:px-6">
    <div class="mx-auto flex max-w-7xl flex-col items-center gap-3 text-[11px] text-slate-500 sm:flex-row sm:justify-between">
      <div class="flex items-center gap-2">
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        <span class="font-display tracking-[0.42em] text-slate-300">CARVER</span>
      </div>
      <div class="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
        <a href="/privacy" class="transition hover:text-slate-300">Privacy</a>
        <a href="/terms" class="transition hover:text-slate-300">Terms</a>
        <a href="/data-deletion" class="transition hover:text-slate-300">Delete my data</a>
      </div>
      <span>© {new Date().getFullYear()} Carver</span>
    </div>
  </footer>
</div>

<style>
  /* ── Gradient headline ── */
  .gradient-text {
    background: linear-gradient(130deg, #22d3ee 0%, #38bdf8 40%, #818cf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* ── Primary CTA — refined, not neon ── */
  .cta-primary {
    background: linear-gradient(135deg, #67e8f9 0%, #38bdf8 55%, #818cf8 100%);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.4) inset,
      0 0 0 1px rgba(34, 211, 238, 0.15),
      0 18px 40px -16px rgba(34, 211, 238, 0.45);
  }
  .cta-primary:hover {
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.4) inset,
      0 0 0 1px rgba(34, 211, 238, 0.25),
      0 22px 60px -18px rgba(34, 211, 238, 0.55);
    transform: translateY(-1px);
  }

  /* ── Pulsing line grid — static on mobile for performance ── */
  .grid-bg {
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.028) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.028) 1px, transparent 1px);
    background-size: 60px 60px;
    animation: grid-pulse 5s ease-in-out infinite;
  }
  @media (max-width: 768px) {
    .grid-bg { animation: none; opacity: 0.6; }
  }
  @keyframes grid-pulse {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
  }

  /* ── Floating particles — hidden on mobile ── */
  .particle {
    position: absolute;
    border-radius: 50%;
    background: rgba(34, 211, 238, var(--op, 0.2));
    animation: float-up linear infinite;
  }
  @media (max-width: 768px) {
    .particle { display: none; }
  }
  @keyframes float-up {
    0% {
      transform: translateY(0) translateX(0);
      opacity: 0;
    }
    10% {
      opacity: var(--op, 0.2);
    }
    80% {
      opacity: var(--op, 0.2);
    }
    100% {
      transform: translateY(-120vh) translateX(20px);
      opacity: 0;
    }
  }

  /* ── Horizontal scan line — off on mobile ── */
  .scan-line {
    position: absolute;
    top: -2px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, rgba(34, 211, 238, 0.3) 30%, rgba(34, 211, 238, 0.3) 70%, transparent 100%);
    animation: scan 14s linear infinite;
    pointer-events: none;
  }
  @media (max-width: 768px) {
    .scan-line { display: none; }
  }
  @keyframes scan {
    0% { top: -2px; opacity: 0; }
    5% { opacity: 1; }
    95% { opacity: 1; }
    100% { top: 100%; opacity: 0; }
  }

  /* ── Animated background orbs — lighter blur on mobile ── */
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(100px);
    animation: float 10s ease-in-out infinite;
  }
  @media (max-width: 768px) {
    .orb { filter: blur(36px); animation: none; }
    .orb-4,
    .orb-5 { display: none; }
  }
  .orb-1 {
    width: 700px;
    height: 700px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.14) 0%, transparent 65%);
    top: -180px;
    left: -150px;
    animation-delay: 0s;
  }
  .orb-2 {
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(14, 165, 233, 0.1) 0%, transparent 65%);
    bottom: -80px;
    right: -80px;
    animation-delay: -4s;
    animation-direction: reverse;
  }
  .orb-3 {
    width: 350px;
    height: 350px;
    background: radial-gradient(circle, rgba(129, 140, 248, 0.08) 0%, transparent 65%);
    top: 45%;
    left: 55%;
    animation-delay: -7s;
  }
  .orb-4 {
    width: 600px;
    height: 300px;
    background: radial-gradient(ellipse, rgba(99, 102, 241, 0.1) 0%, transparent 65%);
    bottom: -60px;
    left: -100px;
    animation-delay: -3s;
    animation-direction: reverse;
    filter: blur(80px);
  }
  .orb-5 {
    width: 280px;
    height: 280px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.09) 0%, transparent 65%);
    top: 10%;
    right: 5%;
    animation-delay: -11s;
    filter: blur(70px);
  }
  .orb-cta {
    position: absolute;
    width: 900px;
    height: 450px;
    background: radial-gradient(ellipse, rgba(34, 211, 238, 0.07) 0%, transparent 55%);
    top: 50%;
    left: 50%;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    filter: blur(60px);
  }
  @media (max-width: 768px) {
    .orb-cta { filter: blur(30px); }
  }
  @keyframes float {
    0%,
    100% {
      transform: translate(0, 0) scale(1);
    }
    33% {
      transform: translate(40px, -30px) scale(1.06);
    }
    66% {
      transform: translate(-25px, 20px) scale(0.94);
    }
  }

  /* ── Ticker / marquee ── */
  .ticker-mask {
    overflow: hidden;
    mask-image: linear-gradient(90deg, transparent 0%, black 12%, black 88%, transparent 100%);
    -webkit-mask-image: linear-gradient(90deg, transparent 0%, black 12%, black 88%, transparent 100%);
  }
  .ticker {
    display: flex;
    width: max-content;
    animation: ticker 22s linear infinite;
  }
  @media (max-width: 768px) {
    .ticker { animation: none; }
  }
  .ticker-item {
    padding: 0.3rem 1.25rem;
    margin: 0 0.2rem;
    border-radius: 9999px;
    border: 1px solid rgba(255, 255, 255, 0.07);
    background: rgba(255, 255, 255, 0.025);
    color: rgba(255, 255, 255, 0.4);
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }
  @keyframes ticker {
    from {
      transform: translateX(0);
    }
    to {
      transform: translateX(-50%);
    }
  }

  /* Matching section glow — reduced blur on mobile */
  .matching-bg-glow {
    left: 50%;
    top: 50%;
    height: 600px;
    width: 800px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    background: rgba(34, 211, 238, 0.05);
    filter: blur(100px);
  }
  @media (max-width: 768px) {
    .matching-bg-glow { filter: blur(30px); height: 300px; width: 300px; }
  }

  /* ── Match demo orb pulse ── */
  @keyframes match-orb-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.1); }
  }

  .match-demo {
    transition: border-color 0.3s, box-shadow 0.3s;
  }
  @media (max-width: 768px) {
    .match-demo-orb { filter: blur(16px) !important; animation: none !important; }
  }
  .match-demo:hover {
    border-color: rgba(34, 211, 238, 0.35);
    box-shadow: 0 24px 80px -20px rgba(34, 211, 238, 0.15);
  }

  /* ── Scroll-reveal animations ── */
  [data-animate] {
    opacity: 0;
    transform: translateY(24px);
    transition:
      opacity 0.65s ease,
      transform 0.65s ease;
  }
  :global([data-animate][data-visible='true']) {
    opacity: 1;
    transform: translateY(0);
  }

  /* Feature cards: also animate-on-scroll, plus hover effects */
  .feature-card {
    opacity: 0;
    transform: translateY(24px);
    transition:
      opacity 0.55s ease,
      transform 0.55s ease,
      border-color 0.3s,
      box-shadow 0.3s,
      translate 0.2s;
  }
  :global(.feature-card[data-visible='true']) {
    opacity: 1;
    transform: translateY(0);
  }
  .feature-card:hover {
    border-color: rgba(34, 211, 238, 0.25);
    box-shadow: 0 24px 60px -20px rgba(34, 211, 238, 0.25);
    translate: 0 -3px;
  }
  @media (max-width: 768px), (pointer: coarse) {
    .feature-card:hover {
      border-color: rgba(255, 255, 255, 0.08);
      box-shadow: none;
      translate: 0;
    }
    .match-demo:hover {
      border-color: rgba(34, 211, 238, 0.2);
      box-shadow: none;
    }
  }

  /* SVG icons in feature cards */
  :global(.feature-card svg) {
    width: 1.2rem;
    height: 1.2rem;
  }
</style>
