<script>
  import { onMount } from "svelte";
  import { getProjectInfo } from "./lib/api.js";
  import Workspace from "./pages/Workspace.svelte";
  import Logo from "./lib/Logo.svelte";

  const stored = localStorage.getItem("theme");
  const initial = stored ? stored === "dark" : document.documentElement.getAttribute("data-theme") !== "light";
  document.documentElement.setAttribute("data-theme", initial ? "dark" : "light");

  let isDark = $state(initial);
  let projectDir = $state("");

  onMount(async () => {
    try {
      const info = await getProjectInfo();
      projectDir = info.project_dir;
    } catch {}
  });

  function toggleTheme() {
    isDark = !isDark;
    const theme = isDark ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }
</script>

<div class="flex flex-col h-screen">
  <nav class="navbar bg-base-200/80 border-b border-base-content/10 px-4 min-h-0 py-1.5 flex items-center">
    <div class="navbar-start gap-1.5 flex items-center">
      <div class="flex items-center gap-1.5">
        <Logo size={20} />
        <span class="text-sm font-semibold tracking-tight">inframate</span>
      </div>
      {#if projectDir}
        <span class="text-base-content/20 text-sm">/</span>
        <span class="text-xs text-base-content/50 font-mono truncate max-w-md" title={projectDir}>
          {projectDir}
        </span>
      {/if}
    </div>

    <div class="navbar-end flex items-center">
      <button class="btn btn-text btn-sm btn-square" onclick={toggleTheme} title="Toggle theme">
        <span class="{isDark ? 'icon-[tabler--sun]' : 'icon-[tabler--moon]'} size-4"></span>
      </button>
    </div>
  </nav>

  <main class="flex-1 overflow-hidden">
    <Workspace />
  </main>
</div>
