<script>
  import '../app.css';
</script>

<div class="min-h-screen bg-black text-white">
  <header class="py-8 px-8 header-glow">
    <div class="max-w-6xl mx-auto flex justify-between items-center">
      <div class="w-1/3"></div>
      <div class="w-1/3 text-center">
        <a href="/" class="text-5xl font-thin tracking-[0.2em] hover:opacity-80 transition-all duration-300 hover:text-shadow-glow">CARVER</a>
      </div>
      <div class="w-1/3 flex justify-end space-x-8">
        <a href="/login" class="text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors">Login</a>
        <a href="/register" class="text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors">Sign Up</a>
      </div>
    </div>
  </header>

  <nav class="max-w-6xl mx-auto px-8 mb-16">
    <div class="flex justify-center space-x-16 border-b border-gray-900 pb-1 relative">
      <a href="/" class="py-3 px-2 text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors border-b-2 border-transparent hover:border-gray-600">Job Board</a>
      <a href="/subscription" class="py-3 px-2 text-sm font-light nav-link-enhanced hover:text-gray-400 transition-colors border-b-2 border-transparent hover:border-gray-600">Subscription</a>
    </div>
  </nav>

  <main class="max-w-6xl mx-auto px-8 pb-16">
    <slot />
  </main>
</div>

<style>
  .hover\:text-shadow-glow:hover {
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.4);
  }
</style> 