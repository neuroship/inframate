<script>
  import { onMount } from "svelte";
  import { getVars, getFile, updateFile } from "../lib/api.js";

  // no props

  let varFiles = $state([]);
  let selectedFile = $state(null);
  let content = $state("");
  let originalContent = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let error = $state("");
  let success = $state("");

  onMount(async () => {
    try {
      varFiles = await getVars();
    } catch (e) {
      error = e.message;
    }
    loading = false;
  });

  async function selectFile(filename) {
    error = "";
    success = "";
    try {
      const data = await getFile(filename);
      selectedFile = filename;
      content = data.content;
      originalContent = data.content;
    } catch (e) {
      error = e.message;
    }
  }

  async function save() {
    saving = true;
    error = "";
    try {
      await updateFile(selectedFile, content);
      originalContent = content;
      success = "Saved";
      setTimeout(() => (success = ""), 2000);
    } catch (e) {
      error = e.message;
    }
    saving = false;
  }

  let isDirty = $derived(content !== originalContent);
</script>

<div class="flex h-full">
  <div class="w-48 border-r border-base-content/10 bg-base-200 overflow-auto">
    {#if loading}
      <div class="flex justify-center py-4">
        <span class="loading loading-spinner loading-xs"></span>
      </div>
    {:else if varFiles.length === 0}
      <div class="p-3 text-xs text-base-content/50">
        <p>No .tfvars files found.</p>
        <p class="mt-1">Create a <code>.tfvars</code> file in your project to manage variables.</p>
      </div>
    {:else}
      {#each varFiles as file}
        <button
          class="w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-base-300 transition-colors {selectedFile === file ? 'bg-base-300 text-primary' : 'text-base-content/70'}"
          onclick={() => selectFile(file)}
        >
          <span class="icon-[tabler--variable] size-3 mr-1 inline-block align-middle"></span>
          {file}
        </button>
      {/each}
    {/if}
  </div>

  <div class="flex-1 flex flex-col">
    {#if selectedFile}
      <div class="flex items-center gap-2 px-3 py-1.5 border-b border-base-content/10 bg-base-200">
        <span class="text-xs font-mono text-base-content/70">{selectedFile}</span>
        {#if isDirty}
          <span class="badge badge-xs badge-warning">modified</span>
        {/if}
        <div class="ms-auto flex gap-1">
          {#if success}
            <span class="text-xs text-success">{success}</span>
          {/if}
          <button class="btn btn-primary btn-xs" onclick={save} disabled={!isDirty || saving}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
      <textarea
        class="flex-1 bg-base-100 p-3 font-mono text-xs resize-none outline-none"
        bind:value={content}
        spellcheck="false"
      ></textarea>
    {:else}
      <div class="flex-1 flex items-center justify-center text-base-content/50">
        <p class="text-xs">Select a tfvars file to edit</p>
      </div>
    {/if}
  </div>
</div>
