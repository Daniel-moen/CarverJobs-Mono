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

<main class="relative min-h-[100dvh] overflow-hidden bg-black px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
  <div class="pointer-events-none absolute inset-0" aria-hidden="true">
    <div class="launch-grid absolute inset-0"></div>
    <div class="launch-orb launch-orb-a"></div>
    <div class="launch-orb launch-orb-b"></div>
  </div>

  <section class="relative mx-auto flex min-h-[calc(100dvh-4rem)] w-full max-w-4xl items-center">
    <article class="w-full rounded-3xl border border-white/12 bg-zinc-950/95 p-6 shadow-[0_40px_120px_-40px_rgba(34,211,238,0.25)] backdrop-blur-sm sm:p-8 md:p-10">
      <p class="inline-flex items-center rounded-full border border-cyan-400/25 bg-cyan-400/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300">
        Early Access
      </p>
      <h1 class="mt-4 text-[clamp(1.85rem,8vw,3.4rem)] font-black leading-[1.02] tracking-tight text-white">
        CARVER is launching soon.
      </h1>
      <p class="mt-4 max-w-2xl text-sm leading-relaxed text-slate-300 sm:text-base">
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
          class="h-12 rounded-xl border border-white/15 bg-black px-4 text-base text-white outline-none ring-cyan-300/70 transition focus:border-cyan-300/45 focus:ring"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          class="h-12 rounded-xl border border-cyan-300/45 bg-cyan-300/15 px-5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-65"
        >
          {isSubmitting ? 'Joining...' : 'Notify me'}
        </button>
      </form>

      {#if status === 'success'}
        <p class="mt-3 text-sm text-emerald-300">You are in. We will email you as soon as we launch.</p>
      {:else if status === 'error'}
        <p class="mt-3 text-sm text-rose-300">{errorMessage}</p>
      {/if}

      <div class="mt-8 grid gap-3 text-xs text-slate-400 sm:grid-cols-3">
        <div class="rounded-xl border border-white/10 bg-black/40 px-3 py-3">Private beta invites</div>
        <div class="rounded-xl border border-white/10 bg-black/40 px-3 py-3">Product updates</div>
        <div class="rounded-xl border border-white/10 bg-black/40 px-3 py-3">Launch-day access</div>
      </div>
    </article>
  </section>
</main>

<style>
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
