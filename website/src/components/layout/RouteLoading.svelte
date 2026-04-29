<script>
  let { compact = false, label = 'Loading...' } = $props()
</script>

{#if compact}
  <p class="py-16 text-center font-mono text-[10px] uppercase tracking-[0.28em] text-slate-500" aria-live="polite">{label}</p>
{:else}
  <main class="mx-auto flex min-h-[50dvh] w-full max-w-3xl items-center justify-center px-4 text-center sm:px-6" aria-busy="true" aria-live="polite">
    <p class="font-mono text-[10px] uppercase tracking-[0.28em] text-slate-500">{label}</p>
  </main>
{/if}
