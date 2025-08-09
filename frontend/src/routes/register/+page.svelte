<script>
  import { goto } from '$app/navigation';
  import { api, ApiError } from '../../lib/api';

  let email = '';
  let password = '';
  let firstName = '';
  let lastName = '';
  let showPassword = false;
  let loading = false;
  let error = '';

  async function handleRegister() {
    if (!email || !password || !firstName || !lastName) {
      error = 'Please fill in all fields';
      return;
    }

    if (password.length < 8) {
      error = 'Password must be at least 8 characters long';
      return;
    }

    try {
      loading = true;
      error = '';
      
      await api.register({
        email: email,
        password: password,
        first_name: firstName,
        last_name: lastName
      });

      // Registration successful, redirect to login
      goto('/login?message=Registration successful! Please log in.');
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.message;
      } else {
        error = 'Registration failed. Please try again.';
      }
      console.error('Registration error:', err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>Sign Up - CarverJobs</title>
</svelte:head>

<div class="max-w-md mx-auto">
  <div class="mb-12 text-center">
    <h1 class="text-2xl font-light mb-2">Create Account</h1>
    <p class="text-gray-500 text-sm">Join the premium maritime network</p>
  </div>
  
  <div class="form-container rounded-xl p-8">
    <form on:submit|preventDefault={handleRegister} class="space-y-6">
      {#if error}
        <div class="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
          <p class="text-red-400 text-sm">{error}</p>
        </div>
      {/if}

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label for="firstName" class="block mb-2 text-sm font-light text-gray-400">First Name</label>
          <input type="text" id="firstName" bind:value={firstName} class="input" placeholder="First" required />
        </div>
        <div>
          <label for="lastName" class="block mb-2 text-sm font-light text-gray-400">Last Name</label>
          <input type="text" id="lastName" bind:value={lastName} class="input" placeholder="Last" required />
        </div>
      </div>
      
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
          {loading ? 'Creating Account...' : 'Create Account'}
        </button>
      </div>
    </form>
  </div>
  
  <div class="mt-8 text-center">
    <p class="text-gray-500 text-sm">
      Already have an account? 
      <a href="/login" class="text-white hover:text-gray-400 transition-colors nav-link-enhanced">Sign in</a>
    </p>
  </div>
</div> 