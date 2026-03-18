<script>
  import { site } from '../../config/site'
  let { currentPage = 'auto-apply', userRole = '', isSubscribed = false, onNavigate = () => {}, onLogout = null } = $props()

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

<header class="sticky top-0 z-10 border-b border-white/10 bg-black/90 backdrop-blur">
  <div class="mx-auto w-full max-w-7xl px-4 py-3 sm:px-6 md:px-8">

    <!-- Desktop nav -->
    <div class="hidden sm:grid sm:grid-cols-3 sm:items-center">
      <nav class="flex gap-2 text-xs sm:gap-3 sm:text-sm">
        {#each visibleNav as item}
          <button
            type="button"
            class={`rounded-md px-3 py-1.5 transition-colors ${
              currentPage === item.key
                ? 'bg-white/10 text-white'
                : 'text-slate-400 hover:bg-white/5 hover:text-white'
            }`}
            onclick={() => navigate(item.key)}
          >
            {item.label}
          </button>
        {/each}
      </nav>
      <p class="text-center text-sm font-semibold tracking-[0.2em] text-slate-100">CARVER</p>
      <div class="flex justify-end">
        {#if onLogout}
          <button
            type="button"
            class="rounded-md border border-white/15 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/30 hover:text-white"
            onclick={onLogout}
          >
            Logout
          </button>
        {/if}
      </div>
    </div>

    <!-- Mobile nav bar -->
    <div class="flex items-center justify-between sm:hidden">
      <button
        type="button"
        class="rounded-md p-1.5 text-slate-400 hover:text-white"
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
      <p class="text-sm font-semibold tracking-[0.2em] text-slate-100">CARVER</p>
      {#if onLogout}
        <button
          type="button"
          class="rounded-md border border-white/15 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/30 hover:text-white"
          onclick={onLogout}
        >
          Logout
        </button>
      {:else}
        <div class="w-16"></div>
      {/if}
    </div>
  </div>

  <!-- Mobile dropdown -->
  {#if mobileOpen}
    <nav class="border-t border-white/10 bg-black/95 px-4 pb-3 pt-2 sm:hidden">
      {#each visibleNav as item}
        <button
          type="button"
          class={`block w-full rounded-md px-3 py-2.5 text-left text-sm transition-colors ${
            currentPage === item.key
              ? 'bg-white/10 text-white'
              : 'text-slate-400 hover:bg-white/5 hover:text-white'
          }`}
          onclick={() => navigate(item.key)}
        >
          {item.label}
        </button>
      {/each}
    </nav>
  {/if}
</header>
