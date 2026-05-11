<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let jobs = $state([])
  let isLoading = $state(true)
  let error = $state('')
  let mounted = $state(false)

  let draftingJob = $state(null)
  let emailTo = $state('')
  let emailSubject = $state('')
  let emailBody = $state('')
  let emailCopied = $state(false)
  let draftLoading = $state(false)
  let draftError = $state('')
  let draftPrompt = $state('')
  const MAX_DRAFT_PROMPT_LEN = 500

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

  async function callDraftApi(jobId, prompt = null, previousBody = null) {
    draftLoading = true
    draftError = ''
    try {
      const body = { job_id: jobId }
      if (prompt) body.prompt = prompt
      if (previousBody) body.previous_body = previousBody
      const res = await apiFetch(`${API_BASE_URL}/matching/draft-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        draftError = err.detail || 'Could not draft email. Try again.'
        return
      }
      const data = await res.json()
      emailTo = data.to || emailTo
      emailSubject = data.subject || emailSubject
      emailBody = data.body || emailBody
    } catch {
      draftError = 'Could not reach drafting service.'
    } finally {
      draftLoading = false
    }
  }

  async function openDraft(job) {
    draftingJob = job
    emailTo = job.contact_email ?? ''
    emailSubject = ''
    emailBody = ''
    draftPrompt = ''
    draftError = ''
    emailCopied = false
    document.body.style.overflow = 'hidden'
    window.scrollTo({ top: 0, behavior: 'auto' })
    await callDraftApi(job.id)
  }

  async function repromptDraft() {
    if (!draftPrompt.trim() || !draftingJob) return
    if (!emailBody.trim()) {
      draftError = 'Generate the first draft before rewriting.'
      return
    }
    const instruction = draftPrompt.trim().slice(0, MAX_DRAFT_PROMPT_LEN)
    if (instruction.length < draftPrompt.trim().length) {
      draftError = `Instruction is too long. Max ${MAX_DRAFT_PROMPT_LEN} characters.`
    }
    draftPrompt = ''
    await callDraftApi(draftingJob.id, instruction, emailBody || null)
  }

  function closeDraft() {
    draftingJob = null
    emailCopied = false
    draftPrompt = ''
    draftError = ''
    document.body.style.overflow = ''
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

<section class="grid gap-4 overflow-hidden">
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
              <div class="skeleton h-5 w-48 max-w-full rounded-lg"></div>
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
          class="job-card group relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400/22 hover:shadow-[0_18px_50px_-22px_rgba(34,211,238,0.3)] min-w-0"
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

            <div class="mt-4 grid grid-cols-2 gap-1.5 sm:gap-2">
              <div class="rounded-xl border border-white/8 bg-black/30 p-2.5 sm:p-3 overflow-hidden">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Timeline</p>
                <p class="mt-1.5 text-xs text-slate-300 truncate">
                  <span class="text-slate-600">Start</span> {job.start_date ?? 'TBC'}
                </p>
                <p class="mt-0.5 text-xs text-slate-300 truncate">
                  <span class="text-slate-600">End</span> {endDateLabel(job)}
                </p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-2.5 sm:p-3 overflow-hidden">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Compensation</p>
                <p class="mt-1.5 text-sm font-semibold text-cyan-300 truncate">{salaryLabel(job)}</p>
                <p class="mt-0.5 text-[10px] text-slate-500 truncate">{job.tips_bonus ?? 'Tips TBC'}</p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-2.5 sm:p-3 overflow-hidden">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Contract</p>
                <p class="mt-1.5 text-xs text-slate-300 truncate">{contractLabel(job)}</p>
                <p class="mt-0.5 text-[10px] text-slate-500 truncate">
                  {job.contract_type?.toLowerCase() === 'permanent' ? 'Long-term' : 'Fixed cycle'}
                </p>
              </div>
              <div class="rounded-xl border border-white/8 bg-black/30 p-2.5 sm:p-3 overflow-hidden">
                <p class="text-[9px] font-bold uppercase tracking-wider text-slate-600">Vessel</p>
                <p class="mt-1.5 text-xs text-slate-300 truncate">
                  {job.yacht_type ?? 'N/A'}{job.yacht_length_m ? ` · ${job.yacht_length_m}m` : ''}
                </p>
                <p class="mt-0.5 text-[10px] text-slate-500 truncate">{job.vessel_flag ?? 'Flag TBC'}</p>
              </div>
            </div>

            <!-- Optional description -->
            {#if job.description}
              <div class="mt-3 rounded-xl border border-white/6 bg-black/20 px-3 py-2.5 overflow-hidden">
                <p class="line-clamp-2 text-xs leading-relaxed text-slate-400 break-words">{job.description}</p>
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

            <!-- Actions -->
            <div class="mt-4 flex items-center gap-2">
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
    class="fixed inset-0 z-50 flex items-start sm:items-center justify-center overflow-y-auto overscroll-contain bg-black/70 backdrop-blur-sm p-4"
    onclick={(e) => { if (e.target === e.currentTarget) closeDraft() }}
    onkeydown={(e) => { if (e.key === 'Escape') closeDraft() }}
    role="dialog"
    aria-modal="true"
    tabindex="-1"
  >
    <div class="draft-panel relative my-4 sm:my-0 w-full max-w-2xl rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl flex flex-col max-h-[92dvh] sm:max-h-[85vh]">
      <div class="flex-none flex items-center justify-between border-b border-white/8 px-5 py-4 sm:px-6">
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

      <div class="flex-1 overflow-y-auto grid gap-4 px-5 py-5 sm:px-6">
        {#if draftLoading && !emailBody}
          <div class="flex flex-col items-center gap-3 py-8">
            <div class="h-6 w-6 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 spinner"></div>
            <p class="text-sm text-slate-400">AI is drafting your email...</p>
          </div>
        {:else}
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
              rows="6"
              class="rounded-lg border border-white/10 bg-black/40 px-3 py-3 text-sm leading-relaxed text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30 resize-y min-h-[120px]"
            ></textarea>
          </label>

          <div class="grid gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Adjust with AI</span>
            <div class="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                bind:value={draftPrompt}
                placeholder="e.g. Make it more casual, mention my STCW cert..."
                onkeydown={(e) => { if (e.key === 'Enter' && !draftLoading) repromptDraft() }}
                class="flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-violet-400/40 focus:ring-1 focus:ring-violet-400/30"
              />
              <button
                type="button"
                onclick={repromptDraft}
                disabled={draftLoading || !draftPrompt.trim()}
                class="flex-none rounded-lg border border-violet-400/30 bg-violet-400/10 px-4 py-2 text-xs font-semibold text-violet-300 transition-all hover:bg-violet-400/20 hover:text-white active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {draftLoading ? 'Rewriting...' : 'Rewrite'}
              </button>
            </div>
          </div>

          {#if draftError}
            <p class="text-sm text-rose-300">{draftError}</p>
          {/if}
        {/if}
      </div>

      {#if emailBody}
        <div class="flex-none grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center border-t border-white/8 px-5 py-4 sm:px-6">
          <button
            type="button"
            onclick={openInMailClient}
            class="col-span-2 rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-5 py-2 text-sm font-semibold text-cyan-300 transition-all hover:bg-cyan-400/20 hover:text-white active:scale-95"
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
            class="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-500 transition hover:text-white sm:ml-auto"
          >
            Cancel
          </button>
        </div>
      {/if}
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

  .spinner {
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  .draft-panel {
    animation: draftSlideIn 0.25s ease-out;
  }
  @keyframes draftSlideIn {
    from { opacity: 0; transform: translateY(24px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
</style>
