<script>
  /** @type {{ title: string, children?: import('svelte').Snippet }} */
  let { title, children } = $props()
</script>

<div class="min-h-screen bg-black text-slate-100">
  <main class="mx-auto max-w-3xl px-4 py-10 sm:px-6">
    <a href="/" class="text-sm text-slate-400 transition hover:text-slate-200">← Home</a>
    <h1 class="mt-6 text-2xl font-semibold tracking-tight text-white sm:text-3xl">{title}</h1>
    <div class="mt-10 space-y-6 text-sm leading-relaxed text-slate-300">
      {@render children?.()}
    </div>
  </main>
</div>
