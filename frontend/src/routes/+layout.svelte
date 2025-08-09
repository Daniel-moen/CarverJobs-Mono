<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  
  let isMenuOpen = false;
  
  // Mock auth state - replace with actual auth store
  let isAuthenticated = false;
  let user: any = null;
  
  function logout() {
    // Clear auth state
    isAuthenticated = false;
    user = null;
    localStorage.removeItem('auth_token');
    goto('/');
  }
</script>

<div class="min-h-screen bg-gray-50">
  <!-- Navigation -->
  <nav class="bg-white shadow-sm border-b border-gray-200">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex justify-between h-16">
        <div class="flex items-center">
          <a href="/" class="flex items-center space-x-2">
            <div class="w-8 h-8 bg-marine-600 rounded-lg flex items-center justify-center">
              <span class="text-white font-bold text-sm">CJ</span>
            </div>
            <span class="text-xl font-bold text-gray-900">CarverJobs</span>
          </a>
        </div>
        
        <!-- Desktop Navigation -->
        <div class="hidden md:flex items-center space-x-8">
          <a href="/jobs" class="text-gray-700 hover:text-marine-600 transition-colors">Jobs</a>
          <a href="/about" class="text-gray-700 hover:text-marine-600 transition-colors">About</a>
          
          {#if isAuthenticated}
            <div class="flex items-center space-x-4">
              <span class="text-sm text-gray-600">Welcome, {user?.first_name}</span>
              <button on:click={logout} class="btn btn-secondary text-sm">Logout</button>
            </div>
          {:else}
            <div class="flex items-center space-x-4">
              <a href="/login" class="text-gray-700 hover:text-marine-600 transition-colors">Login</a>
              <a href="/register" class="btn btn-primary text-sm">Sign Up</a>
            </div>
          {/if}
        </div>
        
        <!-- Mobile menu button -->
        <div class="md:hidden flex items-center">
          <button
            on:click={() => isMenuOpen = !isMenuOpen}
            class="text-gray-500 hover:text-gray-700 p-2"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                    d={isMenuOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
            </svg>
          </button>
        </div>
      </div>
    </div>
    
    <!-- Mobile Navigation -->
    {#if isMenuOpen}
      <div class="md:hidden bg-white border-t border-gray-200">
        <div class="px-2 pt-2 pb-3 space-y-1">
          <a href="/jobs" class="block px-3 py-2 text-gray-700 hover:bg-gray-50 rounded-md">Jobs</a>
          <a href="/about" class="block px-3 py-2 text-gray-700 hover:bg-gray-50 rounded-md">About</a>
          
          {#if isAuthenticated}
            <div class="border-t border-gray-200 pt-2 mt-2">
              <span class="block px-3 py-2 text-sm text-gray-600">Welcome, {user?.first_name}</span>
              <button on:click={logout} class="block w-full text-left px-3 py-2 text-gray-700 hover:bg-gray-50 rounded-md">Logout</button>
            </div>
          {:else}
            <div class="border-t border-gray-200 pt-2 mt-2">
              <a href="/login" class="block px-3 py-2 text-gray-700 hover:bg-gray-50 rounded-md">Login</a>
              <a href="/register" class="block px-3 py-2 text-gray-700 hover:bg-gray-50 rounded-md">Sign Up</a>
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </nav>
  
  <!-- Main Content -->
  <main>
    <slot />
  </main>
  
  <!-- Footer -->
  <footer class="bg-gray-900 text-white mt-16">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
        <div>
          <div class="flex items-center space-x-2 mb-4">
            <div class="w-8 h-8 bg-marine-600 rounded-lg flex items-center justify-center">
              <span class="text-white font-bold text-sm">CJ</span>
            </div>
            <span class="text-xl font-bold">CarverJobs</span>
          </div>
          <p class="text-gray-400">Find your next marine job opportunity</p>
        </div>
        
        <div>
          <h3 class="font-semibold mb-4">Quick Links</h3>
          <ul class="space-y-2 text-gray-400">
            <li><a href="/jobs" class="hover:text-white transition-colors">Browse Jobs</a></li>
            <li><a href="/about" class="hover:text-white transition-colors">About Us</a></li>
            <li><a href="/contact" class="hover:text-white transition-colors">Contact</a></li>
          </ul>
        </div>
        
        <div>
          <h3 class="font-semibold mb-4">Job Categories</h3>
          <ul class="space-y-2 text-gray-400">
            <li><a href="/jobs?type=deck" class="hover:text-white transition-colors">Deck Officers</a></li>
            <li><a href="/jobs?type=engine" class="hover:text-white transition-colors">Engineers</a></li>
            <li><a href="/jobs?type=catering" class="hover:text-white transition-colors">Catering</a></li>
          </ul>
        </div>
      </div>
      
      <div class="border-t border-gray-800 mt-8 pt-8 text-center text-gray-400">
        <p>&copy; 2024 CarverJobs. All rights reserved.</p>
      </div>
    </div>
  </footer>
</div> 