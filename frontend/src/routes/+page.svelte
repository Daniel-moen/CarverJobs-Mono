<script lang="ts">
  import { goto } from '$app/navigation';
  import { Search, MapPin, Clock, Users, TrendingUp, Anchor, Ship, Compass } from 'lucide-svelte';
  
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
    { value: 'deck', label: 'Deck Officers', icon: Compass, color: 'blue' },
    { value: 'engine', label: 'Engineers', icon: Compass, color: 'orange' },
    { value: 'interior', label: 'Interior', icon: Users, color: 'purple' },
    { value: 'crew', label: 'General Crew', icon: Anchor, color: 'gray' },
  ];
  
  const locations = [
    { value: 'worldwide', label: 'Worldwide' },
    { value: 'mediterranean', label: 'Mediterranean' },
    { value: 'caribbean', label: 'Caribbean' },
    { value: 'asia', label: 'Asia Pacific' },
    { value: 'americas', label: 'Americas' },
  ];
  
  const stats = [
    { value: '500+', label: 'Active Jobs', icon: TrendingUp },
    { value: '50+', label: 'Vessels', icon: Ship },
    { value: '1000+', label: 'Crew Members', icon: Users },
    { value: '25+', label: 'Countries', icon: MapPin },
  ];
</script>

<svelte:head>
  <title>CarverJobs - Marine Job Portal</title>
  <meta name="description" content="Find your next marine job opportunity. Browse deck officer, engineer, and crew positions worldwide.">
</svelte:head>

<!-- Hero Section -->
<section class="relative min-h-screen flex items-center justify-center overflow-hidden">
  <!-- Background gradient -->
  <div class="absolute inset-0 bg-gradient-to-br from-dark-950 via-dark-900 to-marine-950/20"></div>
  
  <!-- Animated background elements -->
  <div class="absolute inset-0 overflow-hidden">
    <div class="absolute top-1/4 left-1/4 w-72 h-72 bg-marine-500/5 rounded-full blur-3xl animate-pulse"></div>
    <div class="absolute bottom-1/4 right-1/4 w-96 h-96 bg-marine-400/3 rounded-full blur-3xl animate-pulse delay-1000"></div>
  </div>
  
  <div class="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
    <!-- Main heading -->
    <div class="mb-8 animate-fade-in">
      <h1 class="text-5xl sm:text-6xl lg:text-7xl font-bold mb-6 leading-tight">
        Find Your Next
        <span class="text-gradient block">Marine Career</span>
      </h1>
      <p class="text-xl sm:text-2xl text-dark-300 max-w-3xl mx-auto leading-relaxed">
        Connect with vessels worldwide. From yacht crews to cargo ships, 
        discover opportunities that match your maritime expertise.
      </p>
    </div>
    
    <!-- Search Form -->
    <div class="max-w-4xl mx-auto mb-12 animate-slide-up">
      <div class="glass rounded-2xl p-8 border border-dark-700/50">
        <form on:submit|preventDefault={handleSearch} class="space-y-6">
          <!-- Search input -->
          <div class="relative">
            <Search class="absolute left-4 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
            <input
              type="text"
              bind:value={searchQuery}
              placeholder="Search for deck officer, engineer, chef..."
              class="input pl-12 text-lg h-14"
            />
          </div>
          
          <!-- Filters -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <select bind:value={selectedType} class="input h-14">
              <option value="">All Job Types</option>
              {#each jobTypes as type}
                <option value={type.value}>{type.label}</option>
              {/each}
            </select>
            
            <select bind:value={selectedLocation} class="input h-14">
              <option value="">All Locations</option>
              {#each locations as location}
                <option value={location.value}>{location.label}</option>
              {/each}
            </select>
          </div>
          
          <!-- Search button -->
          <button type="submit" class="btn btn-primary w-full h-14 text-lg font-semibold">
            <Search class="w-5 h-5 mr-2" />
            Search Marine Jobs
          </button>
        </form>
      </div>
    </div>
    
    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-6 animate-fade-in">
      {#each stats as stat}
        <div class="glass rounded-xl p-6 border border-dark-700/30 hover:border-marine-700/50 transition-all">
          <svelte:component this={stat.icon} class="w-8 h-8 text-marine-400 mx-auto mb-3" />
          <div class="text-2xl font-bold text-dark-100 mb-1">{stat.value}</div>
          <div class="text-dark-400 text-sm">{stat.label}</div>
        </div>
      {/each}
    </div>
  </div>
</section>

<!-- Job Categories -->
<section class="py-20 px-4 sm:px-6 lg:px-8">
  <div class="max-w-7xl mx-auto">
    <div class="text-center mb-16">
      <h2 class="text-4xl sm:text-5xl font-bold text-dark-100 mb-6">
        Browse by <span class="text-gradient">Category</span>
      </h2>
      <p class="text-xl text-dark-300 max-w-2xl mx-auto">
        Find opportunities that match your maritime expertise and experience level
      </p>
    </div>
    
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      {#each jobTypes as type}
        <a 
          href="/jobs?type={type.value}" 
          class="card card-hover group relative overflow-hidden"
        >
          <!-- Background gradient -->
          <div class="absolute inset-0 bg-gradient-to-br from-{type.color}-500/5 to-{type.color}-600/10 opacity-0 group-hover:opacity-100 transition-opacity"></div>
          
          <div class="relative z-10">
            <div class="mb-4">
              <svelte:component this={type.icon} class="w-8 h-8 text-{type.color}-400 group-hover:text-{type.color}-300 transition-colors" />
            </div>
            
            <h3 class="text-xl font-semibold text-dark-100 mb-2 group-hover:text-marine-300 transition-colors">
              {type.label}
            </h3>
            
            <p class="text-dark-400 text-sm mb-4">
              Explore all {type.label.toLowerCase()} positions
            </p>
            
            <div class="flex items-center text-marine-400 text-sm font-medium group-hover:text-marine-300 transition-colors">
              Browse positions
              <svg class="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </div>
        </a>
      {/each}
    </div>
  </div>
</section>

<!-- Features Section -->
<section class="py-20 px-4 sm:px-6 lg:px-8 bg-dark-900/30">
  <div class="max-w-7xl mx-auto">
    <div class="text-center mb-16">
      <h2 class="text-4xl sm:text-5xl font-bold text-dark-100 mb-6">
        Why Choose <span class="text-gradient">CarverJobs?</span>
      </h2>
      <p class="text-xl text-dark-300 max-w-2xl mx-auto">
        We specialize in marine recruitment, connecting skilled professionals with opportunities worldwide
      </p>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
      <!-- Feature 1 -->
      <div class="text-center group">
        <div class="relative mb-6">
          <div class="w-16 h-16 bg-marine-500/10 rounded-2xl flex items-center justify-center mx-auto border border-marine-500/20 group-hover:border-marine-500/40 transition-all">
            <Anchor class="w-8 h-8 text-marine-400" />
          </div>
          <div class="absolute inset-0 bg-marine-400/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity"></div>
        </div>
        <h3 class="text-xl font-semibold text-dark-100 mb-3">Specialized Focus</h3>
        <p class="text-dark-400 leading-relaxed">
          Exclusively focused on marine industry jobs, ensuring relevant opportunities for seafarers and maritime professionals.
        </p>
      </div>
      
      <!-- Feature 2 -->
      <div class="text-center group">
        <div class="relative mb-6">
          <div class="w-16 h-16 bg-marine-500/10 rounded-2xl flex items-center justify-center mx-auto border border-marine-500/20 group-hover:border-marine-500/40 transition-all">
            <MapPin class="w-8 h-8 text-marine-400" />
          </div>
          <div class="absolute inset-0 bg-marine-400/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity"></div>
        </div>
        <h3 class="text-xl font-semibold text-dark-100 mb-3">Global Opportunities</h3>
        <p class="text-dark-400 leading-relaxed">
          Access positions on vessels operating worldwide, from luxury yachts to commercial cargo ships.
        </p>
      </div>
      
      <!-- Feature 3 -->
      <div class="text-center group">
        <div class="relative mb-6">
          <div class="w-16 h-16 bg-marine-500/10 rounded-2xl flex items-center justify-center mx-auto border border-marine-500/20 group-hover:border-marine-500/40 transition-all">
            <Users class="w-8 h-8 text-marine-400" />
          </div>
          <div class="absolute inset-0 bg-marine-400/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity"></div>
        </div>
        <h3 class="text-xl font-semibold text-dark-100 mb-3">Verified Companies</h3>
        <p class="text-dark-400 leading-relaxed">
          All employers are verified, ensuring legitimate opportunities with reputable shipping companies and yacht owners.
        </p>
      </div>
    </div>
  </div>
</section>

<!-- CTA Section -->
<section class="py-20 px-4 sm:px-6 lg:px-8">
  <div class="max-w-4xl mx-auto text-center">
    <div class="glass rounded-3xl p-12 border border-marine-500/20">
      <h2 class="text-4xl sm:text-5xl font-bold text-dark-100 mb-6">
        Ready to Set <span class="text-gradient">Sail?</span>
      </h2>
      <p class="text-xl text-dark-300 mb-8 max-w-2xl mx-auto">
        Join thousands of maritime professionals who trust CarverJobs for their career advancement.
      </p>
      <div class="flex flex-col sm:flex-row gap-4 justify-center">
        <a href="/jobs" class="btn btn-primary px-8 py-4 text-lg">
          <Search class="w-5 h-5 mr-2" />
          Browse Jobs
        </a>
        <a href="/register" class="btn btn-outline px-8 py-4 text-lg">
          <Users class="w-5 h-5 mr-2" />
          Create Account
        </a>
      </div>
    </div>
  </div>
</section> 