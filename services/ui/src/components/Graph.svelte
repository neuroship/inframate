<script>
  import { onMount, onDestroy } from "svelte";
  import { createGrid, ModuleRegistry, AllCommunityModule, themeAlpine } from "ag-grid-community";
  import { AllEnterpriseModule } from "ag-grid-enterprise";
  import { getOverview } from "../lib/api.js";

  ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

  const gridTheme = themeAlpine.withParams({
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    backgroundColor: "transparent",
    headerBackgroundColor: "rgba(255,255,255,0.03)",
    oddRowBackgroundColor: "rgba(255,255,255,0.01)",
    rowHoverColor: "rgba(255,255,255,0.04)",
    borderColor: "rgba(255,255,255,0.06)",
    headerForegroundColor: "rgba(255,255,255,0.5)",
    foregroundColor: "rgba(255,255,255,0.8)",
    fontSize: 10.5,
    headerFontWeight: 600,
    cellHorizontalPadding: 8,
    gridSize: 3,
    rowGroupIndentSize: 24,
  });

  // no props

  let gridEl = $state();
  let gridApi = null;
  let loading = $state(true);
  let error = $state("");
  let stats = $state({ total: 0, applied: 0, planned: 0, categories: {} });

  const CATEGORY_COLORS = {
    compute: "#6366f1",
    storage: "#f59e0b",
    network: "#06b6d4",
    security: "#ef4444",
    dns: "#8b5cf6",
    monitoring: "#10b981",
    messaging: "#ec4899",
    devtools: "#f97316",
    data: "#06b6d4",
    resource: "#6b7280",
  };

  const CATEGORY_LABELS = {
    compute: "Compute",
    storage: "Storage",
    network: "Network",
    security: "Security",
    dns: "DNS",
    monitoring: "Monitoring",
    messaging: "Messaging",
    devtools: "DevTools",
    data: "Data Source",
    resource: "Other",
  };

  function CategoryGroupRenderer(params) {
    const cat = params.value || "resource";
    const color = CATEGORY_COLORS[cat] || "#6b7280";
    const label = CATEGORY_LABELS[cat] || cat;
    const count = params.node?.allChildrenCount || 0;
    const el = document.createElement("span");
    el.style.cssText = "display:inline-flex;align-items:center;gap:6px;";
    el.innerHTML = `
      <span style="width:10px;height:10px;border-radius:3px;background:${color};display:inline-block;"></span>
      <span style="font-size:12px;font-weight:600;text-transform:capitalize;">${label}</span>
      <span style="font-size:10px;opacity:0.4;">${count}</span>
    `;
    return el;
  }

  function TypeGroupRenderer(params) {
    const val = params.value || "";
    const count = params.node?.allChildrenCount || 0;
    const el = document.createElement("span");
    el.style.cssText = "display:inline-flex;align-items:center;gap:6px;";
    el.innerHTML = `
      <span style="font-size:11px;font-weight:500;">${val}</span>
      <span style="font-size:10px;opacity:0.35;">${count}</span>
    `;
    return el;
  }

  function StatusRenderer(params) {
    const status = params.value || "planned";
    if (params.node?.group) return null;
    const isApplied = status === "applied";
    const el = document.createElement("span");
    el.style.cssText = "display:inline-flex;align-items:center;gap:4px;font-size:11px;";
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${isApplied ? "#10b981" : "#f59e0b"};display:inline-block;"></span>${isApplied ? "Applied" : "Planned"}`;
    return el;
  }

  function TagsRenderer(params) {
    if (params.node?.group) return null;
    const tags = params.value;
    if (!tags || typeof tags !== "object" || Object.keys(tags).length === 0)
      return null;
    const el = document.createElement("div");
    el.style.cssText = "display:flex;gap:3px;flex-wrap:wrap;align-items:center;";
    for (const [k, v] of Object.entries(tags).slice(0, 3)) {
      const tag = document.createElement("span");
      tag.style.cssText = "font-size:9px;padding:1px 5px;border-radius:4px;background:rgba(100,116,139,0.15);";
      tag.textContent = `${k}: ${v}`;
      el.appendChild(tag);
    }
    if (Object.keys(tags).length > 3) {
      const more = document.createElement("span");
      more.style.cssText = "font-size:9px;opacity:0.4;";
      more.textContent = `+${Object.keys(tags).length - 3}`;
      el.appendChild(more);
    }
    return el;
  }

  function ArnRenderer(params) {
    if (params.node?.group) return null;
    const arn = params.value;
    if (!arn) return null;
    const el = document.createElement("span");
    el.style.cssText = "font-size:9px;font-family:monospace;opacity:0.5;";
    el.textContent = arn.length > 50 ? "…" + arn.slice(-45) : arn;
    el.title = arn;
    return el;
  }

  function DepsRenderer(params) {
    if (params.node?.group) return null;
    const deps = params.value;
    if (!deps || deps.length === 0) return null;
    const el = document.createElement("span");
    el.style.cssText = "font-size:10px;opacity:0.5;";
    el.textContent = `${deps.length}`;
    el.title = deps.join("\n");
    return el;
  }

  const columnDefs = [
    {
      headerName: "Category",
      field: "category",
      rowGroup: true,
      hide: true,
    },
    {
      headerName: "Type",
      field: "label",
      rowGroup: true,
      hide: true,
    },
    {
      headerName: "Name",
      field: "resource_name",
      flex: 2,
      minWidth: 160,
      filter: "agTextColumnFilter",
      cellStyle: { fontSize: "11px" },
    },
    {
      headerName: "Status",
      field: "status",
      width: 95,
      cellRenderer: StatusRenderer,
      filter: true,
    },
    {
      headerName: "ARN",
      field: "arn",
      flex: 2,
      minWidth: 140,
      cellRenderer: ArnRenderer,
      filter: "agTextColumnFilter",
    },
    {
      headerName: "Tags",
      field: "tags",
      flex: 1,
      minWidth: 100,
      cellRenderer: TagsRenderer,
    },
    {
      headerName: "Deps",
      field: "depends_on",
      width: 55,
      cellRenderer: DepsRenderer,
    },
  ];

  const detailColumnDefs = [
    {
      headerName: "Attribute",
      field: "key",
      flex: 1,
      filter: true,
      cellStyle: { fontFamily: "monospace", fontSize: "11px", fontWeight: 600 },
    },
    {
      headerName: "Value",
      field: "value",
      flex: 3,
      filter: true,
      cellStyle: { fontFamily: "monospace", fontSize: "11px" },
      autoHeight: true,
      wrapText: true,
    },
  ];

  const gridOptions = {
    theme: gridTheme,
    columnDefs,
    rowData: [],
    defaultColDef: {
      sortable: true,
      resizable: true,
    },
    animateRows: true,
    groupDefaultExpanded: 0,
    groupDisplayType: "multipleColumns",
    autoGroupColumnDef: {
      minWidth: 200,
    },
    masterDetail: true,
    detailCellRendererParams: {
      detailGridOptions: {
        columnDefs: detailColumnDefs,
        defaultColDef: { sortable: true, resizable: true },
      },
      getDetailRowData: (params) => {
        const attrs = params.data?.attributes || {};
        const detail = Object.entries(attrs)
          .filter(([_, v]) => v !== null && v !== "")
          .map(([key, value]) => ({
            key,
            value: typeof value === "object" ? JSON.stringify(value, null, 2) : String(value),
          }));
        params.successCallback(detail);
      },
    },
    isRowMaster: (data) => {
      return data?.attributes && Object.keys(data.attributes).length > 0;
    },
    rowHeight: 34,
    headerHeight: 32,
  };

  onMount(async () => {
    try {
      const data = await getOverview();

      const s = { total: data.length, applied: 0, planned: 0, categories: {} };
      for (const r of data) {
        if (r.status === "applied") s.applied++;
        else s.planned++;
        const cat = r.category || "resource";
        s.categories[cat] = (s.categories[cat] || 0) + 1;
      }
      stats = s;

      requestAnimationFrame(() => {
        if (gridEl) {
          gridApi = createGrid(gridEl, {
            ...gridOptions,
            rowData: data,
          });
        }
      });
    } catch (e) {
      error = e.message;
    }
    loading = false;
  });

  onDestroy(() => {
    gridApi?.destroy();
  });
</script>

<div class="flex flex-col h-full">
  {#if loading}
    <div class="flex justify-center py-8">
      <span class="loading loading-spinner loading-sm"></span>
    </div>
  {:else if error}
    <div class="p-4">
      <div class="alert alert-soft alert-error text-xs">
        <span class="icon-[tabler--alert-circle] size-4"></span>
        {error}
      </div>
    </div>
  {:else}
    <!-- Stats bar -->
    <div class="flex items-center gap-3 px-4 py-2 border-b border-base-content/10 bg-base-200 flex-wrap">
      <div class="flex items-center gap-1.5 text-xs">
        <span class="icon-[tabler--box] size-3.5 text-base-content/50"></span>
        <span class="font-medium">{stats.total}</span>
        <span class="text-base-content/50">resources</span>
      </div>
      <div class="w-px h-4 bg-base-content/10"></div>
      <div class="flex items-center gap-1.5 text-xs">
        <span class="w-1.5 h-1.5 rounded-full bg-success"></span>
        <span>{stats.applied} applied</span>
      </div>
      <div class="flex items-center gap-1.5 text-xs">
        <span class="w-1.5 h-1.5 rounded-full bg-warning"></span>
        <span>{stats.planned} planned</span>
      </div>
      <div class="w-px h-4 bg-base-content/10"></div>
      {#each Object.entries(stats.categories).sort((a, b) => b[1] - a[1]) as [cat, count]}
        <div class="flex items-center gap-1 text-xs text-base-content/50">
          <span class="w-2 h-2 rounded-sm" style="background: {CATEGORY_COLORS[cat] || '#6b7280'}"></span>
          <span class="capitalize">{cat}</span>
          <span class="text-base-content/30">{count}</span>
        </div>
      {/each}
    </div>

    <!-- AG Grid -->
    <div class="flex-1" bind:this={gridEl}></div>
  {/if}
</div>

<style>
  :global(.ag-watermark) {
    display: none !important;
  }
</style>
