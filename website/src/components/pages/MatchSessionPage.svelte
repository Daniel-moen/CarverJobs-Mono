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
    window.scrollTo({ top: 0, behavior: 'auto' })
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

  function fitTier(compat) {
    if (compat >= 85) return 'strong'
    if (compat >= 65) return 'fair'
    return 'light'
  }
</script>

<section class="ms-root" class:visible={mounted}>

  {#if loading}
    <div class="ms-state">
      <div class="ms-spinner" aria-hidden="true"></div>
      <p class="ms-state-eyebrow">Scanning the fleet</p>
      <p class="ms-state-sub">Loading your match session</p>
    </div>

  {:else if error}
    <div class="ms-state ms-state-error">
      <div class="ms-state-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3L2 21h20L12 3z"/>
          <path d="M12 10v4M12 17.5v.01"/>
        </svg>
      </div>
      <p class="ms-state-eyebrow ms-state-eyebrow-garnet">Could not load</p>
      <p class="ms-state-body">{error}</p>
      <button
        type="button"
        onclick={() => loadSession()}
        class="ms-retry"
      >
        Try again
      </button>
    </div>

  {:else if !matches.length}
    <div class="ms-state">
      <div class="ms-state-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="7"/>
          <path d="M21 21l-4.3-4.3"/>
        </svg>
      </div>
      <p class="ms-state-eyebrow">No matches yet</p>
      <p class="ms-state-body">Run a new match from WhatsApp or the home page.</p>
    </div>

  {:else}
    <header class="ms-head">
      <p class="ms-head-eyebrow">
        <span class="ms-head-pip" aria-hidden="true"></span>
        Match session
        {#if session?.id}· <span class="ms-head-id">#{session.id}</span>{/if}
      </p>
      <h1 class="ms-head-title">
        <span class="ms-head-num">{matches.length}</span>
        <span class="ms-head-num-label">match{matches.length !== 1 ? 'es' : ''} found</span>
      </h1>
      <p class="ms-head-meta">
        Scanned <span class="ms-head-metric">{session?.total_jobs_scanned ?? 0}</span> positions
        {#if session?.created_at}
          <span class="ms-dot" aria-hidden="true">·</span>
          {formatDate(session.created_at)}
        {/if}
      </p>
    </header>

    <ol class="ms-list">
      {#each matches as m, i (m.job?.id ?? i)}
        {@const job = m.job}
        {@const compat = Math.round(m.compatibility ?? 0)}
        {@const tier = fitTier(compat)}
        <li>
          <article class="ms-card" data-tier={tier}>
            <div class="ms-card-top">
              <div class="ms-card-headline">
                <p class="ms-card-eyebrow">
                  {#if job.role}<span>{job.role}</span>{/if}
                  {#if job.role && job.yacht}<span class="ms-card-eyebrow-dot">·</span>{/if}
                  {#if job.yacht}<span>{job.yacht}</span>{/if}
                </p>
                <h3 class="ms-card-title">{job.title}</h3>
              </div>

              <div class="ms-fit" aria-label="Compatibility {compat}%">
                <span class="ms-fit-num">{compat}</span>
                <span class="ms-fit-pct">%</span>
                <span class="ms-fit-label">fit</span>
              </div>
            </div>

            <div class="ms-chips">
              {#if job.location}
                <span class="ms-chip">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.4-7-12a7 7 0 1 1 14 0c0 5.6-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/></svg>
                  {job.location}
                </span>
              {/if}
              {#if job.contract_type}
                <span class="ms-chip">{job.contract_type}</span>
              {/if}
              {#if job.start_date}
                <span class="ms-chip"><span class="ms-chip-label">Start</span> {job.start_date}</span>
              {/if}
              {#if salaryLabel(job)}
                <span class="ms-chip ms-chip-salary">{salaryLabel(job)}</span>
              {/if}
              {#if job.urgent_hire}
                <span class="ms-chip ms-chip-urgent">Urgent</span>
              {/if}
            </div>

            {#if m.reason}
              <p class="ms-reason">{m.reason}</p>
            {/if}

            {#if m.strengths?.length || m.gaps?.length}
              <div class="ms-signals">
                {#if m.strengths?.length}
                  <div class="ms-signal ms-signal-plus">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>
                    {#each m.strengths.slice(0, 3) as s}
                      <span class="ms-signal-tok">{s}</span>
                    {/each}
                  </div>
                {/if}
                {#if m.gaps?.length}
                  <div class="ms-signal ms-signal-minus">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                    {#each m.gaps.slice(0, 2) as g}
                      <span class="ms-signal-tok">{g}</span>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}

            <div class="ms-actions">
              <button
                type="button"
                onclick={() => draftEmail(job)}
                class="ms-btn-primary"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v14H4z"/><path d="M4 7l8 6 8-6"/></svg>
                Draft email
              </button>
              {#if job.application_url}
                <a
                  href={job.application_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="ms-btn-ghost"
                >
                  View listing
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4L10 14"/><path d="M20 14v6H4V4h6"/></svg>
                </a>
              {/if}
            </div>
          </article>
        </li>
      {/each}
    </ol>
  {/if}
</section>

{#if draftingJob}
  <div
    class="ms-modal"
    onclick={(e) => { if (e.target === e.currentTarget) closeDraft() }}
    onkeydown={(e) => { if (e.key === 'Escape') closeDraft() }}
    role="dialog"
    aria-modal="true"
    tabindex="-1"
  >
    <div class="ms-modal-panel">
      <header class="ms-modal-head">
        <div class="ms-modal-headline">
          <p class="ms-modal-eyebrow">Draft email</p>
          <h2 class="ms-modal-title">
            {draftingJob.title ?? draftingJob.role}{draftingJob.yacht ? ` — ${draftingJob.yacht}` : ''}
          </h2>
        </div>
        <button
          type="button"
          onclick={closeDraft}
          class="ms-modal-close"
          aria-label="Close"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>
      </header>

      <div class="ms-modal-body">
        {#if draftLoading && !draftBody}
          <div class="ms-modal-loading">
            <div class="ms-spinner" aria-hidden="true"></div>
            <p class="ms-state-eyebrow">Composing</p>
            <p class="ms-state-sub">AI is drafting your email</p>
          </div>
        {:else}
          <label class="ms-field">
            <span class="ms-field-label">To</span>
            <input
              type="email"
              bind:value={draftTo}
              placeholder="recruiter@example.com"
              class="ms-input"
            />
          </label>

          <label class="ms-field">
            <span class="ms-field-label">Subject</span>
            <input
              type="text"
              bind:value={draftSubject}
              class="ms-input"
            />
          </label>

          <label class="ms-field">
            <span class="ms-field-label">Message</span>
            <textarea
              bind:value={draftBody}
              rows="6"
              class="ms-input ms-textarea"
            ></textarea>
          </label>

          <div class="ms-field ms-field-reprompt">
            <span class="ms-field-label ms-field-label-ai">Adjust with AI</span>
            <div class="ms-reprompt-row">
              <input
                type="text"
                bind:value={draftPrompt}
                placeholder="e.g. make it more casual, mention my STCW cert..."
                onkeydown={(e) => { if (e.key === 'Enter' && !draftLoading) repromptDraft() }}
                class="ms-input ms-input-ai"
              />
              <button
                type="button"
                onclick={repromptDraft}
                disabled={draftLoading || !draftPrompt.trim()}
                class="ms-btn-ai"
              >
                {draftLoading ? 'Rewriting' : 'Rewrite'}
              </button>
            </div>
          </div>

          {#if draftError}
            <p class="ms-modal-error">{draftError}</p>
          {/if}
        {/if}
      </div>

      {#if draftBody}
        <footer class="ms-modal-foot">
          <button
            type="button"
            onclick={() => { window.open(buildMailto(), '_self'); trackClick('match_session_mailto') }}
            class="ms-btn-send"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11l18-8-8 18-2-8z"/></svg>
            Open in mail app
          </button>
          <button
            type="button"
            onclick={copyDraft}
            class="ms-btn-copy"
          >
            {copiedEmail ? 'Copied' : 'Copy to clipboard'}
          </button>
          <button
            type="button"
            onclick={closeDraft}
            class="ms-btn-cancel"
          >
            Cancel
          </button>
        </footer>
      {/if}
    </div>
  </div>
{/if}

<style>
  .ms-root {
    display: grid;
    gap: 1.25rem;
    opacity: 0;
    transform: translateY(14px);
    transition:
      opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
      transform 0.45s cubic-bezier(0.22, 1, 0.36, 1);
    overflow: hidden;
  }
  .ms-root.visible { opacity: 1; transform: translateY(0); }

  @media (prefers-reduced-motion: reduce) {
    .ms-root { opacity: 1 !important; transform: none !important; transition: none !important; }
  }

  /* ── States (loading / error / empty) ──────────────────────────── */
  .ms-state {
    padding: 3rem 1.5rem;
    border-radius: 1rem;
    border: 1px solid rgba(201, 169, 110, 0.18);
    background:
      radial-gradient(80% 60% at 50% 0%, rgba(201, 169, 110, 0.05), transparent 70%),
      linear-gradient(180deg, #0a1015 0%, #050a0e 100%);
    text-align: center;
  }
  .ms-state-error { border-color: rgba(190, 120, 100, 0.32); }
  .ms-state-icon {
    width: 40px;
    height: 40px;
    margin: 0 auto 1rem;
    color: var(--brass);
    opacity: 0.8;
  }
  .ms-state-eyebrow {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.32em;
    text-transform: uppercase;
    color: var(--brass);
  }
  .ms-state-eyebrow-garnet { color: #e09286; }
  .ms-state-sub,
  .ms-state-body {
    margin: 0.65rem 0 0;
    font-size: 13.5px;
    color: var(--text-secondary);
    line-height: 1.55;
  }
  .ms-retry {
    margin-top: 1.25rem;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.65rem 1.1rem;
    border-radius: 9999px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--ivory);
    background: rgba(243, 234, 216, 0.05);
    border: 1px solid rgba(243, 234, 216, 0.18);
    cursor: pointer;
    transition: background 0.18s ease, border-color 0.18s ease;
    min-height: 44px;
  }
  .ms-retry:hover {
    background: rgba(243, 234, 216, 0.1);
    border-color: rgba(243, 234, 216, 0.35);
  }

  /* Brass spinner */
  .ms-spinner {
    width: 32px;
    height: 32px;
    margin: 0 auto 1rem;
    border-radius: 9999px;
    border: 2px solid rgba(201, 169, 110, 0.2);
    border-top-color: var(--brass-bright);
    animation: msSpin 0.9s linear infinite;
  }
  @keyframes msSpin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .ms-spinner { animation: none; border-top-color: rgba(201, 169, 110, 0.2); }
  }

  /* ── Header strip ─────────────────────────────────────────────── */
  .ms-head {
    padding: 0.25rem 0.25rem 1.1rem;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.22);
  }
  .ms-head-eyebrow {
    margin: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
  }
  .ms-head-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--radium);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.18);
  }
  .ms-head-id {
    color: var(--text-muted);
    letter-spacing: 0.18em;
  }
  .ms-head-title {
    margin: 0.75rem 0 0;
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    flex-wrap: wrap;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    color: var(--ivory);
    letter-spacing: -0.025em;
    line-height: 1;
  }
  .ms-head-num {
    font-size: clamp(2.75rem, 8vw, 4.25rem);
    color: var(--brass-bright);
    text-shadow: 0 0 28px rgba(201, 169, 110, 0.28);
    font-variant-numeric: tabular-nums;
  }
  .ms-head-num-label {
    font-size: clamp(1.1rem, 2.6vw, 1.6rem);
    color: var(--ivory);
  }
  .ms-head-meta {
    margin: 0.8rem 0 0;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--text-muted);
  }
  .ms-head-metric {
    color: var(--ivory);
    font-variant-numeric: tabular-nums;
  }
  .ms-dot { margin: 0 0.4rem; opacity: 0.5; }

  /* ── Match list ────────────────────────────────────────────────── */
  .ms-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.9rem;
  }
  .ms-list > li { animation: msCardIn 0.5s cubic-bezier(0.22, 1, 0.36, 1) both; }
  .ms-list > li:nth-child(1) { animation-delay: 40ms; }
  .ms-list > li:nth-child(2) { animation-delay: 90ms; }
  .ms-list > li:nth-child(3) { animation-delay: 140ms; }
  .ms-list > li:nth-child(4) { animation-delay: 190ms; }
  .ms-list > li:nth-child(n+5) { animation-delay: 240ms; }
  @keyframes msCardIn {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .ms-list > li { animation: none; }
  }

  .ms-card {
    position: relative;
    padding: 1.25rem 1.1rem 1.1rem;
    border-radius: 0.85rem;
    border: 1px solid rgba(201, 169, 110, 0.18);
    background:
      radial-gradient(120% 80% at 100% 0%, rgba(201, 169, 110, 0.045), transparent 60%),
      linear-gradient(180deg, #0a1015 0%, #060a0f 100%);
    box-shadow:
      inset 0 1px 0 rgba(201, 169, 110, 0.06),
      0 20px 50px -40px rgba(0, 0, 0, 0.6);
    transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  }
  .ms-card:hover {
    border-color: rgba(201, 169, 110, 0.32);
    transform: translateY(-1px);
  }
  @media (min-width: 640px) { .ms-card { padding: 1.5rem 1.4rem 1.25rem; } }

  .ms-card-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
  }
  .ms-card-headline { min-width: 0; flex: 1; }
  .ms-card-eyebrow {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--brass);
    display: flex;
    flex-wrap: wrap;
    gap: 0 0.5rem;
  }
  .ms-card-eyebrow-dot { opacity: 0.5; }
  .ms-card-title {
    margin: 0.45rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 400;
    font-size: clamp(1.15rem, 3.5vw, 1.45rem);
    line-height: 1.2;
    letter-spacing: -0.018em;
    color: var(--ivory);
    overflow-wrap: anywhere;
  }

  /* Fit score — the hero element */
  .ms-fit {
    flex: none;
    display: grid;
    grid-template-columns: auto auto;
    align-items: baseline;
    justify-items: end;
    gap: 0 0.1rem;
    padding: 0.25rem 0.55rem 0.35rem 0.7rem;
    border-left: 1px dashed rgba(201, 169, 110, 0.28);
    min-width: 72px;
  }
  .ms-fit-num {
    grid-column: 1 / 2;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 300;
    font-size: clamp(2.4rem, 7vw, 3.25rem);
    line-height: 0.95;
    letter-spacing: -0.03em;
    color: var(--brass-bright);
    text-shadow: 0 0 22px rgba(201, 169, 110, 0.3);
    font-variant-numeric: tabular-nums;
  }
  .ms-fit-pct {
    grid-column: 2 / 3;
    align-self: flex-end;
    padding-bottom: 0.3rem;
    font-family: var(--font-serif);
    font-weight: 300;
    font-size: 1rem;
    color: var(--brass);
    opacity: 0.7;
  }
  .ms-fit-label {
    grid-column: 1 / 3;
    margin-top: 0.15rem;
    font-family: var(--font-mono);
    font-size: 9px;
    letter-spacing: 0.32em;
    text-transform: uppercase;
    color: var(--brass);
    opacity: 0.7;
  }

  .ms-card[data-tier="fair"] .ms-fit-num {
    color: var(--ivory);
    text-shadow: 0 0 22px rgba(243, 234, 216, 0.2);
  }
  .ms-card[data-tier="fair"] .ms-fit-pct,
  .ms-card[data-tier="fair"] .ms-fit-label { color: var(--ivory-soft); }

  .ms-card[data-tier="light"] .ms-fit-num {
    color: var(--text-secondary);
    text-shadow: none;
  }
  .ms-card[data-tier="light"] .ms-fit-pct,
  .ms-card[data-tier="light"] .ms-fit-label { color: var(--text-muted); }

  /* Chips */
  .ms-chips {
    margin-top: 0.9rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .ms-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.3rem 0.6rem;
    border-radius: 9999px;
    font-size: 11.5px;
    color: var(--text-secondary);
    background: rgba(243, 234, 216, 0.03);
    border: 1px solid rgba(201, 169, 110, 0.16);
  }
  .ms-chip svg { width: 11px; height: 11px; opacity: 0.7; }
  .ms-chip-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--brass);
    opacity: 0.75;
    margin-right: 0.15rem;
  }
  .ms-chip-salary {
    color: var(--radium);
    background: rgba(141, 240, 196, 0.05);
    border-color: rgba(141, 240, 196, 0.22);
  }
  .ms-chip-urgent {
    color: #ecb4a7;
    background: rgba(190, 90, 70, 0.08);
    border-color: rgba(190, 90, 70, 0.35);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
  }

  /* Reason */
  .ms-reason {
    margin: 0.9rem 0 0;
    font-size: 13.5px;
    line-height: 1.6;
    color: var(--text-secondary);
    overflow-wrap: anywhere;
  }

  /* Strengths / gaps */
  .ms-signals {
    margin-top: 0.85rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.2rem;
  }
  .ms-signal {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .ms-signal svg { width: 11px; height: 11px; }
  .ms-signal-plus { color: var(--radium); }
  .ms-signal-minus { color: var(--brass); }
  .ms-signal-tok {
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.08em;
    text-transform: lowercase;
    color: var(--text-muted);
  }

  /* Actions */
  .ms-actions {
    margin-top: 1rem;
    padding-top: 0.9rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.16);
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
  }
  .ms-btn-primary {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.7rem 1.1rem;
    border-radius: 9999px;
    font-size: 12.5px;
    font-weight: 600;
    color: #06090d;
    background: linear-gradient(180deg, #fbf3df 0%, #ead7a7 100%);
    border: 1px solid rgba(216, 198, 154, 0.55);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.55) inset,
      0 12px 30px -18px rgba(216, 198, 154, 0.4);
    cursor: pointer;
    transition: transform 0.2s ease, filter 0.2s ease;
    min-height: 44px;
  }
  .ms-btn-primary:hover { filter: brightness(1.04); transform: translateY(-1px); }
  .ms-btn-primary svg { width: 13px; height: 13px; }

  .ms-btn-ghost {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.7rem 1rem;
    border-radius: 9999px;
    font-size: 12.5px;
    color: var(--text-secondary);
    background: transparent;
    border: 1px solid rgba(243, 234, 216, 0.14);
    text-decoration: none;
    transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
    min-height: 44px;
  }
  .ms-btn-ghost:hover {
    color: var(--ivory);
    border-color: rgba(243, 234, 216, 0.32);
    background: rgba(243, 234, 216, 0.04);
  }
  .ms-btn-ghost svg { width: 11px; height: 11px; opacity: 0.7; }

  /* ── Draft modal ───────────────────────────────────────────────── */
  .ms-modal {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 1rem;
    overflow-y: auto;
    overscroll-behavior: contain;
    background: rgba(4, 7, 11, 0.78);
    backdrop-filter: blur(8px);
  }
  @media (min-width: 640px) { .ms-modal { align-items: center; } }

  .ms-modal-panel {
    position: relative;
    width: 100%;
    max-width: 640px;
    margin: 1rem 0;
    border-radius: 1rem;
    border: 1px solid rgba(201, 169, 110, 0.22);
    background:
      radial-gradient(120% 80% at 0% 0%, rgba(201, 169, 110, 0.06), transparent 60%),
      linear-gradient(180deg, #0a1015 0%, #050a0e 100%);
    box-shadow:
      inset 0 1px 0 rgba(201, 169, 110, 0.08),
      0 40px 120px -40px rgba(0, 0, 0, 0.8);
    display: flex;
    flex-direction: column;
    max-height: 92dvh;
    animation: msPanelIn 0.28s cubic-bezier(0.22, 1, 0.36, 1) both;
  }
  @media (min-width: 640px) { .ms-modal-panel { max-height: 85vh; margin: 0; } }
  @keyframes msPanelIn {
    from { opacity: 0; transform: translateY(18px) scale(0.98); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
  @media (prefers-reduced-motion: reduce) {
    .ms-modal-panel { animation: none; }
  }

  .ms-modal-head {
    flex: none;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    padding: 1.15rem 1.25rem;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.22);
  }
  @media (min-width: 640px) { .ms-modal-head { padding: 1.25rem 1.5rem; } }

  .ms-modal-headline { min-width: 0; }
  .ms-modal-eyebrow {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
  }
  .ms-modal-title {
    margin: 0.45rem 0 0;
    font-family: var(--font-serif);
    font-optical-sizing: auto;
    font-variation-settings: "SOFT" 100, "opsz" 144;
    font-weight: 400;
    font-size: 1.2rem;
    line-height: 1.25;
    letter-spacing: -0.015em;
    color: var(--ivory);
    overflow-wrap: anywhere;
  }

  .ms-modal-close {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: 9999px;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid rgba(243, 234, 216, 0.14);
    cursor: pointer;
    transition: color 0.18s ease, border-color 0.18s ease;
  }
  .ms-modal-close:hover { color: var(--ivory); border-color: rgba(243, 234, 216, 0.32); }
  .ms-modal-close svg { width: 14px; height: 14px; }

  .ms-modal-body {
    flex: 1;
    overflow-y: auto;
    display: grid;
    gap: 1rem;
    padding: 1.25rem;
  }
  @media (min-width: 640px) { .ms-modal-body { padding: 1.5rem; } }

  .ms-modal-loading {
    text-align: center;
    padding: 2.5rem 1rem;
  }

  .ms-field {
    display: grid;
    gap: 0.35rem;
  }
  .ms-field-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--brass);
  }
  .ms-field-label-ai { color: var(--radium); }

  .ms-input {
    width: 100%;
    padding: 0.7rem 0.85rem;
    border-radius: 0.55rem;
    font-size: 13.5px;
    color: var(--ivory);
    background: rgba(4, 7, 11, 0.6);
    border: 1px solid rgba(201, 169, 110, 0.18);
    outline: none;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
    font-family: var(--font-sans);
  }
  .ms-input::placeholder { color: var(--text-muted); }
  .ms-input:focus {
    border-color: rgba(201, 169, 110, 0.55);
    box-shadow: 0 0 0 3px rgba(201, 169, 110, 0.12);
  }
  .ms-textarea {
    min-height: 140px;
    resize: vertical;
    line-height: 1.55;
  }

  .ms-input-ai:focus {
    border-color: rgba(141, 240, 196, 0.5);
    box-shadow: 0 0 0 3px rgba(141, 240, 196, 0.14);
  }

  .ms-reprompt-row {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  @media (min-width: 520px) {
    .ms-reprompt-row { flex-direction: row; }
    .ms-input-ai { flex: 1; }
  }

  .ms-btn-ai {
    padding: 0.7rem 1.1rem;
    border-radius: 0.55rem;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--radium);
    background: rgba(141, 240, 196, 0.06);
    border: 1px solid rgba(141, 240, 196, 0.3);
    cursor: pointer;
    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
    min-height: 44px;
  }
  .ms-btn-ai:hover:not(:disabled) {
    background: rgba(141, 240, 196, 0.14);
    color: var(--ivory);
    border-color: rgba(141, 240, 196, 0.5);
  }
  .ms-btn-ai:disabled { opacity: 0.4; cursor: not-allowed; }

  .ms-modal-error {
    margin: 0;
    padding: 0.7rem 0.85rem;
    border-radius: 0.55rem;
    font-size: 13px;
    color: #ecb4a7;
    background: rgba(190, 90, 70, 0.08);
    border: 1px solid rgba(190, 90, 70, 0.3);
  }

  .ms-modal-foot {
    flex: none;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.55rem;
    padding: 1rem 1.25rem;
    border-top: 1px dashed rgba(201, 169, 110, 0.22);
  }
  @media (min-width: 640px) {
    .ms-modal-foot {
      grid-template-columns: auto 1fr auto;
      padding: 1rem 1.5rem;
    }
  }

  .ms-btn-send {
    grid-column: 1 / -1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    padding: 0.8rem 1.2rem;
    border-radius: 9999px;
    font-size: 13px;
    font-weight: 600;
    color: #06090d;
    background: linear-gradient(180deg, #fbf3df 0%, #ead7a7 100%);
    border: 1px solid rgba(216, 198, 154, 0.55);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.55) inset,
      0 12px 30px -18px rgba(216, 198, 154, 0.4);
    cursor: pointer;
    transition: transform 0.2s ease, filter 0.2s ease;
    min-height: 44px;
  }
  @media (min-width: 640px) {
    .ms-btn-send { grid-column: 1 / 2; }
  }
  .ms-btn-send:hover { filter: brightness(1.04); transform: translateY(-1px); }
  .ms-btn-send svg { width: 13px; height: 13px; }

  .ms-btn-copy {
    padding: 0.75rem 1rem;
    border-radius: 9999px;
    font-size: 12.5px;
    color: var(--ivory);
    background: rgba(243, 234, 216, 0.04);
    border: 1px solid rgba(243, 234, 216, 0.14);
    cursor: pointer;
    transition: background 0.18s ease, border-color 0.18s ease;
    min-height: 44px;
  }
  .ms-btn-copy:hover {
    background: rgba(243, 234, 216, 0.1);
    border-color: rgba(243, 234, 216, 0.32);
  }

  .ms-btn-cancel {
    padding: 0.75rem 1rem;
    border-radius: 9999px;
    font-size: 12.5px;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid transparent;
    cursor: pointer;
    transition: color 0.18s ease;
    min-height: 44px;
  }
  .ms-btn-cancel:hover { color: var(--ivory); }
</style>
