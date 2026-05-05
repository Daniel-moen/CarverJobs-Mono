<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { forceOpen = false, source = 'website_popup', onRewarded = () => {}, onClose = () => {} } = $props()

  const DISMISS_KEY = 'carver_feedback_prompt_dismissed'
  const SUBMITTED_KEY = 'carver_feedback_submitted'

  let visible = $state(false)
  let checkedStatus = $state(false)
  let submitted = $state(false)
  let submitting = $state(false)
  let error = $state('')
  let rewardMessage = $state('')
  let rating = $state(5)
  let liked = $state('')
  let improved = $state('')
  let confusing = $state('')
  let recommend = $state('maybe')
  let anythingElse = $state('')

  function dismissedLocally() {
    try { return localStorage.getItem(DISMISS_KEY) === 'true' } catch { return false }
  }

  function markDismissed() {
    try { localStorage.setItem(DISMISS_KEY, 'true') } catch { /* ignore */ }
  }

  function markSubmitted() {
    try { localStorage.setItem(SUBMITTED_KEY, 'true') } catch { /* ignore */ }
  }

  function closePrompt() {
    visible = false
    onClose()
  }

  function dismissPrompt() {
    markDismissed()
    closePrompt()
  }

  async function loadStatus() {
    let statusData = null
    try {
      const res = await apiFetch(`${API_BASE_URL}/feedback/status?source=${encodeURIComponent(source)}`, {
        method: 'GET',
        credentials: 'include',
      })
      statusData = await res.json().catch(() => ({}))
      if (res.ok && (!statusData.eligible || statusData.submitted)) {
        submitted = true
        if (statusData.submitted) markSubmitted()
        visible = false
        checkedStatus = true
        return
      }
    } catch {
      checkedStatus = true
      return
    }
    checkedStatus = true
    if (forceOpen || statusData?.force_prompt || !dismissedLocally()) {
      window.setTimeout(() => {
        if (!submitted) visible = true
      }, forceOpen ? 250 : 45000)
    }
  }

  async function submitFeedback() {
    submitting = true
    error = ''
    rewardMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/feedback/submit`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source,
          rating,
          liked,
          improved,
          confusing,
          recommend,
          anything_else: anythingElse,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        error = data.detail || 'Could not submit feedback. Please try again.'
        return
      }
      submitted = true
      markSubmitted()
      if (data.reward_granted) {
        rewardMessage = `Thanks — ${data.reward_amount ?? 5} tokens have been added to your account.`
      } else {
        rewardMessage = 'Thanks — your feedback has already been recorded for this reward.'
      }
      if (data.credits_balance != null) onRewarded(data.credits_balance)
    } catch {
      error = 'Could not reach the server. Please try again.'
    } finally {
      submitting = false
    }
  }

  onMount(loadStatus)
</script>

{#if visible && checkedStatus}
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-black/50 px-4 py-4 backdrop-blur-sm sm:items-center sm:py-8" role="dialog" aria-modal="true" aria-labelledby="feedback-title">
    <section class="w-full max-w-lg rounded-2xl border border-white/[0.1] bg-[#080c12]/95 p-5 shadow-[0_30px_120px_-35px_rgba(34,211,238,0.28)] sm:p-6">
      {#if submitted}
        <div class="text-center">
          <div class="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-emerald-300/30 bg-emerald-300/10 text-emerald-200">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
          </div>
          <h2 class="mt-4 font-display text-2xl text-white">Feedback received</h2>
          <p class="mt-2 text-sm leading-relaxed text-slate-300">{rewardMessage}</p>
          <button
            type="button"
            class="mt-5 rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/60 hover:bg-cyan-300/15"
            onclick={closePrompt}
          >
            Close
          </button>
        </div>
      {:else}
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="font-mono text-[10px] uppercase tracking-[0.28em] text-cyan-300/80">5 token reward</p>
            <h2 id="feedback-title" class="mt-2 font-display text-2xl text-white">Help us improve CARVER</h2>
            <p class="mt-2 text-sm leading-relaxed text-slate-400">
              Share quick feedback about your experience and we’ll reward you with 5 tokens.
            </p>
          </div>
          <button
            type="button"
            class="rounded-full border border-white/10 px-2 py-1 text-xs text-slate-400 transition hover:border-white/25 hover:text-white"
            aria-label="Close feedback prompt"
            onclick={dismissPrompt}
          >
            ✕
          </button>
        </div>

        <form class="mt-5 grid gap-4" onsubmit={(event) => { event.preventDefault(); submitFeedback() }}>
          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Overall experience</span>
            <select
              bind:value={rating}
              class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
            >
              <option value={5}>5 — Excellent</option>
              <option value={4}>4 — Good</option>
              <option value={3}>3 — Okay</option>
              <option value={2}>2 — Poor</option>
              <option value={1}>1 — Very poor</option>
            </select>
          </label>

          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">What did you like?</span>
            <textarea bind:value={liked} rows="2" maxlength="1500" class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20" placeholder="What worked well?"></textarea>
          </label>

          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">What could be improved?</span>
            <textarea bind:value={improved} rows="2" maxlength="1500" class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20" placeholder="What should we change next?"></textarea>
          </label>

          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Did anything confuse or frustrate you?</span>
            <textarea bind:value={confusing} rows="2" maxlength="1500" class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20" placeholder="Optional"></textarea>
          </label>

          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Would you recommend CARVER?</span>
            <select
              bind:value={recommend}
              class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
            >
              <option value="yes">Yes</option>
              <option value="maybe">Maybe</option>
              <option value="no">No</option>
            </select>
          </label>

          <label class="grid gap-1.5">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Anything else?</span>
            <textarea bind:value={anythingElse} rows="2" maxlength="1500" class="rounded-lg border border-white/[0.1] bg-[#04070b] px-3.5 py-2.5 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20" placeholder="Optional"></textarea>
          </label>

          {#if error}
            <p class="rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-sm text-rose-200">{error}</p>
          {/if}

          <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              class="rounded-lg border border-white/10 px-4 py-2 text-sm font-medium text-slate-400 transition hover:border-white/25 hover:text-white"
              onclick={dismissPrompt}
            >
              Maybe later
            </button>
            <button
              type="submit"
              disabled={submitting}
              class="rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-4 py-2 text-sm font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Submitting...' : 'Submit feedback'}
            </button>
          </div>
          <p class="text-[11px] leading-relaxed text-slate-500">Takes less than 2 minutes. Reward available once per user.</p>
        </form>
      {/if}
    </section>
  </div>
{/if}
