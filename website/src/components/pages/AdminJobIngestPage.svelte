<script>
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let sourceUrl = $state('')
  let textInput = $state('')
  let textFileName = $state('')
  let screenshotFile = $state(null)

  let importingText = $state(false)
  let importingImage = $state(false)
  let message = $state('')
  let messageIsError = $state(false)
  let importedJob = $state(null)
  let extractedPreview = $state('')

  function resetFeedback() {
    message = ''
    messageIsError = false
    importedJob = null
    extractedPreview = ''
  }

  async function onTextFileChange(event) {
    const file = event.currentTarget.files?.[0]
    if (!file) return
    const isTxt = (file.name || '').toLowerCase().endsWith('.txt')
    if (!isTxt) {
      message = 'Please upload a .txt file for text import.'
      messageIsError = true
      event.currentTarget.value = ''
      return
    }
    try {
      textInput = await file.text()
      textFileName = file.name
      message = `Loaded text from ${file.name}`
      messageIsError = false
    } catch {
      message = 'Could not read the text file.'
      messageIsError = true
    } finally {
      event.currentTarget.value = ''
    }
  }

  function onScreenshotChange(event) {
    const file = event.currentTarget.files?.[0]
    if (!file) return
    screenshotFile = file
    resetFeedback()
  }

  async function submitText() {
    const trimmed = textInput.trim()
    if (!trimmed) {
      message = 'Add job text first.'
      messageIsError = true
      return
    }
    importingText = true
    resetFeedback()
    try {
      const res = await apiFetch(`${API_BASE_URL}/scraper/import`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: trimmed,
          url: sourceUrl.trim(),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        message = data.detail || `Import failed (${res.status})`
        messageIsError = true
        return
      }
      importedJob = data
      message = 'Job imported successfully.'
      messageIsError = false
    } catch {
      message = 'Could not reach server.'
      messageIsError = true
    } finally {
      importingText = false
    }
  }

  async function submitScreenshot() {
    if (!screenshotFile) {
      message = 'Select a screenshot first.'
      messageIsError = true
      return
    }
    importingImage = true
    resetFeedback()
    try {
      const formData = new FormData()
      formData.append('file', screenshotFile)
      formData.append('url', sourceUrl.trim())

      const res = await apiFetch(`${API_BASE_URL}/scraper/import-image`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        message = data.detail || `Image import failed (${res.status})`
        messageIsError = true
        return
      }
      importedJob = data.job || null
      extractedPreview = data.extracted_text_preview || ''
      message = 'Screenshot processed and imported.'
      messageIsError = false
    } catch {
      message = 'Could not reach server.'
      messageIsError = true
    } finally {
      importingImage = false
    }
  }
</script>

<section class="grid gap-4">
  <header class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
    <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Admin Tool</p>
    <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Job Ingest</h1>
    <p class="mt-2 text-sm text-slate-500">
      Import one job at a time by pasting raw text or uploading a screenshot. Both paths run through the same AI filtering pipeline.
    </p>
  </header>

  <div class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
    <label class="grid gap-1.5">
      <span class="text-xs text-slate-400">Source URL (optional)</span>
      <input
        type="text"
        bind:value={sourceUrl}
        placeholder="https://example.com/job-post"
        class="rounded-md border border-white/15 bg-black px-3 py-2 text-sm text-white outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
      />
    </label>
  </div>

  <div class="grid gap-4 lg:grid-cols-2">
    <article class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Manual Text</p>
      <p class="mt-2 text-xs text-slate-500">Paste job text directly, or load a `.txt` file.</p>

      <div class="mt-3">
        <label class="inline-flex cursor-pointer items-center rounded-lg border border-cyan-400/25 bg-cyan-400/8 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-400/15">
          Load .txt
          <input type="file" accept=".txt,text/plain" class="hidden" onchange={onTextFileChange} />
        </label>
        {#if textFileName}
          <p class="mt-2 text-[11px] text-slate-500">Loaded: {textFileName}</p>
        {/if}
      </div>

      <textarea
        bind:value={textInput}
        rows="12"
        placeholder="Paste raw job post text..."
        class="mt-3 w-full rounded-lg border border-white/12 bg-black/40 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-300/70 transition focus:border-cyan-200/40 focus:ring"
      ></textarea>

      <div class="mt-3 flex items-center justify-between gap-3">
        <p class="text-[11px] text-slate-600">{textInput.trim().length} chars</p>
        <button
          type="button"
          onclick={submitText}
          disabled={importingText}
          class="rounded-lg border border-cyan-400/25 bg-cyan-400/8 px-4 py-2 text-xs font-bold text-cyan-200 transition hover:border-cyan-400/45 hover:bg-cyan-400/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {importingText ? 'Importing...' : 'Import from Text'}
        </button>
      </div>
    </article>

    <article class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Screenshot OCR</p>
      <p class="mt-2 text-xs text-slate-500">Upload an image containing job details; server OCR extracts text, then imports.</p>

      <label class="mt-3 inline-flex cursor-pointer items-center rounded-lg border border-violet-400/25 bg-violet-400/8 px-3 py-1.5 text-xs font-semibold text-violet-200 transition hover:border-violet-400/40 hover:bg-violet-400/15">
        Select Screenshot
        <input
          type="file"
          accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
          class="hidden"
          onchange={onScreenshotChange}
        />
      </label>
      {#if screenshotFile}
        <p class="mt-2 text-[11px] text-slate-500">
          {screenshotFile.name} ({Math.ceil(screenshotFile.size / 1024)} KB)
        </p>
      {/if}

      <button
        type="button"
        onclick={submitScreenshot}
        disabled={importingImage}
        class="mt-4 rounded-lg border border-violet-400/25 bg-violet-400/8 px-4 py-2 text-xs font-bold text-violet-200 transition hover:border-violet-400/45 hover:bg-violet-400/15 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {importingImage ? 'Processing...' : 'Import from Screenshot'}
      </button>

      {#if extractedPreview}
        <div class="mt-4 rounded-lg border border-white/10 bg-black/40 p-3">
          <p class="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Extracted Text Preview</p>
          <p class="whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{extractedPreview}</p>
        </div>
      {/if}
    </article>
  </div>

  {#if message}
    <div class="rounded-xl border px-4 py-3 {messageIsError ? 'border-rose-400/20 bg-rose-400/8 text-rose-300' : 'border-emerald-400/20 bg-emerald-400/8 text-emerald-300'}">
      <p class="text-sm">{message}</p>
    </div>
  {/if}

  {#if importedJob}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-4">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Imported Job</p>
      <div class="mt-2 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
        <p><span class="text-slate-500">ID:</span> {importedJob.id ?? '—'}</p>
        <p><span class="text-slate-500">Source:</span> {importedJob.source ?? 'manual'}</p>
        <p><span class="text-slate-500">Title:</span> {importedJob.title ?? '—'}</p>
        <p><span class="text-slate-500">Role:</span> {importedJob.role ?? '—'}</p>
        <p class="sm:col-span-2"><span class="text-slate-500">Location:</span> {importedJob.location ?? '—'}</p>
      </div>
    </div>
  {/if}
</section>
