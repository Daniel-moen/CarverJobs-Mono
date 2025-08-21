<script>
  import '../app.css';
  import Navbar from '$lib/components/Navbar.svelte';
  import Footer from '$lib/components/Footer.svelte';
</script>

<div class="min-h-screen bg-black text-white flex flex-col">
  <Navbar />
  <main class="max-w-6xl mx-auto px-6 pb-16 flex-1 w-full">
    <slot />
  </main>
  <Footer />
</div>

<style>
  .hover\:text-shadow-glow:hover {
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.4);
  }
</style> 
