<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  const dispatch = createEventDispatcher();

  export let type = '';
  export let location = '';
  export let company = '';

  function emitChange() {
    dispatch('change', { type, location, company });
  }
</script>

<section class="mb-6 grid grid-cols-1 md:grid-cols-3 gap-3">
  <div>
    <label for="type" class="block mb-2 text-xs font-light text-gray-400">Type</label>
    <input id="type" class="input" placeholder="e.g. Deckhand" bind:value={type} on:input={emitChange} />
  </div>
  <div>
    <label for="location" class="block mb-2 text-xs font-light text-gray-400">Location</label>
    <input id="location" class="input" placeholder="e.g. Monaco" bind:value={location} on:input={emitChange} />
  </div>
  <div>
    <label for="company" class="block mb-2 text-xs font-light text-gray-400">Company</label>
    <input id="company" class="input" placeholder="e.g. Feadship" bind:value={company} on:input={emitChange} />
  </div>
</section>
