<script>
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick } from '../../config/analytics'

  let { onNavigate = () => {} } = $props()

  const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp']
  const MAX_BYTES = 8 * 1024 * 1024

  let mode = $state('form') // 'form' | 'text' | 'image'

  // ── Shared status (for the last action) ──
  let resultMessage = $state('')
  let resultKind = $state('') // 'success' | 'error' | ''

  function setResult(kind, msg) {
    resultKind = kind
    resultMessage = msg
  }

  function clearResult() {
    resultKind = ''
    resultMessage = ''
  }

  // ── Guided form state ──
  let form = $state({
    title: '',
    role: '',
    yacht: '',
    location: '',
    yacht_type: '',
    yacht_length_m: '',
    department: '',
    rank_level: '',
    start_date: '',
    contract_type: '',
    rotation: '',
    season: '',
    salary_currency: 'EUR',
    salary_min: '',
    salary_max: '',
    visa_support: false,
    accommodation: '',
    travel_reimbursement: false,
    experience_required_years: '',
    minimum_license: '',
    languages_required: '',
    description: '',
    requirements: '',
    benefits: '',
    contact_email: '',
    application_url: '',
    urgent_hire: false,
  })
  let isSubmittingForm = $state(false)

  function buildFormPayload() {
    const out = {}
    for (const [k, v] of Object.entries(form)) {
      if (typeof v === 'boolean') { out[k] = v; continue }
      const trimmed = String(v ?? '').trim()
      if (!trimmed) continue
      if (k === 'yacht_length_m' || k === 'experience_required_years') {
        const n = parseInt(trimmed, 10)
        if (!Number.isNaN(n) && n > 0) out[k] = n
        continue
      }
      if (k === 'salary_min' || k === 'salary_max') {
        const n = parseFloat(trimmed)
        if (!Number.isNaN(n) && n >= 0) out[k] = n
        continue
      }
      out[k] = trimmed
    }
    return out
  }

  async function submitForm(event) {
    event.preventDefault()
    clearResult()
    if (!form.title.trim() || !form.role.trim() || !form.yacht.trim() || !form.location.trim()) {
      setResult('error', 'Title, role, yacht and location are required.')
      return
    }
    isSubmittingForm = true
    trackClick('agency_submit_form')
    try {
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/form`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildFormPayload()),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setResult('error', data.detail || `Submission failed (${res.status}).`)
        return
      }
      setResult('success', `Posted: "${data.title}" (#${data.id}). It is live on the job board.`)
      // Reset only the unique fields; keep currency/booleans for next submission speed.
      form = { ...form, title: '', role: '', yacht: '', location: '', start_date: '', description: '', requirements: '', benefits: '', application_url: '' }
    } catch {
      setResult('error', 'Could not reach the server.')
    } finally {
      isSubmittingForm = false
    }
  }

  // ── Paste-text state ──
  let textInput = $state('')
  let textUrl = $state('')
  let isSubmittingText = $state(false)

  async function submitText(event) {
    event.preventDefault()
    clearResult()
    const text = textInput.trim()
    if (text.length < 10) {
      setResult('error', 'Please paste the full job description (at least 10 characters).')
      return
    }
    isSubmittingText = true
    trackClick('agency_submit_text')
    try {
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/text`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, url: textUrl.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setResult('error', data.detail || `Submission failed (${res.status}).`)
        return
      }
      setResult('success', `Posted: "${data.title}" (#${data.id}). The AI extracted the details and it is live now.`)
      textInput = ''
      textUrl = ''
    } catch {
      setResult('error', 'Could not reach the server.')
    } finally {
      isSubmittingText = false
    }
  }

  // ── Image upload state ──
  let imageFiles = $state([])
  let imageUrl = $state('')
  let isSubmittingImage = $state(false)
  let dragOver = $state(false)

  function addImageFiles(files) {
    const accepted = []
    for (const f of files) {
      if (!ALLOWED_TYPES.includes(f.type)) continue
      if (f.size > MAX_BYTES) continue
      accepted.push(f)
    }
    imageFiles = [...imageFiles, ...accepted].slice(0, 6)
  }

  function onImagePick(event) {
    const files = [...(event.currentTarget.files ?? [])]
    addImageFiles(files)
    event.currentTarget.value = ''
  }

  function onImageDrop(event) {
    event.preventDefault()
    dragOver = false
    const files = [...(event.dataTransfer?.files ?? [])]
    addImageFiles(files)
  }

  function removeImageAt(index) {
    imageFiles = imageFiles.filter((_, i) => i !== index)
  }

  async function submitImages(event) {
    event.preventDefault()
    clearResult()
    if (!imageFiles.length) {
      setResult('error', 'Add at least one screenshot (PNG/JPEG/WEBP, max 8 MB each).')
      return
    }
    isSubmittingImage = true
    trackClick('agency_submit_image')
    try {
      const fd = new FormData()
      for (const f of imageFiles) fd.append('files', f)
      fd.append('url', imageUrl.trim())
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/image`, {
        method: 'POST',
        credentials: 'include',
        body: fd,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setResult('error', data.detail || `Submission failed (${res.status}).`)
        return
      }
      const job = data.job || {}
      setResult('success', `Posted: "${job.title}" (#${job.id}). The AI read your screenshots and the job is live now.`)
      imageFiles = []
      imageUrl = ''
    } catch {
      setResult('error', 'Could not reach the server.')
    } finally {
      isSubmittingImage = false
    }
  }
</script>

<section class="grid gap-4">
  <header class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
    <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Agency Tools</p>
    <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Post a Job</h1>
    <p class="mt-2 text-sm text-slate-400">
      Three ways to add a position. Pick whichever is fastest for you — every submission goes live immediately on the public job board.
    </p>
  </header>

  <!-- Mode tabs -->
  <div class="inline-flex w-full rounded-xl border border-white/10 bg-zinc-950 p-1 text-sm">
    {#each [['form', 'Guided form'], ['text', 'Paste text'], ['image', 'Upload screenshots']] as [key, label]}
      <button
        type="button"
        class={`flex-1 rounded-lg px-3 py-2 transition ${mode === key ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white'}`}
        onclick={() => { mode = key; clearResult() }}
      >
        {label}
      </button>
    {/each}
  </div>

  {#if resultMessage}
    <div class={`rounded-xl border p-4 text-sm ${resultKind === 'success' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100' : 'border-rose-400/30 bg-rose-400/10 text-rose-100'}`}>
      <div class="flex items-start justify-between gap-3">
        <p>{resultMessage}</p>
        <button type="button" onclick={clearResult} class="text-xs text-slate-300 hover:text-white" aria-label="Dismiss">✕</button>
      </div>
      {#if resultKind === 'success'}
        <button
          type="button"
          onclick={() => onNavigate('agency-dashboard')}
          class="mt-2 text-xs font-semibold text-emerald-200 underline-offset-4 transition hover:underline"
        >
          View my submissions →
        </button>
      {/if}
    </div>
  {/if}

  {#if mode === 'form'}
    <form class="rounded-2xl border border-white/8 bg-zinc-950 p-5" onsubmit={submitForm}>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Job title <span class="text-rose-400">*</span></span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.title} maxlength="160" required />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Role <span class="text-rose-400">*</span></span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.role} placeholder="e.g. Stewardess" maxlength="120" required />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Yacht name <span class="text-rose-400">*</span></span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.yacht} placeholder="e.g. M/Y Serenity (or 'Private Yacht')" maxlength="120" required />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Location <span class="text-rose-400">*</span></span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.location} placeholder="e.g. Antibes, France" maxlength="120" required />
        </label>

        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Yacht type</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.yacht_type} placeholder="Motor / Sail" maxlength="80" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Length (m)</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="number" min="1" max="600" bind:value={form.yacht_length_m} />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Department</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.department} placeholder="Interior / Deck / Engineering" maxlength="60" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Rank / Level</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.rank_level} placeholder="Junior / 2nd / Chief" maxlength="60" />
        </label>

        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Start date</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.start_date} placeholder="ASAP, June 2026, etc." maxlength="40" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Contract type</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.contract_type} placeholder="Permanent / Seasonal / Day work" maxlength="60" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Rotation</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.rotation} placeholder="2:2, 3:1, etc." maxlength="50" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Season</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.season} placeholder="Med / Caribbean" maxlength="60" />
        </label>

        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Currency</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.salary_currency} maxlength="10" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Salary min (per month)</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="number" min="0" step="50" bind:value={form.salary_min} />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Salary max (per month)</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="number" min="0" step="50" bind:value={form.salary_max} />
        </label>

        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Years of experience required</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="number" min="0" max="80" bind:value={form.experience_required_years} />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Minimum license</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.minimum_license} placeholder="STCW, OOW 3000, etc." maxlength="120" />
        </label>
        <label class="grid gap-1.5 sm:col-span-2">
          <span class="text-xs text-slate-400">Languages required</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="text" bind:value={form.languages_required} placeholder="English, Spanish" maxlength="200" />
        </label>

        <label class="grid gap-1.5 sm:col-span-2">
          <span class="text-xs text-slate-400">Description</span>
          <textarea class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" rows="4" bind:value={form.description} maxlength="5000"></textarea>
        </label>
        <label class="grid gap-1.5 sm:col-span-2">
          <span class="text-xs text-slate-400">Requirements</span>
          <textarea class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" rows="3" bind:value={form.requirements} maxlength="5000"></textarea>
        </label>
        <label class="grid gap-1.5 sm:col-span-2">
          <span class="text-xs text-slate-400">Benefits</span>
          <textarea class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" rows="2" bind:value={form.benefits} maxlength="5000"></textarea>
        </label>

        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Application contact email</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="email" bind:value={form.contact_email} maxlength="160" />
        </label>
        <label class="grid gap-1.5">
          <span class="text-xs text-slate-400">Application URL</span>
          <input class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40" type="url" bind:value={form.application_url} maxlength="260" />
        </label>

        <label class="flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" bind:checked={form.visa_support} />
          Visa support
        </label>
        <label class="flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" bind:checked={form.travel_reimbursement} />
          Travel reimbursement
        </label>
        <label class="flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" bind:checked={form.urgent_hire} />
          Urgent hire
        </label>
      </div>

      <div class="mt-5 flex justify-end">
        <button
          type="submit"
          disabled={isSubmittingForm}
          class="rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-5 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmittingForm ? 'Posting…' : 'Post job'}
        </button>
      </div>
    </form>

  {:else if mode === 'text'}
    <form class="rounded-2xl border border-white/8 bg-zinc-950 p-5 grid gap-4" onsubmit={submitText}>
      <p class="text-sm text-slate-400">
        Paste the full job advert. Our AI will pull out the role, location, salary, requirements and contact details for you.
      </p>
      <label class="grid gap-1.5">
        <span class="text-xs text-slate-400">Source URL (optional)</span>
        <input
          type="url"
          bind:value={textUrl}
          placeholder="https://your-agency.com/jobs/chief-stew"
          class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40"
          maxlength="260"
        />
      </label>
      <label class="grid gap-1.5">
        <span class="text-xs text-slate-400">Job description</span>
        <textarea
          bind:value={textInput}
          rows="14"
          maxlength="5000"
          placeholder="Paste the entire listing — title, role, yacht details, salary, requirements, contact…"
          class="rounded-md border border-white/15 bg-black px-3 py-2 font-mono text-sm text-slate-100 outline-none focus:border-cyan-200/40"
        ></textarea>
        <p class="text-[11px] text-slate-600">{textInput.trim().length} / 5000 characters</p>
      </label>
      <div class="flex justify-end">
        <button
          type="submit"
          disabled={isSubmittingText}
          class="rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-5 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmittingText ? 'Posting…' : 'Post job'}
        </button>
      </div>
    </form>

  {:else}
    <form class="rounded-2xl border border-white/8 bg-zinc-950 p-5 grid gap-4" onsubmit={submitImages}>
      <p class="text-sm text-slate-400">
        Drop screenshots of your job advert (max 6 images, 8 MB each, PNG / JPEG / WEBP). Our AI will read them and extract the details.
      </p>
      <label class="grid gap-1.5">
        <span class="text-xs text-slate-400">Source URL (optional)</span>
        <input
          type="url"
          bind:value={imageUrl}
          placeholder="https://your-agency.com/jobs/chief-stew"
          class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none focus:border-cyan-200/40"
          maxlength="260"
        />
      </label>

      <div
        class={`rounded-xl border-2 border-dashed p-6 text-center transition ${dragOver ? 'border-cyan-400/60 bg-cyan-400/5' : 'border-white/15'}`}
        ondragover={(e) => { e.preventDefault(); dragOver = true }}
        ondragleave={() => (dragOver = false)}
        ondrop={onImageDrop}
        role="presentation"
      >
        <p class="text-sm text-slate-300">Drop images here, or</p>
        <label class="mt-3 inline-flex cursor-pointer items-center rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-400/20">
          Choose files
          <input type="file" accept="image/png,image/jpeg,image/webp" multiple class="hidden" onchange={onImagePick} />
        </label>
      </div>

      {#if imageFiles.length > 0}
        <ul class="grid gap-2 text-xs">
          {#each imageFiles as file, i (i)}
            <li class="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/40 px-3 py-2">
              <span class="truncate text-slate-200">{file.name}</span>
              <span class="text-slate-500">{(file.size / 1024).toFixed(0)} KB</span>
              <button type="button" onclick={() => removeImageAt(i)} class="text-slate-500 transition hover:text-rose-300" aria-label="Remove">✕</button>
            </li>
          {/each}
        </ul>
      {/if}

      <div class="flex justify-end">
        <button
          type="submit"
          disabled={isSubmittingImage || imageFiles.length === 0}
          class="rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-5 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmittingImage ? 'Reading screenshots…' : 'Post job'}
        </button>
      </div>
    </form>
  {/if}
</section>
