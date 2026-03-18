<script>
  function handlePointerMove(event) {
    const rect = event.currentTarget.getBoundingClientRect()
    event.currentTarget.style.setProperty('--mx', `${event.clientX - rect.left}px`)
    event.currentTarget.style.setProperty('--my', `${event.clientY - rect.top}px`)
  }

  function resetPointer(event) {
    event.currentTarget.style.setProperty('--mx', '50%')
    event.currentTarget.style.setProperty('--my', '50%')
  }
  const cards = [
    {
      title: 'Module-ready',
      description: 'Extend sections and layout blocks without touching core app composition.',
    },
    {
      title: 'Responsive',
      description: 'Dashboard structure adapts from phones to large displays with simple grids.',
    },
    {
      title: 'Secure baseline',
      description: 'Minimal surface area, clear structure, and Docker-first deployment model.',
    },
  ]
</script>

<section id="modules" class="md:col-span-4 grid gap-4">
  {#each cards as card}
    <article
      class="group relative overflow-hidden rounded-xl border border-white/10 bg-zinc-950 p-5 transition duration-300 hover:-translate-y-0.5 hover:border-cyan-200/35 hover:shadow-[0_16px_40px_-20px_rgba(34,211,238,0.45)]"
      style="--mx:50%; --my:50%;"
      onmousemove={handlePointerMove}
      onmouseleave={resetPointer}
    >
      <div
        class="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style="background: radial-gradient(260px circle at var(--mx) var(--my), rgba(34,211,238,0.2), transparent 60%);"
      ></div>
      <div class="relative z-10">
        <h2 class="text-base font-semibold text-white">{card.title}</h2>
        <p class="mt-2 text-sm leading-relaxed text-slate-300">{card.description}</p>
      </div>
    </article>
  {/each}
</section>
