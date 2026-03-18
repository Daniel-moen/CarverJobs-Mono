<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let jobs = $state([])
  let isLoading = $state(true)
  let error = $state('')
  let mounted = $state(false)

  function contractLabel(job) {
    return job.contract_type ?? (job.rotation ? `Rotational (${job.rotation})` : 'Unspecified')
  }

  function endDateLabel(job) {
    if (job.contract_type?.toLowerCase() === 'permanent') return 'Permanent'
    if (job.contract_type?.toLowerCase() === 'seasonal') return 'Seasonal / TBC'
    return 'TBC'
  }

  function salaryLabel(job) {
    if (job.salary_min && job.salary_max) {
      return `${job.salary_currency ?? 'EUR'} ${Math.round(job.salary_min)}–${Math.round(job.salary_max)}`
    }
    return 'TBC'
  }

  async function loadJobs() {
    isLoading = true
    error = ''
    mounted = false
    try {
      const response = await apiFetch(`${API_BASE_URL}/jobs`, {
        method: 'GET',
        credentials: 'include',
      })
      if (!response.ok) {
        error = response.status === 401 ? 'Please sign in again to load jobs.' : 'Failed to load jobs.'
        jobs = []
        return
      }
      jobs = await response.json()
    } catch {
      error = 'Could not reach API.'
      jobs = []
    } finally {
      isLoading = false
      requestAnimationFrame(() => (mounted = true))
    }
  }

  function handlePointerMove(e) {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }

  function resetPointer(e) {
    e.currentTarget.style.setProperty('--mx', '50%')
    e.currentTarget.style.setProperty('--my', '50%')
  }

  onMount(() => loadJobs())
</script>

<section class="grid gap-4">
  <!-- Header -->
  <header class="relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-5">
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-sky-400/10 blur-3xl header-orb"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-cyan-400/7 blur-2xl header-orb" style="animation-delay:-2.5s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex items-start justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Job Board</p>
        </div>
        <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Live Openings</h1>
        <p class="mt-1.5 text-sm text-slate-500">
          Server-matched vacancies ready for your pipeline.
        </p>
      </div>
      {#if !isLoading && !error}
        <div class="flex-none rounded-xl border border-sky-400/15 bg-sky-400/5 px-3 py-2 text-center">
          <p class="text-[9px] font-bold uppercase tracking-widest text-sky-500">Found</p>
          <p class="mt-0.5 text-lg font-black text-white">{jobs.length}</p>
        </div>
      {/if}
    </div>
  </header>

  <!-- Skeleton loading -->
  {#if isLoading}
    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {#each [1, 2, 3, 4] as _}
        <div class="overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-5">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 space-y-2">
              <div class="skeleton h-3 w-20 rounded-full"></div>
              <div class="skeleton h-5 w-48 rounded-lg"></div>
              <div class="skeleton h-3.5 w-32 rounded-full"></div>
            </div>
            <div class="skeleton h-6 w-16 rounded-full"></div>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-2.5">
            {#each [1, 2, 3, 4] as _}
              <div class="skeleton h-16 rounded-xl"></div>
            {/each}
          </div>
        </div>
      {/each}
    </div>

  <!-- Error state -->
  {:else if error}
    <div class="rounded-2xl border border-rose-400/15 bg-zinc-950 px-6 py-8 text-center">
      <p class="text-sm text-rose-300">{error}</p>
      <button
        type="button"
        onclick={loadJobs}
        class="mt-4 rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-slate-300 transition-all hover:border-white/30 hover:text-white"
      >
        Retry
      </button>
    </div>

  <!-- Empty state -->
  {:else if jobs.length === 0}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 px-6 py-12 text-center">
      <p class="text-sm text-slate-500">No jobs found yet. Check back soon.</p>
    </div>

  <!-- Job cards -->
  {:else}
    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {#each jobs as job, i}
        <article
          class="job-card group relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400/22 hover:shadow-[0_18px_50px_-22px_rgba(34,211,238,0.3)]"
          class:visible={mounted}
          style="--mx:50%; --my:50%; --delay:{i * 55}ms;"
          onmousemove={handlePointerMove}
          onmouseleave={resetPointer}
        >
          <!-- Spotlight -->
          <div
            class="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
            style="background: radial-gradient(220px circle at var(--mx) var(--my), rgba(34,211,238,0.1), transparent 65%);"
          ></div>

          <div class="relative z-10">
            <!-- Top row -->
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">{job.role}</p>
                <h2 class="mt-1 truncate text-base font-bold leading-tight text-white">
                  {job.title ?? job.role}
                </h2>
                <p class="mt-0.5 truncate text-sm text-slate-400">{job.yacht} · {job.location}</p>
              </div>
              <span
                class="flex-none rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider {job.status === 'priority'
                  ? 'bg-amber-400/15 text-amber-300 ring-1 ring-amber-400/25'
                  : 'bg-emerald-400/12 text-emerald-300 ring-1 ring-emerald-400/20'}"
              >
                {job.status}
              </span>
            </div>

            <!-- Info grid -->
            <div class="mt-4 grid grid-cols-2 gap-2">
              <div class="rounded-xl border border-white/8 bg-black/30 p-3">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Timeline</p>
                <p class="mt-1.5 text-xs text-slate-300">
                  <span class="text-slate-600">Start</span> {job.start_date ?? 'TBC'}
                </p>
                <p class="mt-0.5 text-xs text-slate-300">
                  <span class="text-slate-600">End</span> {endDateLabel(job)}
                </p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-3">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Compensation</p>
                <p class="mt-1.5 text-sm font-semibold text-cyan-300">{salaryLabel(job)}</p>
                <p class="mt-0.5 text-[10px] text-slate-500 truncate">{job.tips_bonus ?? 'Tips TBC'}</p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-3">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Contract</p>
                <p class="mt-1.5 text-xs text-slate-300">{contractLabel(job)}</p>
                <p class="mt-0.5 text-[10px] text-slate-500">
                  {job.contract_type?.toLowerCase() === 'permanent' ? 'Long-term' : 'Fixed cycle'}
                </p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-3">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Vessel</p>
                <p class="mt-1.5 text-xs text-slate-300">
                  {job.yacht_type ?? 'N/A'}{job.yacht_length_m ? ` · ${job.yacht_length_m}m` : ''}
                </p>
                <p class="mt-0.5 text-[10px] text-slate-500">{job.vessel_flag ?? 'Flag TBC'}</p>
              </div>
            </div>

            <!-- Optional description -->
            {#if job.description}
              <div class="mt-3 rounded-xl border border-white/6 bg-black/20 px-3 py-2.5">
                <p class="line-clamp-2 text-xs leading-relaxed text-slate-400">{job.description}</p>
              </div>
            {/if}

            <!-- Requirements tags -->
            {#if job.minimum_license || job.certifications_required}
              <div class="mt-3 flex flex-wrap gap-1.5">
                {#if job.minimum_license}
                  <span class="rounded-full border border-sky-400/18 bg-sky-400/8 px-2.5 py-0.5 text-[10px] font-medium text-sky-300">
                    {job.minimum_license}
                  </span>
                {/if}
                {#if job.certifications_required}
                  {#each job.certifications_required.split(',').slice(0, 3) as cert}
                    <span class="rounded-full border border-white/8 bg-white/4 px-2.5 py-0.5 text-[10px] font-medium text-slate-400">
                      {cert.trim()}
                    </span>
                  {/each}
                {/if}
              </div>
            {/if}

            <!-- Quick actions — appear on hover -->
            <div class="mt-4 flex items-center gap-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
              <button
                type="button"
                class="rounded-lg border border-cyan-400/30 bg-cyan-400/8 px-4 py-1.5 text-xs font-semibold text-cyan-300 transition-all hover:bg-cyan-400/18 hover:text-white active:scale-95"
              >
                Quick Apply
              </button>
              <button
                type="button"
                class="rounded-lg border border-white/10 bg-white/4 px-4 py-1.5 text-xs font-medium text-slate-400 transition-all hover:border-white/20 hover:text-white active:scale-95"
              >
                Save
              </button>
            </div>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

<style>
  /* Header orb pulse + scan */
  .header-orb {
    animation: headerOrbPulse 4.5s ease-in-out infinite;
  }
  .header-scan-line {
    position: absolute;
    top: -1px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(34,211,238,0.28), transparent);
    animation: headerScan 8s linear infinite;
    pointer-events: none;
  }
  @keyframes headerOrbPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.55; transform: scale(1.14); }
  }
  @keyframes headerScan {
    0%   { top: -1px; opacity: 0; }
    8%   { opacity: 1; }
    92%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }

  /* Shimmer skeleton */
  .skeleton {
    background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.6s ease-in-out infinite;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* Staggered card entrance */
  .job-card {
    opacity: 0;
    transform: translateY(16px);
    transition:
      opacity 0.45s ease,
      transform 0.45s ease,
      border-color 0.25s,
      box-shadow 0.25s,
      translate 0.2s;
    transition-delay: var(--delay, 0ms);
  }
  .job-card.visible {
    opacity: 1;
    transform: translateY(0);
  }
</style>
