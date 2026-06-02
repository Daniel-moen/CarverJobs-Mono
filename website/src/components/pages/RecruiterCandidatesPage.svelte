<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let candidates = $state([])
  let total = $state(0)
  let unlockCost = $state(0)
  let balance = $state(0)
  let isLoading = $state(true)
  let errorMessage = $state('')
  let unlockingSlug = $state('')

  // Filters
  let roleFilter = $state('')
  let locationFilter = $state('')
  let queryFilter = $state('')

  function buildQuery() {
    const params = new URLSearchParams()
    if (roleFilter.trim()) params.set('role', roleFilter.trim())
    if (locationFilter.trim()) params.set('location', locationFilter.trim())
    if (queryFilter.trim()) params.set('q', queryFilter.trim())
    const qs = params.toString()
    return qs ? `?${qs}` : ''
  }

  async function loadCandidates() {
    isLoading = true
    errorMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/recruiter/candidates${buildQuery()}`, {
        method: 'GET',
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        errorMessage = data.detail || `Failed to load candidates (${res.status}).`
        candidates = []
        return
      }
      candidates = Array.isArray(data?.candidates) ? data.candidates : []
      total = data?.total ?? candidates.length
      unlockCost = data?.unlock_cost ?? 0
      balance = data?.balance ?? 0
    } catch {
      errorMessage = 'Could not reach the server.'
      candidates = []
    } finally {
      isLoading = false
    }
  }

  async function unlock(slug) {
    unlockingSlug = slug
    errorMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/recruiter/candidates/${slug}/unlock`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        errorMessage = data.detail || 'Could not unlock this candidate.'
        return
      }
      balance = data.balance ?? balance
      candidates = candidates.map((c) =>
        c.profile_slug === slug
          ? { ...c, unlocked: true, email: data.email, phone: data.phone }
          : c
      )
    } catch {
      errorMessage = 'Could not reach the server.'
    } finally {
      unlockingSlug = ''
    }
  }

  function fullName(c) {
    const name = [c.first_name, c.last_name].filter(Boolean).join(' ').trim()
    return name || 'Crew member'
  }

  onMount(loadCandidates)
</script>

<section class="grid gap-4">
  <header class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 class="text-xl font-semibold text-white">Find Crew</h1>
      <p class="mt-1 text-sm text-slate-400">
        Search the crew pool and unlock contact details with tokens.
      </p>
    </div>
    <div class="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-right">
      <p class="text-[10px] uppercase tracking-[0.2em] text-slate-500">Token balance</p>
      <p class="text-lg font-bold text-white">{balance}</p>
    </div>
  </header>

  <!-- Filters -->
  <form
    class="grid gap-2 rounded-xl border border-white/10 bg-zinc-950 p-3 sm:grid-cols-[1fr_1fr_1fr_auto]"
    onsubmit={(e) => { e.preventDefault(); loadCandidates() }}
  >
    <input
      bind:value={roleFilter}
      placeholder="Role (e.g. Deckhand)"
      class="rounded-lg border border-white/10 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/40"
    />
    <input
      bind:value={locationFilter}
      placeholder="Location"
      class="rounded-lg border border-white/10 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/40"
    />
    <input
      bind:value={queryFilter}
      placeholder="Name or keyword"
      class="rounded-lg border border-white/10 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/40"
    />
    <button
      type="submit"
      class="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20"
    >
      Search
    </button>
  </form>

  {#if errorMessage}
    <div class="rounded-lg border border-rose-400/20 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
      {errorMessage}
    </div>
  {/if}

  {#if isLoading}
    <p class="py-8 text-center text-sm text-slate-500">Loading candidates…</p>
  {:else if candidates.length === 0}
    <p class="py-8 text-center text-sm text-slate-500">No candidates match your search.</p>
  {:else}
    <p class="text-xs text-slate-500">{total} candidate{total === 1 ? '' : 's'}</p>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each candidates as c (c.profile_slug)}
        <article class="flex flex-col gap-3 rounded-xl border border-white/10 bg-zinc-950 p-4">
          <div class="flex items-start justify-between gap-2">
            <div>
              <p class="font-semibold text-white">{fullName(c)}</p>
              <p class="text-xs text-cyan-300/80">{c.desired_role || 'Open to roles'}</p>
            </div>
            {#if c.unlocked}
              <span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-emerald-200">Unlocked</span>
            {/if}
          </div>

          <dl class="grid gap-1 text-xs text-slate-400">
            {#if c.current_location}<div><dt class="inline text-slate-500">Location:</dt> {c.current_location}</div>{/if}
            {#if c.nationality}<div><dt class="inline text-slate-500">Nationality:</dt> {c.nationality}</div>{/if}
            {#if c.years_experience}<div><dt class="inline text-slate-500">Experience:</dt> {c.years_experience}</div>{/if}
            {#if c.languages}<div><dt class="inline text-slate-500">Languages:</dt> {c.languages}</div>{/if}
          </dl>

          {#if c.has_cv || c.has_photo}
            <div class="flex gap-1.5">
              {#if c.has_cv}<span class="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-400">CV</span>{/if}
              {#if c.has_photo}<span class="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-400">Photo</span>{/if}
            </div>
          {/if}

          <div class="mt-auto border-t border-white/5 pt-3">
            {#if c.unlocked}
              <div class="grid gap-1 text-sm">
                {#if c.email}<a href={`mailto:${c.email}`} class="text-cyan-300 hover:underline">{c.email}</a>{/if}
                {#if c.phone}<a href={`tel:${c.phone}`} class="text-cyan-300 hover:underline">{c.phone}</a>{/if}
                {#if !c.email && !c.phone}<span class="text-slate-500">No contact details on file.</span>{/if}
              </div>
            {:else}
              <button
                type="button"
                onclick={() => unlock(c.profile_slug)}
                disabled={unlockingSlug === c.profile_slug || balance < unlockCost}
                class="w-full rounded-lg border border-cyan-300/30 bg-cyan-300/10 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {unlockingSlug === c.profile_slug
                  ? 'Unlocking…'
                  : balance < unlockCost
                    ? `Need ${unlockCost} tokens`
                    : `Unlock contact — ${unlockCost} tokens`}
              </button>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>
