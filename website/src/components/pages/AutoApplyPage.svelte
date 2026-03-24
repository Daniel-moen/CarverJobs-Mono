<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick } from '../../config/analytics'

  let { isSubscribed = false, onNavigate = () => {}, autoStartMatch = false, onMatchStarted = () => {} } = $props()

  let mounted = $state(false)
  let matchState = $state('idle')
  let matchError = $state('')
  let allMatches = $state([])
  let matchIndex = $state(0)
  let matchedJob = $derived(allMatches[matchIndex]?.job ?? null)
  let matchAI = $derived(allMatches[matchIndex]?.ai ?? null)
  let profileSlug = $state('')
  let copiedEmail = $state(false)
  let draftTo = $state('')
  let draftSubject = $state('')
  let draftBody = $state('')
  let draftError = $state('')

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    try {
      const res = await apiFetch(`${API_BASE_URL}/profile/me`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        profileSlug = data.profile?.profile_slug ?? ''
      }
    } catch { /* ignore */ }

    if (autoStartMatch && matchState === 'idle') {
      onMatchStarted()
      startMatch()
    }
  })

  let matchRetries = $state(0)
  let matchProgress = $state(null)
  const MAX_RETRIES = 2

  async function startMatch(isRetry = false) {
    trackClick(isRetry ? 'retry_match' : 'start_match')
    matchState = 'loading'
    matchError = ''
    matchProgress = null
    if (!isRetry) {
      allMatches = []
      matchIndex = 0
      matchRetries = 0
    }
    try {
      const res = await apiFetch(`${API_BASE_URL}/matching/find`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        if ((res.status === 502 || res.status === 503) && matchRetries < MAX_RETRIES) {
          matchRetries += 1
          await new Promise(r => setTimeout(r, 1500 * matchRetries))
          return startMatch(true)
        }
        matchError = err.detail ?? `Matching failed (${res.status}). Please try again.`
        matchState = 'error'
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(line.slice(6))
              if (currentEvent === 'complete') {
                if (parsed.matched && parsed.matches?.length) {
                  allMatches = parsed.matches.map(m => ({
                    job: m.job,
                    ai: {
                      matched: m.matched,
                      compatibility: m.compatibility,
                      reason: m.reason,
                      strengths: m.strengths,
                      gaps: m.gaps,
                      factor_scores: m.factor_scores,
                    },
                  }))
                  matchIndex = 0
                  matchState = 'matched'
                } else {
                  matchState = 'no-match'
                }
                return
              } else if (currentEvent === 'error') {
                matchError = parsed.detail ?? 'Matching failed. Please try again.'
                matchState = 'error'
                return
              } else if (currentEvent === 'progress') {
                matchProgress = parsed
              }
            } catch { /* ignore malformed data lines */ }
            currentEvent = ''
          } else if (line.trim() === '' || line.startsWith(':')) {
            // blank line or comment/keepalive — reset event type
          }
        }
      }

      if (matchState === 'loading') {
        matchState = 'no-match'
      }
    } catch {
      if (matchRetries < MAX_RETRIES) {
        matchRetries += 1
        await new Promise(r => setTimeout(r, 1500 * matchRetries))
        return startMatch(true)
      }
      matchError = 'Could not reach matching service. Check your connection and try again.'
      matchState = 'error'
    }
  }

  function skipMatch() {
    trackClick('match_skip')
    if (matchIndex + 1 < allMatches.length) {
      matchIndex += 1
    } else {
      matchState = 'no-more'
    }
  }

  function buildMailto() {
    const to = encodeURIComponent(draftTo)
    const subject = encodeURIComponent(draftSubject)
    const body = encodeURIComponent(draftBody)
    return `mailto:${to}?subject=${subject}&body=${body}`
  }

  async function copyDraft() {
    const text = `To: ${draftTo}\nSubject: ${draftSubject}\n\n${draftBody}`
    try {
      await navigator.clipboard.writeText(text)
      copiedEmail = true
      setTimeout(() => (copiedEmail = false), 2000)
    } catch { /* ignore */ }
  }

  async function startDraft() {
    if (!matchedJob) return
    trackClick('match_apply_yes')
    matchState = 'drafting-loading'
    draftError = ''
    copiedEmail = false
    try {
      const res = await apiFetch(`${API_BASE_URL}/matching/draft-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ job_id: matchedJob.id }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        draftError = err.detail ?? `Draft failed (${res.status}).`
        matchState = 'drafting-error'
        return
      }
      const data = await res.json()
      draftTo = data.to || matchedJob.contact_email || ''
      draftSubject = data.subject || ''
      draftBody = data.body || ''
      matchState = 'drafting'
    } catch {
      draftError = 'Could not reach drafting service.'
      matchState = 'drafting-error'
    }
  }

  function salaryLabel(job) {
    if (job.salary_min && job.salary_max) {
      return `${job.salary_currency ?? 'EUR'} ${Math.round(job.salary_min)}–${Math.round(job.salary_max)}/mo`
    }
    return null
  }

  function resetMatch() {
    matchState = 'idle'
    allMatches = []
    matchIndex = 0
    matchError = ''
  }
</script>

<section class="grid gap-4">
  <!-- Header -->
  <header class="relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-4 py-4 sm:px-6 sm:py-5">
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-cyan-400/10 blur-3xl" style="animation: pulseOrb 4.5s ease-in-out infinite;"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-emerald-400/7 blur-2xl" style="animation: pulseOrb 4.5s ease-in-out infinite; animation-delay:-2.3s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex items-start justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Application Engine</p>
        </div>
        <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Match & Apply</h1>
        <p class="mt-1.5 max-w-lg text-sm text-slate-500">
          Find your best job match and apply in one click.
        </p>
      </div>
    </div>
  </header>

  <!-- Two cards: Auto Match + Auto Apply -->
  <div class="grid gap-4 lg:grid-cols-2">

    <!-- Auto Match Card -->
    <article
      class="match-card group relative overflow-hidden rounded-2xl border border-cyan-400/20 bg-gradient-to-br from-sky-950/60 via-indigo-950/50 to-cyan-950/40 p-6"
      class:visible={mounted}
      style="--delay:100ms;"
    >
      <div class="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-cyan-400/12 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite;"></div>
      <div class="relative z-10">
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-300/60">Auto Match</p>
        </div>
        <h2 class="mt-2 text-xl font-black text-white">Find Your Match</h2>
        <p class="mt-1.5 text-sm leading-relaxed text-slate-400">
          AI-powered matching against your crew profile. We'll find the best open position for you.
        </p>

        {#if matchState === 'idle'}
          <button
            type="button"
            onclick={() => { startMatch() }}
            class="mt-5 relative overflow-hidden rounded-lg border border-cyan-300/35 bg-cyan-300/8 px-6 py-3 text-sm font-semibold text-cyan-100 transition-all duration-200 hover:border-cyan-300/55 hover:bg-cyan-300/18 hover:text-white active:scale-95"
          >
            <span class="flex items-center gap-2">
              <span class="h-1.5 w-1.5 rounded-full bg-cyan-400"></span>
              Start Matching
            </span>
          </button>

        {:else if matchState === 'loading'}
          <div class="mt-5 rounded-xl border border-cyan-400/15 bg-black/30 px-5 py-4">
            <div class="flex items-center gap-3">
              <div class="match-spinner h-5 w-5 rounded-full border-2 border-cyan-400/30 border-t-cyan-400"></div>
              <div>
                <p class="text-sm font-semibold text-white">
                  {matchRetries > 0 ? `Retrying... (attempt ${matchRetries + 1})` : 'Matching in progress...'}
                </p>
                <p class="mt-0.5 text-xs text-slate-500">
                  {#if matchProgress && matchProgress.total_jobs > 0}
                    Scanned {matchProgress.jobs_scanned} of {matchProgress.total_jobs} jobs — {matchProgress.matches_so_far} matches so far (batch {matchProgress.batch}/{matchProgress.total_batches})
                  {:else}
                    Analysing your profile against open positions...
                  {/if}
                </p>
              </div>
            </div>
            <div class="mt-3 h-1 overflow-hidden rounded-full bg-white/5">
              {#if matchProgress && matchProgress.total_jobs > 0}
                <div class="h-full rounded-full bg-cyan-400/40 transition-all duration-500" style="width: {Math.round((matchProgress.jobs_scanned / matchProgress.total_jobs) * 100)}%"></div>
              {:else}
                <div class="h-full rounded-full bg-cyan-400/40 match-progress"></div>
              {/if}
            </div>
          </div>

        {:else if matchState === 'matched' && matchedJob}
          <!-- Original Job Posting -->
          <div class="mt-5 rounded-xl border border-white/10 bg-black/30 p-4">
            <div class="flex items-center justify-between gap-3">
              <div class="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 3.75A2.75 2.75 0 018.75 1h2.5A2.75 2.75 0 0114 3.75v.443c.572.055 1.14.122 1.706.2C17.053 4.582 18 5.75 18 7.07v3.469c0 1.126-.694 2.191-1.83 2.54-1.952.6-4.03.93-6.17.93s-4.219-.33-6.17-.93C2.694 12.73 2 11.665 2 10.539V7.07c0-1.321.947-2.489 2.294-2.676A41.047 41.047 0 016 3.993V3.75zm6.5 0v.325a41.622 41.622 0 00-5 0V3.75c0-.69.56-1.25 1.25-1.25h2.5c.69 0 1.25.56 1.25 1.25zM10 10a1 1 0 00-1 1v.01a1 1 0 001 1h.01a1 1 0 001-1V11a1 1 0 00-1-1H10z" clip-rule="evenodd"/><path d="M3 15.055v-.684c.126.053.255.1.39.142 2.092.642 4.313.987 6.61.987 2.297 0 4.518-.345 6.61-.987.135-.041.264-.089.39-.142v.684c0 1.347-.985 2.53-2.363 2.686a41.454 41.454 0 01-9.274 0C3.985 17.585 3 16.402 3 15.055z"/></svg>
                Job Posting
              </div>
              {#if matchedJob.urgent_hire}
                <span class="rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300">Urgent</span>
              {/if}
            </div>

            <h3 class="mt-3 text-lg font-bold text-white">{matchedJob.title}</h3>

            <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-300">
              <span>{matchedJob.role}</span>
              <span class="text-white/15">|</span>
              <span>{matchedJob.yacht}{#if matchedJob.yacht_type} ({matchedJob.yacht_type}{#if matchedJob.yacht_length_m}, {matchedJob.yacht_length_m}m{/if}){/if}</span>
            </div>

            <div class="mt-3 flex flex-wrap gap-2 text-[11px]">
              <span class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-400">{matchedJob.location}</span>
              {#if matchedJob.contract_type}
                <span class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-400">{matchedJob.contract_type}</span>
              {/if}
              {#if matchedJob.season}
                <span class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-400">{matchedJob.season}</span>
              {/if}
              {#if matchedJob.start_date}
                <span class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-400">Start: {matchedJob.start_date}</span>
              {/if}
              {#if salaryLabel(matchedJob)}
                <span class="rounded-full border border-cyan-400/20 bg-cyan-400/5 px-2.5 py-0.5 text-cyan-300">{salaryLabel(matchedJob)}</span>
              {/if}
              {#if matchedJob.experience_required_years}
                <span class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-400">{matchedJob.experience_required_years}+ yrs exp</span>
              {/if}
            </div>

            {#if matchedJob.description}
              <div class="mt-4 border-t border-white/6 pt-3">
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-600">Description</p>
                <p class="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-slate-300">{matchedJob.description}</p>
              </div>
            {/if}

            {#if matchedJob.requirements}
              <div class="mt-3 border-t border-white/6 pt-3">
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-600">Requirements</p>
                <p class="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-slate-400">{matchedJob.requirements}</p>
              </div>
            {/if}

            {#if matchedJob.certifications_required}
              <div class="mt-3 border-t border-white/6 pt-3">
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-600">Certifications Required</p>
                <p class="mt-1.5 text-sm text-slate-400">{matchedJob.certifications_required}</p>
              </div>
            {/if}

            {#if matchedJob.languages_required}
              <div class="mt-3 border-t border-white/6 pt-3">
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-600">Languages</p>
                <p class="mt-1.5 text-sm text-slate-400">{matchedJob.languages_required}</p>
              </div>
            {/if}

            {#if matchedJob.recruiter_name || matchedJob.recruiter_agency}
              <div class="mt-3 border-t border-white/6 pt-3 text-xs text-slate-500">
                {#if matchedJob.recruiter_name}
                  <span>Contact: {matchedJob.recruiter_name}</span>
                {/if}
                {#if matchedJob.recruiter_agency}
                  <span> — {matchedJob.recruiter_agency}</span>
                {/if}
              </div>
            {/if}
          </div>

          <!-- AI Analysis -->
          {#if matchAI}
            <div class="mt-3 rounded-xl border border-cyan-400/15 bg-cyan-400/5 p-4">
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-cyan-300/70">
                  <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor"><path d="M10 1a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 1zM5.05 3.05a.75.75 0 011.06 0l1.062 1.06a.75.75 0 11-1.06 1.061L5.05 4.111a.75.75 0 010-1.06zm9.9 0a.75.75 0 010 1.06l-1.06 1.061a.75.75 0 01-1.061-1.06l1.06-1.061a.75.75 0 011.061 0zM10 7a3 3 0 100 6 3 3 0 000-6zm-6.25 3a.75.75 0 01-.75-.75h-1.5a.75.75 0 010 1.5h1.5A.75.75 0 013.75 10zm14.5 0a.75.75 0 01-.75.75h-1.5a.75.75 0 010-1.5h1.5a.75.75 0 01.75.75zm-12.138 3.879a.75.75 0 011.06 0l1.061 1.06a.75.75 0 01-1.06 1.061l-1.061-1.06a.75.75 0 010-1.061zm8.318 0a.75.75 0 010 1.06l-1.06 1.061a.75.75 0 11-1.061-1.06l1.06-1.061a.75.75 0 011.061 0zM10 15a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 15z"/></svg>
                  AI Analysis
                </div>
                <span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-0.5 text-xs font-bold text-emerald-300">{Math.round(matchAI.compatibility)}% match</span>
              </div>

              {#if matchAI.reason}
                <p class="mt-3 text-sm leading-relaxed text-slate-300">{matchAI.reason}</p>
              {/if}

              {#if matchAI.strengths?.length || matchAI.gaps?.length}
                <div class="mt-3 grid gap-3 sm:grid-cols-2">
                  {#if matchAI.strengths?.length}
                    <div>
                      <p class="text-[10px] font-bold uppercase tracking-wider text-emerald-400/70">Strengths</p>
                      <ul class="mt-1.5 space-y-1">
                        {#each matchAI.strengths as s}
                          <li class="flex items-start gap-1.5 text-xs text-slate-400">
                            <span class="mt-1 h-1 w-1 flex-none rounded-full bg-emerald-400/60"></span>
                            {s}
                          </li>
                        {/each}
                      </ul>
                    </div>
                  {/if}
                  {#if matchAI.gaps?.length}
                    <div>
                      <p class="text-[10px] font-bold uppercase tracking-wider text-amber-400/70">Gaps</p>
                      <ul class="mt-1.5 space-y-1">
                        {#each matchAI.gaps as g}
                          <li class="flex items-start gap-1.5 text-xs text-slate-400">
                            <span class="mt-1 h-1 w-1 flex-none rounded-full bg-amber-400/60"></span>
                            {g}
                          </li>
                        {/each}
                      </ul>
                    </div>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}

          <!-- Actions -->
          <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div class="flex flex-wrap items-center gap-3">
              {#if matchedJob.contact_email}
                <button
                  type="button"
                  onclick={startDraft}
                  class="rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-5 py-2.5 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-300/20 hover:text-white active:scale-95"
                >
                  Apply Now
                </button>
              {:else}
                <span class="rounded-lg border border-white/10 bg-white/5 px-5 py-2.5 text-sm text-slate-500">No contact email listed</span>
              {/if}
              <button
                type="button"
                onclick={skipMatch}
                class="rounded-lg border border-white/10 px-4 py-2.5 text-sm text-slate-400 transition hover:border-cyan-300/30 hover:text-cyan-200 active:scale-95"
              >
                Skip →
              </button>
            </div>
            <span class="text-xs tabular-nums text-slate-600">{matchIndex + 1} / {allMatches.length}</span>
          </div>

        {:else if matchState === 'drafting-loading'}
          <div class="mt-5 rounded-xl border border-cyan-400/15 bg-black/30 px-5 py-4">
            <div class="flex items-center gap-3">
              <div class="match-spinner h-5 w-5 rounded-full border-2 border-cyan-400/30 border-t-cyan-400"></div>
              <div>
                <p class="text-sm font-semibold text-white">Drafting your email...</p>
                <p class="mt-0.5 text-xs text-slate-500">AI is writing a personalised application based on your profile.</p>
              </div>
            </div>
          </div>

        {:else if matchState === 'drafting-error'}
          <div class="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/8 px-5 py-4">
            <p class="text-sm text-rose-300">{draftError}</p>
            <button
              type="button"
              onclick={() => (matchState = 'matched')}
              class="mt-3 rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white"
            >
              Back to Match
            </button>
          </div>

        {:else if matchState === 'drafting'}
          <div class="mt-5 space-y-3">
            <div class="rounded-xl border border-cyan-400/20 bg-black/40 p-4">
              <div class="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-cyan-300/60">
                <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M3 4a2 2 0 00-2 2v1.161l8.441 4.221a1.25 1.25 0 001.118 0L19 7.162V6a2 2 0 00-2-2H3z"/><path d="M19 8.839l-7.77 3.885a2.75 2.75 0 01-2.46 0L1 8.839V14a2 2 0 002 2h14a2 2 0 002-2V8.839z"/></svg>
                AI-Drafted Email
              </div>

              <div class="mt-3 space-y-2 text-sm">
                <div class="flex gap-2">
                  <span class="flex-none font-medium text-slate-500">To:</span>
                  <span class="text-white">{draftTo}</span>
                </div>
                <div class="flex gap-2">
                  <span class="flex-none font-medium text-slate-500">Subject:</span>
                  <span class="text-white">{draftSubject}</span>
                </div>
              </div>

              <div class="mt-3 rounded-lg border border-white/6 bg-white/3 p-3">
                <pre class="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-300">{draftBody}</pre>
              </div>
            </div>

            <div class="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onclick={copyDraft}
                class="flex items-center gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300/8 px-5 py-2.5 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white"
              >
                {#if copiedEmail}
                  <svg class="h-4 w-4 text-emerald-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/></svg>
                  Copied
                {:else}
                  <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z"/><path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z"/></svg>
                  Copy Email
                {/if}
              </button>
              <a
                href={buildMailto()}
                onclick={() => trackClick('match_apply_mailto')}
                class="flex items-center gap-2 rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-5 py-2.5 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-300/20 hover:text-white"
              >
                <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path d="M5.433 13.917l1.262-3.155A4 4 0 017.58 9.42l6.92-6.918a2.121 2.121 0 013 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 01-.65-.65z"/><path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0010 3H4.75A2.75 2.75 0 002 5.75v9.5A2.75 2.75 0 004.75 18h9.5A2.75 2.75 0 0017 15.25V10a.75.75 0 00-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5z"/></svg>
                Open in Email Client
              </a>
              <button
                type="button"
                onclick={() => (matchState = 'matched')}
                class="rounded-lg border border-white/10 px-4 py-2.5 text-sm text-slate-400 transition hover:border-white/20 hover:text-white"
              >
                Back
              </button>
            </div>
          </div>

        {:else if matchState === 'no-more'}
          <div class="mt-5 rounded-xl border border-amber-400/18 bg-black/30 px-5 py-4">
            <p class="text-sm font-semibold text-white">No more matches</p>
            <p class="mt-1 text-xs text-slate-500">You've seen all {allMatches.length} matched positions. Run matching again or update your profile for new results.</p>
            <button
              type="button"
              onclick={resetMatch}
              class="mt-3 rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white"
            >
              Start Over
            </button>
          </div>

        {:else if matchState === 'no-match'}
          <div class="mt-5 rounded-xl border border-amber-400/18 bg-black/30 px-5 py-4">
            <p class="text-sm font-semibold text-white">No matches right now</p>
            <p class="mt-1 text-xs text-slate-500">No open positions closely match your profile at the moment. Check back soon or update your profile.</p>
            <button
              type="button"
              onclick={resetMatch}
              class="mt-3 rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white"
            >
              Try Again
            </button>
          </div>

        {:else if matchState === 'error'}
          <div class="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/8 px-5 py-4">
            <p class="text-sm font-medium text-rose-300">{matchError}</p>
            <div class="mt-3 flex items-center gap-3">
              <button
                type="button"
                onclick={() => { startMatch() }}
                class="rounded-lg border border-cyan-300/30 bg-cyan-300/8 px-5 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white active:scale-95"
              >
                Retry Matching
              </button>
              <button
                type="button"
                onclick={resetMatch}
                class="rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white"
              >
                Cancel
              </button>
            </div>
          </div>
        {/if}
      </div>
    </article>

    <!-- Auto Apply Card — Coming Soon -->
    <article
      class="match-card group relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-6"
      class:visible={mounted}
      style="--delay:200ms;"
    >
      <div class="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-fuchsia-400/8 blur-3xl" style="animation: pulseOrb 4s ease-in-out infinite; animation-delay:-2s;"></div>
      <div class="relative z-10">
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-fuchsia-400/50"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-fuchsia-300/40">Auto Apply</p>
        </div>
        <h2 class="mt-2 text-xl font-black text-white/40">Auto Apply</h2>
        <p class="mt-1.5 text-sm leading-relaxed text-slate-600">
          Automatic applications to matched positions — drafts and sends on your behalf.
        </p>
        <div class="mt-6 flex items-center gap-3 rounded-xl border border-white/6 bg-black/30 px-5 py-4">
          <div class="flex h-9 w-9 flex-none items-center justify-center rounded-lg border border-fuchsia-400/15 bg-fuchsia-400/5">
            <svg class="h-4 w-4 text-fuchsia-300/50" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z" clip-rule="evenodd" />
            </svg>
          </div>
          <div>
            <p class="text-sm font-semibold text-white/60">Coming Soon</p>
            <p class="text-xs text-slate-600">This feature is under development.</p>
          </div>
        </div>
      </div>
    </article>
  </div>
</section>

<style>
  @media (max-width: 768px) {
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
  @keyframes headerScan {
    0%   { top: -1px; opacity: 0; }
    8%   { opacity: 1; }
    92%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }

  .match-card {
    opacity: 0;
    transform: translateY(14px);
    transition: opacity 0.45s ease, transform 0.45s ease;
    transition-delay: var(--delay, 0ms);
  }
  .match-card.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .match-spinner {
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .match-progress {
    animation: progressSlide 25s ease-out forwards;
  }
  @keyframes progressSlide {
    0%   { width: 0%; }
    30%  { width: 40%; }
    60%  { width: 65%; }
    80%  { width: 80%; }
    100% { width: 92%; }
  }

  @keyframes pulseOrb {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.12); }
  }
</style>
