<script>
  import { onMount, onDestroy } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  const AUTO_REFRESH_MS = 5 * 60 * 1000

  let loading = $state(true)
  let error = $state('')
  let services = $state({})
  let lastRun = $state(null)
  let nextRunSeconds = $state(300)
  let countdown = $state(300)
  let countdownInterval = null
  let autoRefreshTimeout = null
  let mounted = $state(false)

  async function loadStatus() {
    loading = true
    error = ''
    mounted = false
    try {
      const response = await apiFetch(`${API_BASE_URL}/status/services`, {
        method: 'GET',
        credentials: 'include',
      })
      if (!response.ok) {
        error = response.status === 401 ? 'Please log in again.' : 'Could not load status.'
        services = {}
        return
      }
      const payload = await response.json()
      services = payload?.services ?? {}
      lastRun = payload?.last_run ?? null
      nextRunSeconds = payload?.next_run_seconds ?? 300
      countdown = nextRunSeconds
      startCountdown()
    } catch {
      error = 'Could not reach the server.'
      services = {}
    } finally {
      loading = false
      requestAnimationFrame(() => (mounted = true))
    }
    scheduleAutoRefresh()
  }

  function startCountdown() {
    clearInterval(countdownInterval)
    countdownInterval = setInterval(() => {
      countdown = Math.max(0, countdown - 1)
    }, 1000)
  }

  function scheduleAutoRefresh() {
    clearTimeout(autoRefreshTimeout)
    autoRefreshTimeout = setTimeout(() => loadStatus(), AUTO_REFRESH_MS)
  }

  function formatCheckedAt(iso) {
    if (!iso) return ''
    try { return new Date(iso).toLocaleTimeString() } catch { return iso }
  }

  function formatLastRun(iso) {
    if (!iso) return 'Not yet run'
    try { return new Date(iso).toLocaleString() } catch { return iso }
  }

  function fmtCountdown(secs) {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
  }

  function uptimePct(history) {
    if (!history?.length) return null
    return Math.round((history.filter(h => h.connected).length / history.length) * 100)
  }

  function barTitle(h) {
    const time = formatCheckedAt(h.checked_at)
    return h.connected ? `Up at ${time}` : `Down at ${time}`
  }

  const serviceEntries = $derived(Object.entries(services))
  const allUp = $derived(serviceEntries.length > 0 && serviceEntries.every(([, info]) => info.connected))

  onMount(() => loadStatus())
  onDestroy(() => {
    clearInterval(countdownInterval)
    clearTimeout(autoRefreshTimeout)
  })
</script>

<section class="grid gap-4">
  <!-- Header -->
  <header class="relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-5">
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-emerald-400/9 blur-3xl header-orb"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-cyan-400/6 blur-2xl header-orb" style="animation-delay:-2s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex items-start justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          {#if !loading && !error}
            <span class="h-1.5 w-1.5 rounded-full {allUp ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}"></span>
          {/if}
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">System</p>
        </div>
        <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Status</h1>
        <p class="mt-1.5 text-sm text-slate-500">Components checked every 5 minutes.</p>
      </div>
      <div class="flex items-center gap-3">
        {#if countdown > 0 && !loading}
          <div class="rounded-xl border border-white/8 bg-zinc-900 px-3 py-2 text-center">
            <p class="text-[9px] font-bold uppercase tracking-widest text-slate-600">Next check</p>
            <p class="mt-0.5 text-xs font-bold tabular-nums text-cyan-300">{fmtCountdown(countdown)}</p>
          </div>
        {/if}
        <button
          type="button"
          onclick={loadStatus}
          class="rounded-xl border border-white/10 bg-white/4 px-3 py-2 text-xs font-semibold text-slate-400 transition-all hover:border-white/20 hover:text-white active:scale-95"
        >
          Refresh
        </button>
      </div>
    </div>
    {#if lastRun}
      <p class="relative mt-3 text-[10px] text-slate-600">
        Last check: <span class="text-slate-500">{formatLastRun(lastRun)}</span>
      </p>
    {/if}
  </header>

  <!-- Loading skeleton -->
  {#if loading}
    <div class="grid gap-4 sm:grid-cols-2">
      {#each [1, 2, 3, 4] as _}
        <div class="overflow-hidden rounded-xl border border-white/8 bg-zinc-950 p-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <div class="skeleton h-2 w-2 rounded-full"></div>
              <div class="skeleton h-4 w-24 rounded"></div>
            </div>
            <div class="skeleton h-5 w-20 rounded-full"></div>
          </div>
          <div class="skeleton mt-3 h-3 w-40 rounded"></div>
          <div class="skeleton mt-4 h-7 w-full rounded-md"></div>
        </div>
      {/each}
    </div>

  <!-- Error -->
  {:else if error}
    <div class="rounded-2xl border border-rose-400/15 bg-zinc-950 px-6 py-8 text-center">
      <p class="text-sm text-rose-300">{error}</p>
      <button
        type="button"
        onclick={loadStatus}
        class="mt-4 rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-slate-300 transition-all hover:border-white/30 hover:text-white"
      >
        Retry
      </button>
    </div>

  <!-- Service cards -->
  {:else}
    <!-- Overall status banner -->
    <div
      class="status-banner rounded-xl border px-5 py-3 flex items-center gap-3 {allUp
        ? 'border-emerald-400/18 bg-emerald-400/6'
        : 'border-rose-400/18 bg-rose-400/6'}"
      class:visible={mounted}
    >
      <span class="h-2 w-2 flex-none rounded-full {allUp ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}"></span>
      <p class="text-sm font-semibold {allUp ? 'text-emerald-200' : 'text-rose-200'}">
        {allUp ? 'All systems operational' : 'One or more services are degraded'}
      </p>
    </div>

    <div class="grid gap-3 sm:grid-cols-2">
      {#each serviceEntries as [name, info], i}
        {@const history = info.history ?? []}
        {@const pct = uptimePct(history)}
        <article
          class="service-card group relative overflow-hidden rounded-xl border border-white/8 bg-zinc-950 p-4 transition-all duration-300 hover:-translate-y-0.5 {info.connected
            ? 'hover:border-emerald-400/18 hover:shadow-[0_12px_40px_-16px_rgba(52,211,153,0.2)]'
            : 'hover:border-rose-400/18 hover:shadow-[0_12px_40px_-16px_rgba(248,113,113,0.2)]'}"
          class:visible={mounted}
          style="--delay: {i * 60}ms;"
        >
          <!-- Name + badge -->
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-2.5">
              <span
                class="h-2 w-2 flex-none rounded-full {info.connected
                  ? 'bg-emerald-400 shadow-[0_0_6px_2px_rgba(52,211,153,0.4)] animate-pulse'
                  : 'bg-rose-500'}"
              ></span>
              <p class="text-sm font-semibold capitalize text-white">
                {name.replaceAll('_', ' ')}
              </p>
            </div>
            <span
              class="rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider {info.connected
                ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                : 'border-rose-400/25 bg-rose-400/10 text-rose-300'}"
            >
              {info.connected ? 'Operational' : 'Degraded'}
            </span>
          </div>

          <!-- Detail -->
          {#if info.connected && info.detail}
            <p class="mt-2 text-xs text-slate-500">{info.detail}</p>
          {/if}
          {#if !info.connected}
            <p class="mt-2 text-xs text-rose-400/70">Service unavailable</p>
            {#if info.code}
              <p class="mt-0.5 font-mono text-[10px] text-slate-600">{info.code}</p>
            {/if}
          {/if}

          <!-- Uptime history bar -->
          {#if history.length > 0}
            <div class="mt-4">
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[10px] text-slate-600">Last {history.length} checks</span>
                {#if pct !== null}
                  <span
                    class="text-[10px] font-bold {pct === 100
                      ? 'text-emerald-400'
                      : pct >= 90
                        ? 'text-amber-400'
                        : 'text-rose-400'}"
                  >
                    {pct}% uptime
                  </span>
                {/if}
              </div>
              <div class="flex h-6 items-stretch gap-px overflow-hidden rounded-lg">
                {#each history as h}
                  <div
                    title={barTitle(h)}
                    class="flex-1 cursor-default transition-opacity hover:opacity-70 {h.connected
                      ? 'bg-emerald-500/70'
                      : 'bg-rose-500/70'}"
                  ></div>
                {/each}
              </div>
              <div class="mt-1 flex justify-between text-[10px] text-slate-700">
                <span>{formatCheckedAt(history[0]?.checked_at)}</span>
                <span>{formatCheckedAt(history[history.length - 1]?.checked_at)}</span>
              </div>
            </div>
          {:else}
            <p class="mt-4 text-[10px] text-slate-700">Waiting for first check.</p>
          {/if}

          {#if info.checked_at}
            <p class="mt-2 text-[10px] text-slate-700">Checked {formatCheckedAt(info.checked_at)}</p>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</section>

<style>
  /* Header orb pulse + scan */
  .header-orb {
    animation: headerOrbPulse 4.5s ease-in-out infinite;
  }
  .header-scan-line {
    position: absolute;
    top: -1px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(52,211,153,0.28), transparent);
    animation: headerScan 8s linear infinite;
    pointer-events: none;
  }
  @keyframes headerOrbPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.55; transform: scale(1.14); }
  }
  @keyframes headerScan {
    0%   { top: -1px; opacity: 0; }
    8%   { opacity: 1; }
    92%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }

  .skeleton {
    background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.6s ease-in-out infinite;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  .status-banner,
  .service-card {
    opacity: 0;
    transform: translateY(12px);
    transition:
      opacity 0.4s ease,
      transform 0.4s ease,
      border-color 0.25s,
      box-shadow 0.25s,
      translate 0.2s;
    transition-delay: var(--delay, 0ms);
  }
  .status-banner.visible,
  .service-card.visible {
    opacity: 1;
    transform: translateY(0);
  }
</style>
