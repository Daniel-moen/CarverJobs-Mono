<script lang="ts">
  export type Job = {
    id: string;
    title: string;
    company: string;
    location: string;
    salary?: string;
    type?: string;
  };
  export let job: Job;
  export let onClick: (job: Job) => void = () => {};
</script>

<article class="job-card group cursor-pointer" role="button" tabindex="0" on:click={() => onClick(job)} on:keydown={(e) => (e.key==='Enter'||e.key===' ') && onClick(job)}>
  <div class="flex justify-between items-start">
    <div class="flex-1">
      <h3 class="text-lg font-medium mb-1 group-hover:text-gray-300 transition-colors">{job.title}</h3>
      <p class="text-gray-400 text-sm mb-1">{job.company}</p>
      <div class="flex items-center gap-4">
        <p class="text-gray-500 text-sm">{job.location}</p>
        {#if job.type}
          <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-900/30 text-blue-300">{job.type}</span>
        {/if}
      </div>
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
</article>
