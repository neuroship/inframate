<script>
  import { onMount } from "svelte";
  import { getResources, getState } from "../lib/api.js";

  // no props

  let resources = $state([]);
  let loading = $state(true);
  let error = $state("");
  let expandedIdx = $state(-1);

  onMount(async () => {
    try {
      resources = await getResources();
    } catch (e) {
      error = e.message;
    }
    loading = false;
  });

  function modeIcon(mode) {
    return mode === "data" ? "icon-[tabler--database]" : "icon-[tabler--box]";
  }

  function typeColor(type) {
    if (type?.startsWith("aws_")) return "badge-primary";
    if (type?.startsWith("google_")) return "badge-warning";
    if (type?.startsWith("azurerm_")) return "badge-info";
    return "badge-secondary";
  }
</script>

<div class="p-4">
  {#if loading}
    <div class="flex justify-center py-8">
      <span class="loading loading-spinner loading-sm"></span>
    </div>
  {:else if error}
    <div class="alert alert-soft alert-error text-xs">
      <span class="icon-[tabler--alert-circle] size-4"></span>
      {error}
    </div>
  {:else if resources.length === 0}
    <div class="text-center py-8 text-base-content/50">
      <span class="icon-[tabler--database-off] size-8 block mx-auto mb-2"></span>
      <p class="text-xs">No resources in state yet. Resources appear here after <code class="text-primary">terraform apply</code>.</p>
      <p class="text-xs mt-1">Use the <strong>Graph</strong> tab to see your planned resource topology, or <strong>Operations</strong> to run apply.</p>
    </div>
  {:else}
    <div class="text-xs text-base-content/50 mb-3">{resources.length} resources in state</div>
    <div class="flex flex-col gap-1">
      {#each resources as res, i}
        <div class="card card-border bg-base-200 card-xs">
          <button class="card-body p-3 cursor-pointer text-left" onclick={() => (expandedIdx = expandedIdx === i ? -1 : i)}>
            <div class="flex items-center gap-2">
              <span class="{modeIcon(res.mode)} size-3.5 text-base-content/50"></span>
              <span class="badge badge-sm {typeColor(res.type)}">{res.type}</span>
              <span class="text-xs font-medium">{res.name}</span>
              {#if res.module}
                <span class="text-xs text-base-content/40">({res.module})</span>
              {/if}
              <span class="ms-auto icon-[tabler--chevron-{expandedIdx === i ? 'up' : 'down'}] size-3.5 text-base-content/40"></span>
            </div>
          </button>
          {#if expandedIdx === i}
            <div class="px-3 pb-3">
              <pre class="text-xs bg-base-300 rounded p-2 overflow-auto max-h-64 font-mono">{JSON.stringify(res.attributes, null, 2)}</pre>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
