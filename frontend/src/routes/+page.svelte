<script>
  import { onMount } from 'svelte';
  import { api, ApiError } from '../lib/api';

  let jobs = [];
  let loading = true;
  let error = '';

  async function loadJobs() {
    try {
      loading = true;
      error = '';
      const response = await api.getJobs({ limit: 10 });
      jobs = response.jobs || [];
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.message;
      } else {
        error = 'Failed to load jobs';
      }
      console.error('Error loading jobs:', err);
      
      // Fallback to mock data if API fails
      jobs = [
        {
          id: '1',
          title: 'Chief Engineer',
          company: 'Luxury Motor Yacht',
          location: 'Mediterranean',
          salary: '$8,000/month'
        },
        {
          id: '2',
          title: 'Second Officer',
          company: 'Superyacht Management',
          location: 'Caribbean',
          salary: '$6,500/month'
        },
        {
          id: '3',
          title: 'Chief Stewardess',
          company: 'Private Yacht Owner',
          location: 'French Riviera',
          salary: '$5,500/month'
        }
      ];
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadJobs();
  });
</script>

<svelte:head>
  <title>CarverJobs - Job Board</title>
</svelte:head>

<div class="grid gap-4 max-w-4xl mx-auto">
  {#if loading}
    <div class="text-center py-12">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-white"></div>
      <p class="mt-4 text-gray-400">Loading jobs...</p>
    </div>
  {:else if error}
    <div class="text-center py-12">
      <p class="text-red-400 mb-4">{error}</p>
      <button on:click={loadJobs} class="btn">Try Again</button>
    </div>
  {:else if jobs.length === 0}
    <div class="text-center py-12">
      <p class="text-gray-400">No jobs available at the moment.</p>
    </div>
  {:else}
    {#each jobs as job}
      <div class="job-card group cursor-pointer">
        <div class="flex justify-between items-start">
          <div class="flex-1">
            <h3 class="text-lg font-medium mb-1 group-hover:text-gray-300 transition-colors">{job.title}</h3>
            <p class="text-gray-400 text-sm mb-1">{job.company}</p>
            <p class="text-gray-500 text-sm">{job.location}</p>
          </div>
          <div class="text-right">
            {#if job.salary}
              <p class="text-white font-medium text-sm">{job.salary}</p>
            {/if}
            <div class="mt-3">
              <span class="text-xs text-gray-500 group-hover:text-gray-400 transition-colors">View Details →</span>
            </div>
          </div>
        </div>
      </div>
    {/each}
  {/if}
</div> 