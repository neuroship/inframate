<script>
  import { onMount } from "svelte";
  import { getProjectInfo } from "../lib/api.js";
  import { lastActionError } from "../lib/stores.js";
  import Resources from "../components/Resources.svelte";
  import Costs from "../components/Costs.svelte";
  import FileEditor from "../components/FileEditor.svelte";
  import VarsPanel from "../components/VarsPanel.svelte";
  import AiSidebar from "../components/AiSidebar.svelte";

  let projectDir = $state("");
  let activeTab = $state("resources");
  let error = $state("");
  let showAiSidebar = $state(false);
  let openFile = $state(null);
  let openLine = $state(null);
  let openSeq = $state(0);
  let loaded = $state(false);

  function handleNavigateToFile({ file, line }) {
    openFile = file;
    openLine = line;
    openSeq++;
    activeTab = "files";
  }

  const tabs = [
    { id: "resources", label: "Resources", icon: "icon-[tabler--table]" },
    { id: "costs", label: "Costs", icon: "icon-[tabler--currency-dollar]" },
    { id: "files", label: "Files", icon: "icon-[tabler--file-code]" },
    { id: "vars", label: "Variables", icon: "icon-[tabler--variable]" },
  ];

  onMount(async () => {
    try {
      const info = await getProjectInfo();
      projectDir = info.project_dir;
      loaded = true;
    } catch (e) {
      error = e.message;
      loaded = true;
    }
  });
</script>

{#if error}
  <div class="p-4">
    <div class="alert alert-soft alert-error text-xs">
      <span class="icon-[tabler--alert-circle] size-4"></span>
      {error}
    </div>
  </div>
{:else if !loaded}
  <div class="flex justify-center py-12">
    <span class="loading loading-spinner loading-sm"></span>
  </div>
{:else}
  <div class="flex flex-col h-full">
    <div class="bg-base-200 border-b border-base-content/10 px-4 pt-2">
      <div class="flex items-center gap-2 mb-2">
        <span class="icon-[tabler--terminal-2] size-3.5 text-base-content/40"></span>
        <span class="text-xs text-base-content/50 font-mono">{projectDir}</span>
        <button
          class="btn btn-text btn-xs btn-square ms-auto {showAiSidebar ? 'text-primary' : ''}"
          onclick={() => (showAiSidebar = !showAiSidebar)}
          aria-label="Toggle AI assistant"
          title="AI Assistant"
        >
          <span class="icon-[tabler--robot] size-4"></span>
        </button>
      </div>
      <div class="tabs tabs-bordered tabs-sm">
        {#each tabs as tab}
          <button
            class="tab gap-1.5 text-xs {activeTab === tab.id ? 'tab-active' : ''}"
            onclick={() => (activeTab = tab.id)}
          >
            <span class="{tab.icon} size-3.5"></span>
            {tab.label}
          </button>
        {/each}
      </div>
    </div>

    <div class="flex flex-1 overflow-hidden">
      <div class="flex-1 overflow-hidden relative">
        <div class="absolute inset-0 overflow-auto" class:hidden={activeTab !== "resources"}>
          <Resources onnavigate={handleNavigateToFile} />
        </div>
        <div class="absolute inset-0 overflow-auto" class:hidden={activeTab !== "costs"}>
          <Costs />
        </div>
        <div class="absolute inset-0 overflow-auto" class:hidden={activeTab !== "files"}>
          <FileEditor {openFile} {openLine} {openSeq} />
        </div>
        <div class="absolute inset-0 overflow-auto" class:hidden={activeTab !== "vars"}>
          <VarsPanel />
        </div>
      </div>
      {#if showAiSidebar}
        <AiSidebar
          onclose={() => (showAiSidebar = false)}
          actionContext={$lastActionError}
        />
      {/if}
    </div>
  </div>
{/if}
