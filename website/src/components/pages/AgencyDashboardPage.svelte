<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { onNavigate = () => {} } = $props()

  let jobs = $state([])
  let isLoading = $state(true)
  let errorMessage = $state('')

  async function loadMine() {
    isLoading = true
    errorMessage = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/jobs/submit/mine`, {
        method: 'GET',
        credentials: 'include',
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        errorMessage = data.detail || `Failed to load (${res.status}).`
        jobs = []
        return
      }
      const data = await res.json().catch(() => ({}))
      jobs = Array.isArray(data?.jobs) ? data.jobs : []
    } catch {
      errorMessage = 'Could not reach the server.'
      jobs = []
    } finally {
      isLoading = false
    }
  }

  function formatDate(iso) {
    if (!iso) return '—'
    try {
      const d = new Date(iso)
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    } catch {
      return iso
    }
  }

  function statusClass(status) {
    if (status === 'open' || status === 'priority') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
    if (status === 'filled') return 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200'
    if (status === 'closed') return 'border-white/15 bg-white/5 text-slate-300'
    return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
  }

  onMount(loadMine)
</script>

<section class="grid gap-4">
  <header class="flex flex-col gap-3 rounded-2xl border border-white/8 bg-zinc-950 p-5 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Agency Dashboard</p>
      <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">My Jobs</h1>
      <p class="mt-2 text-sm text-slate-400">All positions you've posted, newest first.</p>
    </div>
    <div class="flex gap-2">
      <button
        type="button"
        onclick={loadMine}
        class="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/30 hover:text-white"
      >
        Refresh
      </button>
      <button
        type="button"
        onclick={() => onNavigate('agency-submit')}
        class="rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-4 py-2 text-xs font-bold text-cyan-100 transition hover:bg-cyan-400/25"
      >
        Post a job
      </button>
    </div>
  </header>

  {#if errorMessage}
    <div class="rounded-xl border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-100">
      {errorMessage}
    </div>
  {/if}

  {#if isLoading}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-8 text-center text-sm text-slate-500">
      Loading your submissions…
    </div>
  {:else if jobs.length === 0}
    <div class="rounded-2xl border border-white/8 bg-zinc-950 p-8 text-center">
      <p class="text-sm text-slate-300">You haven't posted any jobs yet.</p>
      <button
        type="button"
        onclick={() => onNavigate('agency-submit')}
        class="mt-4 rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-4 py-2 text-xs font-bold text-cyan-100 transition hover:bg-cyan-400/25"
      >
        Post your first job
      </button>
    </div>
  {:else}
    <div class="overflow-hidden rounded-2xl border border-white/8 bg-zinc-950">
      <table class="w-full text-left text-sm">
        <thead class="border-b border-white/10 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th class="px-4 py-3 font-semibold">Title</th>
            <th class="px-4 py-3 font-semibold">Role</th>
            <th class="px-4 py-3 font-semibold">Yacht</th>
            <th class="px-4 py-3 font-semibold">Location</th>
            <th class="px-4 py-3 font-semibold">Status</th>
            <th class="px-4 py-3 font-semibold">Posted</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-white/5">
          {#each jobs as job (job.id)}
            <tr class="hover:bg-white/[0.02]">
              <td class="px-4 py-3 text-white">{job.title}</td>
              <td class="px-4 py-3 text-slate-300">{job.role}</td>
              <td class="px-4 py-3 text-slate-300">{job.yacht}</td>
              <td class="px-4 py-3 text-slate-300">{job.location}</td>
              <td class="px-4 py-3">
                <span class={`inline-block rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusClass(job.status)}`}>
                  {job.status}
                </span>
              </td>
              <td class="px-4 py-3 text-slate-500">{formatDate(job.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="text-[11px] text-slate-600">Need to edit or close a job? Email support and we'll take care of it.</p>
  {/if}
</section>
