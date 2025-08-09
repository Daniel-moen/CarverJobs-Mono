<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Search, Filter, MapPin, Clock, DollarSign, Ship, Users, Building } from 'lucide-svelte';
  
  // Mock job data - replace with API call
  const mockJobs = [
    {
      id: '1',
      title: 'Chief Engineer',
      company: 'Luxury Motor Yacht',
      location: 'Mediterranean',
      type: 'engine',
      vessel: 'Motor Yacht',
      duration: '6 months',
      salary: '$8,000/month',
      description: 'Seeking experienced Chief Engineer for 65m motor yacht operating in Mediterranean waters.',
      postedAt: '2024-01-15T10:00:00Z'
    },
    {
      id: '2',
      title: 'Second Officer',
      company: 'Superyacht Management',
      location: 'Caribbean',
      type: 'deck',
      vessel: 'Superyacht',
      duration: 'Rotational',
      salary: '$6,500/month',
      description: 'Second Officer position on 80m+ superyacht with excellent crew facilities.',
      postedAt: '2024-01-14T15:30:00Z'
    },
    {
      id: '3',
      title: 'Chief Stewardess',
      company: 'Private Yacht Owner',
      location: 'French Riviera',
      type: 'interior',
      vessel: 'Motor Yacht',
      duration: '4 months',
      salary: '$5,500/month',
      description: 'Leading interior team on prestigious 45m motor yacht based in French Riviera.',
      postedAt: '2024-01-13T09:15:00Z'
    },
    {
      id: '4',
      title: 'Deckhand',
      company: 'Charter Management',
      location: 'Bahamas',
      type: 'deck',
      vessel: 'Charter Yacht',
      duration: '8 months',
      salary: '$3,200/month',
      description: 'Entry level deckhand position on busy charter yacht in Bahamas.',
      postedAt: '2024-01-12T14:45:00Z'
    },
    {
      id: '5',
      title: 'Yacht Chef',
      company: 'Expedition Yacht',
      location: 'Worldwide',
      type: 'interior',
      vessel: 'Expedition Yacht',
      duration: 'Permanent',
      salary: '$7,000/month',
      description: 'Experienced chef for world-cruising expedition yacht with adventurous owners.',
      postedAt: '2024-01-11T11:20:00Z'
    }
  ];
  
  let jobs = mockJobs;
  let searchQuery = '';
  let selectedType = '';
  let selectedLocation = '';
  let showFilters = false;
  
  // Get filter values from URL params
  $: {
    searchQuery = $page.url.searchParams.get('q') || '';
    selectedType = $page.url.searchParams.get('type') || '';
    selectedLocation = $page.url.searchParams.get('location') || '';
  }
  
  // Filter jobs based on search criteria
  $: filteredJobs = jobs.filter(job => {
    const matchesSearch = !searchQuery || 
      job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.company.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.description.toLowerCase().includes(searchQuery.toLowerCase());
    
    const matchesType = !selectedType || job.type === selectedType;
    const matchesLocation = !selectedLocation || 
      job.location.toLowerCase().includes(selectedLocation.toLowerCase());
    
    return matchesSearch && matchesType && matchesLocation;
  });
  
  function updateFilters() {
    const params = new URLSearchParams();
    if (searchQuery) params.set('q', searchQuery);
    if (selectedType) params.set('type', selectedType);
    if (selectedLocation) params.set('location', selectedLocation);
    
    goto(`/jobs?${params.toString()}`);
  }
  
  function getJobTypeBadge(type: string) {
    const badges = {
      deck: 'badge-deck',
      engine: 'badge-engine', 
      interior: 'badge-interior',
      crew: 'badge-crew'
    };
    return badges[type] || 'badge-crew';
  }
  
  function formatDate(dateString: string) {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = Math.abs(now.getTime() - date.getTime());
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 1) return '1 day ago';
    if (diffDays < 7) return `${diffDays} days ago`;
    if (diffDays < 30) return `${Math.ceil(diffDays / 7)} weeks ago`;
    return `${Math.ceil(diffDays / 30)} months ago`;
  }
  
  const jobTypes = [
    { value: 'deck', label: 'Deck Officers' },
    { value: 'engine', label: 'Engineers' },
    { value: 'interior', label: 'Interior' },
    { value: 'crew', label: 'General Crew' }
  ];
  
  const locations = [
    { value: 'mediterranean', label: 'Mediterranean' },
    { value: 'caribbean', label: 'Caribbean' },
    { value: 'bahamas', label: 'Bahamas' },
    { value: 'french riviera', label: 'French Riviera' },
    { value: 'worldwide', label: 'Worldwide' }
  ];
</script>

<svelte:head>
  <title>Marine Jobs - CarverJobs</title>
  <meta name="description" content="Browse the latest marine job opportunities. Find yacht crew, deck officer, engineer, and interior positions worldwide.">
</svelte:head>

<div class="min-h-screen bg-dark-950 py-8">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    
    <!-- Header -->
    <div class="mb-8">
      <h1 class="text-4xl font-bold text-dark-100 mb-4">
        Marine <span class="text-gradient">Jobs</span>
      </h1>
      <p class="text-xl text-dark-300">
        Discover your next career opportunity aboard vessels worldwide
      </p>
    </div>
    
    <!-- Search and Filters -->
    <div class="mb-8">
      <div class="glass rounded-xl p-6 border border-dark-700/50">
        
        <!-- Search Bar -->
        <div class="relative mb-6">
          <Search class="absolute left-4 top-1/2 transform -translate-y-1/2 text-dark-400 w-5 h-5" />
          <input
            type="text"
            bind:value={searchQuery}
            on:input={updateFilters}
            placeholder="Search jobs by title, company, or description..."
            class="input pl-12 w-full"
          />
        </div>
        
        <!-- Filter Toggle -->
        <div class="flex items-center justify-between mb-4">
          <div class="text-dark-300">
            <span class="font-medium">{filteredJobs.length}</span> jobs found
          </div>
          <button
            on:click={() => showFilters = !showFilters}
            class="btn btn-ghost"
          >
            <Filter class="w-4 h-4 mr-2" />
            Filters
          </button>
        </div>
        
        <!-- Filters -->
        {#if showFilters}
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-dark-700">
            <div>
              <label class="block text-sm font-medium text-dark-300 mb-2">Job Type</label>
              <select bind:value={selectedType} on:change={updateFilters} class="input">
                <option value="">All Types</option>
                {#each jobTypes as type}
                  <option value={type.value}>{type.label}</option>
                {/each}
              </select>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-dark-300 mb-2">Location</label>
              <select bind:value={selectedLocation} on:change={updateFilters} class="input">
                <option value="">All Locations</option>
                {#each locations as location}
                  <option value={location.value}>{location.label}</option>
                {/each}
              </select>
            </div>
          </div>
        {/if}
      </div>
    </div>
    
    <!-- Job Results -->
    {#if filteredJobs.length === 0}
      <div class="text-center py-12">
        <div class="w-24 h-24 bg-dark-800 rounded-full flex items-center justify-center mx-auto mb-4">
          <Search class="w-8 h-8 text-dark-500" />
        </div>
        <h3 class="text-xl font-semibold text-dark-300 mb-2">No jobs found</h3>
        <p class="text-dark-400">Try adjusting your search criteria or filters</p>
      </div>
    {:else}
      <div class="space-y-6">
        {#each filteredJobs as job}
          <div class="card card-hover group cursor-pointer" on:click={() => goto(`/jobs/${job.id}`)}>
            <div class="flex flex-col lg:flex-row lg:items-center justify-between">
              
              <!-- Job Info -->
              <div class="flex-1 mb-4 lg:mb-0">
                <div class="flex items-start justify-between mb-3">
                  <div>
                    <h3 class="text-xl font-semibold text-dark-100 group-hover:text-marine-300 transition-colors mb-1">
                      {job.title}
                    </h3>
                    <div class="flex items-center text-dark-400 text-sm mb-2">
                      <Building class="w-4 h-4 mr-1" />
                      {job.company}
                    </div>
                  </div>
                  <span class="badge {getJobTypeBadge(job.type)} ml-4">
                    {job.type}
                  </span>
                </div>
                
                <p class="text-dark-300 mb-4 line-clamp-2">
                  {job.description}
                </p>
                
                <!-- Job Details -->
                <div class="flex flex-wrap gap-4 text-sm text-dark-400">
                  {#if job.location}
                    <div class="flex items-center">
                      <MapPin class="w-4 h-4 mr-1" />
                      {job.location}
                    </div>
                  {/if}
                  
                  {#if job.vessel}
                    <div class="flex items-center">
                      <Ship class="w-4 h-4 mr-1" />
                      {job.vessel}
                    </div>
                  {/if}
                  
                  {#if job.duration}
                    <div class="flex items-center">
                      <Clock class="w-4 h-4 mr-1" />
                      {job.duration}
                    </div>
                  {/if}
                  
                  {#if job.salary}
                    <div class="flex items-center text-marine-400 font-medium">
                      <DollarSign class="w-4 h-4 mr-1" />
                      {job.salary}
                    </div>
                  {/if}
                </div>
              </div>
              
              <!-- Action Area -->
              <div class="flex flex-col items-end justify-between lg:pl-6">
                <div class="text-dark-500 text-sm mb-4">
                  {formatDate(job.postedAt)}
                </div>
                
                <button class="btn btn-outline group-hover:btn-primary transition-all">
                  View Details
                  <svg class="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        {/each}
      </div>
      
      <!-- Load More / Pagination could go here -->
      <div class="text-center mt-12">
        <button class="btn btn-secondary">
          Load More Jobs
        </button>
      </div>
    {/if}
  </div>
</div>

<style>
  .line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
</style> 