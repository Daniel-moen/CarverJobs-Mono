<script>
  import { site } from '../../config/site'
  let { currentPage = 'auto-apply', userRole = '', isSubscribed = false, creditsBalance = 0, onNavigate = () => {}, onLogout = null } = $props()

  const visibleNav = $derived(
    site.nav.filter(item =>
      (!item.adminOnly || userRole === 'admin') &&
      (!item.hideWhenSubscribed || !isSubscribed)
    )
  )

  let mobileOpen = $state(false)

  function navigate(key) {
    onNavigate(key)
    mobileOpen = false
  }
</script>

<header class="sticky top-0 z-20 border-b border-white/[0.06] bg-[#04070b]/80 backdrop-blur-xl supports-[backdrop-filter]:bg-[#04070b]/65">
  <div class="mx-auto w-full max-w-7xl px-4 py-3 sm:px-6 md:px-8">

    <!-- Desktop nav -->
    <div class="hidden sm:grid sm:grid-cols-3 sm:items-center">
      <nav class="flex items-center gap-1 text-sm">
        {#each visibleNav as item}
          <button
            type="button"
            class={`relative rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
              currentPage === item.key
                ? 'text-white'
                : 'text-slate-400 hover:text-white'
            }`}
            onclick={() => navigate(item.key)}
          >
            {item.label}
            {#if currentPage === item.key}
              <span class="absolute inset-x-3 -bottom-[13px] h-px bg-cyan-300/70" aria-hidden="true"></span>
            {/if}
          </button>
        {/each}
      </nav>

      <a
        href="/"
        onclick={(e) => { e.preventDefault(); navigate('auto-apply') }}
        class="group flex items-center justify-center gap-3 select-none"
        aria-label="Carver home"
      >
        <span class="relative flex h-2 w-2 items-center justify-center">
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/50 opacity-60"></span>
          <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        </span>
        <span class="flex items-baseline gap-1.5">
          <span class="wordmark text-[14px] text-ivory transition group-hover:text-white">CARVER</span>
          <span class="font-display text-[12px] italic text-cyan-200/60 transition group-hover:text-cyan-100/80">v3</span>
        </span>
      </a>

      <div class="flex items-center justify-end gap-2.5">
        {#if userRole === 'crew'}
          <div class="flex items-center gap-1.5 rounded-full border border-cyan-300/20 bg-cyan-300/[0.06] px-3 py-1 text-[11px] font-semibold text-cyan-100">
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 9.5h4a2 2 0 0 1 0 4H9.5a2 2 0 0 0 0 4H15"/></svg>
            <span>{creditsBalance}<span class="ml-0.5 text-cyan-200/70 font-normal">{creditsBalance === 1 ? 'token' : 'tokens'}</span></span>
          </div>
        {/if}
        {#if onLogout}
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.02] px-3 py-1.5 text-[11px] font-medium text-slate-300 transition hover:border-white/25 hover:bg-white/[0.05] hover:text-white"
            onclick={onLogout}
          >
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            Sign out
          </button>
        {/if}
      </div>
    </div>

    <!-- Mobile nav bar -->
    <div class="flex items-center justify-between sm:hidden">
      <button
        type="button"
        class="rounded-lg p-2 text-slate-400 hover:text-white active:text-white"
        onclick={() => (mobileOpen = !mobileOpen)}
        aria-label="Toggle menu"
      >
        {#if mobileOpen}
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        {:else}
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        {/if}
      </button>

      <a
        href="/"
        onclick={(e) => { e.preventDefault(); navigate('auto-apply') }}
        class="flex items-center gap-2.5"
        aria-label="Carver home"
      >
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-300"></span>
        <span class="flex items-baseline gap-1.5">
          <span class="wordmark text-[13px] text-ivory">CARVER</span>
          <span class="font-display text-[11px] italic text-cyan-200/60">v3</span>
        </span>
      </a>

      {#if onLogout}
        <div class="flex items-center gap-2">
          {#if userRole === 'crew'}
            <div class="rounded-full border border-cyan-300/25 bg-cyan-300/[0.06] px-2.5 py-1 text-[10px] font-semibold text-cyan-100">
              {creditsBalance}
            </div>
          {/if}
          <button
            type="button"
            class="rounded-full border border-white/15 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-white/30 hover:text-white"
            onclick={onLogout}
            aria-label="Sign out"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          </button>
        </div>
      {:else}
        <div class="w-9"></div>
      {/if}
    </div>
  </div>

  <!-- Mobile dropdown -->
  {#if mobileOpen}
    <nav class="mobile-menu border-t border-white/[0.06] bg-[#04070b]/95 px-4 pb-4 pt-2 sm:hidden">
      {#each visibleNav as item}
        <button
          type="button"
          class={`block w-full rounded-lg px-4 py-3 text-left text-sm font-medium transition-colors active:bg-white/10 ${
            currentPage === item.key
              ? 'bg-white/[0.06] text-white'
              : 'text-slate-400 hover:bg-white/[0.04] hover:text-white'
          }`}
          onclick={() => navigate(item.key)}
        >
          {item.label}
        </button>
      {/each}
    </nav>
  {/if}
</header>

<style>
  .mobile-menu {
    animation: slideDown 0.18s ease-out;
  }
  @keyframes slideDown {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
