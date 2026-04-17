<script>
  import { onMount, onDestroy } from "svelte";
  import { createGrid, ModuleRegistry, AllCommunityModule, themeAlpine } from "ag-grid-community";
  import { AllEnterpriseModule } from "ag-grid-enterprise";
  import { getCosts } from "../lib/api.js";

  ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

  // no props

  let gridEl = $state();
  let gridApi = null;
  let loading = $state(false);
  let error = $state("");
  let rows = $state([]);
  let selectedPeriod = $state(30);
  let totalCost = $state(null);
  let serviceCosts = $state([]);
  let searchText = $state("");

  const periods = [7, 14, 30, 60, 90];

  let isDark = $state(document.documentElement.getAttribute("data-theme") !== "light");
  const obs = new MutationObserver(() => {
    isDark = document.documentElement.getAttribute("data-theme") !== "light";
  });
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const darkTheme = themeAlpine.withParams({
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    backgroundColor: "transparent",
    headerBackgroundColor: "rgba(255,255,255,0.03)",
    oddRowBackgroundColor: "rgba(255,255,255,0.01)",
    rowHoverColor: "rgba(255,255,255,0.04)",
    borderColor: "rgba(255,255,255,0.06)",
    headerForegroundColor: "rgba(255,255,255,0.5)",
    foregroundColor: "rgba(255,255,255,0.8)",
    fontSize: 10.5, headerFontWeight: 600, cellHorizontalPadding: 8, gridSize: 3, rowGroupIndentSize: 24,
  });
  const lightTheme = themeAlpine.withParams({
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    backgroundColor: "transparent",
    headerBackgroundColor: "rgba(0,0,0,0.03)",
    oddRowBackgroundColor: "rgba(0,0,0,0.02)",
    rowHoverColor: "rgba(0,0,0,0.04)",
    borderColor: "rgba(0,0,0,0.08)",
    headerForegroundColor: "rgba(0,0,0,0.6)",
    foregroundColor: "rgba(0,0,0,0.85)",
    fontSize: 10.5, headerFontWeight: 600, cellHorizontalPadding: 8, gridSize: 3, rowGroupIndentSize: 24,
  });
  let gridTheme = $derived(isDark ? darkTheme : lightTheme);

  $effect(() => {
    if (gridApi) gridApi.setGridOption("theme", gridTheme);
  });

  $effect(() => {
    searchText;
    applySearch();
  });

  function CostRenderer(params) {
    const cost = params.value;
    if (cost == null) return null;
    if (params.node?.group) {
      if (cost === 0) return null;
      const el = document.createElement("span");
      el.style.cssText = "font-size:10px;font-weight:600;font-family:monospace;";
      el.textContent = `$${cost.toFixed(2)}`;
      return el;
    }
    const el = document.createElement("span");
    if (cost === 0) {
      el.style.cssText = "font-size:10px;opacity:0.3;";
      el.textContent = "\u2014";
    } else {
      el.style.cssText = "font-size:10px;font-weight:500;font-family:monospace;";
      el.textContent = `$${cost.toFixed(2)}`;
      if (cost > 100) el.style.color = "#ef4444";
      else if (cost > 10) el.style.color = "#f59e0b";
      else el.style.color = "#10b981";
    }
    return el;
  }

  function ActionRenderer(params) {
    if (params.node?.group) return null;
    const action = params.value;
    if (!action || action === "no-op") return null;
    const styles = {
      create: { color: "#6366f1", label: "Create" },
      update: { color: "#f59e0b", label: "Update" },
      destroy: { color: "#ef4444", label: "Destroy" },
      replace: { color: "#ec4899", label: "Replace" },
    };
    const s = styles[action] || { color: "#6b7280", label: action };
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;`;
    el.innerHTML = `<span style="width:5px;height:5px;border-radius:50%;background:${s.color};display:inline-block;"></span>${s.label}`;
    return el;
  }

  function ArnRenderer(params) {
    if (params.node?.group) return null;
    const arn = params.value;
    if (!arn) return null;
    const el = document.createElement("span");
    el.style.cssText = "font-size:9px;font-family:monospace;opacity:0.5;";
    el.textContent = arn.length > 50 ? "\u2026" + arn.slice(-45) : arn;
    el.title = arn;
    return el;
  }

  const columnDefs = [
    { headerName: "Service", field: "service", rowGroup: true, hide: true },
    { headerName: "Category", field: "category", rowGroup: true, hide: true },
    {
      headerName: "Name", field: "resource_name", flex: 2, minWidth: 160,
      filter: "agTextColumnFilter", cellStyle: { fontSize: "11px" },
    },
    { headerName: "Type", field: "display_type", width: 140, filter: "agTextColumnFilter",
      cellStyle: { fontSize: "10px", opacity: 0.6 } },
    { headerName: "Action", field: "action", width: 90, cellRenderer: ActionRenderer, filter: true },
    { headerName: "Cost/mo", field: "cost_monthly", width: 100, cellRenderer: CostRenderer, aggFunc: "sum", sort: "desc" },
    { headerName: "ARN", field: "arn", flex: 2, minWidth: 120, cellRenderer: ArnRenderer, filter: "agTextColumnFilter" },
  ];

  function applySearch() {
    if (!gridApi) return;
    if (!searchText.trim()) {
      gridApi.setGridOption("rowData", rows);
      return;
    }
    const q = searchText.trim().toLowerCase();
    gridApi.setGridOption("rowData", rows.filter((r) =>
      (r.resource_name || "").toLowerCase().includes(q) ||
      (r.arn || "").toLowerCase().includes(q) ||
      (r.resource_type || "").toLowerCase().includes(q) ||
      (r.service || "").toLowerCase().includes(q)
    ));
  }

  async function fetchCosts() {
    loading = true;
    error = "";
    try {
      const data = await getCosts(selectedPeriod);

      // Per-resource costs from overview resources
      let resources = (data.resources || []).filter((r) => r.cost_monthly != null && r.cost_monthly > 0);

      // Build service summary from service_costs
      const svc = data.service_costs || {};
      serviceCosts = Object.entries(svc)
        .filter(([k, v]) => !k.startsWith("_") && v.total > 0.01)
        .map(([name, v]) => ({ name, total: v.total }))
        .sort((a, b) => b.total - a.total);

      // If no per-resource data but we have service costs, show service-level rows
      if (resources.length === 0 && serviceCosts.length > 0) {
        resources = serviceCosts.map((s) => ({
          service: s.name.replace(/Amazon |AWS /g, ""),
          category: "service",
          resource_name: s.name,
          display_type: "Service Total",
          action: "",
          cost_monthly: Math.round(s.total * 100) / 100,
          arn: "",
          resource_type: "",
        }));
      }

      rows = resources;
      totalCost = data.total_monthly ?? serviceCosts.reduce((s, c) => s + c.total, 0);
      gridApi?.setGridOption("rowData", resources);
    } catch (e) {
      error = e.message;
    }
    loading = false;
  }

  function initGrid() {
    if (gridEl && !gridApi) {
      gridApi = createGrid(gridEl, {
        theme: gridTheme,
        columnDefs,
        rowData: rows,
        defaultColDef: { sortable: true, resizable: true },
        animateRows: true,
        groupDefaultExpanded: 1,
        groupDisplayType: "multipleColumns",
        autoGroupColumnDef: { minWidth: 180 },
        grandTotalRow: "bottom",
        rowHeight: 34,
        headerHeight: 32,
      });
    } else if (gridApi) {
      gridApi.setGridOption("rowData", rows);
    }
  }

  onMount(async () => {
    await fetchCosts();
    requestAnimationFrame(initGrid);
  });

  onDestroy(() => {
    obs.disconnect();
    gridApi?.destroy();
  });
</script>

<div class="flex flex-col h-full">
  <!-- Action bar -->
  <div class="flex items-center gap-3 px-4 py-2 border-b border-base-content/10 bg-base-200">
    <!-- Period selector -->
    <div class="flex items-center gap-1">
      {#each periods as p}
        <button
          class="btn btn-xs {selectedPeriod === p ? 'btn-primary' : 'btn-soft'}"
          onclick={() => { selectedPeriod = p; fetchCosts(); }}
          disabled={loading}
        >
          {p}d
        </button>
      {/each}
    </div>

    <div class="w-px h-5 bg-base-content/10"></div>

    <button
      class="btn btn-soft btn-xs"
      onclick={fetchCosts}
      disabled={loading}
    >
      {#if loading}
        <span class="loading loading-spinner loading-xs"></span>
      {:else}
        <span class="icon-[tabler--refresh] size-3.5"></span>
      {/if}
      Refresh
    </button>

    <div class="ms-auto flex items-center gap-2">
      <div class="relative">
        <span class="icon-[tabler--search] size-3 absolute left-2 top-1/2 -translate-y-1/2 text-base-content/30"></span>
        <input
          type="text"
          class="input input-xs pl-7 w-44 text-xs"
          placeholder="Search name or ARN..."
          bind:value={searchText}
        />
      </div>
      {#if totalCost !== null}
        <div class="flex items-center gap-1.5 text-xs">
          <span class="icon-[tabler--currency-dollar] size-4 text-base-content/40"></span>
          <span class="font-mono font-semibold text-sm">{totalCost.toFixed(2)}</span>
          <span class="text-base-content/30">/mo</span>
        </div>
      {/if}
    </div>
  </div>

  {#if error}
    <div class="p-4">
      <div class="alert alert-soft alert-error text-xs">
        <span class="icon-[tabler--alert-circle] size-4"></span>
        {error}
      </div>
    </div>
  {/if}

  <!-- Service cost summary -->
  {#if serviceCosts.length > 0}
    <div class="flex items-center gap-2 px-4 py-1.5 border-b border-base-content/10 flex-wrap">
      {#each serviceCosts as svc}
        <div class="flex items-center gap-1.5 text-xs text-base-content/50">
          <span class="font-medium text-base-content/70">{svc.name.replace(/Amazon |AWS /g, "")}</span>
          <span class="font-mono text-base-content/40">${svc.total.toFixed(2)}</span>
        </div>
        {#if svc !== serviceCosts[serviceCosts.length - 1]}
          <div class="w-px h-3 bg-base-content/10"></div>
        {/if}
      {/each}
    </div>
  {/if}

  <!-- Grid -->
  {#if loading && rows.length === 0}
    <div class="flex flex-col items-center justify-center py-12 gap-3">
      <span class="loading loading-spinner loading-md text-primary"></span>
      <span class="text-xs text-base-content/50">Fetching cost data...</span>
    </div>
  {:else}
    <div class="flex-1" bind:this={gridEl}></div>
  {/if}
</div>

<style>
  :global(.ag-watermark) {
    display: none !important;
  }
</style>
