<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '../lib/api';
	import JobCardSkeleton from '$lib/components/JobCardSkeleton.svelte';

	type Job = {
		id: string;
		title: string;
		company: string;
		location: string;
		salary?: string;
		type?: string;
	};

	let jobs: Job[] = [];
	let loading = true;
	let error = '';

	async function loadJobs() {
		loading = true;
		error = '';
		
		try {
			const response = await api.getJobs({ limit: 10 });
			jobs = response.jobs || [];
		} catch (err) {
			console.error('Error loading jobs:', err);
			jobs = []; // Ensure jobs are cleared on error

			if (err instanceof ApiError) {
				if (err.status === 500) {
					error = 'The job database is currently being updated. Please try again in a few minutes.';
				} else {
					error = err.message;
				}
			} else {
				error = 'Failed to load jobs. Please check your internet connection.';
			}
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadJobs();
	});
</script>

<svelte:head>
	<title>CarverJobs - Yacht Job Board</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-8">
	<div class="grid gap-4">
		{#if loading}
			<!-- Show 5 skeleton loaders -->
			{#each Array(5) as _}
				<JobCardSkeleton />
			{/each}
		{:else if error}
			<div class="text-center py-12">
				<p class="text-red-400 mb-4">{error}</p>
				<button
					on:click={loadJobs}
					class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded text-white transition-colors"
				>
					Try Again
				</button>
			</div>
		{:else if jobs.length === 0}
			<div class="text-center py-12">
				<p class="text-gray-400 mb-4">No jobs available at the moment.</p>
				<button
					on:click={loadJobs}
					class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded text-white transition-colors"
				>
					Refresh
				</button>
			</div>
		{:else}
			{#each jobs as job}
				<div class="job-card group cursor-pointer">
					<div class="flex justify-between items-start">
						<div class="flex-1">
							<h3 class="text-lg font-medium mb-1 group-hover:text-gray-300 transition-colors">
								{job.title}
							</h3>
							<p class="text-gray-400 text-sm mb-1">{job.company}</p>
							<div class="flex items-center space-x-4">
								<p class="text-gray-500 text-sm">{job.location}</p>
								{#if job.type}
									<span
										class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-900/30 text-blue-300"
									>
										{job.type}
									</span>
								{/if}
							</div>
						</div>
						<div class="text-right">
							{#if job.salary}
								<p class="text-white font-medium text-sm">{job.salary}</p>
							{/if}
							<div class="mt-3">
								<span class="text-xs text-gray-500 group-hover:text-gray-400 transition-colors"
									>View Details →</span
								>
							</div>
						</div>
					</div>
				</div>
			{/each}

			<div class="text-center py-6">
				<button
					on:click={loadJobs}
					class="text-gray-400 hover:text-gray-300 text-sm transition-colors"
				>
					Load More Jobs
				</button>
			</div>
		{/if}
	</div>
</div>

<style>
	:global(.job-card) {
		background-color: rgb(31 41 55);
		border: 1px solid rgb(55 65 81);
		border-radius: 0.5rem;
		padding: 1.5rem;
		transition: border-color 0.15s ease-in-out;
	}

	:global(.job-card:hover) {
		border-color: rgb(75 85 99);
	}
</style> 