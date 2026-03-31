<script>
  import { API_BASE_URL, apiFetch } from '../../config/api'

  const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

  let sourceUrl = $state('')
  let textInput = $state('')
  let textFileName = $state('')
  let importingText = $state(false)
  let textMessage = $state('')
  let textIsError = $state(false)
  let textImportedJob = $state(null)

  let imageJobs = $state([])
  let dragOver = $state(false)
  let nextId = 0

  function addFiles(files) {
    for (const file of files) {
      if (!ALLOWED_TYPES.includes(file.type)) continue
      if (file.size > 8 * 1024 * 1024) continue
      const entry = {
        id: nextId++,
        file,
        status: 'queued',
        message: '',
        job: null,
        aiExtracted: null,
      }
      imageJobs = [...imageJobs, entry]
      processImage(entry)
    }
  }

  function onDrop(event) {
    event.preventDefault()
    dragOver = false
    const files = [...(event.dataTransfer?.files ?? [])]
    if (files.length) addFiles(files)
  }

  function onDragOver(event) {
    event.preventDefault()
    dragOver = true
  }

  function onDragLeave() {
    dragOver = false
  }

  function onFileInput(event) {
    const files = [...(event.currentTarget.files ?? [])]
    if (files.length) addFiles(files)
    event.currentTarget.value = ''
  }

  function updateEntry(id, patch) {
    imageJobs = imageJobs.map(e => e.id === id ? { ...e, ...patch } : e)
  }

  function dismissEntry(id) {
    imageJobs = imageJobs.filter(e => e.id !== id)
  }

  function clearCompleted() {
    imageJobs = imageJobs.filter(e => e.status === 'queued' || e.status === 'processing')
  }

  async function processImage(entry) {
    updateEntry(entry.id, { status: 'processing', message: 'AI is reading...' })
    try {
      const formData = new FormData()
      formData.append('file', entry.file)
      formData.append('url', sourceUrl.trim())

      const res = await apiFetch(`${API_BASE_URL}/scraper/import-image`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        updateEntry(entry.id, {
          status: 'error',
          message: data.detail || `Failed (${res.status})`,
        })
        return
      }
      updateEntry(entry.id, {
        status: 'success',
        message: 'Imported',
        job: data.job || null,
        aiExtracted: data.ai_extracted || null,
      })
    } catch {
      updateEntry(entry.id, { status: 'error', message: 'Could not reach server.' })
    }
  }

  async function onTextFileChange(event) {
    const file = event.currentTarget.files?.[0]
    if (!file) return
    if (!(file.name || '').toLowerCase().endsWith('.txt')) {
      textMessage = 'Please upload a .txt file.'
      textIsError = true
      event.currentTarget.value = ''
      return
    }
    try {
      textInput = await file.text()
      textFileName = file.name
      textMessage = `Loaded ${file.name}`
      textIsError = false
    } catch {
      textMessage = 'Could not read the file.'
      textIsError = true
    } finally {
      event.currentTarget.value = ''
    }
  }

  async function submitText() {
    const trimmed = textInput.trim()
    if (!trimmed) { textMessage = 'Add job text first.'; textIsError = true; return }
    importingText = true
    textMessage = ''
    textIsError = false
    textImportedJob = null
    try {
      const res = await apiFetch(`${API_BASE_URL}/scraper/import`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed, url: sourceUrl.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { textMessage = data.detail || `Import failed (${res.status})`; textIsError = true; return }
      textImportedJob = data
      textMessage = 'Job imported successfully.'
      textIsError = false
    } catch {
      textMessage = 'Could not reach server.'
      textIsError = true
    } finally {
      importingText = false
    }
  }

  const processingCount = $derived(imageJobs.filter(e => e.status === 'processing').length)
  const successCount = $derived(imageJobs.filter(e => e.status === 'success').length)
  const errorCount = $derived(imageJobs.filter(e => e.status === 'error').length)
  const hasFinished = $derived(imageJobs.some(e => e.status === 'success' || e.status === 'error'))
</script>

<section class="grid gap-4">
  <header class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
    <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Admin Tool</p>
    <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Job Ingest</h1>
    <p class="mt-2 text-sm text-slate-500">
      Import jobs by pasting text or dropping screenshots. AI reads images directly and imports valid jobs automatically.
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

    <!-- Text input -->
    <article class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Manual Text</p>
      <p class="mt-2 text-xs text-slate-500">Paste job text directly, or load a .txt file.</p>

      <div class="mt-3">
        <label class="inline-flex cursor-pointer items-center rounded-lg border border-cyan-400/25 bg-cyan-400/8 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-400/15">
          Load .txt
          <input type="file" accept=".txt,text/plain" class="hidden" onchange={onTextFileChange} />
        </label>
        {#if textFileName}
          <span class="ml-2 text-[11px] text-slate-500">{textFileName}</span>
        {/if}
      </div>

      <textarea
        bind:value={textInput}
        rows="10"
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

      {#if textMessage}
        <p class="mt-3 text-xs {textIsError ? 'text-rose-300' : 'text-emerald-300'}">{textMessage}</p>
      {/if}
      {#if textImportedJob}
        <div class="mt-3 rounded-lg border border-emerald-400/15 bg-emerald-400/5 p-3 text-xs text-slate-300">
          <span class="text-slate-500">#{textImportedJob.id}</span> {textImportedJob.title ?? '—'} — <span class="text-emerald-300">{textImportedJob.role ?? '—'}</span>
        </div>
      {/if}
    </article>

    <!-- Screenshot drop zone -->
    <article class="rounded-2xl border border-white/8 bg-zinc-950 p-5">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Screenshots</p>
      <p class="mt-2 text-xs text-slate-500">Drop or select images — AI reads each one immediately.</p>

      <div
        class="drop-zone mt-3 rounded-xl border-2 border-dashed p-6 text-center transition-colors
          {dragOver ? 'border-violet-400 bg-violet-400/10' : 'border-white/15 bg-black/20 hover:border-white/25'}"
        ondrop={onDrop}
        ondragover={onDragOver}
        ondragleave={onDragLeave}
        role="button"
        tabindex="0"
      >
        <p class="text-sm {dragOver ? 'text-violet-200' : 'text-slate-500'}">
          {dragOver ? 'Drop images here' : 'Drag & drop screenshots here'}
        </p>
        <p class="mt-1 text-[11px] text-slate-600">PNG, JPG, WebP — up to 8 MB each</p>
        <label class="mt-3 inline-flex cursor-pointer items-center rounded-lg border border-violet-400/25 bg-violet-400/8 px-3 py-1.5 text-xs font-semibold text-violet-200 transition hover:border-violet-400/40 hover:bg-violet-400/15">
          Or select files
          <input
            type="file"
            accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
            multiple
            class="hidden"
            onchange={onFileInput}
          />
        </label>
      </div>

      {#if imageJobs.length > 0}
        <div class="mt-3 flex items-center justify-between gap-3">
          <div class="flex flex-wrap gap-2 text-[11px]">
            {#if processingCount > 0}
              <span class="flex items-center gap-1 text-violet-300">
                <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400"></span>
                {processingCount} processing
              </span>
            {/if}
            {#if successCount > 0}
              <span class="text-emerald-300">{successCount} imported</span>
            {/if}
            {#if errorCount > 0}
              <span class="text-rose-300">{errorCount} rejected</span>
            {/if}
          </div>
          {#if hasFinished}
            <button
              type="button"
              onclick={clearCompleted}
              class="text-[11px] text-slate-600 transition hover:text-slate-400"
            >
              Clear finished
            </button>
          {/if}
        </div>

        <div class="mt-2 max-h-[420px] space-y-2 overflow-y-auto">
          {#each imageJobs as entry (entry.id)}
            <div class="rounded-lg border p-3 transition-colors
              {entry.status === 'processing' ? 'border-violet-400/20 bg-violet-400/5' :
               entry.status === 'success' ? 'border-emerald-400/15 bg-emerald-400/5' :
               entry.status === 'error' ? 'border-rose-400/15 bg-rose-400/5' :
               'border-white/8 bg-white/[0.02]'}"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  {#if entry.status === 'processing'}
                    <span class="h-2 w-2 flex-none animate-pulse rounded-full bg-violet-400"></span>
                  {:else if entry.status === 'success'}
                    <span class="h-2 w-2 flex-none rounded-full bg-emerald-400"></span>
                  {:else if entry.status === 'error'}
                    <span class="h-2 w-2 flex-none rounded-full bg-rose-400"></span>
                  {:else}
                    <span class="h-2 w-2 flex-none rounded-full bg-slate-600"></span>
                  {/if}
                  <span class="truncate text-xs text-slate-300">{entry.file.name}</span>
                  <span class="flex-none text-[10px] text-slate-600">{Math.ceil(entry.file.size / 1024)} KB</span>
                </div>
                <button
                  type="button"
                  onclick={() => dismissEntry(entry.id)}
                  class="flex-none text-slate-600 transition hover:text-slate-400"
                  aria-label="Dismiss"
                >
                  <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {#if entry.status === 'processing'}
                <p class="mt-1.5 text-[11px] text-violet-300 animate-pulse">{entry.message}</p>
              {:else if entry.status === 'error'}
                <p class="mt-1.5 text-[11px] text-rose-300">{entry.message}</p>
              {:else if entry.status === 'success' && entry.job}
                <div class="mt-1.5 grid gap-0.5 text-[11px] text-slate-300">
                  <p><span class="text-slate-500">#{entry.job.id}</span> {entry.job.title ?? '—'}</p>
                  <p><span class="text-emerald-300">{entry.job.role ?? '—'}</span> — {entry.job.location ?? '—'}</p>
                </div>
                {#if entry.aiExtracted?.description}
                  <p class="mt-1 text-[10px] leading-relaxed text-slate-500">{entry.aiExtracted.description}</p>
                {/if}
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </article>
  </div>
</section>

<style>
  .drop-zone {
    cursor: pointer;
  }
</style>
