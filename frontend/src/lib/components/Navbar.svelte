<script lang="ts">
  export let active: 'home' | 'subscription' | 'login' | 'register' | undefined;
</script>

<header class="py-6 px-6 header-glow">
  <div class="max-w-6xl mx-auto flex justify-between items-center">
    <div class="w-1/3"></div>
    <div class="w-1/3 text-center">
      <a href="/" aria-label="CarverJobs Home" class="text-4xl md:text-5xl font-thin tracking-[0.2em] hover:opacity-80 transition-all duration-300 hover:text-shadow-glow">CARVER</a>
    </div>
    <nav class="w-1/3 flex justify-end items-center gap-6" aria-label="Primary">
      <a href="/login" class="text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors {active==='login' ? 'text-white' : ''}">Login</a>
      <a href="/register" class="text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors {active==='register' ? 'text-white' : ''}">Sign Up</a>
    </nav>
  </div>
</header>

<nav class="max-w-6xl mx-auto px-6 mb-10" aria-label="Sections">
  <div class="flex justify-center gap-12 divider pb-1">
    <a href="/" class="py-3 px-2 text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors border-b-2 border-transparent hover:border-gray-500 {active==='home' ? 'border-gray-500' : ''}">Job Board</a>
    <a href="/subscription" class="py-3 px-2 text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors border-b-2 border-transparent hover:border-gray-500 {active==='subscription' ? 'border-gray-500' : ''}">Subscription</a>
  </div>
</nav>
