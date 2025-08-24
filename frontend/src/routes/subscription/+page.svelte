<script lang="ts">
  import Navbar from '$lib/components/Navbar.svelte';
  import Footer from '$lib/components/Footer.svelte';
</script>

<svelte:head>
  <title>Subscription - CarverJobs</title>
</svelte:head>

<Navbar active="subscription" />
<div class="max-w-4xl mx-auto px-4 py-8">
  <h1 class="text-3xl font-light mb-8 text-center">Premium Subscription</h1>
  
  <div class="subscription-card border-2 border-gray-700 rounded-xl p-8">
    <p class="text-gray-500 mb-6">Premium features coming soon</p>
    <ul class="space-y-4">
      <li class="flex items-start">
        <span class="inline-block w-2 h-2 bg-gray-400 rounded-full mt-1.5 mr-3 feature-dot"></span>
        <span class="text-gray-400">Access to exclusive job listings</span>
      </li>
      <li class="flex items-start">
        <span class="inline-block w-2 h-2 bg-gray-400 rounded-full mt-1.5 mr-3 feature-dot"></span>
        <span class="text-gray-400">Direct messaging with employers</span>
      </li>
      <li class="flex items-start">
        <span class="inline-block w-2 h-2 bg-gray-400 rounded-full mt-1.5 mr-3 feature-dot"></span>
        <span class="text-gray-400">Profile verification badge</span>
      </li>
      <li class="flex items-start">
        <span class="inline-block w-2 h-2 bg-gray-400 rounded-full mt-1.5 mr-3 feature-dot"></span>
        <span class="text-gray-400">Advanced search filters</span>
      </li>
    </ul>
    
    <div class="mt-8 text-center">
      <button class="btn" disabled>Coming Soon</button>
    </div>
  </div>
</div>
<Footer /> 