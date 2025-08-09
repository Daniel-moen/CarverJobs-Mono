<script lang="ts">
  import { goto } from '$app/navigation';
  
  let searchQuery = '';
  let selectedType = '';
  let selectedLocation = '';
  
  function handleSearch() {
    const params = new URLSearchParams();
    if (searchQuery) params.set('q', searchQuery);
    if (selectedType) params.set('type', selectedType);
    if (selectedLocation) params.set('location', selectedLocation);
    
    goto(`/jobs?${params.toString()}`);
  }
  
  const jobTypes = [
    { value: 'deck', label: 'Deck Officers' },
    { value: 'engine', label: 'Engineers' },
    { value: 'catering', label: 'Catering' },
    { value: 'technical', label: 'Technical' },
  ];
  
  const locations = [
    { value: 'worldwide', label: 'Worldwide' },
    { value: 'europe', label: 'Europe' },
    { value: 'asia', label: 'Asia' },
    { value: 'americas', label: 'Americas' },
    { value: 'middle-east', label: 'Middle East' },
  ];
</script>

<svelte:head>
  <title>CarverJobs - Marine Job Portal</title>
  <meta name="description" content="Find your next marine job opportunity. Browse deck officer, engineer, and catering positions worldwide.">
</svelte:head>

<!-- Hero Section -->
<section class="bg-gradient-to-r from-marine-600 to-marine-800 text-white">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-24">
    <div class="text-center">
      <h1 class="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6">
        Find Your Next <span class="text-marine-200">Marine</span> Career
      </h1>
      <p class="text-xl sm:text-2xl text-marine-100 mb-8 max-w-3xl mx-auto">
        Discover opportunities aboard vessels worldwide. From deck officers to engineers, 
        we connect maritime professionals with their ideal positions.
      </p>
      
      <!-- Search Form -->
      <div class="bg-white rounded-lg p-6 max-w-4xl mx-auto">
        <form on:submit|preventDefault={handleSearch} class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="md:col-span-2">
            <input
              type="text"
              bind:value={searchQuery}
              placeholder="Job title, company, or keywords..."
              class="input text-gray-900"
            />
          </div>
          
          <div>
            <select bind:value={selectedType} class="input text-gray-900">
              <option value="">All Job Types</option>
              {#each jobTypes as type}
                <option value={type.value}>{type.label}</option>
              {/each}
            </select>
          </div>
          
          <div>
            <select bind:value={selectedLocation} class="input text-gray-900">
              <option value="">All Locations</option>
              {#each locations as location}
                <option value={location.value}>{location.label}</option>
              {/each}
            </select>
          </div>
          
          <div class="md:col-span-4">
            <button type="submit" class="btn btn-primary w-full text-lg py-3">
              Search Marine Jobs
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</section>

<!-- Features Section -->
<section class="py-16">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-12">
      <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
        Why Choose CarverJobs?
      </h2>
      <p class="text-xl text-gray-600 max-w-2xl mx-auto">
        We specialize in marine recruitment, connecting skilled professionals with top shipping companies worldwide.
      </p>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
      <div class="text-center">
        <div class="w-16 h-16 bg-marine-100 rounded-lg flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-marine-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
        <h3 class="text-xl font-semibold text-gray-900 mb-2">Specialized Focus</h3>
        <p class="text-gray-600">Exclusively focused on marine industry jobs, ensuring relevant opportunities for seafarers.</p>
      </div>
      
      <div class="text-center">
        <div class="w-16 h-16 bg-marine-100 rounded-lg flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-marine-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h3 class="text-xl font-semibold text-gray-900 mb-2">Global Opportunities</h3>
        <p class="text-gray-600">Access positions on vessels operating worldwide, from cargo ships to luxury yachts.</p>
      </div>
      
      <div class="text-center">
        <div class="w-16 h-16 bg-marine-100 rounded-lg flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-marine-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h3 class="text-xl font-semibold text-gray-900 mb-2">Verified Companies</h3>
        <p class="text-gray-600">All employers are verified, ensuring legitimate opportunities with reputable shipping companies.</p>
      </div>
    </div>
  </div>
</section>

<!-- Job Categories -->
<section class="bg-gray-100 py-16">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-12">
      <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">Browse by Category</h2>
      <p class="text-xl text-gray-600">Find opportunities that match your maritime expertise</p>
    </div>
    
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      {#each jobTypes as type}
        <a href="/jobs?type={type.value}" class="card hover:shadow-md transition-shadow group">
          <h3 class="text-lg font-semibold text-gray-900 mb-2 group-hover:text-marine-600 transition-colors">
            {type.label}
          </h3>
          <p class="text-gray-600 text-sm">View all {type.label.toLowerCase()} positions</p>
          <div class="mt-4 text-marine-600 text-sm font-medium">Browse positions →</div>
        </a>
      {/each}
    </div>
  </div>
</section>

<!-- CTA Section -->
<section class="bg-marine-600 text-white py-16">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
    <h2 class="text-3xl sm:text-4xl font-bold mb-4">Ready to Set Sail?</h2>
    <p class="text-xl text-marine-100 mb-8 max-w-2xl mx-auto">
      Join thousands of maritime professionals who trust CarverJobs for their career advancement.
    </p>
    <div class="flex flex-col sm:flex-row gap-4 justify-center">
      <a href="/jobs" class="btn bg-white text-marine-600 hover:bg-gray-100 text-lg px-8 py-3">
        Browse Jobs
      </a>
      <a href="/register" class="btn border-2 border-white text-white hover:bg-white hover:text-marine-600 text-lg px-8 py-3">
        Create Account
      </a>
    </div>
  </div>
</section> 