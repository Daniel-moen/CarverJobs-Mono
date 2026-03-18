<script>
  /**
   * ScrubChart — multi-line SVG chart with mouse scrubbing.
   *
   * Props:
   *   series  — Array of { name: string, color: string, data: number[] }
   *   labels  — Array of time-strings, one per data point (same length as data)
   *   title   — Section heading shown above the chart
   *   height  — SVG render height in px (default 90)
   */
  let { series = [], labels = [], title = '', height = 90 } = $props()

  const W = 400   // SVG viewport width (scales with CSS)
  const H = $derived(height)

  // ── Derived geometry ────────────────────────────────────────────────────────

  const n         = $derived(series[0]?.data?.length ?? 0)
  const maxVal    = $derived(Math.max(1, ...series.flatMap(s => s.data ?? [])))
  const hasData   = $derived(n > 1)

  function toX(i) {
    return n <= 1 ? 0 : (i / (n - 1)) * W
  }
  function toY(v) {
    const pad = 4
    return (H - pad) - (Math.max(0, v) / maxVal) * (H - pad * 2)
  }
  function points(data) {
    return (data ?? []).map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ')
  }
  function areaPath(data) {
    if (!data?.length) return ''
    return `${points(data)} ${W},${H} 0,${H}`
  }

  // ── Scrubbing state ─────────────────────────────────────────────────────────

  let containerEl  = $state(null)
  let hoverIndex   = $state(-1)
  let scrubPct     = $state(0)   // 0–1, used for tooltip left position

  function scrubTo(clientX) {
    if (!containerEl || n === 0) return
    const rect = containerEl.getBoundingClientRect()
    const pct  = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    hoverIndex = Math.round(pct * (n - 1))
    scrubPct   = hoverIndex / Math.max(n - 1, 1)
  }
  function onMouseMove(e) { scrubTo(e.clientX) }
  function onMouseLeave() { hoverIndex = -1 }

  function onTouchMove(e) {
    e.preventDefault()
    scrubTo(e.touches[0].clientX)
  }
  function onTouchEnd() { hoverIndex = -1 }

  // Tooltip flip: if scrub is past 60% from left, show tooltip on the left side.
  const tooltipLeft  = $derived(scrubPct < 0.6)
  const scrubSvgX    = $derived(scrubPct * W)
</script>

<div class="rounded-xl border border-white/10 bg-zinc-950 p-4">
  <!-- Title + legend ────────────────────────────────────────────────────── -->
  <div class="mb-3 flex flex-wrap items-start justify-between gap-2">
    <p class="text-xs text-slate-400">{title}</p>
    <div class="flex flex-wrap gap-3">
      {#each series as s}
        <span class="flex items-center gap-1.5 text-[10px] text-slate-400">
          <span class="inline-block h-1.5 w-4 rounded-full" style="background:{s.color}"></span>
          {s.name}
        </span>
      {/each}
    </div>
  </div>

  {#if !hasData}
    <div class="flex items-center justify-center text-xs text-slate-600"
         style="height:{height}px">
      Collecting — graphs appear after the first minute
    </div>
  {:else}
    <!-- Chart container: mouse events captured here ───────────────────── -->
    <div
      class="relative select-none"
      bind:this={containerEl}
      onmousemove={onMouseMove}
      onmouseleave={onMouseLeave}
      ontouchmove={onTouchMove}
      ontouchend={onTouchEnd}
      role="img"
      aria-label={title}
    >
      <!-- SVG ──────────────────────────────────────────────────────────── -->
      <svg
        viewBox="0 0 {W} {H}"
        preserveAspectRatio="none"
        class="w-full overflow-visible"
        style="height:{height}px"
        aria-hidden="true"
      >
        <!-- Grid lines -->
        {#each [0.25, 0.5, 0.75] as f}
          <line x1="0" y1={H * f} x2={W} y2={H * f}
                stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        {/each}

        <!-- Area fills (faint) + lines for each series -->
        {#each series as s}
          <polygon points={areaPath(s.data)} fill={s.color} opacity="0.08" />
        {/each}
        {#each series as s}
          <polyline
            points={points(s.data)}
            fill="none"
            stroke={s.color}
            stroke-width="1.8"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
        {/each}

        <!-- Scrub cursor -->
        {#if hoverIndex >= 0}
          <line
            x1={scrubSvgX} y1="0"
            x2={scrubSvgX} y2={H}
            stroke="rgba(255,255,255,0.25)"
            stroke-width="1"
            stroke-dasharray="3 2"
          />
          <!-- Dots for each series at the hovered index -->
          {#each series as s}
            {@const v  = s.data[hoverIndex] ?? 0}
            {@const cx = scrubSvgX}
            {@const cy = toY(v)}
            <circle {cx} {cy} r="3.5" fill={s.color} stroke="#09090b" stroke-width="1.5" />
          {/each}
        {/if}
      </svg>

      <!-- Tooltip (HTML, absolutely positioned) ────────────────────────── -->
      {#if hoverIndex >= 0}
        <div
          class="pointer-events-none absolute top-0 z-10 min-w-[130px] rounded-lg
                 border border-white/10 bg-zinc-900 px-3 py-2 shadow-xl"
          style="
            {tooltipLeft ? 'right' : 'left'}: calc({tooltipLeft ? (1 - scrubPct) * 100 : scrubPct * 100}% + 10px);
            transform: translateY(4px);
          "
        >
          <p class="mb-1.5 text-[10px] text-slate-500">{labels[hoverIndex] ?? ''}</p>
          {#each series as s}
            <div class="flex items-center justify-between gap-3">
              <span class="flex items-center gap-1.5 text-[11px] text-slate-400">
                <span class="inline-block h-1.5 w-2.5 rounded-full flex-none" style="background:{s.color}"></span>
                {s.name}
              </span>
              <span class="text-[11px] font-semibold" style="color:{s.color}">
                {s.data[hoverIndex] ?? 0}
              </span>
            </div>
          {/each}
        </div>
      {/if}

      <!-- X-axis time labels ───────────────────────────────────────────── -->
      <div class="relative mt-1 h-3 text-[9px] text-slate-600">
        {#if labels.length}
          <span class="absolute left-0">{labels[0]}</span>
          {#if labels.length > 2}
            <span class="absolute left-1/2 -translate-x-1/2">{labels[Math.floor(labels.length / 2)]}</span>
          {/if}
          <span class="absolute right-0">{labels[labels.length - 1]}</span>
        {/if}
      </div>
    </div>
  {/if}
</div>
