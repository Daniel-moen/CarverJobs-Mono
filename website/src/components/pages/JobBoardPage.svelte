<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let jobs = $state([])
  let isLoading = $state(true)
  let error = $state('')
  let mounted = $state(false)

  let draftingJob = $state(null)
  let profileSlug = $state('')
  let profileUrl = $derived(profileSlug ? `${window.location.origin}/crew/${profileSlug}` : '')
  let emailTo = $state('')
  let emailSubject = $state('')
  let emailBody = $state('')
  let emailCopied = $state(false)

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

  function buildEmailDraft(job) {
    const role = job.title ?? job.role
    const yacht = job.yacht ?? 'the vessel'
    emailTo = job.contact_email ?? ''
    emailSubject = `Application – ${role} on ${yacht}`
    emailBody = `Dear Hiring Manager,

I am writing to express my interest in the ${role} position on ${yacht}${job.location ? ` (${job.location})` : ''}.

Please find my full crew profile and qualifications here:
${profileUrl || '[Complete your profile to generate your link]'}

I would welcome the opportunity to discuss how my experience aligns with this role. Please don't hesitate to reach out with any questions.

Kind regards`
  }

  function openDraft(job) {
    buildEmailDraft(job)
    draftingJob = job
  }

  function closeDraft() {
    draftingJob = null
    emailCopied = false
  }

  function openInMailClient() {
    const subject = encodeURIComponent(emailSubject)
    const body = encodeURIComponent(emailBody)
    const mailto = `mailto:${encodeURIComponent(emailTo)}?subject=${subject}&body=${body}`
    window.open(mailto, '_self')
  }

  async function copyDraftToClipboard() {
    const text = `To: ${emailTo}\nSubject: ${emailSubject}\n\n${emailBody}`
    try {
      await navigator.clipboard.writeText(text)
      emailCopied = true
      setTimeout(() => (emailCopied = false), 2000)
    } catch { /* clipboard unavailable */ }
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

  async function loadProfileSlug() {
    try {
      const saved = localStorage.getItem('carver_profile')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (parsed.profileSlug) { profileSlug = parsed.profileSlug; return }
      }
    } catch { /* ignore */ }
    try {
      const res = await apiFetch(`${API_BASE_URL}/profile/me`, { credentials: 'include' })
      if (!res.ok) return
      const data = await res.json()
      profileSlug = data.profile?.profile_slug ?? ''
    } catch { /* ignore */ }
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

  onMount(() => {
    loadJobs()
    loadProfileSlug()
  })
</script>

<section class="grid gap-4">
  <!-- Header -->
  <header class="relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-4 py-4 sm:px-6 sm:py-5">
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-sky-400/10 blur-3xl header-orb"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-cyan-400/7 blur-2xl header-orb" style="animation-delay:-2.5s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div class="min-w-0">
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
        <div class="flex-shrink-0 self-start rounded-xl border border-sky-400/15 bg-sky-400/5 px-3 py-2 text-center">
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

            <!-- Actions — visible on mobile, appear on hover on desktop -->
            <div class="mt-4 flex items-center gap-2 transition-opacity duration-200 sm:opacity-0 sm:group-hover:opacity-100">
              <button
                type="button"
                onclick={() => openDraft(job)}
                class="rounded-lg border border-cyan-400/30 bg-cyan-400/8 px-4 py-1.5 text-xs font-semibold text-cyan-300 transition-all hover:bg-cyan-400/18 hover:text-white active:scale-95"
              >
                Draft Email
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

<!-- Email draft overlay -->
{#if draftingJob}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    onclick={(e) => { if (e.target === e.currentTarget) closeDraft() }}
    onkeydown={(e) => { if (e.key === 'Escape') closeDraft() }}
    role="dialog"
    aria-modal="true"
    tabindex="-1"
  >
    <div class="draft-panel relative w-full max-w-2xl rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl">
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-white/8 px-5 py-4 sm:px-6">
        <div class="min-w-0">
          <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Draft Email</p>
          <h2 class="mt-1 truncate text-base font-bold text-white">
            {draftingJob.title ?? draftingJob.role} — {draftingJob.yacht}
          </h2>
        </div>
        <button
          type="button"
          onclick={closeDraft}
          class="ml-4 flex-none rounded-lg border border-white/10 p-1.5 text-slate-500 transition hover:border-white/20 hover:text-white"
          aria-label="Close"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>
      </div>

      <!-- Form -->
      <div class="grid gap-4 px-5 py-5 sm:px-6">
        <label class="grid gap-1.5">
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">To</span>
          <input
            type="email"
            bind:value={emailTo}
            placeholder="recruiter@example.com"
            class="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30"
          />
        </label>

        <label class="grid gap-1.5">
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Subject</span>
          <input
            type="text"
            bind:value={emailSubject}
            class="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30"
          />
        </label>

        <label class="grid gap-1.5">
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Message</span>
          <textarea
            bind:value={emailBody}
            rows="10"
            class="rounded-lg border border-white/10 bg-black/40 px-3 py-3 text-sm leading-relaxed text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30 resize-y"
          ></textarea>
        </label>

        {#if profileUrl}
          <div class="flex items-center gap-2 rounded-lg border border-sky-400/15 bg-sky-400/5 px-3 py-2">
            <span class="text-[10px] font-bold uppercase tracking-wider text-sky-500">Profile Link</span>
            <a href={profileUrl} target="_blank" rel="noopener" class="truncate text-xs text-sky-300 underline decoration-sky-400/30 hover:text-white">
              {profileUrl}
            </a>
          </div>
        {:else}
          <div class="flex items-center gap-2 rounded-lg border border-amber-400/15 bg-amber-400/5 px-3 py-2">
            <span class="text-xs text-amber-300">Complete your profile to attach your crew link.</span>
          </div>
        {/if}
      </div>

      <!-- Actions -->
      <div class="flex flex-wrap items-center gap-2 border-t border-white/8 px-5 py-4 sm:px-6">
        <button
          type="button"
          onclick={openInMailClient}
          class="rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-5 py-2 text-sm font-semibold text-cyan-300 transition-all hover:bg-cyan-400/20 hover:text-white active:scale-95"
        >
          Open in Mail App
        </button>
        <button
          type="button"
          onclick={copyDraftToClipboard}
          class="rounded-lg border border-white/12 bg-white/5 px-5 py-2 text-sm font-medium text-slate-300 transition-all hover:border-white/25 hover:text-white active:scale-95"
        >
          {emailCopied ? 'Copied!' : 'Copy to Clipboard'}
        </button>
        <button
          type="button"
          onclick={closeDraft}
          class="ml-auto rounded-lg px-4 py-2 text-sm text-slate-500 transition hover:text-white"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* Header orb pulse + scan — reduced on mobile */
  .header-orb {
    animation: headerOrbPulse 4.5s ease-in-out infinite;
  }
  @media (max-width: 768px) {
    .header-orb { filter: blur(16px) !important; animation: none; }
    .header-scan-line { display: none; }
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

  .draft-panel {
    animation: draftSlideIn 0.25s ease-out;
  }
  @keyframes draftSlideIn {
    from { opacity: 0; transform: translateY(24px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
</style>
