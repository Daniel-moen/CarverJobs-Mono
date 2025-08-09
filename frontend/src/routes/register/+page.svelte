<script>
  import { goto } from '$app/navigation';
  import { Mail, Lock, User, Eye, EyeOff, Anchor } from 'lucide-svelte';
  
  let firstName = '';
  let lastName = '';
  let email = '';
  let password = '';
  let confirmPassword = '';
  let showPassword = false;
  let showConfirmPassword = false;
  let isLoading = false;
  let error = '';
  
  async function handleRegister() {
    // Validation
    if (!firstName || !lastName || !email || !password || !confirmPassword) {
      error = 'Please fill in all fields';
      return;
    }
    
    if (password !== confirmPassword) {
      error = 'Passwords do not match';
      return;
    }
    
    if (password.length < 8) {
      error = 'Password must be at least 8 characters long';
      return;
    }
    
    isLoading = true;
    error = '';
    
    try {
      // TODO: Replace with actual API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Mock successful registration
      localStorage.setItem('auth_token', 'mock-jwt-token');
      goto('/jobs');
    } catch (err) {
      error = 'Registration failed. Please try again.';
    } finally {
      isLoading = false;
    }
  }
</script>

<svelte:head>
  <title>Sign Up - CarverJobs</title>
  <meta name="description" content="Create your CarverJobs account to access marine job opportunities worldwide.">
</svelte:head>

<div class="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
  <!-- Background elements -->
  <div class="absolute inset-0 overflow-hidden">
    <div class="absolute top-1/3 left-1/4 w-72 h-72 bg-marine-500/5 rounded-full blur-3xl"></div>
    <div class="absolute bottom-1/3 right-1/4 w-96 h-96 bg-marine-400/3 rounded-full blur-3xl"></div>
  </div>
  
  <div class="relative z-10 max-w-md w-full space-y-8">
    
    <!-- Header -->
    <div class="text-center">
      <div class="flex justify-center mb-6">
        <div class="relative">
          <Anchor class="w-12 h-12 text-marine-400" />
          <div class="absolute inset-0 blur-md bg-marine-400/20 rounded-full"></div>
        </div>
      </div>
      <h2 class="text-3xl font-bold text-dark-100 mb-2">
        Create your account
      </h2>
      <p class="text-dark-400">
        Join thousands of maritime professionals
      </p>
    </div>
    
    <!-- Register Form -->
    <div class="glass rounded-2xl p-8 border border-dark-700/50">
      <form on:submit|preventDefault={handleRegister} class="space-y-6">
        
        {#if error}
          <div class="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <p class="text-red-400 text-sm">{error}</p>
          </div>
        {/if}
        
        <!-- Name Fields -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="firstName" class="block text-sm font-medium text-dark-300 mb-2">
              First name
            </label>
            <div class="relative">
              <User class="absolute left-3 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
              <input
                id="firstName"
                type="text"
                bind:value={firstName}
                placeholder="First name"
                class="input pl-11 focus-ring"
                required
              />
            </div>
          </div>
          
          <div>
            <label for="lastName" class="block text-sm font-medium text-dark-300 mb-2">
              Last name
            </label>
            <div class="relative">
              <User class="absolute left-3 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
              <input
                id="lastName"
                type="text"
                bind:value={lastName}
                placeholder="Last name"
                class="input pl-11 focus-ring"
                required
              />
            </div>
          </div>
        </div>
        
        <!-- Email -->
        <div>
          <label for="email" class="block text-sm font-medium text-dark-300 mb-2">
            Email address
          </label>
          <div class="relative">
            <Mail class="absolute left-3 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
            <input
              id="email"
              type="email"
              bind:value={email}
              placeholder="Enter your email"
              class="input pl-11 focus-ring"
              required
            />
          </div>
        </div>
        
        <!-- Password -->
        <div>
          <label for="password" class="block text-sm font-medium text-dark-300 mb-2">
            Password
          </label>
          <div class="relative">
            <Lock class="absolute left-3 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              bind:value={password}
              placeholder="Create a password (8+ characters)"
              class="input pl-11 pr-11 focus-ring"
              required
            />
            <button
              type="button"
              on:click={() => showPassword = !showPassword}
              class="absolute right-3 top-1/2 transform -translate-y-1/2 text-dark-400 hover:text-dark-300 transition-colors"
            >
              {#if showPassword}
                <EyeOff class="w-5 h-5" />
              {:else}
                <Eye class="w-5 h-5" />
              {/if}
            </button>
          </div>
        </div>
        
        <!-- Confirm Password -->
        <div>
          <label for="confirmPassword" class="block text-sm font-medium text-dark-300 mb-2">
            Confirm password
          </label>
          <div class="relative">
            <Lock class="absolute left-3 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
            <input
              id="confirmPassword"
              type={showConfirmPassword ? 'text' : 'password'}
              bind:value={confirmPassword}
              placeholder="Confirm your password"
              class="input pl-11 pr-11 focus-ring"
              required
            />
            <button
              type="button"
              on:click={() => showConfirmPassword = !showConfirmPassword}
              class="absolute right-3 top-1/2 transform -translate-y-1/2 text-dark-400 hover:text-dark-300 transition-colors"
            >
              {#if showConfirmPassword}
                <EyeOff class="w-5 h-5" />
              {:else}
                <Eye class="w-5 h-5" />
              {/if}
            </button>
          </div>
        </div>
        
        <!-- Terms -->
        <div class="flex items-start">
          <input
            type="checkbox"
            class="w-4 h-4 text-marine-500 bg-dark-800 border-dark-600 rounded focus:ring-marine-500 focus:ring-2 mt-1"
            required
          />
          <label class="ml-2 text-sm text-dark-400">
            I agree to the
            <a href="/terms" class="text-marine-400 hover:text-marine-300 transition-colors">Terms of Service</a>
            and
            <a href="/privacy" class="text-marine-400 hover:text-marine-300 transition-colors">Privacy Policy</a>
          </label>
        </div>
        
        <!-- Submit Button -->
        <button
          type="submit"
          disabled={isLoading}
          class="btn btn-primary w-full h-12 text-lg {isLoading ? 'opacity-50 cursor-not-allowed' : ''}"
        >
          {#if isLoading}
            <div class="loading-dot mr-2"></div>
            Creating account...
          {:else}
            Create account
          {/if}
        </button>
      </form>
      
      <!-- Social Login (Optional) -->
      <div class="mt-6">
        <div class="relative">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-dark-700"></div>
          </div>
          <div class="relative flex justify-center text-sm">
            <span class="bg-dark-900 px-2 text-dark-400">Or continue with</span>
          </div>
        </div>
        
        <div class="mt-6">
          <button class="btn btn-secondary w-full">
            Continue with Google
          </button>
        </div>
      </div>
    </div>
    
    <!-- Sign In Link -->
    <div class="text-center">
      <p class="text-dark-400">
        Already have an account?
        <a href="/login" class="text-marine-400 hover:text-marine-300 transition-colors font-medium">
          Sign in here
        </a>
      </p>
    </div>
  </div>
</div> 