<script>
  import '../app.css';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Search, Menu, X, User, LogOut, Anchor } from 'lucide-svelte';
  
  let isMenuOpen = false;
  let isAuthenticated = false;
  let user = null;
  
  function logout() {
    isAuthenticated = false;
    user = null;
    localStorage.removeItem('auth_token');
    goto('/');
  }
  
  function toggleMenu() {
    isMenuOpen = !isMenuOpen;
  }
</script>

<div class="min-h-screen bg-dark-950 text-dark-50">
  <!-- Navigation -->
  <nav class="glass-nav sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16">
        <!-- Logo -->
        <a href="/" class="flex items-center space-x-3 group">
          <div class="relative">
            <Anchor class="w-8 h-8 text-marine-400 group-hover:text-marine-300 transition-colors" />
            <div class="absolute inset-0 blur-md bg-marine-400/20 group-hover:bg-marine-300/30 transition-all rounded-full"></div>
          </div>
          <span class="text-xl font-bold text-gradient">CarverJobs</span>
        </a>
        
        <!-- Desktop Navigation -->
        <div class="hidden md:flex items-center space-x-8">
          <a href="/jobs" class="nav-link" class:nav-link-active={$page.url.pathname === '/jobs'}>
            Jobs
          </a>
          <a href="/about" class="nav-link" class:nav-link-active={$page.url.pathname === '/about'}>
            About
          </a>
          
          {#if isAuthenticated}
            <div class="flex items-center space-x-4">
              <button class="nav-link flex items-center space-x-2">
                <User class="w-4 h-4" />
                <span>{user?.first_name}</span>
              </button>
              <button on:click={logout} class="btn btn-ghost">
                <LogOut class="w-4 h-4" />
              </button>
            </div>
          {:else}
            <div class="flex items-center space-x-4">
              <a href="/login" class="nav-link">Login</a>
              <a href="/register" class="btn btn-outline">Sign Up</a>
            </div>
          {/if}
        </div>
        
        <!-- Mobile menu button -->
        <button
          on:click={toggleMenu}
          class="md:hidden p-2 rounded-lg text-dark-400 hover:text-dark-100 hover:bg-dark-800 transition-all"
        >
          {#if isMenuOpen}
            <X class="w-6 h-6" />
          {:else}
            <Menu class="w-6 h-6" />
          {/if}
        </button>
      </div>
    </div>
    
    <!-- Mobile Navigation -->
    {#if isMenuOpen}
      <div class="md:hidden glass border-t border-dark-800/50 animate-slide-up">
        <div class="px-4 py-6 space-y-4">
          <a href="/jobs" class="block nav-link py-2" class:nav-link-active={$page.url.pathname === '/jobs'}>
            Jobs
          </a>
          <a href="/about" class="block nav-link py-2" class:nav-link-active={$page.url.pathname === '/about'}>
            About
          </a>
          
          <div class="border-t border-dark-800 pt-4 mt-4">
            {#if isAuthenticated}
              <div class="space-y-3">
                <div class="flex items-center space-x-2 text-dark-300">
                  <User class="w-4 h-4" />
                  <span>{user?.first_name}</span>
                </div>
                <button on:click={logout} class="btn btn-ghost w-full justify-start">
                  <LogOut class="w-4 h-4 mr-2" />
                  Logout
                </button>
              </div>
            {:else}
              <div class="space-y-3">
                <a href="/login" class="block nav-link py-2">Login</a>
                <a href="/register" class="btn btn-outline w-full">Sign Up</a>
              </div>
            {/if}
          </div>
        </div>
      </div>
    {/if}
  </nav>
  
  <!-- Main Content -->
  <main class="min-h-screen">
    <slot />
  </main>
  
  <!-- Footer -->
  <footer class="border-t border-dark-800 bg-dark-950/50 backdrop-blur-sm mt-20">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-8">
        <!-- Brand -->
        <div class="md:col-span-2">
          <div class="flex items-center space-x-3 mb-4">
            <Anchor class="w-8 h-8 text-marine-400" />
            <span class="text-xl font-bold text-gradient">CarverJobs</span>
          </div>
          <p class="text-dark-400 text-sm max-w-md">
            Find your next marine career opportunity. Connect with vessels worldwide and advance your maritime profession.
          </p>
        </div>
        
        <!-- Quick Links -->
        <div>
          <h3 class="font-semibold text-dark-200 mb-4">Quick Links</h3>
          <ul class="space-y-2">
            <li><a href="/jobs" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">Browse Jobs</a></li>
            <li><a href="/about" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">About Us</a></li>
            <li><a href="/contact" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">Contact</a></li>
          </ul>
        </div>
        
        <!-- Job Categories -->
        <div>
          <h3 class="font-semibold text-dark-200 mb-4">Categories</h3>
          <ul class="space-y-2">
            <li><a href="/jobs?type=deck" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">Deck Officers</a></li>
            <li><a href="/jobs?type=engine" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">Engineers</a></li>
            <li><a href="/jobs?type=interior" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">Interior</a></li>
            <li><a href="/jobs?type=crew" class="text-dark-400 hover:text-marine-400 transition-colors text-sm">General Crew</a></li>
          </ul>
        </div>
      </div>
      
      <!-- Bottom Bar -->
      <div class="border-t border-dark-800 mt-8 pt-8 flex flex-col sm:flex-row justify-between items-center">
        <p class="text-dark-500 text-sm">&copy; 2024 CarverJobs. All rights reserved.</p>
        <div class="flex items-center space-x-4 mt-4 sm:mt-0">
          <span class="text-dark-500 text-sm">Built for seafarers</span>
          <div class="w-2 h-2 bg-marine-500 rounded-full animate-pulse"></div>
        </div>
      </div>
    </div>
  </footer>
</div> 