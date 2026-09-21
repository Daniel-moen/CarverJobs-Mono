<script>
  /**
   * RouteError — what a failed route chunk shows instead of "Loading..."
   * forever.
   *
   * Every page is a dynamic `import()` of a content-hashed chunk. After a
   * deploy the old index.html in a phone's cache still points at chunk
   * names that no longer exist, so the import rejects, the `{#await}` had
   * no `{:catch}`, and the visitor sat on "Loading..." until they gave up.
   * (147 uncaught JS errors in the 22 Sep 2026 review.)
   *
   * A hard reload fixes it: index.html is served `no-cache`, so the fresh
   * document carries the current asset hashes.
   */
  import { onMount } from 'svelte'
  import { trackError } from '../../config/analytics'

  /** @type {{ error?: unknown, compact?: boolean, page?: string }} */
  let { error = null, compact = false, page = '' } = $props()

  onMount(() => {
    const err = /** @type {{ message?: string, stack?: string }} */ (error ?? {})
    trackError('chunk_load_failed', err.message ?? String(error), { page, stack: err.stack })
  })

  function reload() {
    window.location.reload()
  }
</script>

<div
  class="flex flex-col items-center gap-3 px-4 text-center {compact
    ? 'py-16'
    : 'mx-auto min-h-[50dvh] w-full max-w-3xl justify-center sm:px-6'}"
  role="alert"
>
  <p class="font-mono text-[10px] uppercase tracking-[0.28em] text-slate-500">Couldn't load this page</p>
  <p class="max-w-sm text-[13px] leading-relaxed text-slate-400">
    Carver was updated while this tab was open, so part of the app is missing. Reloading picks up the new version.
  </p>
  <button
    type="button"
    onclick={reload}
    class="mt-1 inline-flex items-center gap-2 rounded-lg border border-cyan-300/40 bg-gradient-to-b from-cyan-300/15 to-cyan-300/5 px-4 py-2 text-[13px] font-semibold text-cyan-50 transition hover:border-cyan-300/60 hover:from-cyan-300/25 hover:text-white"
  >
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
    </svg>
    Reload
  </button>
</div>
