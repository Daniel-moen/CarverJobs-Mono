<script>
  /**
   * CrewPreviewPage — the login-free shop window for the crew pool.
   *
   * Why it exists: as of the 22 Sep 2026 review there were 2 agency accounts
   * and 0 contact unlocks ever, with a free first unlock on the table. An
   * agency had no way to see a single candidate without creating an account
   * first, so it never found out whether there was anybody worth paying for.
   *
   * Everything here comes from GET /recruiter/preview, which is anonymised
   * server-side: initials at most, never a name, slug, photo or contact. The
   * blur on the contact row is honest — there is nothing behind it in the
   * payload to reveal.
   */
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackEvent, trackOutboundClick } from '../../config/analytics'
  import {
    AGENCY_UNLOCK_PROMISE,
    RECRUITER_UNLOCK_COST_TOKENS,
  } from '../../config/site'

  let { onAgencySignup = () => {} } = $props()

  let candidates = $state([])
  let total = $state(0)
  let unlockCost = $state(RECRUITER_UNLOCK_COST_TOKENS)
  let isLoading = $state(true)
  let errorMessage = $state('')

  async function loadPreview() {
    isLoading = true
    errorMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/recruiter/preview`, { method: 'GET' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        errorMessage = 'Could not load the crew preview right now.'
        candidates = []
        return
      }
      candidates = Array.isArray(data?.candidates) ? data.candidates : []
      total = Number(data?.total ?? candidates.length)
      // Server value wins — the constant is only the pre-flight default.
      unlockCost = Number(data?.unlock_cost) || RECRUITER_UNLOCK_COST_TOKENS
    } catch {
      errorMessage = 'Could not reach the server.'
      candidates = []
    } finally {
      isLoading = false
    }
  }

  function signUp(source) {
    trackOutboundClick('crew_preview_cta', { label: source, value: String(candidates.length) })
    onAgencySignup()
  }

  /** Cards are sparse by nature — only render the rows that have a value. */
  function facts(c) {
    return [
      ['Nationality', c.nationality],
      ['Based', c.region],
      ['Experience', c.years_experience],
      ['Languages', c.languages],
      ['Available', c.available_from],
      ['Certifications', c.certifications_count ? `${c.certifications_count} on file` : ''],
    ].filter(([, value]) => Boolean(value))
  }

  onMount(() => {
    trackEvent('crew_preview_view')
    loadPreview()
  })
</script>

<main class="mx-auto w-full max-w-6xl px-4 pb-16 pt-8 sm:px-6 md:px-8">
  <a
    href="/"
    class="inline-flex items-center gap-1.5 text-[12px] text-slate-500 transition hover:text-slate-200"
  >
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    Back to Carver
  </a>

  <header class="mt-6 max-w-2xl">
    <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-cyan-300/80">For agencies &amp; captains</p>
    <h1 class="mt-3 text-3xl font-black tracking-tight text-white sm:text-4xl">
      See who's actually looking.
    </h1>
    <p class="mt-3 text-[15px] leading-relaxed text-slate-400">
      A sample of the crew currently discoverable on Carver, shown anonymously. Create a free
      agency account to see full profiles, search by role and location, and unlock contact details.
    </p>
    <p class="mt-3 inline-flex items-center gap-2 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.07] px-3 py-1.5 text-[13px] text-emerald-200">
      <span class="h-1.5 w-1.5 rounded-full bg-emerald-300"></span>
      {AGENCY_UNLOCK_PROMISE}
    </p>
  </header>

  <div class="mt-6 flex flex-wrap items-center gap-3">
    <button
      type="button"
      onclick={() => signUp('header')}
      class="rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-5 py-2.5 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white"
    >
      Create a free agency account
    </button>
    <a
      href="/pricing"
      onclick={() => trackOutboundClick('crew_preview_cta', { label: 'pricing' })}
      class="text-[13px] text-slate-400 underline-offset-4 transition hover:text-slate-200 hover:underline"
    >
      See token pricing
    </a>
  </div>

  {#if errorMessage}
    <p class="mt-8 rounded-lg border border-rose-400/20 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
      {errorMessage}
    </p>
  {:else if isLoading}
    <p class="py-16 text-center text-sm text-slate-500">Loading crew…</p>
  {:else if candidates.length === 0}
    <div class="mt-10 rounded-2xl border border-white/8 bg-zinc-950 p-8 text-center">
      <p class="text-sm text-slate-300">No crew are discoverable right now.</p>
      <p class="mt-2 text-[13px] text-slate-500">
        New profiles land daily. Create an account and you'll be searching the moment they do.
      </p>
      <button
        type="button"
        onclick={() => signUp('empty')}
        class="mt-5 rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-4 py-2 text-[13px] font-semibold text-cyan-100 transition hover:bg-cyan-300/20"
      >
        Create a free agency account
      </button>
    </div>
  {:else}
    <p class="mt-10 text-xs uppercase tracking-[0.18em] text-slate-500">
      {#if total > candidates.length}
        Showing {candidates.length} of {total} discoverable crew
      {:else}
        {total} discoverable crew
      {/if}
    </p>

    <div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each candidates as c, i (i)}
        <article class="flex flex-col gap-3 rounded-xl border border-white/10 bg-zinc-950 p-4">
          <div class="flex items-start justify-between gap-2">
            <div>
              <p class="font-semibold text-white">{c.initials || 'Crew member'}</p>
              <p class="text-xs text-cyan-300/80">{c.desired_role || 'Open to roles'}</p>
            </div>
            {#if c.has_cv}
              <span class="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-400">CV</span>
            {/if}
          </div>

          {#if facts(c).length}
            <dl class="grid gap-1 text-xs text-slate-400">
              {#each facts(c) as [label, value]}
                <div><dt class="inline text-slate-500">{label}:</dt> {value}</div>
              {/each}
            </dl>
          {:else}
            <p class="text-xs text-slate-600">Profile details available to agency accounts.</p>
          {/if}

          <div class="mt-auto border-t border-white/5 pt-3">
            <div class="relative">
              <div class="select-none blur-[5px]" aria-hidden="true">
                <p class="text-sm text-cyan-300">name.surname@example.com</p>
                <p class="text-sm text-cyan-300">+00 00 000 0000</p>
              </div>
              <button
                type="button"
                onclick={() => signUp('card')}
                class="absolute inset-0 flex items-center justify-center rounded-lg bg-black/45 text-[12px] font-semibold text-white transition hover:bg-black/25"
              >
                <span class="inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-black/70 px-3 py-1">
                  <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  Unlock contact
                </span>
              </button>
            </div>
          </div>
        </article>
      {/each}
    </div>

    <div class="mt-10 rounded-2xl border border-white/8 bg-zinc-950 p-6 text-center">
      <h2 class="text-lg font-bold text-white">Ready to reach them?</h2>
      <p class="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-slate-400">
        {AGENCY_UNLOCK_PROMISE} Tokens are bought on the Buy Tokens tab — no contract, no
        per-placement fee, no card needed to sign up.
      </p>
      <button
        type="button"
        onclick={() => signUp('footer')}
        class="mt-5 rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-5 py-2.5 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white"
      >
        Create a free agency account
      </button>
      <p class="mt-3 font-mono text-[11px] tracking-[0.06em] text-slate-600">
        {unlockCost} tokens per unlock after the first · unlocked contacts stay open
      </p>
    </div>
  {/if}
</main>
