<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick } from '../../config/analytics'

  let { isSubscribed = false, creditsBalance = 0, onCreditsChanged = () => {}, onNavigate = () => {}, autoStartMatch = false, onMatchStarted = () => {} } = $props()

  // sessionStorage key for persisting the most recent match result across
  // in-app tab switches. Without this the component re-mounts in 'idle' and
  // the user sees 'Start Matching' again instead of their previous results.
  const STORAGE_KEY = 'carver_auto_apply_state'

  let mounted = $state(false)
  let state = $state('idle')
  let error = $state('')
  let matches = $state([])
  let totalScanned = $state(0)
  let sessionId = $state(0)
  let retries = $state(0)

  function persistMatchState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        state, matches, totalScanned, sessionId, error,
      }))
    } catch { /* storage unavailable / quota */ }
  }

  function clearPersistedMatchState() {
    try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  }

  function restoreMatchState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      if (!raw) return false
      const saved = JSON.parse(raw)
      // Only restore terminal states — never resume 'loading' (the SSE
      // stream is gone) or 'idle' (nothing useful to remember).
      if (!saved || !['done', 'no-match', 'error'].includes(saved.state)) {
        return false
      }
      state        = saved.state
      matches      = Array.isArray(saved.matches) ? saved.matches : []
      totalScanned = Number(saved.totalScanned) || 0
      sessionId    = Number(saved.sessionId) || 0
      error        = typeof saved.error === 'string' ? saved.error : ''
      return true
    } catch {
      return false
    }
  }

  function resetToIdle() {
    state = 'idle'
    matches = []
    error = ''
    totalScanned = 0
    sessionId = 0
    clearPersistedMatchState()
  }

  let draftingJob = $state(null)
  let draftTo = $state('')
  let draftSubject = $state('')
  let draftBody = $state('')
  let draftLoading = $state(false)
  let draftError = $state('')
  let draftPrompt = $state('')
  let copiedEmail = $state(false)

  /** Crew job share (same pipeline as dashboard ingest) */
  const JOB_IMG_TYPES = ['image/png', 'image/jpeg', 'image/webp']
  let jobPasteText = $state('')
  let jobSourceUrl = $state('')
  let jobSubmitBusy = $state(false)
  let jobSubmitMsg = $state('')
  let jobSubmitErr = $state('')
  let jobDragOver = $state(false)

  const jobTextOk = $derived(jobPasteText.trim().length >= 10)

  const MAX_RETRIES = 2
  const MAX_DRAFT_PROMPT_LEN = 500

  // True when matching failed because the user has no CrewProfile row yet.
  // In that case Retry will keep failing — we route them to the profile page.
  const needsProfileSetup = $derived(
    state === 'error' && /save your profile/i.test(error || '')
  )

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    const restored = restoreMatchState()
    if (autoStartMatch && state === 'idle' && !restored) {
      onMatchStarted()
      runMatch()
    } else if (autoStartMatch) {
      // Consume the flag so we don't auto-start later — the user already
      // has a previous result on screen.
      onMatchStarted()
    }
  })

  async function runMatch(isRetry = false) {
    trackClick(isRetry ? 'retry_match' : 'start_match')
    state = 'loading'
    error = ''
    if (!isRetry) {
      matches = []
      totalScanned = 0
      sessionId = 0
      retries = 0
    }
    // 'loading' is intentionally not persisted — clear any stale prior result.
    clearPersistedMatchState()

    try {
      const res = await apiFetch(`${API_BASE_URL}/matching/find`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        credentials: 'include',
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        if ((res.status === 502 || res.status === 503) && retries < MAX_RETRIES) {
          retries += 1
          await new Promise(r => setTimeout(r, 1500 * retries))
          return runMatch(true)
        }
        error = err.detail ?? `Matching failed (${res.status}). Please try again.`
        state = 'error'
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''
      let gotComplete = false

      function handleLine(line) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6))
            if (currentEvent === 'complete') {
              gotComplete = true
              totalScanned = parsed.total_jobs_scanned ?? 0
              sessionId = Number(parsed.session_id) || 0
              if (typeof parsed.credits_remaining === 'number') {
                onCreditsChanged(parsed.credits_remaining)
              }
              if (parsed.matched && parsed.matches?.length) {
                matches = parsed.matches
                state = 'done'
              } else {
                state = 'no-match'
              }
              persistMatchState()
            } else if (currentEvent === 'error') {
              error = parsed.detail ?? 'Matching failed.'
              state = 'error'
              persistMatchState()
            }
          } catch { /* ignore parse errors on progress events */ }
          currentEvent = ''
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) handleLine(line)
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        for (const line of buffer.split('\n')) handleLine(line)
      }

      if (!gotComplete && state === 'loading') {
        error = 'Connection lost before matching finished. Please try again.'
        state = 'error'
        persistMatchState()
      }
    } catch {
      if (retries < MAX_RETRIES) {
        retries += 1
        await new Promise(r => setTimeout(r, 1500 * retries))
        return runMatch(true)
      }
      error = 'Could not reach matching service. Check your connection and try again.'
      state = 'error'
      persistMatchState()
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
    window.scrollTo({ top: 0, behavior: 'auto' })
    await callDraftApi(job.id)
  }

  async function repromptDraft() {
    if (!draftPrompt.trim() || !draftingJob) return
    if (!draftBody.trim()) {
      draftError = 'Generate the first draft before rewriting.'
      return
    }
    const instruction = draftPrompt.trim().slice(0, MAX_DRAFT_PROMPT_LEN)
    if (instruction.length < draftPrompt.trim().length) {
      draftError = `Instruction is too long. Max ${MAX_DRAFT_PROMPT_LEN} characters.`
    }
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

  async function submitSharedJobText() {
    if (!jobTextOk || jobSubmitBusy) return
    trackClick('crew_submit_job_text')
    jobSubmitBusy = true
    jobSubmitErr = ''
    jobSubmitMsg = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ text: jobPasteText.trim(), url: jobSourceUrl.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        jobSubmitErr = typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`
        return
      }
      if (typeof data.credits_balance === 'number') onCreditsChanged(data.credits_balance)
      const t = data.title || 'the role'
      jobSubmitMsg = `“${t}” is live on the job board. +1 token.`
      jobPasteText = ''
    } catch {
      jobSubmitErr = 'Could not reach the server.'
    } finally {
      jobSubmitBusy = false
    }
  }

  function validateJobShareFiles(fileList) {
    const files = Array.from(fileList || []).filter((f) => f && f.size > 0)
    if (!files.length) {
      jobSubmitErr = 'Choose at least one image.'
      return null
    }
    if (files.length > 6) {
      jobSubmitErr = 'Use at most 6 images per submit.'
      return null
    }
    let total = 0
    for (const f of files) {
      if (!JOB_IMG_TYPES.includes(f.type)) {
        jobSubmitErr = 'Use only PNG, JPG, or WebP images.'
        return null
      }
      if (f.size > 8 * 1024 * 1024) {
        jobSubmitErr = 'Each image must be under 8 MB.'
        return null
      }
      total += f.size
    }
    if (total > 24 * 1024 * 1024) {
      jobSubmitErr = 'Combined images must be under 24 MB.'
      return null
    }
    return files
  }

  async function submitSharedJobImages(fileList) {
    const files = validateJobShareFiles(fileList)
    if (!files) return
    trackClick('crew_submit_job_image')
    jobSubmitBusy = true
    jobSubmitErr = ''
    jobSubmitMsg = ''
    try {
      const form = new FormData()
      for (const f of files) form.append('files', f)
      form.append('url', jobSourceUrl.trim())
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/image`, {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        jobSubmitErr = typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`
        return
      }
      if (typeof data.credits_balance === 'number') onCreditsChanged(data.credits_balance)
      const j = data.job || {}
      const t = j.title || 'the role'
      jobSubmitMsg = `“${t}” is live on the job board. +1 token.`
    } catch {
      jobSubmitErr = 'Could not reach the server.'
    } finally {
      jobSubmitBusy = false
    }
  }

  function onJobShareDrop(e) {
    e.preventDefault()
    jobDragOver = false
    const dt = e.dataTransfer?.files
    if (dt?.length) submitSharedJobImages(dt)
  }

  function onJobShareDragOver(e) {
    e.preventDefault()
    jobDragOver = true
  }

  function onJobShareFilePick(e) {
    const list = e.currentTarget.files
    e.currentTarget.value = ''
    if (list?.length) submitSharedJobImages(list)
  }
</script>

<section class="grid gap-5 overflow-hidden" class:visible={mounted}>

  {#if state === 'idle'}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:p-8 text-center">
      <h1 class="text-2xl font-black tracking-tight text-white sm:text-3xl">Find Your Matches</h1>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-400">
        AI scans every open position against your crew profile and returns all matches.
      </p>
      <div class="mx-auto mt-4 inline-flex rounded-full border border-cyan-300/25 bg-cyan-300/10 px-4 py-1.5 text-xs font-semibold text-cyan-100">
        {creditsBalance} token{creditsBalance === 1 ? '' : 's'} available
      </div>
      <p class="mx-auto mt-2 max-w-md text-xs text-slate-500">
        Matching costs 1 token. Spot a job in a group or post? Submit it (paste or screenshot) to earn 1 token.
      </p>
      <button
        type="button"
        disabled={creditsBalance < 1}
        onclick={() => runMatch()}
        class="mt-6 rounded-lg border border-cyan-300/35 bg-cyan-300/8 px-8 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/55 hover:bg-cyan-300/18 hover:text-white active:scale-95 disabled:cursor-not-allowed disabled:opacity-45"
      >
        {creditsBalance < 1 ? 'Need 1 Token' : 'Start Matching'}
      </button>
    </div>

  {:else if state === 'loading'}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-8 sm:p-10 text-center">
      <div class="mx-auto h-8 w-8 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 spinner"></div>
      <p class="mt-4 text-sm font-semibold text-white">
        {retries > 0 ? `Retrying... (attempt ${retries + 1})` : 'Matching in progress...'}
      </p>
      <p class="mt-1 text-xs text-slate-500">This can take 30–60 seconds depending on the number of open positions.</p>
    </div>

  {:else if state === 'error'}
    <div class="rounded-2xl border border-rose-400/20 bg-zinc-950 p-6 sm:p-8 text-center">
      <p class="text-sm text-rose-300">{error}</p>
      <div class="mt-4 flex flex-wrap justify-center gap-3">
        {#if needsProfileSetup}
          <button
            type="button"
            onclick={() => { trackClick('match_error_go_to_profile'); onNavigate('profile') }}
            class="rounded-lg border border-cyan-300/35 bg-cyan-300/10 px-5 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20 hover:text-white active:scale-95"
          >
            Go to Profile
          </button>
          <button
            type="button"
            onclick={resetToIdle}
            class="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-400 transition hover:text-white"
          >
            Cancel
          </button>
        {:else}
          <button
            type="button"
            onclick={() => runMatch()}
            class="rounded-lg border border-cyan-300/30 bg-cyan-300/8 px-5 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white active:scale-95"
          >
            Retry
          </button>
          <button
            type="button"
            onclick={resetToIdle}
            class="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-400 transition hover:text-white"
          >
            Cancel
          </button>
        {/if}
      </div>
    </div>

  {:else if state === 'no-match'}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:p-8 text-center">
      <p class="text-sm font-semibold text-white">No matches right now</p>
      <p class="mt-1 text-xs text-slate-500">No open positions closely match your profile. Check back soon or update your profile.</p>
      <button
        type="button"
        onclick={resetToIdle}
        class="mt-4 rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-400 transition hover:text-white"
      >
        Try Again
      </button>
    </div>

  {:else if state === 'done'}
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-xl font-bold text-white">{matches.length} Match{matches.length !== 1 ? 'es' : ''} Found</h1>
        <p class="text-xs text-slate-500">Scanned {totalScanned} positions</p>
        <p class="mt-1 text-xs text-cyan-200">{creditsBalance} token{creditsBalance === 1 ? '' : 's'} remaining</p>
      </div>
      <button
        type="button"
        onclick={resetToIdle}
        class="rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:text-white"
      >
        Run Again
      </button>
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

        <!-- Apply / Draft -->
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

  <!-- Share a job — public crew flow (earn token when AI accepts) -->
  <article class="rounded-2xl border border-amber-400/20 bg-gradient-to-b from-zinc-950 to-zinc-950/95 p-5 sm:p-6">
    <div class="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.22em] text-amber-400/80">Community</p>
        <h2 class="mt-1 text-lg font-bold tracking-tight text-white sm:text-xl">Share a job</h2>
        <p class="mt-1 max-w-xl text-sm text-slate-400">
          Saw a role in a crew group, page, or feed? Submit it easily—paste the text or drop a screenshot. We check it with AI, put it on the board, and you get <span class="text-amber-200/90">1 token</span> for matching.
        </p>
      </div>
    </div>

    <label class="mt-4 block">
      <span class="text-[11px] font-medium text-slate-500">Original link <span class="text-slate-600">(optional)</span></span>
      <input
        type="url"
        bind:value={jobSourceUrl}
        placeholder="https://…"
        disabled={jobSubmitBusy}
        class="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white placeholder-slate-600 outline-none transition focus:border-amber-400/35 focus:ring-1 focus:ring-amber-400/25 disabled:opacity-50"
      />
    </label>

    <div class="mt-5 grid gap-5 lg:grid-cols-2">
      <div class="rounded-xl border border-white/8 bg-black/25 p-4">
        <p class="text-xs font-semibold text-slate-300">Paste text</p>
        <p class="mt-0.5 text-[11px] text-slate-600">Full job ad copy works best (min. 10 characters).</p>
        <textarea
          bind:value={jobPasteText}
          rows="6"
          maxlength="5000"
          disabled={jobSubmitBusy}
          placeholder="Paste the job listing here…"
          class="mt-3 w-full resize-y rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-amber-400/35 focus:ring-1 focus:ring-amber-400/20 disabled:opacity-50"
        ></textarea>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span class="text-[11px] text-slate-600">{jobPasteText.trim().length} / 5000</span>
          <button
            type="button"
            disabled={!jobTextOk || jobSubmitBusy}
            onclick={submitSharedJobText}
            class="rounded-lg border border-amber-400/35 bg-amber-400/10 px-4 py-2 text-xs font-semibold text-amber-100 transition hover:border-amber-400/50 hover:bg-amber-400/18 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {jobSubmitBusy ? 'Checking…' : 'Submit text'}
          </button>
        </div>
      </div>

      <div class="rounded-xl border border-white/8 bg-black/25 p-4">
        <p class="text-xs font-semibold text-slate-300">Screenshot</p>
        <p class="mt-0.5 text-[11px] text-slate-600">PNG, JPG, or WebP · up to 6 images · 8 MB each · 24 MB total</p>
        <div
          class="drop-share mt-3 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors
            {jobDragOver ? 'border-amber-400/50 bg-amber-400/10' : 'border-white/12 bg-black/20 hover:border-white/20'}"
          ondrop={onJobShareDrop}
          ondragover={onJobShareDragOver}
          ondragleave={() => (jobDragOver = false)}
          role="presentation"
        >
          <p class="text-sm text-slate-400">{jobDragOver ? 'Drop to upload' : 'Drag image(s) here'}</p>
          <label class="mt-3 cursor-pointer rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-1.5 text-xs font-semibold text-amber-100 transition hover:bg-amber-400/18">
            Choose files
            <input
              type="file"
              multiple
              accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
              class="hidden"
              disabled={jobSubmitBusy}
              onchange={onJobShareFilePick}
            />
          </label>
        </div>
      </div>
    </div>

    {#if jobSubmitMsg}
      <p class="mt-4 rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">{jobSubmitMsg}</p>
    {/if}
    {#if jobSubmitErr}
      <p class="mt-4 rounded-lg border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">{jobSubmitErr}</p>
    {/if}
  </article>
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
            onclick={() => { window.open(buildMailto(), '_self'); trackClick('match_apply_mailto') }}
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
