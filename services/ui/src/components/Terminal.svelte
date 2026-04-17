<script>
  import { streamTerraform, getVars } from "../lib/api.js";

  // no props

  let output = $state("");
  let running = $state(false);
  let runResult = $state(null); // null | "success" | "error"
  let controller = $state(null);
  let varFiles = $state([]);
  let selectedVarFile = $state("");
  let outputEl;

  import { onMount } from "svelte";

  onMount(async () => {
    try {
      varFiles = await getVars();
    } catch (_) {}
  });

  function hasError(text) {
    if (!text) return false;
    return /\bError[:\s]/i.test(text) || /failed/i.test(text);
  }

  function run(command) {
    output = "";
    running = true;
    runResult = null;
    const body = {};
    if (selectedVarFile) body.var_file = selectedVarFile;

    controller = streamTerraform(
      command,
      body,
      (data) => {
        output += data;
        if (outputEl) outputEl.scrollTop = outputEl.scrollHeight;
      },
      () => {
        running = false;
        runResult = hasError(output) ? "error" : "success";
      }
    );
  }

  function stop() {
    controller?.abort();
    running = false;
    output += "\n[Aborted]\n";
  }
</script>

<div class="flex flex-col h-full">
  <div class="flex items-center gap-2 px-4 py-2 border-b border-base-content/10 bg-base-200">
    <button class="btn btn-soft btn-sm" onclick={() => run("init")} disabled={running}>
      <span class="icon-[tabler--download] size-3.5"></span>
      Init
    </button>
    <button class="btn btn-primary btn-sm" onclick={() => run("plan")} disabled={running}>
      <span class="icon-[tabler--list-check] size-3.5"></span>
      Plan
    </button>
    <button class="btn btn-soft btn-success btn-sm" onclick={() => run("apply")} disabled={running}>
      <span class="icon-[tabler--rocket] size-3.5"></span>
      Apply
    </button>
    <button class="btn btn-soft btn-error btn-sm" onclick={() => run("destroy")} disabled={running}>
      <span class="icon-[tabler--trash] size-3.5"></span>
      Destroy
    </button>

    {#if varFiles.length > 0}
      <select class="select select-sm text-xs" bind:value={selectedVarFile}>
        <option value="">No var file</option>
        {#each varFiles as vf}
          <option value={vf}>{vf}</option>
        {/each}
      </select>
    {/if}

    <div class="ms-auto flex items-center gap-2">
      {#if running}
        <span class="loading loading-spinner loading-xs text-primary"></span>
        <button class="btn btn-soft btn-error btn-xs" onclick={stop}>Stop</button>
      {:else if runResult === "success"}
        <span class="flex items-center gap-1 text-success text-xs font-medium"><span class="icon-[tabler--circle-check] size-3.5"></span>Completed</span>
      {:else if runResult === "error"}
        <span class="flex items-center gap-1 text-error text-xs font-medium"><span class="icon-[tabler--circle-x] size-3.5"></span>Failed</span>
      {/if}
      <button class="btn btn-text btn-xs" onclick={() => { output = ""; runResult = null; }} disabled={running}>
        Clear
      </button>
    </div>
  </div>

  <pre
    bind:this={outputEl}
    class="flex-1 bg-base-300 p-3 font-mono text-xs overflow-auto whitespace-pre-wrap"
  >{output || "Run a terraform command to see output here."}</pre>
</div>
