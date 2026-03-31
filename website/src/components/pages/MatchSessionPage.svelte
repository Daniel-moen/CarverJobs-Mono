<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick } from '../../config/analytics'

  let { sessionId = 0 } = $props()

  let mounted = $state(false)
  let loading = $state(true)
  let error = $state('')
  let session = $state(null)
  let matches = $state([])

  let draftingJob = $state(null)
  let draftTo = $state('')
  let draftSubject = $state('')
  let draftBody = $state('')
  let draftLoading = $state(false)
  let draftError = $state('')
  let draftPrompt = $state('')
  let copiedEmail = $state(false)

  const MAX_DRAFT_PROMPT_LEN = 500

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    await loadSession()
  })

  async function loadSession() {
    loading = true
    error = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/matching/sessions/${sessionId}`, {
        method: 'GET',
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        error = err.detail ?? `Could not load matches (${res.status}).`
        return
      }
      const data = await res.json()
      session = data
      matches = (data.results ?? []).sort((a, b) => (b.compatibility ?? 0) - (a.compatibility ?? 0))
    } catch {
      error = 'Could not reach the server. Please try again.'
    } finally {
      loading = false
    }
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
      draftTo = data.to || draftTo
      draftSubject = data.subject || draftSubject
      draftBody = data.body || draftBody
    } catch {
      draftError = 'Could not reach drafting service.'
    } finally {
      draftLoading = false
    }
  }

  async function draftEmail(job) {
    draftingJob = job
    draftTo = job.contact_email ?? ''
    draftSubject = ''
    draftBody = ''
    draftPrompt = ''
    draftError = ''
    copiedEmail = false
    document.body.style.overflow = 'hidden'
    window.scrollTo({ top: 0, behavior: 'instant' })
    trackClick('match_session_draft_email')
    await callDraftApi(job.id)
  }

  async function repromptDraft() {
    if (!draftPrompt.trim() || !draftingJob) return
    if (!draftBody.trim()) {
      draftError = 'Generate the first draft before rewriting.'
      return
    }
    const instruction = draftPrompt.trim().slice(0, MAX_DRAFT_PROMPT_LEN)
    draftPrompt = ''
    await callDraftApi(draftingJob.id, instruction, draftBody || null)
  }

  function closeDraft() {
    draftingJob = null
    copiedEmail = false
    draftPrompt = ''
    draftError = ''
    document.body.style.overflow = ''
  }

  async function copyDraft() {
    const text = `To: ${draftTo}\nSubject: ${draftSubject}\n\n${draftBody}`
    try {
      await navigator.clipboard.writeText(text)
      copiedEmail = true
      setTimeout(() => (copiedEmail = false), 2000)
    } catch { /* ignore */ }
  }

  function buildMailto() {
    return `mailto:${encodeURIComponent(draftTo)}?subject=${encodeURIComponent(draftSubject)}&body=${encodeURIComponent(draftBody)}`
  }

  function salaryLabel(job) {
    if (job.salary_min && job.salary_max) {
      return `${job.salary_currency ?? 'EUR'} ${Math.round(job.salary_min)}–${Math.round(job.salary_max)}/mo`
    }
    return null
  }

  function formatDate(iso) {
    if (!iso) return ''
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    } catch { return '' }
  }
</script>

<section class="grid gap-5 overflow-hidden" class:visible={mounted}>

  {#if loading}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-8 sm:p-10 text-center">
      <div class="mx-auto h-8 w-8 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 spinner"></div>
      <p class="mt-4 text-sm font-semibold text-white">Loading your matches...</p>
    </div>

  {:else if error}
    <div class="rounded-2xl border border-rose-400/20 bg-zinc-950 p-6 sm:p-8 text-center">
      <p class="text-sm text-rose-300">{error}</p>
      <button
        type="button"
        onclick={() => loadSession()}
        class="mt-4 rounded-lg border border-cyan-300/30 bg-cyan-300/8 px-5 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white active:scale-95"
      >
        Retry
      </button>
    </div>

  {:else if !matches.length}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:p-8 text-center">
      <p class="text-sm font-semibold text-white">No matches in this session</p>
      <p class="mt-1 text-xs text-slate-500">Run a new match from WhatsApp or the home page.</p>
    </div>

  {:else}
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-xl font-bold text-white">{matches.length} Match{matches.length !== 1 ? 'es' : ''}</h1>
        <p class="text-xs text-slate-500">
          Scanned {session?.total_jobs_scanned ?? 0} positions
          {#if session?.created_at}
            · {formatDate(session.created_at)}
          {/if}
        </p>
      </div>
    </div>

    {#each matches as m, i (m.job?.id ?? i)}
      {@const job = m.job}
      {@const compat = Math.round(m.compatibility ?? 0)}
      <article class="rounded-xl border border-white/8 bg-zinc-950 p-4 sm:p-5 overflow-hidden min-w-0">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <h3 class="text-base font-bold text-white truncate">{job.title}</h3>
            <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-slate-400">
              {#if job.role}<span>{job.role}</span>{/if}
              {#if job.yacht}<span class="text-white/15">·</span><span>{job.yacht}</span>{/if}
            </div>
          </div>
          <span class="shrink-0 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-0.5 text-xs font-bold text-emerald-300">{compat}%</span>
        </div>

        <div class="mt-2.5 flex flex-wrap gap-1.5 text-[11px]">
          {#if job.location}
            <span class="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">{job.location}</span>
          {/if}
          {#if job.contract_type}
            <span class="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">{job.contract_type}</span>
          {/if}
          {#if job.start_date}
            <span class="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">Start: {job.start_date}</span>
          {/if}
          {#if salaryLabel(job)}
            <span class="rounded-full border border-cyan-400/20 bg-cyan-400/5 px-2 py-0.5 text-cyan-300">{salaryLabel(job)}</span>
          {/if}
          {#if job.urgent_hire}
            <span class="rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-0.5 font-bold uppercase text-rose-300">Urgent</span>
          {/if}
        </div>

        {#if m.reason}
          <p class="mt-2.5 text-sm leading-relaxed text-slate-400 break-words">{m.reason}</p>
        {/if}

        {#if m.strengths?.length || m.gaps?.length}
          <div class="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
            {#if m.strengths?.length}
              <div class="flex flex-wrap items-center gap-1">
                <span class="font-medium text-emerald-400/70">+</span>
                {#each m.strengths.slice(0, 3) as s}
                  <span class="text-slate-500">{s}</span>
                {/each}
              </div>
            {/if}
            {#if m.gaps?.length}
              <div class="flex flex-wrap items-center gap-1">
                <span class="font-medium text-amber-400/70">−</span>
                {#each m.gaps.slice(0, 2) as g}
                  <span class="text-slate-500">{g}</span>
                {/each}
              </div>
            {/if}
          </div>
        {/if}

        <div class="mt-3 border-t border-white/6 pt-3">
          <div class="flex flex-wrap items-center gap-2">
            <button
              onclick={() => draftEmail(job)}
              class="rounded-md border border-cyan-300/30 bg-cyan-300/8 px-4 py-1.5 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white active:scale-95"
            >
              Draft Email
            </button>
            {#if job.application_url}
              <a
                href={job.application_url}
                target="_blank"
                rel="noopener noreferrer"
                class="rounded-md border border-white/10 px-3 py-1.5 text-xs text-slate-400 transition hover:text-white"
              >
                View Listing
              </a>
            {/if}
          </div>
        </div>
      </article>
    {/each}
  {/if}
</section>

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
            {draftingJob.title ?? draftingJob.role} — {draftingJob.yacht ?? ''}
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
        {#if draftLoading && !draftBody}
          <div class="flex flex-col items-center gap-3 py-8">
            <div class="h-6 w-6 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 spinner"></div>
            <p class="text-sm text-slate-400">AI is drafting your email...</p>
          </div>
        {:else}
          <label class="grid gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">To</span>
            <input
              type="email"
              bind:value={draftTo}
              placeholder="recruiter@example.com"
              class="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30"
            />
          </label>

          <label class="grid gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Subject</span>
            <input
              type="text"
              bind:value={draftSubject}
              class="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/30"
            />
          </label>

          <label class="grid gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Message</span>
            <textarea
              bind:value={draftBody}
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

      {#if draftBody}
        <div class="flex-none grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center border-t border-white/8 px-5 py-4 sm:px-6">
          <button
            type="button"
            onclick={() => { window.open(buildMailto(), '_self'); trackClick('match_session_mailto') }}
            class="col-span-2 rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-5 py-2 text-sm font-semibold text-cyan-300 transition-all hover:bg-cyan-400/20 hover:text-white active:scale-95"
          >
            Open in Mail App
          </button>
          <button
            type="button"
            onclick={copyDraft}
            class="rounded-lg border border-white/12 bg-white/5 px-5 py-2 text-sm font-medium text-slate-300 transition-all hover:border-white/25 hover:text-white active:scale-95"
          >
            {copiedEmail ? 'Copied!' : 'Copy to Clipboard'}
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
  section {
    opacity: 0;
    transform: translateY(10px);
    transition: opacity 0.35s ease, transform 0.35s ease;
  }
  section.visible {
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
