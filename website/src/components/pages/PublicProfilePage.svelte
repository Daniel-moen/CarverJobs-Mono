<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { slug = '' } = $props()

  let profile = $state(null)
  let loading = $state(true)
  let error = $state('')

  onMount(async () => {
    try {
      const res = await apiFetch(`${API_BASE_URL}/p/${encodeURIComponent(slug)}`)
      if (!res.ok) {
        error = res.status === 404 ? 'Profile not found.' : 'Could not load profile.'
        return
      }
      profile = await res.json()
    } catch {
      error = 'Could not reach server.'
    } finally {
      loading = false
    }
  })

  const displayName = $derived(
    profile ? [profile.first_name, profile.last_name].filter(Boolean).join(' ') || 'Crew Member' : ''
  )
</script>

{#if loading}
  <div class="flex min-h-[60vh] items-center justify-center">
    <p class="text-sm text-slate-500">Loading profile…</p>
  </div>
{:else if error}
  <div class="flex min-h-[60vh] items-center justify-center">
    <div class="text-center">
      <p class="text-lg font-semibold text-white">Oops</p>
      <p class="mt-2 text-sm text-slate-400">{error}</p>
    </div>
  </div>
{:else if profile}
  <div class="mx-auto max-w-3xl space-y-5 py-6">
    <!-- Profile Header -->
    <header class="pub-card relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-6">
      <div class="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-cyan-400/8 blur-3xl"></div>
      <div class="relative flex items-center gap-5">
        <div class="h-20 w-20 flex-none overflow-hidden rounded-full border-2 {profile.has_photo ? 'border-cyan-400/30' : 'border-white/10'} bg-black/40">
          {#if profile.photo_url}
            <img src="{API_BASE_URL}{profile.photo_url}" alt={displayName} class="h-full w-full object-cover" />
          {:else}
            <div class="flex h-full w-full items-center justify-center text-2xl font-bold text-slate-700">
              {profile.first_name?.[0]?.toUpperCase() ?? '?'}{profile.last_name?.[0]?.toUpperCase() ?? ''}
            </div>
          {/if}
        </div>
        <div>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Crew Profile</p>
          <h1 class="mt-1 text-2xl font-black tracking-tight text-white">{displayName}</h1>
          {#if profile.desired_role}
            <p class="mt-1 text-sm text-cyan-300">{profile.desired_role}</p>
          {/if}
          <div class="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400">
            {#if profile.nationality}
              <span class="rounded-full border border-white/8 px-2 py-0.5">{profile.nationality}</span>
            {/if}
            {#if profile.current_location}
              <span class="rounded-full border border-white/8 px-2 py-0.5">{profile.current_location}</span>
            {/if}
            {#if profile.years_experience}
              <span class="rounded-full border border-white/8 px-2 py-0.5">{profile.years_experience} yrs experience</span>
            {/if}
          </div>
        </div>
      </div>
    </header>

    <!-- Bio + Details -->
    <div class="grid gap-5 lg:grid-cols-2">
      {#if profile.bio}
        <article class="pub-card rounded-2xl border border-white/8 bg-zinc-950 p-5 lg:col-span-2">
          <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">About</p>
          <p class="mt-3 text-sm leading-relaxed text-slate-300">{profile.bio}</p>
        </article>
      {/if}

      <article class="pub-card rounded-2xl border border-white/8 bg-zinc-950 p-5">
        <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Career Preferences</p>
        <div class="mt-3 grid gap-2 text-sm">
          {#if profile.contract_type}
            <div class="flex justify-between"><span class="text-slate-500">Contract</span><span class="text-slate-200">{profile.contract_type}</span></div>
          {/if}
          {#if profile.preferred_locations}
            <div class="flex justify-between gap-4"><span class="flex-none text-slate-500">Locations</span><span class="text-right text-slate-200">{profile.preferred_locations}</span></div>
          {/if}
          {#if profile.rotation_preference}
            <div class="flex justify-between"><span class="text-slate-500">Rotation</span><span class="text-slate-200">{profile.rotation_preference}</span></div>
          {/if}
          {#if profile.available_from}
            <div class="flex justify-between"><span class="text-slate-500">Available</span><span class="text-slate-200">{profile.available_from}</span></div>
          {/if}
        </div>
      </article>

      <article class="pub-card rounded-2xl border border-white/8 bg-zinc-950 p-5">
        <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Qualifications</p>
        <div class="mt-3 grid gap-2 text-sm">
          {#if profile.certifications}
            <div><span class="text-slate-500">Certifications</span><p class="mt-0.5 text-slate-200">{profile.certifications}</p></div>
          {/if}
          {#if profile.languages}
            <div><span class="text-slate-500">Languages</span><p class="mt-0.5 text-slate-200">{profile.languages}</p></div>
          {/if}
        </div>

        <!-- Document indicators -->
        <div class="mt-4 flex flex-wrap gap-2">
          {#if profile.has_cv}
            <span class="rounded-full border border-emerald-400/20 bg-emerald-400/8 px-2.5 py-1 text-[10px] font-semibold text-emerald-300">CV available</span>
          {/if}
          {#if profile.has_references}
            <span class="rounded-full border border-emerald-400/20 bg-emerald-400/8 px-2.5 py-1 text-[10px] font-semibold text-emerald-300">References available</span>
          {/if}
        </div>
      </article>
    </div>

    <!-- Job History -->
    {#if profile.job_history && profile.job_history.length > 0}
      <article class="pub-card rounded-2xl border border-white/8 bg-zinc-950 p-5">
        <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Recent Positions</p>
        <div class="mt-4 grid gap-3">
          {#each profile.job_history as entry}
            <div class="flex items-start gap-3 rounded-xl border border-white/6 bg-black/20 px-4 py-3">
              <div class="mt-1.5 h-2 w-2 flex-none rounded-full bg-cyan-400/40"></div>
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2">
                  <p class="text-sm font-semibold text-white">{entry.role}</p>
                  <span class="text-xs text-slate-500">on</span>
                  <p class="text-sm text-cyan-200">{entry.yacht_name}</p>
                  {#if entry.yacht_type}
                    <span class="rounded-full border border-white/8 px-2 py-0.5 text-[9px] text-slate-500">{entry.yacht_type}</span>
                  {/if}
                </div>
                {#if entry.start_date || entry.end_date}
                  <p class="mt-0.5 text-[11px] text-slate-500">{entry.start_date ?? '?'} — {entry.end_date ?? 'Present'}</p>
                {/if}
                {#if entry.description}
                  <p class="mt-1 text-xs leading-relaxed text-slate-400">{entry.description}</p>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </article>
    {/if}

    <!-- Footer -->
    <p class="text-center text-[10px] text-slate-700">Powered by CARVER</p>
  </div>
{/if}

<style>
  .pub-card {
    animation: pubFadeIn 0.5s ease both;
  }
  @keyframes pubFadeIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
