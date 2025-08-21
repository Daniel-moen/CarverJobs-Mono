<script lang="ts">
  import { onMount } from 'svelte';
  import { api, ApiError } from '../lib/api';
  import JobCardSkeleton from '$lib/components/JobCardSkeleton.svelte';
  import JobCard, { type Job } from '$lib/components/JobCard.svelte';
  import Filters from '$lib/components/Filters.svelte';

  let jobs: Job[] = [];
  let loading = true;
  let error = '';

  let type = '';
  let location = '';
  let company = '';

  async function loadJobs() {
    loading = true;
    error = '';
    try {
      const response = await api.getJobs({ limit: 10, type, location, company });
      jobs = response.jobs || [];
    } catch (err) {
      console.error('Error loading jobs:', err);
      jobs = [];
      if (err instanceof ApiError) {
        error = err.status === 500
          ? 'The job database is currently being updated. Please try again in a few minutes.'
          : err.message;
      } else {
        error = 'Failed to load jobs. Please check your internet connection.';
      }
    } finally {
      loading = false;
    }
  }

  function handleFilterChange(e: CustomEvent) {
    type = e.detail.type;
    location = e.detail.location;
    company = e.detail.company;
    loadJobs();
  }

  function handleOpen(job: Job) {
    // Placeholder for future navigation
    console.log('Open job', job.id);
  }

  onMount(loadJobs);
</script>

<svelte:head>
  <title>CarverJobs - Yacht Job Board</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-6">
  <Filters bind:type bind:location bind:company on:change={handleFilterChange} />

  {#if loading}
    <div class="grid gap-4" aria-busy="true" aria-live="polite">
      {#each Array(5) as _}
        <JobCardSkeleton />
      {/each}
    </div>
  {:else if error}
    <div class="text-center py-12" role="alert">
      <p class="text-red-400 mb-4">{error}</p>
      <button on:click={loadJobs} class="btn">Try Again</button>
    </div>
  {:else if jobs.length === 0}
    <div class="text-center py-12">
      <p class="text-gray-400 mb-4">No jobs match your filters.</p>
      <button on:click={() => { type=''; location=''; company=''; loadJobs(); }} class="btn">Clear Filters</button>
    </div>
  {:else}
    <div class="grid gap-4">
      {#each jobs as job}
        <JobCard {job} on:click={() => handleOpen(job)} />
      {/each}
    </div>
    <div class="text-center py-6">
      <button on:click={loadJobs} class="text-gray-400 hover:text-gray-300 text-sm transition-colors">Load More Jobs</button>
    </div>
  {/if}
</div>
