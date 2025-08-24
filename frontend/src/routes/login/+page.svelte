<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { api, ApiError } from '../../lib/api';
  import Navbar from '$lib/components/Navbar.svelte';

  let email = '';
  let password = '';
  let showPassword = false;
  let loading = false;
  let error = '';
  let successMessage = '';

  // Check for success message from registration
  $: {
    const message = $page.url.searchParams.get('message');
    if (message) {
      successMessage = message;
    }
  }

  async function handleLogin() {
    if (!email || !password) {
      error = 'Please fill in all fields';
      return;
    }

    try {
      loading = true;
      error = '';
      
      const response = await api.login({
        email: email,
        password: password
      });

      // Store the token
      localStorage.setItem('auth_token', response.token);
      
      // Redirect to home page
      goto('/');
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.message;
      } else {
        error = 'Login failed. Please try again.';
      }
      console.error('Login error:', err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>Login - CarverJobs</title>
</svelte:head>

<Navbar active="login" />
<div class="flex items-center justify-center min-h-[calc(100vh-200px)]">
  <div class="w-full max-w-md">
    <div class="form-container p-8 rounded-xl">
      <h2 class="text-2xl font-light mb-6 text-center">Welcome Back</h2>
      
      {#if successMessage}
        <div class="alert-success">
          <p class="text-green-400 text-sm">{successMessage}</p>
        </div>
      {/if}
      
      {#if error}
        <div class="alert-error">
          <p class="text-red-400 text-sm">{error}</p>
        </div>
      {/if}
      
      <form on:submit|preventDefault={handleLogin} class="space-y-6">
        <div>
          <label for="email" class="block mb-2 text-sm font-light text-gray-400">Email Address</label>
          <input type="email" id="email" bind:value={email} class="input" placeholder="your@email.com" required />
        </div>
        
        <div>
          <label for="password" class="block mb-2 text-sm font-light text-gray-400">Password</label>
          <div class="relative">
            {#if showPassword}
              <input type="text" id="password" bind:value={password} class="input pr-16" placeholder="••••••••" required />
            {:else}
              <input type="password" id="password" bind:value={password} class="input pr-16" placeholder="••••••••" required />
            {/if}
            <button
              type="button"
              on:click={() => (showPassword = !showPassword)}
              class="absolute right-4 top-1/2 transform -translate-y-1/2 text-xs text-gray-500 hover:text-gray-400 transition-colors"
            >
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
        
        <div class="pt-4">
          <button type="submit" disabled={loading} class="btn w-full {loading ? 'opacity-50 cursor-not-allowed' : ''}">
            {loading ? 'Signing In...' : 'Sign In'}
          </button>
        </div>
      </form>
    </div>
    
    <div class="mt-8 text-center">
      <p class="text-gray-500 text-sm">
        Don't have an account? 
        <a href="/register" class="text-white hover:text-gray-400 transition-colors nav-link-enhanced">Sign up</a>
      </p>
    </div>
  </div>
</div> 