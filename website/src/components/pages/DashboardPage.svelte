<script>
  import { onMount, onDestroy } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import ScrubChart from '../charts/ScrubChart.svelte'

  const POLL_MS = 30_000

  let loading       = $state(true)
  let error         = $state('')
  let errorCode     = $state('')
  let stats         = $state(null)
  let flagsData     = $state(null)
  let pollTimeout   = null
  let lastFetched   = $state(null)
  let togglingKey   = $state(null)
  let toggleError   = $state('')
  let mounted       = $state(false)

  let scraperStatus    = $state(null)
  let triggering       = $state(false)
  let triggerMessage   = $state('')
  let triggerIsError   = $state(false)
  let triggeringWeb    = $state(false)
  let triggerWebMsg    = $state('')
  let triggerWebIsErr  = $state(false)
  let analyticsData    = $state(null)
  let flowsData        = $state(null)

  let errorLogs        = $state([])
  let loadingErrors    = $state(false)
  let analyzingId      = $state(null)
  let expandedError    = $state(null)

  let reviewingJobs    = $state(false)
  let reviewResult     = $state(null)
  let reviewError      = $state('')

  let pfLoading        = $state(false)
  let pfResult         = $state(null)
  let pfError          = $state('')
  let pfSubStatus      = $state(null)
  let pfCancelling     = $state(false)

  async function pfCheckout(redirect) {
    pfLoading = true
    pfError = ''
    pfResult = null
    try {
      const res = await apiFetch(`${API_BASE_URL}/subscription/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { pfError = data.detail || `Error ${res.status}`; return }
      pfResult = data
      if (redirect && data.payfast_url && data.form_fields) {
        const form = document.createElement('form')
        form.method = 'POST'
        form.action = data.payfast_url
        for (const [k, v] of Object.entries(data.form_fields)) {
          const input = document.createElement('input')
          input.type = 'hidden'; input.name = k; input.value = String(v)
          form.appendChild(input)
        }
        document.body.appendChild(form)
        form.submit()
      }
    } catch { pfError = 'Could not reach server.' }
    finally { pfLoading = false }
  }

  async function pfStatus() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/subscription/status`, { method: 'GET', credentials: 'include' })
      pfSubStatus = res.ok ? await res.json() : { error: `Error ${res.status}` }
    } catch { pfSubStatus = { error: 'Could not reach server.' } }
  }

  async function pfCancel() {
    pfCancelling = true
    pfError = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/subscription/cancel`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { pfError = data.detail || `Error ${res.status}`; return }
      pfSubStatus = { ok: true, subscribed: false }
      pfError = ''
      pfResult = null
    } catch { pfError = 'Could not reach server.' }
    finally { pfCancelling = false }
  }

  async function loadStats() {
    error = ''
    errorCode = ''
    try {
      const [statsRes, flagsRes, scraperRes, analyticsRes, flowsRes] = await Promise.all([
        apiFetch(`${API_BASE_URL}/admin/stats`,           { method: 'GET', credentials: 'include' }),
        apiFetch(`${API_BASE_URL}/admin/flags`,           { method: 'GET', credentials: 'include' }),
        apiFetch(`${API_BASE_URL}/scraper/status`,        { method: 'GET', credentials: 'include' }),
        apiFetch(`${API_BASE_URL}/admin/analytics`,       { method: 'GET', credentials: 'include' }),
        apiFetch(`${API_BASE_URL}/admin/analytics/flows`, { method: 'GET', credentials: 'include' }),
      ])
      if (!statsRes.ok) {
        if (statsRes.status === 401 || statsRes.status === 403) {
          error = 'You do not have permission to view this page.'
          errorCode = 'CRV-2001'
        } else {
          error = 'Dashboard data could not be loaded.'
          errorCode = statsRes.headers.get('X-Error-Code') || 'CRV-5001'
        }
        return
      }
      stats         = await statsRes.json()
      flagsData     = flagsRes.ok     ? await flagsRes.json()     : null
      scraperStatus = scraperRes.ok   ? await scraperRes.json()   : null
      analyticsData = analyticsRes.ok ? await analyticsRes.json() : null
      flowsData     = flowsRes.ok     ? await flowsRes.json()     : null
      lastFetched   = new Date()
    } catch {
      error = 'Could not reach the server.'
      errorCode = 'CRV-1001'
    } finally {
      loading = false
      requestAnimationFrame(() => (mounted = true))
    }
    pollTimeout = setTimeout(loadStats, POLL_MS)
  }

  async function toggleFlag(key) {
    if (!flagsData) return
    togglingKey = key
    toggleError = ''
    const newVal = !flagsData.flags[key]
    try {
      const res = await apiFetch(`${API_BASE_URL}/admin/flags`, {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, enabled: newVal }),
      })
      if (res.ok) {
        const data = await res.json()
        flagsData = { ...flagsData, flags: data.flags }
      } else {
        const code = res.headers.get('X-Error-Code') || 'CRV-5002'
        toggleError = `Could not update flag. (${code})`
        setTimeout(() => { toggleError = '' }, 4000)
      }
    } catch {
      toggleError = 'Could not reach the server. (CRV-1001)'
      setTimeout(() => { toggleError = '' }, 4000)
    } finally { togglingKey = null }
  }

  async function triggerScrape() {
    triggering     = true
    triggerMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/scraper/trigger`, { method: 'POST', credentials: 'include' })
      if (res.ok) {
        triggerIsError = false
        triggerMessage = 'Apify scrape started.'
        setTimeout(async () => {
          const r = await apiFetch(`${API_BASE_URL}/scraper/status`, { method: 'GET', credentials: 'include' })
          if (r.ok) scraperStatus = await r.json()
        }, 1200)
      } else {
        const data = await res.json().catch(() => ({}))
        const code = res.headers.get('X-Error-Code') || ''
        triggerIsError = true
        triggerMessage = (data.detail || 'Could not trigger scrape.') + (code ? ` (${code})` : '')
      }
    } catch {
      triggerIsError = true
      triggerMessage = 'Could not reach the server.'
    } finally {
      triggering = false
      setTimeout(() => { triggerMessage = '' }, 5000)
    }
  }

  async function triggerWebScrape() {
    triggeringWeb  = true
    triggerWebMsg  = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/scraper/trigger-web`, { method: 'POST', credentials: 'include' })
      if (res.ok) {
        triggerWebIsErr = false
        triggerWebMsg   = 'Web scrape started.'
        setTimeout(async () => {
          const r = await apiFetch(`${API_BASE_URL}/scraper/status`, { method: 'GET', credentials: 'include' })
          if (r.ok) scraperStatus = await r.json()
        }, 1200)
      } else {
        const data = await res.json().catch(() => ({}))
        triggerWebIsErr = true
        triggerWebMsg   = data.detail || 'Could not trigger web scrape.'
      }
    } catch {
      triggerWebIsErr = true
      triggerWebMsg   = 'Could not reach the server.'
    } finally {
      triggeringWeb = false
      setTimeout(() => { triggerWebMsg = '' }, 5000)
    }
  }

  function fmtUptime(secs) {
    if (secs == null) return '—'
    const d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600)
    const m = Math.floor((secs % 3600) / 60), s = secs % 60
    if (d > 0) return `${d}d ${h}h ${m}m`
    if (h > 0) return `${h}h ${m}m`
    if (m > 0) return `${m}m ${s}s`
    return `${s}s`
  }

  function fmtTime(iso) {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleString() } catch { return iso }
  }

  function barPct(v, total) {
    return total ? `${Math.min(100, Math.round((v / total) * 100))}%` : '0%'
  }

  const ev  = $derived(stats?.events ?? {})
  const db  = $derived(stats?.db     ?? {})
  const ts  = $derived(stats?.time_series ?? [])

  const tsLabels = $derived(ts.map(p =>
    new Date(p.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  ))
  const errorTrackerSeries = $derived([
    { name: '4xx',        color: '#fbbf24', data: ts.map(p => p.errors_4xx      ?? 0) },
    { name: '5xx',        color: '#f87171', data: ts.map(p => p.errors_5xx      ?? 0) },
    { name: 'Rate limit', color: '#fb923c', data: ts.map(p => p.rate_limit_hits ?? 0) },
    { name: 'CSRF',       color: '#a78bfa', data: ts.map(p => p.csrf_rejections ?? 0) },
  ])
  const requestTrackerSeries = $derived([
    { name: 'Requests',    color: '#94a3b8', data: ts.map(p => p.requests            ?? 0) },
    { name: 'API resp ms', color: '#67e8f9', data: ts.map(p => p.avg_response_ms     ?? 0) },
    { name: 'AI resp ms',  color: '#a78bfa', data: ts.map(p => p.avg_ai_response_ms  ?? 0) },
  ])
  const authTrackerSeries = $derived([
    { name: 'Success', color: '#34d399', data: ts.map(p => p.logins_success ?? 0) },
    { name: 'Failed',  color: '#f87171', data: ts.map(p => p.logins_failed  ?? 0) },
  ])
  const onboardSeries = $derived(ts.map(p => p.onboard_started))
  const onboardPct = $derived(ev.onboard_started
    ? Math.round((ev.onboard_completed / ev.onboard_started) * 100) : null)
  const loginTotal = $derived((ev.logins_success ?? 0) + (ev.logins_failed ?? 0))
  const jobStatusEntries = $derived(Object.entries(db.jobs_by_status ?? {}).sort((a, b) => b[1] - a[1]))
  const roleEntries      = $derived(Object.entries(db.users_by_role  ?? {}).sort((a, b) => b[1] - a[1]))
  const errorsByModule   = $derived(stats?.errors_by_module ?? {})
  const moduleErrorEntries = $derived(
    Object.entries(errorsByModule)
      .map(([mod, counts]) => ({ module: mod, e4xx: counts['4xx'] ?? 0, e5xx: counts['5xx'] ?? 0, total: (counts['4xx'] ?? 0) + (counts['5xx'] ?? 0) }))
      .sort((a, b) => b.total - a.total)
  )
  const moduleErrorTotal = $derived(moduleErrorEntries.reduce((s, e) => s + e.total, 0))
  const recentModuleErrors = $derived(
    ts.filter(p => p.errors_by_module && Object.keys(p.errors_by_module).length > 0).slice(-10).reverse()
  )
  const topPages        = $derived(analyticsData?.page_views?.by_page ?? [])
  const topClicks       = $derived(analyticsData?.button_clicks?.by_label ?? [])
  const userFlows       = $derived(flowsData?.flows ?? [])
  const pageTransitions = $derived(flowsData?.transitions ?? [])

  // Scraper history chart — last 40 entries, one data point per run
  const scraperHistory  = $derived((scraperStatus?.source_history ?? []).slice(-40))
  const scraperChartLabels = $derived(scraperHistory.map(e => {
    try { return new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) } catch { return '' }
  }))
  const _sources = ['apify', 'dockwalk', 'workonayacht', 'faststream', 'crewfinders', 'vikingcrew']
  const _sourceColors = { apify: '#818cf8', dockwalk: '#34d399', workonayacht: '#38bdf8', faststream: '#fb923c', crewfinders: '#a78bfa', vikingcrew: '#f472b6' }
  const _sourceDimColors = { apify: '#818cf840', dockwalk: '#34d39940', workonayacht: '#38bdf840', faststream: '#fb923c40', crewfinders: '#a78bfa40', vikingcrew: '#f472b640' }
  const scraperFetchedSeries = $derived(
    _sources.map(src => ({
      name: `${src} fetched`,
      color: _sourceDimColors[src],
      data: scraperHistory.map(e => e.source === src ? e.fetched : null),
    }))
  )
  const scraperCreatedSeries = $derived(
    _sources.map(src => ({
      name: `${src} new`,
      color: _sourceColors[src],
      data: scraperHistory.map(e => e.source === src ? e.created : null),
    }))
  )
  const scraperChartSeries = $derived([...scraperFetchedSeries, ...scraperCreatedSeries])

  const apifyEnabled  = $derived(flagsData?.flags?.scraper     ?? true)
  const webEnabled    = $derived(flagsData?.flags?.scraper_web ?? true)

  const webLastBySource = $derived(
    Object.fromEntries(
      ['dockwalk', 'workonayacht'].map(src => {
        const last = [...scraperHistory].reverse().find(e => e.source === src)
        return [src, last ?? null]
      })
    )
  )

  async function loadErrors() {
    loadingErrors = true
    try {
      const res = await apiFetch(`${API_BASE_URL}/admin/errors`, { method: 'GET', credentials: 'include' })
      if (res.ok) errorLogs = (await res.json()).errors ?? []
    } catch { /* silent */ } finally {
      loadingErrors = false
    }
  }

  async function analyzeError(id) {
    analyzingId = id
    try {
      const res = await apiFetch(`${API_BASE_URL}/admin/errors/${id}/analyze`, {
        method: 'POST', credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        errorLogs = errorLogs.map(e => e.id === id ? { ...e, ai_analysis: data.analysis } : e)
      }
    } catch { /* silent */ } finally {
      analyzingId = null
    }
  }

  async function reviewJobs() {
    reviewingJobs = true
    reviewResult  = null
    reviewError   = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/admin/jobs/review`, {
        method: 'POST', credentials: 'include',
      })
      if (res.ok) {
        reviewResult = await res.json()
        loadStats()
      } else {
        const data = await res.json().catch(() => ({}))
        const code = res.headers.get('X-Error-Code') || ''
        reviewError = (data.detail || 'AI job review failed.') + (code ? ` (${code})` : '')
      }
    } catch {
      reviewError = 'Could not reach the server.'
    } finally {
      reviewingJobs = false
    }
  }

  function fmtRelTime(iso) {
    if (!iso) return '—'
    try {
      const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
      if (diff < 60) return `${diff}s ago`
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
      return `${Math.floor(diff / 86400)}d ago`
    } catch { return iso }
  }

  onMount(() => { loadStats(); loadErrors() })
  onDestroy(() => clearTimeout(pollTimeout))
</script>

<section class="grid gap-4">

  <!-- ── Header ── -->
  <header class="dash-card relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-5" class:visible={mounted}>
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-violet-400/9 blur-3xl header-orb"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-8 h-32 w-32 rounded-full bg-indigo-400/7 blur-2xl header-orb" style="animation-delay:-2.2s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Admin</p>
        </div>
        <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Dashboard</h1>
        <p class="mt-1.5 text-sm text-slate-500">Live metrics · auto-updates every 30s · toggles take effect immediately.</p>
      </div>
      <button
        type="button"
        onclick={loadStats}
        class="rounded-xl border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-semibold text-slate-400 transition hover:border-white/20 hover:text-white active:scale-95"
      >
        Refresh
      </button>
    </div>
    {#if lastFetched || stats}
      <div class="relative mt-3 flex flex-wrap gap-4 text-[10px] text-slate-600">
        {#if lastFetched}
          <span>Fetched <span class="text-slate-500">{fmtTime(lastFetched.toISOString())}</span></span>
        {/if}
        {#if stats}
          <span>Up since <span class="text-slate-500">{fmtTime(stats.server_started_at)}</span>
            · uptime <span class="font-bold text-cyan-400">{fmtUptime(stats.uptime_seconds)}</span>
          </span>
        {/if}
      </div>
    {/if}
  </header>

  {#if loading}
    <!-- Skeleton -->
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {#each [1,2,3,4] as _}
        <div class="overflow-hidden rounded-xl border border-white/8 bg-zinc-950 p-4">
          <div class="skeleton h-3 w-24 rounded"></div>
          <div class="skeleton mt-3 h-8 w-16 rounded-lg"></div>
          <div class="skeleton mt-2 h-3 w-20 rounded"></div>
        </div>
      {/each}
    </div>

  {:else if error}
    <div class="rounded-2xl border border-rose-400/15 bg-zinc-950 px-6 py-6">
      <p class="text-sm text-rose-300">{error}</p>
      {#if errorCode}
        <p class="mt-1 font-mono text-xs text-rose-500/60">{errorCode}</p>
      {/if}
    </div>

  {:else if stats}

    <!-- ── Feature Toggles ── -->
    {#if flagsData}
      <div class="dash-card" class:visible={mounted} style="--delay:60ms;">
        <div class="mb-3 flex items-center justify-between gap-2">
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Feature Toggles</p>
          <p class="text-[10px] text-slate-700">Resets on restart</p>
        </div>
        {#if toggleError}
          <p class="mb-3 rounded-xl border border-rose-400/20 bg-rose-400/8 px-3 py-2 font-mono text-xs text-rose-300">{toggleError}</p>
        {/if}
        <div class="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {#each Object.entries(flagsData.flags) as [key, enabled]}
            {@const label = flagsData.labels?.[key] ?? key}
            {@const isToggling = togglingKey === key}
            <button
              type="button"
              onclick={() => toggleFlag(key)}
              disabled={isToggling}
              class="flex items-center justify-between rounded-xl border px-4 py-3 text-left transition-all duration-200
                {enabled
                  ? 'border-emerald-400/20 bg-emerald-400/6 hover:border-emerald-400/35'
                  : 'border-rose-400/20 bg-rose-400/6 hover:border-rose-400/35'}
                disabled:cursor-wait disabled:opacity-50"
            >
              <div>
                <p class="text-xs font-semibold {enabled ? 'text-emerald-200' : 'text-rose-200'}">{label}</p>
                <p class="mt-0.5 text-[10px] {enabled ? 'text-emerald-500' : 'text-rose-500'}">{enabled ? 'Enabled' : 'DISABLED'}</p>
              </div>
              <div class="relative ml-3 h-5 w-9 flex-none rounded-full transition-colors {enabled ? 'bg-emerald-400' : 'bg-zinc-700'}">
                <div class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-md transition-all {enabled ? 'left-[18px]' : 'left-0.5'}"></div>
              </div>
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <!-- ── Scrapers ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:100ms;">
      <div class="mb-4 flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full {scraperStatus?.running ? 'animate-pulse bg-cyan-400' : scraperStatus?.last_status === 'ok' ? 'bg-emerald-400' : 'bg-zinc-600'}"></span>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Scrapers</p>
        {#if scraperStatus?.running}
          <span class="rounded-full border border-cyan-400/20 bg-cyan-400/8 px-2 py-0.5 text-[10px] font-bold text-cyan-300 animate-pulse">Running…</span>
        {/if}
      </div>

      <div class="grid gap-3 lg:grid-cols-2">

        <!-- Apify (paid) panel -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <div class="mb-3 flex items-center justify-between gap-2">
            <div>
              <p class="text-xs font-bold text-slate-200">Apify — Facebook Groups</p>
              <p class="text-[10px] text-amber-400/70">Paid per run · billed via Apify</p>
            </div>
            {#if flagsData}
              <button
                type="button"
                onclick={() => toggleFlag('scraper')}
                disabled={togglingKey === 'scraper'}
                class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[10px] font-semibold transition disabled:cursor-wait disabled:opacity-50
                  {apifyEnabled ? 'border-emerald-400/20 bg-emerald-400/6 text-emerald-300 hover:border-emerald-400/35' : 'border-zinc-700 bg-zinc-800 text-slate-500 hover:border-zinc-600'}"
              >
                <div class="relative h-3.5 w-6 flex-none rounded-full {apifyEnabled ? 'bg-emerald-400' : 'bg-zinc-700'}">
                  <div class="absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white shadow transition-all {apifyEnabled ? 'left-[10px]' : 'left-0.5'}"></div>
                </div>
                {apifyEnabled ? 'Auto on' : 'Auto off'}
              </button>
            {/if}
          </div>

          {#if scraperStatus}
            {@const sc = scraperStatus}
            <div class="mb-3 flex flex-wrap gap-1.5">
              {#if sc.configured}
                <span class="rounded-full border border-emerald-400/20 bg-emerald-400/8 px-2 py-0.5 text-[10px] font-bold text-emerald-300">Configured</span>
              {:else}
                <span class="rounded-full border border-amber-400/20 bg-amber-400/8 px-2 py-0.5 text-[10px] font-bold text-amber-300">Not configured</span>
              {/if}
              {#if sc.last_status === 'ok'}
                <span class="rounded-full border border-emerald-400/20 bg-emerald-400/8 px-2 py-0.5 text-[10px] font-bold text-emerald-300">Last: OK</span>
              {:else if sc.last_status === 'error'}
                <span class="rounded-full border border-rose-400/20 bg-rose-400/8 px-2 py-0.5 text-[10px] font-bold text-rose-300">Last: Error</span>
              {:else}
                <span class="rounded-full border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-[10px] font-bold text-slate-500">Never run</span>
              {/if}
            </div>

            {#if sc.last_status === 'error' && sc.last_error}
              <div class="mb-3 rounded-lg border border-rose-400/15 bg-rose-400/6 px-3 py-2">
                <p class="font-mono text-[10px] text-rose-300">{sc.last_error.code}</p>
                <p class="mt-0.5 text-[10px] text-rose-200/60">{sc.last_error.detail}</p>
              </div>
            {/if}

            {#if sc.last_counts}
              <div class="mb-3 flex flex-wrap gap-3 text-xs">
                {#each [['Fetched', sc.last_counts.items_fetched, 'text-slate-300'], ['New', sc.last_counts.created, 'text-emerald-300'], ['Skipped', sc.last_counts.skipped, 'text-slate-500'], ['Errors', sc.last_counts.errors, 'text-rose-300']] as [lbl, val, cls]}
                  <div><span class="text-slate-600">{lbl} </span><span class="font-semibold {cls}">{val ?? '—'}</span></div>
                {/each}
              </div>
            {/if}

            <div class="mb-3 text-[10px] text-slate-600">
              Last: <span class="text-slate-400">{fmtTime(sc.last_run_at)}</span>
              {#if apifyEnabled && sc.next_run_at}
                · Next: <span class="text-slate-400">{fmtTime(sc.next_run_at)}</span>
              {:else if !apifyEnabled}
                · <span class="text-amber-500/60">auto paused</span>
              {/if}
            </div>
          {/if}

          <div class="flex items-center gap-2">
            <button
              type="button"
              onclick={triggerScrape}
              disabled={triggering || scraperStatus?.running}
              class="rounded-lg border border-violet-400/25 bg-violet-400/8 px-3 py-1.5 text-xs font-bold text-violet-200 transition hover:border-violet-400/45 hover:bg-violet-400/15 disabled:cursor-not-allowed disabled:opacity-35 active:scale-95"
            >
              {triggering ? 'Starting…' : scraperStatus?.running ? 'Running…' : 'Run Apify Now'}
            </button>
            {#if triggerMessage}
              <p class="text-[10px] {triggerIsError ? 'text-rose-300' : 'text-emerald-300'}">{triggerMessage}</p>
            {/if}
          </div>
        </div>

        <!-- Web scrapers (free) panel -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <div class="mb-3 flex items-center justify-between gap-2">
            <div>
              <p class="text-xs font-bold text-slate-200">Web Scrapers</p>
              <p class="text-[10px] text-emerald-400/70">Free · runs every cycle automatically</p>
            </div>
            {#if flagsData}
              <button
                type="button"
                onclick={() => toggleFlag('scraper_web')}
                disabled={togglingKey === 'scraper_web'}
                class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[10px] font-semibold transition disabled:cursor-wait disabled:opacity-50
                  {webEnabled ? 'border-emerald-400/20 bg-emerald-400/6 text-emerald-300 hover:border-emerald-400/35' : 'border-zinc-700 bg-zinc-800 text-slate-500 hover:border-zinc-600'}"
              >
                <div class="relative h-3.5 w-6 flex-none rounded-full {webEnabled ? 'bg-emerald-400' : 'bg-zinc-700'}">
                  <div class="absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white shadow transition-all {webEnabled ? 'left-[10px]' : 'left-0.5'}"></div>
                </div>
                {webEnabled ? 'Auto on' : 'Auto off'}
              </button>
            {/if}
          </div>

          <!-- Active scrapers list + per-source last results -->
          {#if scraperStatus?.web_scrapers}
            <div class="mb-3 space-y-1.5">
              {#each scraperStatus.web_scrapers.filter(s => s.enabled) as s}
                {@const key = s.name.toLowerCase().replace(/\s+/g,'').replace('yotspot','workonayacht')}
                {@const h = webLastBySource[key]}
                <div class="flex items-center justify-between text-[10px]">
                  <span class="flex items-center gap-1.5 font-medium text-slate-300">
                    <span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
                    {s.name}
                    {#if s.needs_proxy && !scraperStatus.scrape_do_configured}
                      <span class="text-amber-400/70">(proxy needed)</span>
                    {:else if s.needs_proxy && scraperStatus.scrape_do_configured}
                      <span class="text-slate-600">(via proxy)</span>
                    {/if}
                  </span>
                  {#if h}
                    <span class="text-slate-500">
                      fetched <span class="text-slate-300">{h.fetched}</span>
                      · new <span class="font-bold text-emerald-300">{h.created}</span>
                      · <span class="text-slate-600">{fmtTime(h.ts)}</span>
                    </span>
                  {:else}
                    <span class="text-slate-700">No runs yet</span>
                  {/if}
                </div>
              {/each}
              {#if !scraperStatus.web_scrapers.some(s => s.enabled)}
                <p class="text-[10px] text-slate-600">All web scrapers disabled.</p>
              {/if}
            </div>
          {:else if scraperHistory.length}
            <div class="mb-3 space-y-1.5">
              {#each [['dockwalk','Dockwalk'],['workonayacht','Yotspot'],['faststream','Faststream']] as [src, label]}
                {@const h = webLastBySource[src]}
                <div class="flex items-center justify-between text-[10px]">
                  <span class="font-medium text-slate-300">{label}</span>
                  {#if h}
                    <span class="text-slate-500">fetched <span class="text-slate-300">{h.fetched}</span> · new <span class="font-bold text-emerald-300">{h.created}</span></span>
                  {:else}
                    <span class="text-slate-700">No runs yet</span>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="mb-3 text-[10px] text-slate-700">No runs recorded yet.</p>
          {/if}

          <div class="flex items-center gap-2">
            <button
              type="button"
              onclick={triggerWebScrape}
              disabled={triggeringWeb || scraperStatus?.running}
              class="rounded-lg border border-emerald-400/25 bg-emerald-400/8 px-3 py-1.5 text-xs font-bold text-emerald-200 transition hover:border-emerald-400/45 hover:bg-emerald-400/15 disabled:cursor-not-allowed disabled:opacity-35 active:scale-95"
            >
              {triggeringWeb ? 'Starting…' : scraperStatus?.running ? 'Running…' : 'Run Web Now'}
            </button>
            {#if triggerWebMsg}
              <p class="text-[10px] {triggerWebIsErr ? 'text-rose-300' : 'text-emerald-300'}">{triggerWebMsg}</p>
            {/if}
          </div>
        </div>
      </div>

      <!-- Scraper history chart -->
      {#if scraperHistory.length > 1}
        <div class="mt-4 border-t border-white/5 pt-4">
          <div class="mb-2 flex items-center gap-4">
            <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Jobs Found vs New — per source</p>
            <div class="flex flex-wrap items-center gap-3 text-[10px]">
              {#each [['apify','#818cf8'],['dockwalk','#34d399'],['workonayacht','#38bdf8'],['faststream','#fb923c'],['crewfinders','#a78bfa'],['vikingcrew','#f472b6']] as [src, col]}
                <span class="flex items-center gap-1">
                  <span class="inline-block h-1.5 w-4 rounded-full opacity-30" style="background:{col}"></span>
                  <span class="inline-block h-1.5 w-4 rounded-full" style="background:{col}"></span>
                  <span class="text-slate-500">{src}</span>
                </span>
              {/each}
              <span class="text-slate-700">(faded = fetched, bright = new)</span>
            </div>
          </div>
          <ScrubChart series={scraperChartSeries} labels={scraperChartLabels} title="" height={100} />
        </div>
      {/if}
    </div>

    <!-- ── Database ── -->
    <div class="dash-card" class:visible={mounted} style="--delay:140ms;">
      <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Database</p>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {#each [
          { label: 'Total Users',  value: db.users_total,  glow: '34,211,238'   },
          { label: 'Active Users', value: db.users_active, glow: '52,211,153'   },
          { label: 'Total Jobs',   value: db.jobs_total,   glow: '167,139,250'  },
        ] as card}
          <div class="rounded-xl border border-white/8 bg-zinc-950 p-4 transition hover:border-[rgba({card.glow},0.2)]">
            <p class="text-[10px] font-medium uppercase tracking-wider text-slate-600">{card.label}</p>
            <p class="mt-2 text-3xl font-black text-white">{card.value ?? '—'}</p>
          </div>
        {/each}

        {#if jobStatusEntries.length}
          <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
            <p class="mb-3 text-[10px] font-medium uppercase tracking-wider text-slate-600">Jobs by Status</p>
            <div class="space-y-2">
              {#each jobStatusEntries as [s, n]}
                <div class="flex items-center gap-2">
                  <span class="w-14 truncate text-[10px] capitalize text-slate-400">{s}</span>
                  <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/6">
                    <div class="h-full rounded-full bg-violet-400/55 transition-all" style="width:{barPct(n, db.jobs_total)}"></div>
                  </div>
                  <span class="text-[10px] font-bold text-slate-300">{n}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if roleEntries.length}
          <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
            <p class="mb-3 text-[10px] font-medium uppercase tracking-wider text-slate-600">Users by Role</p>
            <div class="space-y-2">
              {#each roleEntries as [r, n]}
                <div class="flex items-center gap-2">
                  <span class="w-14 truncate text-[10px] capitalize text-slate-400">{r}</span>
                  <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/6">
                    <div class="h-full rounded-full bg-cyan-400/55 transition-all" style="width:{barPct(n, db.users_total)}"></div>
                  </div>
                  <span class="text-[10px] font-bold text-slate-300">{n}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>

    <!-- ── AI Job Review ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:160ms;">
      <div class="mb-4 flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">AI Job Review</p>
      </div>
      <p class="mb-4 text-xs text-slate-500">
        Scan all jobs in the database with AI. Non-job entries (spam, seekers, ads) are automatically deleted.
      </p>

      <div class="flex items-center gap-3">
        <button
          type="button"
          onclick={reviewJobs}
          disabled={reviewingJobs}
          class="rounded-lg border border-amber-400/25 bg-amber-400/8 px-4 py-2 text-xs font-bold text-amber-200 transition hover:border-amber-400/45 hover:bg-amber-400/15 disabled:cursor-not-allowed disabled:opacity-35 active:scale-95"
        >
          {reviewingJobs ? 'Reviewing…' : 'Review All Jobs'}
        </button>
        {#if reviewingJobs}
          <span class="text-[10px] text-slate-500 animate-pulse">AI is scanning jobs — this may take a moment…</span>
        {/if}
      </div>

      {#if reviewError}
        <div class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/8 px-3 py-2">
          <p class="text-xs text-rose-300">{reviewError}</p>
        </div>
      {/if}

      {#if reviewResult}
        <div class="mt-4 rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p class="text-[10px] text-slate-600">Total</p>
              <p class="mt-1 text-2xl font-black text-slate-200">{reviewResult.total ?? reviewResult.reviewed}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">Reviewed</p>
              <p class="mt-1 text-2xl font-black text-cyan-300">{reviewResult.reviewed}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">Deleted</p>
              <p class="mt-1 text-2xl font-black {reviewResult.deleted > 0 ? 'text-rose-300' : 'text-emerald-300'}">{reviewResult.deleted}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">Kept</p>
              <p class="mt-1 text-2xl font-black text-emerald-300">{reviewResult.reviewed - reviewResult.deleted}</p>
            </div>
          </div>
          {#if reviewResult.failed_batches > 0}
            <p class="mt-2 text-[10px] text-amber-400">{reviewResult.failed_batches} batch(es) failed — those jobs were kept as-is.</p>
          {/if}

          {#if reviewResult.deleted_jobs?.length > 0}
            <div class="mt-4 border-t border-white/5 pt-3">
              <p class="mb-2 text-[10px] font-bold uppercase tracking-wider text-rose-400">Removed Entries</p>
              <div class="max-h-48 space-y-1.5 overflow-y-auto">
                {#each reviewResult.deleted_jobs as job}
                  <div class="flex items-start gap-2 rounded-lg bg-rose-400/5 px-3 py-2">
                    <span class="mt-0.5 flex-none rounded bg-rose-400/15 px-1.5 py-0.5 font-mono text-[10px] text-rose-400">#{job.id}</span>
                    <div class="min-w-0">
                      <p class="truncate text-xs font-medium text-slate-300">{job.title}</p>
                      <p class="mt-0.5 text-[10px] text-slate-500">{job.reason}</p>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {:else if reviewResult.deleted === 0}
            <p class="mt-3 text-xs text-emerald-400/80">All jobs passed review — database is clean.</p>
          {/if}
        </div>
      {/if}
    </div>

    <!-- ── Request Activity ── -->
    <div class="dash-card" class:visible={mounted} style="--delay:180ms;">
      <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Request Activity</p>
      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {#each [
          { label: 'Total Requests',   value: ev.requests_total,                  cls: 'text-slate-200'  },
          { label: 'API Avg Resp',     value: `${ev.avg_response_ms ?? 0}ms`,     cls: 'text-cyan-300'   },
          { label: 'AI Avg Resp',      value: `${ev.avg_ai_response_ms ?? 0}ms`,  cls: 'text-violet-300' },
          { label: 'Rate Limit Hits',  value: ev.rate_limit_hits ?? 0,            cls: 'text-amber-300'  },
          { label: 'CSRF Rejections',  value: ev.csrf_rejections ?? 0,            cls: 'text-rose-300'   },
        ] as card}
          <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
            <p class="text-[10px] font-medium uppercase tracking-wider text-slate-600">{card.label}</p>
            <p class="mt-2 text-2xl font-black {card.cls}">{card.value}</p>
          </div>
        {/each}
      </div>
      <div class="grid gap-3 lg:grid-cols-2">
        <ScrubChart series={requestTrackerSeries} labels={tsLabels} title="Traffic — requests/min · API resp ms · AI resp ms" height={90} />
        <ScrubChart series={errorTrackerSeries}   labels={tsLabels} title="Error tracker — 4xx · 5xx · rate limits · CSRF"     height={90} />
      </div>
    </div>

    <!-- ── Errors by Module ── -->
    {#if moduleErrorEntries.length}
      <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:220ms;">
        <p class="mb-1 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Errors by Module</p>
        <p class="mb-4 text-[10px] text-slate-700">Cumulative since last restart · sorted by total.</p>
        <div class="space-y-2.5">
          {#each moduleErrorEntries as { module, e4xx, e5xx, total }}
            <div class="flex items-center gap-3">
              <span class="w-20 truncate text-[11px] font-medium text-slate-300">{module}</span>
              <div class="flex flex-1 gap-px overflow-hidden rounded-full bg-white/5" style="height:8px">
                {#if e4xx > 0}
                  <div class="h-full rounded-l-full bg-amber-400/65" style="width:{moduleErrorTotal ? Math.max(2, (e4xx / moduleErrorTotal) * 100) : 0}%" title="{e4xx} client errors (4xx)"></div>
                {/if}
                {#if e5xx > 0}
                  <div class="h-full rounded-r-full bg-rose-400/65" style="width:{moduleErrorTotal ? Math.max(2, (e5xx / moduleErrorTotal) * 100) : 0}%" title="{e5xx} server errors (5xx)"></div>
                {/if}
              </div>
              <div class="flex items-center gap-1.5 text-[10px]">
                <span class="text-amber-300">{e4xx}</span>
                <span class="text-slate-700">/</span>
                <span class="text-rose-300">{e5xx}</span>
                <span class="text-slate-600 ml-1">= {total}</span>
              </div>
            </div>
          {/each}
        </div>
        <div class="mt-3 flex items-center gap-4 border-t border-white/5 pt-3 text-[10px] text-slate-600">
          <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full bg-amber-400/65"></span>4xx (client)</span>
          <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full bg-rose-400/65"></span>5xx (server)</span>
        </div>
        {#if recentModuleErrors.length}
          <div class="mt-4 border-t border-white/5 pt-3">
            <p class="mb-2 text-[10px] font-bold text-slate-600">Recent errors per minute</p>
            <div class="max-h-40 space-y-1.5 overflow-y-auto">
              {#each recentModuleErrors as point}
                <div class="flex items-start gap-3 text-xs">
                  <span class="w-14 flex-none text-[10px] text-slate-700">
                    {new Date(point.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <div class="flex flex-wrap gap-1.5">
                    {#each Object.entries(point.errors_by_module) as [mod, counts]}
                      <span class="rounded-lg border border-white/8 bg-white/4 px-2 py-0.5 text-[10px]">
                        <span class="font-medium text-slate-300">{mod}</span>
                        {#if counts['4xx']}<span class="ml-1 text-amber-400">{counts['4xx']}×4xx</span>{/if}
                        {#if counts['5xx']}<span class="ml-1 text-rose-400">{counts['5xx']}×5xx</span>{/if}
                      </span>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}

    <!-- ── Analytics ── -->
    {#if analyticsData}
      <div class="dash-card" class:visible={mounted} style="--delay:260ms;">
        <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">User Analytics</p>
        <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {#each [
            { label: 'Total Events',   value: analyticsData.total_events ?? 0,                cls: 'text-slate-200'  },
            { label: 'Page Views',     value: analyticsData.page_views?.total ?? 0,           cls: 'text-cyan-300'   },
            { label: 'Button Clicks',  value: analyticsData.button_clicks?.total ?? 0,        cls: 'text-violet-300' },
            { label: 'Chat Messages',  value: (analyticsData.chat?.messages_sent ?? 0) + (analyticsData.chat?.messages_received ?? 0), cls: 'text-emerald-300' },
          ] as card}
            <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
              <p class="text-[10px] font-medium uppercase tracking-wider text-slate-600">{card.label}</p>
              <p class="mt-2 text-2xl font-black {card.cls}">{card.value}</p>
            </div>
          {/each}
        </div>
        <div class="grid gap-3 lg:grid-cols-2">
          {#if topPages.length}
            <div class="rounded-2xl border border-white/8 bg-zinc-950 p-4">
              <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Most Viewed Pages</p>
              <div class="space-y-2">
                {#each topPages as { page, count }}
                  {@const maxCount = topPages[0]?.count ?? 1}
                  <div class="flex items-center gap-3">
                    <span class="w-24 truncate text-[11px] text-slate-300">{page}</span>
                    <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div class="h-full rounded-full bg-cyan-400/45" style="width:{Math.max(4, (count / maxCount) * 100)}%"></div>
                    </div>
                    <span class="text-[11px] font-bold text-cyan-300">{count}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
          {#if topClicks.length}
            <div class="rounded-2xl border border-white/8 bg-zinc-950 p-4">
              <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Most Clicked Buttons</p>
              <div class="space-y-2">
                {#each topClicks as { label, count }}
                  {@const maxCount = topClicks[0]?.count ?? 1}
                  <div class="flex items-center gap-3">
                    <span class="w-28 truncate text-[11px] text-slate-300">{label}</span>
                    <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div class="h-full rounded-full bg-violet-400/45" style="width:{Math.max(4, (count / maxCount) * 100)}%"></div>
                    </div>
                    <span class="text-[11px] font-bold text-violet-300">{count}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
        {#if (analyticsData.chat?.messages_sent ?? 0) > 0 || (analyticsData.chat?.messages_received ?? 0) > 0}
          <div class="mt-3 rounded-2xl border border-white/8 bg-zinc-950 p-4">
            <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Chat Interactions</p>
            <div class="flex gap-6">
              <div>
                <p class="text-[10px] text-slate-600">Sent by user</p>
                <p class="mt-1 text-2xl font-black text-cyan-300">{analyticsData.chat?.messages_sent ?? 0}</p>
              </div>
              <div>
                <p class="text-[10px] text-slate-600">AI responses</p>
                <p class="mt-1 text-2xl font-black text-emerald-300">{analyticsData.chat?.messages_received ?? 0}</p>
              </div>
            </div>
          </div>
        {/if}
      </div>
    {/if}

    <!-- ── User Flows ── -->
    {#if userFlows.length || pageTransitions.length}
      <div class="dash-card" class:visible={mounted} style="--delay:300ms;">
        <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">User Flows</p>
        <div class="grid gap-3 lg:grid-cols-2">
          {#if pageTransitions.length}
            <div class="rounded-2xl border border-white/8 bg-zinc-950 p-4">
              <p class="mb-1 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Page Transitions</p>
              <p class="mb-3 text-[10px] text-slate-700">Most common navigation paths.</p>
              <div class="space-y-2">
                {#each pageTransitions as { from: fromPage, to: toPage, count }}
                  {@const maxCount = pageTransitions[0]?.count ?? 1}
                  <div class="flex items-center gap-2">
                    <span class="w-18 truncate text-right text-[10px] text-slate-300">{fromPage}</span>
                    <span class="text-[10px] text-slate-700">→</span>
                    <span class="w-18 truncate text-[10px] text-slate-300">{toPage}</span>
                    <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div class="h-full rounded-full bg-indigo-400/45" style="width:{Math.max(6, (count / maxCount) * 100)}%"></div>
                    </div>
                    <span class="text-[10px] font-bold text-indigo-300">{count}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
          {#if userFlows.length}
            <div class="rounded-2xl border border-white/8 bg-zinc-950 p-4">
              <p class="mb-1 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Recent Sessions</p>
              <p class="mb-3 text-[10px] text-slate-700">Last {userFlows.length} user sessions.</p>
              <div class="max-h-72 space-y-2.5 overflow-y-auto">
                {#each userFlows as flow}
                  <div class="rounded-xl border border-white/6 bg-white/[0.02] px-3 py-2">
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-mono text-[10px] text-slate-600">{flow.session_id}</span>
                      <span class="text-[10px] text-slate-700">{flow.event_count} events</span>
                    </div>
                    {#if flow.pages.length}
                      <div class="mt-1.5 flex flex-wrap items-center gap-1">
                        {#each flow.pages as page, i}
                          {#if i > 0}<span class="text-[9px] text-slate-700">→</span>{/if}
                          <span class="rounded-md bg-indigo-400/10 px-1.5 py-0.5 text-[10px] text-indigo-300">{page}</span>
                        {/each}
                      </div>
                    {/if}
                    {#if flow.started_at}
                      <p class="mt-1 text-[9px] text-slate-700">{fmtTime(flow.started_at)}</p>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/if}

    <!-- ── Auth + Onboarding ── -->
    <div class="dash-card" class:visible={mounted} style="--delay:340ms;">
      <div class="grid gap-4 lg:grid-cols-2">
        <!-- Authentication -->
        <div>
          <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Authentication</p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <p class="text-[10px] text-slate-600">Successful</p>
                  <p class="mt-1.5 text-2xl font-black text-emerald-300">{ev.logins_success ?? 0}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600">Failed</p>
                  <p class="mt-1.5 text-2xl font-black text-rose-300">{ev.logins_failed ?? 0}</p>
                </div>
              </div>
              {#if loginTotal > 0}
                <div class="mt-4">
                  <div class="h-1.5 overflow-hidden rounded-full bg-white/8">
                    <div class="h-full rounded-full bg-emerald-400 transition-all" style="width:{barPct(ev.logins_success ?? 0, loginTotal)}"></div>
                  </div>
                  <p class="mt-1 text-[10px] text-slate-500">
                    {Math.round(((ev.logins_success ?? 0) / loginTotal) * 100)}% success rate
                  </p>
                </div>
              {/if}
            </div>
            <ScrubChart series={authTrackerSeries} labels={tsLabels} title="Login attempts / min" height={90} />
          </div>
        </div>
        <!-- Onboarding -->
        <div>
          <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Onboarding Funnel</p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-xl border border-white/8 bg-zinc-950 p-4">
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <p class="text-[10px] text-slate-600">Started</p>
                  <p class="mt-1.5 text-2xl font-black text-cyan-300">{ev.onboard_started ?? 0}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600">Completed</p>
                  <p class="mt-1.5 text-2xl font-black text-emerald-300">{ev.onboard_completed ?? 0}</p>
                </div>
              </div>
              {#if onboardPct !== null}
                <div class="mt-4">
                  <div class="h-1.5 overflow-hidden rounded-full bg-white/8">
                    <div class="h-full rounded-full bg-emerald-400 transition-all" style="width:{onboardPct}%"></div>
                  </div>
                  <p class="mt-1 text-[10px] font-bold text-violet-300">{onboardPct}% conversion</p>
                </div>
              {:else}
                <p class="mt-4 text-[10px] text-slate-700">No sessions yet.</p>
              {/if}
            </div>
            <ScrubChart
              series={[{ name: 'Onboard started', color: '#818cf8', data: onboardSeries }]}
              labels={tsLabels}
              title="Onboarding sessions / min"
              height={90}
            />
          </div>
        </div>
      </div>
    </div>

    <!-- ── AI & Matching ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:380ms;">
      <p class="mb-4 text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">AI & Matching</p>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {#each [
          { label: 'Interview Turns',     value: ev.interview_turns,                      cls: 'text-cyan-300'    },
          { label: 'OpenAI Avg Latency',   value: `${ev.avg_ai_response_ms ?? 0}ms`,       cls: 'text-violet-300'  },
          { label: 'Matching Queued',     value: ev.matching_queued,                      cls: 'text-violet-300'  },
          { label: 'Matching Completed',  value: ev.matching_completed,                   cls: 'text-emerald-300' },
          { label: 'Feature Blocks',      value: ev.feature_blocked,                      cls: 'text-amber-300'   },
        ] as row}
          <div class="rounded-xl border border-white/8 bg-black/20 p-3">
            <p class="text-[10px] text-slate-600">{row.label}</p>
            <p class="mt-1.5 text-xl font-black {row.cls}">{row.value ?? 0}</p>
          </div>
        {/each}
      </div>
    </div>

    <!-- ── WhatsApp ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:420ms;">
      <div class="mb-4 flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">WhatsApp</p>
      </div>
      <div class="grid gap-3 lg:grid-cols-2">

        <!-- DB stats -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Sessions (DB)</p>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <p class="text-[10px] text-slate-600">Total Sessions</p>
              <p class="mt-1.5 text-2xl font-black text-emerald-300">{db.whatsapp_sessions_total ?? 0}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">Onboarding</p>
              <p class="mt-1.5 text-2xl font-black text-cyan-300">{db.whatsapp_sessions_by_mode?.onboarding ?? 0}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">In Chat Mode</p>
              <p class="mt-1.5 text-2xl font-black text-violet-300">{db.whatsapp_sessions_by_mode?.chat ?? 0}</p>
            </div>
            <div>
              <p class="text-[10px] text-slate-600">Onboarded %</p>
              <p class="mt-1.5 text-2xl font-black text-amber-300">
                {db.whatsapp_sessions_total
                  ? Math.round(((db.whatsapp_sessions_by_mode?.chat ?? 0) / db.whatsapp_sessions_total) * 100)
                  : 0}%
              </p>
            </div>
          </div>
          {#if (db.whatsapp_sessions_total ?? 0) > 0}
            <div class="mt-3 border-t border-white/5 pt-3">
              <div class="h-1.5 overflow-hidden rounded-full bg-white/8">
                <div
                  class="h-full rounded-full bg-violet-400 transition-all"
                  style="width:{barPct(db.whatsapp_sessions_by_mode?.chat ?? 0, db.whatsapp_sessions_total)}"
                ></div>
              </div>
              <p class="mt-1 text-[10px] text-slate-600">
                <span class="text-violet-300">{db.whatsapp_sessions_by_mode?.chat ?? 0}</span> completed onboarding ·
                <span class="text-cyan-300">{db.whatsapp_sessions_by_mode?.onboarding ?? 0}</span> still in progress
              </p>
            </div>
          {/if}
        </div>

        <!-- Magic tokens + activity -->
        <div class="space-y-3">
          <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
            <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Magic Link Auth</p>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <p class="text-[10px] text-slate-600">Tokens Issued</p>
                <p class="mt-1.5 text-2xl font-black text-slate-200">{db.whatsapp_magic_tokens_total ?? 0}</p>
              </div>
              <div>
                <p class="text-[10px] text-slate-600">Tokens Used</p>
                <p class="mt-1.5 text-2xl font-black text-emerald-300">{db.whatsapp_magic_tokens_used ?? 0}</p>
              </div>
            </div>
            {#if (db.whatsapp_magic_tokens_total ?? 0) > 0}
              <div class="mt-3">
                <div class="h-1.5 overflow-hidden rounded-full bg-white/8">
                  <div
                    class="h-full rounded-full bg-emerald-400 transition-all"
                    style="width:{barPct(db.whatsapp_magic_tokens_used ?? 0, db.whatsapp_magic_tokens_total)}"
                  ></div>
                </div>
                <p class="mt-1 text-[10px] text-slate-600">
                  {Math.round(((db.whatsapp_magic_tokens_used ?? 0) / db.whatsapp_magic_tokens_total) * 100)}% redemption rate
                </p>
              </div>
            {/if}
          </div>

          <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
            <p class="mb-3 text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Activity (since restart)</p>
            <div class="grid grid-cols-2 gap-x-4 gap-y-2.5">
              {#each [
                { label: 'Messages In',    value: ev.whatsapp_messages    ?? 0, cls: 'text-emerald-300' },
                { label: 'Crew Matches',   value: ev.crew_matches         ?? 0, cls: 'text-cyan-300'    },
                { label: 'Apply Drafts',   value: ev.whatsapp_apply_drafts ?? 0, cls: 'text-violet-300' },
                { label: 'Magic Logins',   value: ev.whatsapp_magic_logins ?? 0, cls: 'text-amber-300'  },
              ] as row}
                <div>
                  <p class="text-[10px] text-slate-600">{row.label}</p>
                  <p class="mt-0.5 text-xl font-black {row.cls}">{row.value}</p>
                </div>
              {/each}
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- ── PayFast Test ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:450ms;">
      <div class="mb-4 flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full bg-cyan-400"></span>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">PayFast Subscription Test</p>
      </div>

      <div class="grid gap-3 lg:grid-cols-3">
        <!-- Checkout -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <p class="mb-2 text-xs font-bold text-slate-200">Checkout</p>
          <p class="mb-3 text-[10px] text-slate-600">POST /subscription/checkout</p>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              onclick={() => pfCheckout(false)}
              disabled={pfLoading}
              class="rounded-lg border border-cyan-400/25 bg-cyan-400/8 px-3 py-1.5 text-xs font-bold text-cyan-200 transition hover:border-cyan-400/45 hover:bg-cyan-400/15 disabled:opacity-35 active:scale-95"
            >
              {pfLoading ? 'Loading...' : 'Get Data'}
            </button>
            <button
              type="button"
              onclick={() => pfCheckout(true)}
              disabled={pfLoading}
              class="rounded-lg border border-emerald-400/25 bg-emerald-400/8 px-3 py-1.5 text-xs font-bold text-emerald-200 transition hover:border-emerald-400/45 hover:bg-emerald-400/15 disabled:opacity-35 active:scale-95"
            >
              {pfLoading ? 'Redirecting...' : 'Go to PayFast'}
            </button>
          </div>
        </div>

        <!-- Status -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <p class="mb-2 text-xs font-bold text-slate-200">Status</p>
          <p class="mb-3 text-[10px] text-slate-600">GET /subscription/status</p>
          <button
            type="button"
            onclick={pfStatus}
            class="rounded-lg border border-violet-400/25 bg-violet-400/8 px-3 py-1.5 text-xs font-bold text-violet-200 transition hover:border-violet-400/45 hover:bg-violet-400/15 active:scale-95"
          >
            Check Status
          </button>
          {#if pfSubStatus}
            <div class="mt-3">
              {#if pfSubStatus.error}
                <span class="rounded-full bg-rose-400/15 px-2 py-0.5 text-[10px] font-bold text-rose-300">{pfSubStatus.error}</span>
              {:else if pfSubStatus.subscribed}
                <span class="rounded-full bg-emerald-400/15 px-2 py-0.5 text-[10px] font-bold text-emerald-300">Active</span>
                {#if pfSubStatus.next_billing_date}
                  <p class="mt-1 text-[10px] text-slate-500">Next bill: {pfSubStatus.next_billing_date}</p>
                {/if}
              {:else}
                <span class="rounded-full bg-slate-700 px-2 py-0.5 text-[10px] font-bold text-slate-400">Not subscribed</span>
              {/if}
            </div>
          {/if}
        </div>

        <!-- Cancel -->
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 p-4">
          <p class="mb-2 text-xs font-bold text-slate-200">Cancel</p>
          <p class="mb-3 text-[10px] text-slate-600">POST /subscription/cancel</p>
          <button
            type="button"
            onclick={pfCancel}
            disabled={pfCancelling}
            class="rounded-lg border border-rose-400/25 bg-rose-400/8 px-3 py-1.5 text-xs font-bold text-rose-200 transition hover:border-rose-400/45 hover:bg-rose-400/15 disabled:opacity-35 active:scale-95"
          >
            {pfCancelling ? 'Cancelling...' : 'Cancel Sub'}
          </button>
        </div>
      </div>

      {#if pfError}
        <div class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{pfError}</div>
      {/if}

      {#if pfResult}
        <div class="mt-3 rounded-lg border border-white/8 bg-black/40 p-3">
          <p class="mb-1 text-[10px] font-bold text-slate-500">Response</p>
          <pre class="max-h-48 overflow-auto text-[10px] leading-relaxed text-slate-400">{JSON.stringify(pfResult, null, 2)}</pre>
        </div>
      {/if}
    </div>

    <!-- ── Error Log ── -->
    <div class="dash-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:460ms;">
      <div class="mb-4 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-rose-400"></span>
          <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Error Log</p>
          {#if errorLogs.length > 0}
            <span class="rounded-full bg-rose-400/15 px-2 py-0.5 text-[10px] font-bold text-rose-400">{errorLogs.length}</span>
          {/if}
        </div>
        <button
          type="button"
          onclick={loadErrors}
          disabled={loadingErrors}
          class="rounded-xl border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-semibold text-slate-400 transition hover:border-white/20 hover:text-white active:scale-95 disabled:opacity-40"
        >
          {loadingErrors ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {#if loadingErrors && errorLogs.length === 0}
        <p class="text-xs text-slate-600">Loading errors…</p>
      {:else if errorLogs.length === 0}
        <div class="rounded-xl border border-white/8 bg-zinc-900/50 px-4 py-6 text-center">
          <p class="text-xs text-slate-600">No errors recorded yet.</p>
        </div>
      {:else}
        <div class="space-y-2">
          {#each errorLogs as entry (entry.id)}
            {@const is5xx = (entry.status_code ?? 0) >= 500}
            <div class="rounded-xl border {is5xx ? 'border-rose-400/20' : 'border-amber-400/15'} bg-zinc-900/50 p-3">

              <!-- top row: badge + path + time + expand toggle -->
              <div class="flex flex-wrap items-start justify-between gap-2">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold {is5xx ? 'bg-rose-400/15 text-rose-300' : 'bg-amber-400/15 text-amber-300'}">
                    {entry.status_code ?? '???'}
                  </span>
                  {#if entry.method}
                    <span class="font-mono text-[10px] text-slate-500">{entry.method}</span>
                  {/if}
                  <span class="max-w-[260px] truncate font-mono text-xs text-slate-400">{entry.path ?? '—'}</span>
                  {#if entry.module}
                    <span class="rounded bg-white/6 px-1.5 py-0.5 text-[10px] text-slate-500">{entry.module}</span>
                  {/if}
                  {#if entry.crv_code}
                    <span class="font-mono text-[10px] text-slate-600">{entry.crv_code}</span>
                  {/if}
                </div>
                <div class="flex shrink-0 items-center gap-2">
                  <span class="text-[10px] text-slate-600">{fmtRelTime(entry.created_at)}</span>
                  {#if entry.traceback}
                    <button
                      type="button"
                      onclick={() => expandedError = expandedError === entry.id ? null : entry.id}
                      class="rounded px-1.5 py-0.5 text-[10px] text-slate-500 transition hover:bg-white/6 hover:text-slate-300"
                    >
                      {expandedError === entry.id ? 'Hide trace' : 'Trace'}
                    </button>
                  {/if}
                </div>
              </div>

              <!-- message -->
              <p class="mt-1.5 text-xs {is5xx ? 'text-rose-300' : 'text-amber-300'}">{entry.message}</p>

              <!-- AI analysis -->
              {#if entry.ai_analysis}
                <div class="mt-2.5 rounded-lg border border-violet-400/20 bg-violet-400/5 p-3">
                  <p class="mb-1 text-[10px] font-bold uppercase tracking-wider text-violet-400">AI Analysis</p>
                  <p class="whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{entry.ai_analysis}</p>
                </div>
              {/if}

              <!-- analyze button -->
              <div class="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onclick={() => analyzeError(entry.id)}
                  disabled={analyzingId === entry.id}
                  class="rounded-lg border border-violet-400/25 bg-violet-400/8 px-2.5 py-1 text-[10px] font-semibold text-violet-300 transition hover:border-violet-400/40 hover:bg-violet-400/15 active:scale-95 disabled:opacity-40"
                >
                  {analyzingId === entry.id ? 'Analyzing…' : entry.ai_analysis ? 'Re-analyze' : 'Analyze with AI'}
                </button>
                {#if entry.request_id}
                  <span class="font-mono text-[10px] text-slate-700">req:{entry.request_id}</span>
                {/if}
              </div>

              <!-- traceback (expanded) -->
              {#if expandedError === entry.id && entry.traceback}
                <div class="mt-3 overflow-x-auto rounded-lg bg-black/50 p-3">
                  <pre class="text-[10px] leading-relaxed text-slate-400 whitespace-pre">{entry.traceback}</pre>
                </div>
              {/if}

            </div>
          {/each}
        </div>
      {/if}
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
    background: linear-gradient(90deg, transparent, rgba(167,139,250,0.28), transparent);
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

  .dash-card {
    opacity: 0;
    transform: translateY(12px);
    transition: opacity 0.45s ease, transform 0.45s ease;
    transition-delay: var(--delay, 0ms);
  }
  .dash-card.visible {
    opacity: 1;
    transform: translateY(0);
  }
</style>
