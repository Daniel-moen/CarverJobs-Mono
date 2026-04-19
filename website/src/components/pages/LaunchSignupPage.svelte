<script>
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let email = $state('')
  let isSubmitting = $state(false)
  let status = $state('idle')
  let errorMessage = $state('')

  async function submitSignup(event) {
    event.preventDefault()
    if (isSubmitting) return

    isSubmitting = true
    status = 'idle'
    errorMessage = ''

    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        errorMessage = payload?.detail ?? 'Could not save your email right now.'
        status = 'error'
        return
      }

      status = 'success'
      email = ''
    } catch {
      errorMessage = 'Network error. Please try again in a moment.'
      status = 'error'
    } finally {
      isSubmitting = false
    }
  }
</script>

<main class="relative min-h-[100dvh] overflow-hidden bg-[#04070b] px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
  <div class="pointer-events-none absolute inset-0" aria-hidden="true">
    <div class="launch-grid absolute inset-0"></div>
    <div class="launch-orb launch-orb-a"></div>
    <div class="launch-orb launch-orb-b"></div>
  </div>

  <header class="relative mx-auto flex w-full max-w-4xl items-center justify-between">
    <a href="/" class="flex items-center gap-2.5">
      <span class="relative flex h-2 w-2 items-center justify-center">
        <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/50 opacity-60"></span>
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
      </span>
      <span class="font-display text-[14px] tracking-[0.42em] text-ivory">CARVER</span>
    </a>
    <span class="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Pre-launch</span>
  </header>

  <section class="relative mx-auto flex min-h-[calc(100dvh-7rem)] w-full max-w-4xl items-center">
    <article class="w-full rounded-3xl border border-white/[0.08] bg-[#0a0e14]/95 p-6 shadow-[0_40px_120px_-40px_rgba(34,211,238,0.22)] backdrop-blur-sm sm:p-8 md:p-10">
      <p class="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.025] px-3 py-1 font-mono text-[10px] uppercase tracking-[0.24em] text-slate-300">
        <span class="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
        Early access
      </p>
      <h1 class="mt-5 font-display text-[clamp(2rem,8vw,3.6rem)] font-light leading-[1.04] text-white">
        CARVER is launching <em class="italic gradient-text">soon.</em>
      </h1>
      <p class="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-300/85 sm:text-[16px]">
        Join the launch list for first access, release updates, and private beta invites.
      </p>

      <form class="mt-7 grid gap-3 sm:grid-cols-[1fr_auto]" onsubmit={submitSignup}>
        <label class="sr-only" for="waitlist-email">Email address</label>
        <input
          id="waitlist-email"
          type="email"
          bind:value={email}
          required
          autocomplete="email"
          placeholder="you@domain.com"
          class="h-12 rounded-xl border border-white/[0.1] bg-[#04070b] px-4 text-[15px] text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          class="h-12 rounded-xl border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-6 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-65"
        >
          {isSubmitting ? 'Joining...' : 'Notify me →'}
        </button>
      </form>

      {#if status === 'success'}
        <p class="mt-3 inline-flex items-center gap-1.5 text-[13px] text-emerald-300">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
          You're in. We'll email you as soon as we launch.
        </p>
      {:else if status === 'error'}
        <p class="mt-3 text-[13px] text-rose-300">{errorMessage}</p>
      {:else}
        <p class="mt-3 inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <svg class="h-3.5 w-3.5 text-emerald-300/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          We'll only use your email for launch updates.
        </p>
      {/if}

      <div class="mt-8 grid gap-3 text-[12px] text-slate-400 sm:grid-cols-3">
        <div class="rounded-xl border border-white/[0.07] bg-[#04070b]/60 px-4 py-3">Private beta invites</div>
        <div class="rounded-xl border border-white/[0.07] bg-[#04070b]/60 px-4 py-3">Product updates</div>
        <div class="rounded-xl border border-white/[0.07] bg-[#04070b]/60 px-4 py-3">Launch-day access</div>
      </div>
    </article>
  </section>
</main>

<style>
  .gradient-text {
    background: linear-gradient(130deg, #67e8f9 0%, #38bdf8 45%, #818cf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .launch-grid {
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.024) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.024) 1px, transparent 1px);
    background-size: 52px 52px;
  }

  .launch-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(70px);
  }

  .launch-orb-a {
    top: -110px;
    left: -90px;
    height: 420px;
    width: 420px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.15) 0%, transparent 65%);
  }

  .launch-orb-b {
    right: -90px;
    bottom: -110px;
    height: 360px;
    width: 360px;
    background: radial-gradient(circle, rgba(99, 102, 241, 0.14) 0%, transparent 65%);
  }

  @media (max-width: 768px) {
    .launch-orb {
      filter: blur(34px);
    }
  }
</style>
