<script>
  import { site } from '../../config/site'
</script>

<section id="overview" class="md:col-span-8 rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-[0_10px_40px_-20px_rgba(255,255,255,0.15)] sm:p-8">
  <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Dashboard</p>
  <h1 class="mt-4 max-w-3xl text-3xl font-semibold leading-tight text-white sm:text-4xl md:text-5xl">
    {site.tagline}
  </h1>
  <p class="mt-5 max-w-2xl text-sm leading-relaxed text-slate-300 sm:text-base">
    {site.description}
  </p>
  <div class="mt-8 grid gap-3 sm:grid-cols-3">
    <div class="rounded-lg border border-white/10 bg-black p-4">
      <p class="text-xs text-slate-400">System status</p>
      <p class="mt-2 text-xl font-semibold text-white">Operational</p>
    </div>
    <div class="rounded-lg border border-white/10 bg-black p-4">
      <p class="text-xs text-slate-400">Services</p>
      <p class="mt-2 text-xl font-semibold text-white">2 Online</p>
    </div>
    <div class="rounded-lg border border-white/10 bg-black p-4">
      <p class="text-xs text-slate-400">Mode</p>
      <p class="mt-2 text-xl font-semibold text-white">Dark-only</p>
    </div>
  </div>
</section>
