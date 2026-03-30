<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick } from '../../config/analytics'

  let { isSubscribed = false, onNavigate = () => {}, autoStartMatch = false, onMatchStarted = () => {} } = $props()

  let mounted = $state(false)
  let state = $state('idle')
  let error = $state('')
  let matches = $state([])
  let totalScanned = $state(0)
  let retries = $state(0)

  let draftingJobId = $state(null)
  let draftTo = $state('')
  let draftSubject = $state('')
  let draftBody = $state('')
  let copiedEmail = $state(false)

  const MAX_RETRIES = 2

  onMount(async () => {
    requestAnimationFrame(() => (mounted = true))
    if (autoStartMatch && state === 'idle') {
      onMatchStarted()
      runMatch()
    }
  })

  async function runMatch(isRetry = false) {
    trackClick(isRetry ? 'retry_match' : 'start_match')
    state = 'loading'
    error = ''
    if (!isRetry) {
      matches = []
      totalScanned = 0
      retries = 0
    }

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
              if (parsed.matched && parsed.matches?.length) {
                matches = parsed.matches
                state = 'done'
              } else {
                state = 'no-match'
              }
            } else if (currentEvent === 'error') {
              error = parsed.detail ?? 'Matching failed.'
              state = 'error'
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
      }
    } catch {
      if (retries < MAX_RETRIES) {
        retries += 1
        await new Promise(r => setTimeout(r, 1500 * retries))
        return runMatch(true)
      }
      error = 'Could not reach matching service. Check your connection and try again.'
      state = 'error'
    }
  }

  async function draftEmail(job) {
    draftingJobId = job.id
    draftTo = ''
    draftSubject = ''
    draftBody = ''
    copiedEmail = false
    try {
      const res = await apiFetch(`${API_BASE_URL}/matching/draft-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ job_id: job.id }),
      })
      if (!res.ok) {
        draftingJobId = null
        return
      }
      const data = await res.json()
      draftTo = data.to || job.contact_email || ''
      draftSubject = data.subject || ''
      draftBody = data.body || ''
    } catch {
      draftingJobId = null
    }
  }

  function closeDraft() {
    draftingJobId = null
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
</script>

<section class="grid gap-5" class:visible={mounted}>

  {#if state === 'idle'}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:p-8 text-center">
      <h1 class="text-2xl font-black tracking-tight text-white sm:text-3xl">Find Your Matches</h1>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-400">
        AI scans every open position against your crew profile and returns all matches.
      </p>
      <button
        type="button"
        onclick={() => runMatch()}
        class="mt-6 rounded-lg border border-cyan-300/35 bg-cyan-300/8 px-8 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/55 hover:bg-cyan-300/18 hover:text-white active:scale-95"
      >
        Start Matching
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
      <div class="mt-4 flex justify-center gap-3">
        <button
          type="button"
          onclick={() => runMatch()}
          class="rounded-lg border border-cyan-300/30 bg-cyan-300/8 px-5 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/18 hover:text-white active:scale-95"
        >
          Retry
        </button>
        <button
          type="button"
          onclick={() => { state = 'idle'; matches = []; error = '' }}
          class="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-400 transition hover:text-white"
        >
          Cancel
        </button>
      </div>
    </div>

  {:else if state === 'no-match'}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-6 sm:p-8 text-center">
      <p class="text-sm font-semibold text-white">No matches right now</p>
      <p class="mt-1 text-xs text-slate-500">No open positions closely match your profile. Check back soon or update your profile.</p>
      <button
        type="button"
        onclick={() => { state = 'idle'; matches = [] }}
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
      </div>
      <button
        type="button"
        onclick={() => { state = 'idle'; matches = [] }}
        class="rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:text-white"
      >
        Run Again
      </button>
    </div>

    {#each matches as m, i (m.job?.id ?? i)}
      {@const job = m.job}
      {@const compat = Math.round(m.compatibility ?? 0)}
      <article class="rounded-xl border border-white/8 bg-zinc-950 p-4 sm:p-5">
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
          <p class="mt-2.5 text-sm leading-relaxed text-slate-400">{m.reason}</p>
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
          {#if draftingJobId === job.id && draftBody}
            <div class="space-y-2.5">
              <div class="rounded-lg border border-white/8 bg-black/40 p-3 text-sm">
                <div class="flex gap-2 text-xs text-slate-500"><span class="font-medium">To:</span><span class="text-white">{draftTo}</span></div>
                <div class="mt-1 flex gap-2 text-xs text-slate-500"><span class="font-medium">Subject:</span><span class="text-white">{draftSubject}</span></div>
                <pre class="mt-2 whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-slate-300">{draftBody}</pre>
              </div>
              <div class="flex flex-wrap gap-2">
                <button onclick={copyDraft} class="rounded-md border border-cyan-300/25 bg-cyan-300/8 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-300/18">
                  {copiedEmail ? 'Copied!' : 'Copy'}
                </button>
                <a
                  href={buildMailto()}
                  onclick={() => trackClick('match_apply_mailto')}
                  class="rounded-md border border-emerald-300/30 bg-emerald-300/10 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-300/20"
                >
                  Open in Email
                </a>
                <button onclick={closeDraft} class="rounded-md border border-white/10 px-3 py-1.5 text-xs text-slate-500 transition hover:text-white">
                  Close
                </button>
              </div>
            </div>
          {:else if draftingJobId === job.id && !draftBody}
            <div class="flex items-center gap-2">
              <div class="h-4 w-4 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 spinner"></div>
              <span class="text-xs text-slate-500">Drafting email...</span>
            </div>
          {:else}
            <div class="flex flex-wrap items-center gap-2">
              {#if job.contact_email}
                <button
                  onclick={() => draftEmail(job)}
                  class="rounded-md border border-emerald-300/30 bg-emerald-300/10 px-4 py-1.5 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-300/20 hover:text-white active:scale-95"
                >
                  Apply
                </button>
              {:else}
                <span class="text-xs text-slate-600">No contact email</span>
              {/if}
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
          {/if}
        </div>
      </article>
    {/each}
  {/if}
</section>

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
</style>
