<script>
  import { onMount, onDestroy } from "svelte";
  import { createGrid, ModuleRegistry, AllCommunityModule, themeAlpine } from "ag-grid-community";
  import { AllEnterpriseModule } from "ag-grid-enterprise";
  import { streamInventory, getCosts, streamTerraform, streamAwsDelete, checkAwsDeletePreconditions } from "../lib/api.js";
  import ConfirmModal from "./ConfirmModal.svelte";

  ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

  let { onnavigate = null } = $props();

  let gridEl = $state();
  let gridApi = null;
  let scanning = $state(false);
  let phase = $state("");
  let scanLog = $state("");
  let error = $state("");
  let rows = $state([]);
  let stats = $state({ total: 0, both: 0, aws_only: 0, tf_only: 0 });
  let activeFilter = $state("all"); // "all" | "aws_only" | "tf_only" | "both"
  let searchText = $state("");

  // Costs
  let costsLoading = $state(false);
  let totalCost = $state(null);

  // Selection & actions
  let selectedCount = $state(0);
  let actionOutput = $state("");
  let actionRunning = $state(false);
  let actionLabel = $state("");
  let showOutput = $state(false);
  let outputEl = $state();
  let actionResult = $state(null); // null | "success" | "error"
  let confirmOpen = $state(false);
  let confirmMessage = $state("");
  let confirmType = $state("");
  let preconditionWarnings = $state([]);

  // Map inventory resource type → AWS billing service name (for fallback cost distribution)
  const TYPE_TO_BILLING = {
    aws_instance: "Amazon Elastic Compute Cloud - Compute",
    aws_eip: "Amazon Elastic Compute Cloud - Compute",
    aws_lb: "Amazon Elastic Load Balancing",
    aws_alb: "Amazon Elastic Load Balancing",
    aws_lb_target_group: "Amazon Elastic Load Balancing",
    aws_db_instance: "Amazon Relational Database Service",
    aws_rds_cluster: "Amazon Relational Database Service",
    aws_s3_bucket: "Amazon Simple Storage Service",
    aws_lambda_function: "AWS Lambda",
    aws_ecs_service: "Amazon Elastic Container Service",
    aws_ecs_cluster: "Amazon Elastic Container Service",
    aws_cloudfront_distribution: "Amazon CloudFront",
    aws_route53_zone: "Amazon Route 53",
    aws_cloudwatch_log_group: "Amazon CloudWatch",
    aws_dynamodb_table: "Amazon DynamoDB",
    aws_sqs_queue: "Amazon Simple Queue Service",
    aws_sns_topic: "Amazon Simple Notification Service",
    aws_kms_key: "AWS Key Management Service",
    aws_secretsmanager_secret: "AWS Secrets Manager",
    aws_ecr_repository: "Amazon EC2 Container Registry (ECR)",
    aws_efs_file_system: "Amazon Elastic File System",
    aws_nat_gateway: "Amazon Virtual Private Cloud",
    aws_cognito_user_pool: "Amazon Cognito",
    aws_guardduty_detector: "Amazon GuardDuty",
    aws_api_gateway_rest_api: "Amazon API Gateway",
    aws_apigatewayv2_api: "Amazon API Gateway",
    aws_eks_cluster: "Amazon Elastic Kubernetes Service",
    aws_elasticache_cluster: "Amazon ElastiCache",
  };

  let isDark = $state(document.documentElement.getAttribute("data-theme") !== "light");
  const obs = new MutationObserver(() => {
    isDark = document.documentElement.getAttribute("data-theme") !== "light";
  });
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const darkTheme = themeAlpine.withParams({
    fontFamily: "'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace",
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
    fontFamily: "'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace",
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
    applyFilter();
  });

  function SourceRenderer(params) {
    if (params.node?.group) return null;
    const src = params.value;
    const styles = {
      both: { color: "#10b981", label: "Matched" },
      aws_only: { color: "#f59e0b", label: "AWS Only" },
      tf_only: { color: "#8b5cf6", label: "TF Only" },
    };
    const s = styles[src] || { color: "#6b7280", label: src };
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:600;`;
    el.innerHTML = `<span style="width:7px;height:7px;border-radius:2px;background:${s.color};display:inline-block;"></span>${s.label}`;
    return el;
  }

  function ConsoleUrlRenderer(params) {
    if (params.node?.group) return null;
    const url = params.value;
    if (!url) return null;
    const el = document.createElement("a");
    el.href = url;
    el.target = "_blank";
    el.rel = "noopener";
    el.style.cssText = "font-size:10px;color:#06b6d4;text-decoration:none;display:inline-flex;align-items:center;gap:3px;";
    el.innerHTML = `<span style="font-size:12px;">↗</span>Console`;
    return el;
  }

  function DefRenderer(params) {
    if (params.node?.group) return null;
    const file = params.data?.tf_file;
    const line = params.data?.tf_line;
    if (!file) return null;
    const el = document.createElement("button");
    el.style.cssText = "font-size:10px;color:#8b5cf6;background:none;border:none;cursor:pointer;display:inline-flex;align-items:center;gap:3px;padding:0;";
    el.innerHTML = `<span style="font-size:12px;">⌖</span>${file}:${line}`;
    el.title = `Go to ${file} line ${line}`;
    el.onclick = (e) => {
      e.stopPropagation();
      if (onnavigate) onnavigate({ file, line });
    };
    return el;
  }

  function TfActionRenderer(params) {
    if (params.node?.group) return null;
    const action = params.value;
    if (!action) return null;
    const styles = {
      "no-op": { color: "#10b981", label: "No Change" },
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

  function TagsRenderer(params) {
    if (params.node?.group) return null;
    const tags = params.value;
    if (!tags || typeof tags !== "object" || Object.keys(tags).length === 0) return null;
    const el = document.createElement("div");
    el.style.cssText = "display:flex;gap:3px;flex-wrap:wrap;align-items:center;";
    for (const [k, v] of Object.entries(tags).slice(0, 2)) {
      const tag = document.createElement("span");
      tag.style.cssText = "font-size:9px;padding:1px 4px;border-radius:3px;background:rgba(100,116,139,0.15);";
      tag.textContent = `${k}: ${v}`;
      el.appendChild(tag);
    }
    if (Object.keys(tags).length > 2) {
      const more = document.createElement("span");
      more.style.cssText = "font-size:9px;opacity:0.4;";
      more.textContent = `+${Object.keys(tags).length - 2}`;
      el.appendChild(more);
    }
    return el;
  }

  function ExtraRenderer(params) {
    if (params.node?.group) return null;
    const extra = params.value;
    if (!extra || typeof extra !== "object" || Object.keys(extra).length === 0) return null;
    const el = document.createElement("span");
    el.style.cssText = "font-size:9px;opacity:0.5;font-family:monospace;";
    el.textContent = Object.entries(extra)
      .filter(([_, v]) => v !== "" && v !== 0)
      .map(([k, v]) => `${k}=${v}`)
      .slice(0, 3)
      .join(" ");
    return el;
  }

  function CostRenderer(params) {
    if (params.node?.group) {
      // Show aggregated value for group rows
      const val = params.value;
      if (val == null || val === 0) return null;
      const el = document.createElement("span");
      el.style.cssText = "font-size:10px;font-weight:600;font-family:monospace;opacity:0.6;";
      el.textContent = `$${val.toFixed(2)}`;
      return el;
    }
    const cost = params.value;
    if (cost == null) return null;
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

  const columnDefs = [
    { headerName: "Service", field: "service", rowGroup: true, hide: true },
    { headerName: "Type", field: "type", rowGroup: true, hide: true },
    {
      headerName: "Name", field: "name", flex: 2, minWidth: 160,
      filter: "agTextColumnFilter", cellStyle: { fontSize: "10.5px" },
    },
    { headerName: "Source", field: "source", width: 100, cellRenderer: SourceRenderer, filter: true },
    { headerName: "TF Name", field: "tf_resource_name", width: 120, filter: "agTextColumnFilter",
      cellStyle: { fontSize: "10px", fontFamily: "monospace", opacity: 0.6 } },
    { headerName: "TF Action", field: "tf_action", width: 100, cellRenderer: TfActionRenderer, filter: true },
    { headerName: "Def", field: "tf_file", width: 120, cellRenderer: DefRenderer },
    { headerName: "AWS", field: "console_url", width: 70, cellRenderer: ConsoleUrlRenderer },
    { headerName: "ARN / ID", field: "arn", flex: 2, minWidth: 120,
      cellStyle: { fontSize: "9px", fontFamily: "monospace", opacity: 0.5 },
      filter: "agTextColumnFilter" },
    { headerName: "Cost/mo", field: "cost_monthly", width: 85, cellRenderer: CostRenderer, aggFunc: "sum", sort: "desc" },
    { headerName: "Tags", field: "tags", flex: 1, minWidth: 80, cellRenderer: TagsRenderer },
    { headerName: "Details", field: "extra", flex: 1, minWidth: 100, cellRenderer: ExtraRenderer },
  ];

  function scan() {
    scanning = true;
    phase = "Starting scan...";
    scanLog = "";
    rows = [];
    error = "";
    gridApi?.setGridOption("loading", true);

    streamInventory(
      (raw) => {
        try {
          const msg = JSON.parse(raw);
          if (msg.type === "phase") {
            phase = msg.message || msg.phase;
            if (msg.count != null) scanLog = `Found ${msg.count} resources`;
          } else if (msg.type === "log") {
            scanLog = msg.message;
          } else if (msg.type === "result") {
            rows = msg.data;
            computeStats(msg.data);
            gridApi?.setGridOption("rowData", msg.data);
            gridApi?.setGridOption("loading", false);
          }
        } catch (_) {}
      },
      () => {
        scanning = false;
        phase = "";
        scanLog = "";
        gridApi?.setGridOption("loading", false);
        if (rows.length > 0) fetchCosts();
      }
    );
  }

  function computeStats(data) {
    const s = { total: data.length, both: 0, aws_only: 0, tf_only: 0 };
    for (const r of data) {
      if (r.source === "both") s.both++;
      else if (r.source === "aws_only") s.aws_only++;
      else if (r.source === "tf_only") s.tf_only++;
    }
    stats = s;
  }

  function applyFilter(filter) {
    if (filter !== undefined) activeFilter = filter;
    if (!gridApi) return;
    let filtered = rows;
    if (activeFilter !== "all") {
      filtered = filtered.filter((r) => r.source === activeFilter);
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      filtered = filtered.filter((r) =>
        (r.name || "").toLowerCase().includes(q) ||
        (r.arn || "").toLowerCase().includes(q) ||
        (r.type || "").toLowerCase().includes(q) ||
        (r.tf_resource_name || "").toLowerCase().includes(q) ||
        (r.service || "").toLowerCase().includes(q)
      );
    }
    gridApi.setGridOption("rowData", filtered);
  }

  function getSelectedTfAddresses() {
    const selected = gridApi?.getSelectedRows() || [];
    return selected
      .filter((r) => r.tf_resource_name && r.source !== "aws_only")
      .map((r) => `${r.type}.${r.tf_resource_name}`);
  }

  function hasError(output) {
    if (!output) return false;
    if (/Apply complete!/.test(output)) return false;
    if (/Plan:.*to add/.test(output) && !/\bError:/.test(output)) return false;
    return /\bError:/.test(output) || /Apply.*failed/.test(output) || /exited with non-zero/.test(output);
  }

  async function handleDestroyClick() {
    const sel = gridApi?.getSelectedRows() || [];
    const awsOnly = sel.filter(r => r.source === "aws_only");
    const awsN = awsOnly.length;
    const tfN = sel.length - awsN;
    const parts = [];
    if (tfN > 0) parts.push(`${tfN} via terraform`);
    if (awsN > 0) parts.push(`${awsN} via AWS API`);

    // Check preconditions for AWS-only resources
    preconditionWarnings = [];
    if (awsOnly.length > 0) {
      try {
        preconditionWarnings = await checkAwsDeletePreconditions(awsOnly);
      } catch (_) {}
    }

    let msg = `Delete ${selectedCount} resource${selectedCount > 1 ? "s" : ""} (${parts.join(", ")})? This cannot be undone.`;
    if (preconditionWarnings.length > 0) {
      msg += "\n\nThe following resources require additional steps:";
      for (const w of preconditionWarnings) {
        msg += `\n• ${w.name}: ${w.warning}`;
      }
    }
    confirmMessage = msg;
    confirmType = "destroy_selected";
    confirmOpen = true;
  }

  function destroySelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;

    const tfAddrs = getSelectedTfAddresses();
    const awsOnlyResources = selected.filter((r) => r.source === "aws_only");

    actionOutput = "";
    actionRunning = true;
    actionResult = null;
    showOutput = true;

    let pending = 0;
    function onPartDone() {
      pending--;
      if (pending === 0) {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        scan();
      }
    }

    // Terraform destroy for managed resources
    if (tfAddrs.length > 0) {
      pending++;
      const targets = tfAddrs.map((a) => `-target=${a}`);
      actionLabel = `Destroy ${selected.length} resource${selected.length > 1 ? "s" : ""}`;
      streamTerraform("destroy", { args: targets },
        (data) => {
          actionOutput += data + "\n";
          if (outputEl) outputEl.scrollTop = outputEl.scrollHeight;
        },
        onPartDone
      );
    }

    // AWS delete for unmanaged resources
    if (awsOnlyResources.length > 0) {
      pending++;
      actionLabel = `Delete ${awsOnlyResources.length} AWS resource${awsOnlyResources.length > 1 ? "s" : ""}`;
      streamAwsDelete(awsOnlyResources,
        (data) => {
          actionOutput += data + "\n";
          if (outputEl) outputEl.scrollTop = outputEl.scrollHeight;
        },
        onPartDone
      );
    }
  }

  function taintSelected() {
    const addrs = getSelectedTfAddresses();
    if (addrs.length === 0) return;

    actionOutput = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = `Taint ${addrs.length} resource${addrs.length > 1 ? "s" : ""}`;
    showOutput = true;

    streamTerraform("taint", { addresses: addrs },
      (data) => {
        actionOutput += data;
        if (outputEl) outputEl.scrollTop = outputEl.scrollHeight;
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
      }
    );
  }

  async function fetchCosts() {
    costsLoading = true;
    try {
      const costData = await getCosts();

      // Build lookup from overview resources that have costs
      const costLookup = {};
      for (const r of costData.resources || []) {
        if (r.cost_monthly == null) continue;
        if (r.arn) costLookup[r.arn] = r.cost_monthly;
        const attrs = r.attributes || {};
        if (attrs.id) costLookup[attrs.id] = r.cost_monthly;
        if (attrs.name) costLookup[attrs.name] = r.cost_monthly;
        if (attrs.bucket) costLookup[attrs.bucket] = r.cost_monthly;
        if (r.resource_name) costLookup[r.resource_name] = r.cost_monthly;
      }

      // First pass: match by arn/id/name
      const unmatched = {};
      const updated = rows.map((row) => {
        const cost = costLookup[row.arn] ?? costLookup[row.id] ?? costLookup[row.name] ?? null;
        if (cost != null) return { ...row, cost_monthly: cost };
        // Track unmatched for service-level fallback
        const billing = TYPE_TO_BILLING[row.type];
        if (billing) {
          if (!unmatched[billing]) unmatched[billing] = [];
          unmatched[billing].push(row);
        }
        return { ...row, cost_monthly: null };
      });

      // Second pass: distribute service-level costs to unmatched rows
      const svcCosts = costData.service_costs || {};
      for (const [svc, svcRows] of Object.entries(unmatched)) {
        const svcTotal = svcCosts[svc]?.total;
        if (svcTotal && svcTotal > 0) {
          const perRow = svcTotal / svcRows.length;
          for (const row of svcRows) {
            const idx = updated.findIndex((r) => r.id === row.id && r.type === row.type);
            if (idx >= 0) updated[idx] = { ...updated[idx], cost_monthly: Math.round(perRow * 100) / 100 };
          }
        }
      }

      rows = updated;
      totalCost = Math.round(updated.reduce((sum, r) => sum + (r.cost_monthly || 0), 0) * 100) / 100;
      gridApi?.setGridOption("rowData", activeFilter === "all" ? updated : updated.filter((r) => r.source === activeFilter));
    } catch (e) {
      console.error("fetchCosts error:", e);
    }
    costsLoading = false;
  }

  onMount(() => {
    requestAnimationFrame(() => {
      if (gridEl) {
        gridApi = createGrid(gridEl, {
          theme: gridTheme,
          columnDefs,
          rowData: [],
          loading: true,
          defaultColDef: { sortable: true, resizable: true },
          animateRows: true,
          groupDefaultExpanded: 0,
          groupDisplayType: "multipleColumns",
          autoGroupColumnDef: { minWidth: 180, cellStyle: { fontSize: "10.5px" } },
          grandTotalRow: "bottom",
          rowSelection: { mode: "multiRow", checkboxes: true, headerCheckbox: true, groupSelects: "descendants" },
          isRowSelectable: (node) => !node.group,
          onSelectionChanged: () => {
            selectedCount = gridApi?.getSelectedRows()?.length || 0;
          },
          rowHeight: 34,
          headerHeight: 32,
        });
      }
    });

    // Auto-scan on mount
    scan();
  });

  onDestroy(() => {
    gridApi?.destroy();
  });
</script>

<div class="flex flex-col h-full">
  <!-- Action bar -->
  <div class="flex items-center gap-3 px-4 py-2 border-b border-base-content/10 bg-base-200">
    <button
      class="btn btn-soft btn-xs"
      onclick={scan}
      disabled={scanning}
    >
      {#if scanning}
        <span class="loading loading-spinner loading-xs"></span>
      {:else}
        <span class="icon-[tabler--refresh] size-3.5"></span>
      {/if}
      Rescan
    </button>

    {#if scanning}
      <span class="text-xs text-base-content/50">{phase}</span>
      {#if scanLog}
        <span class="text-[10px] font-mono text-base-content/30">{scanLog}</span>
      {/if}
    {/if}

    {#if !scanning && rows.length > 0}
      <div class="flex items-center gap-1">
        <button
          class="btn btn-xs {activeFilter === 'all' ? 'btn-primary' : 'btn-soft'}"
          onclick={() => applyFilter("all")}
        >
          All {stats.total}
        </button>
        <button
          class="btn btn-xs {activeFilter === 'both' ? 'btn-primary' : 'btn-soft'}"
          onclick={() => applyFilter("both")}
        >
          <span class="w-1.5 h-1.5 rounded-sm bg-success"></span>
          Matched {stats.both}
        </button>
        <button
          class="btn btn-xs {activeFilter === 'aws_only' ? 'btn-warning' : 'btn-soft'}"
          onclick={() => applyFilter("aws_only")}
        >
          <span class="w-1.5 h-1.5 rounded-sm bg-warning"></span>
          Orphans {stats.aws_only}
        </button>
        <button
          class="btn btn-xs {activeFilter === 'tf_only' ? 'btn-primary' : 'btn-soft'}"
          onclick={() => applyFilter("tf_only")}
          style={activeFilter === 'tf_only' ? 'background:#8b5cf6;border-color:#8b5cf6;' : ''}
        >
          <span class="w-1.5 h-1.5 rounded-sm" style="background:#8b5cf6"></span>
          TF Only {stats.tf_only}
        </button>
      </div>

      {#if selectedCount > 0}
        <div class="w-px h-5 bg-base-content/10"></div>
        <button class="btn btn-error btn-xs" onclick={handleDestroyClick} disabled={actionRunning}>
          <span class="icon-[tabler--trash] size-3.5"></span> Destroy {selectedCount}
        </button>
        <button class="btn btn-warning btn-xs" onclick={taintSelected} disabled={actionRunning}>
          <span class="icon-[tabler--flag] size-3.5"></span> Taint {selectedCount}
        </button>
      {/if}

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
        {#if totalCost !== null || costsLoading}
          <div class="flex items-center gap-1.5 text-xs">
            <span class="icon-[tabler--currency-dollar] size-3.5 text-base-content/40"></span>
            {#if costsLoading}
              <span class="loading loading-spinner loading-xs"></span>
            {:else}
              <span class="font-mono font-medium">${totalCost?.toFixed(2)}</span>
              <span class="text-base-content/30">/mo</span>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  {#if error}
    <div class="p-4">
      <div class="alert alert-soft alert-error text-xs">
        <span class="icon-[tabler--alert-circle] size-4"></span>
        {error}
      </div>
    </div>
  {/if}

  <!-- Output panel -->
  {#if showOutput}
    <div class="border-b border-base-content/10 bg-base-200 max-h-48 overflow-auto">
      <div class="flex items-center justify-between px-3 py-1 border-b border-base-content/5">
        <span class="text-xs text-base-content/50 flex items-center gap-1.5">
          {actionLabel}
          {#if actionRunning}
            <span class="loading loading-dots loading-xs"></span>
          {:else if actionResult === "success"}
            <span class="flex items-center gap-1 text-success font-medium"><span class="icon-[tabler--circle-check] size-3.5"></span>Completed</span>
          {:else if actionResult === "error"}
            <span class="flex items-center gap-1 text-error font-medium"><span class="icon-[tabler--circle-x] size-3.5"></span>Failed</span>
          {/if}
        </span>
        <div class="flex gap-1">
          <button class="btn btn-text btn-xs" onclick={() => { actionOutput = ""; showOutput = false; }} aria-label="Close">
            <span class="icon-[tabler--x] size-3"></span>
          </button>
        </div>
      </div>
      {#if actionOutput}
        <pre bind:this={outputEl} class="px-3 py-2 font-mono text-xs whitespace-pre-wrap text-base-content/80">{actionOutput}</pre>
      {/if}
    </div>
  {/if}

  <!-- Grid -->
  <div class="flex-1" bind:this={gridEl}></div>
</div>

<ConfirmModal
  bind:open={confirmOpen}
  title="Confirm Destroy"
  message={confirmMessage}
  confirmLabel="Destroy"
  variant="error"
  onconfirm={() => { if (confirmType === "destroy_selected") destroySelected(); }}
/>

<style>
  :global(.ag-watermark) {
    display: none !important;
  }
</style>
