<script>
  import { onMount, onDestroy, tick } from "svelte";
  import { createGrid, ModuleRegistry, AllCommunityModule, themeAlpine } from "ag-grid-community";
  import { AllEnterpriseModule } from "ag-grid-enterprise";
  import { streamOverviewFresh, getOverview, getCosts, streamTerraform, streamImport, streamCloudScan, getVars, streamChatSession, getFile, updateFile, getAwsStatus, streamSummarize } from "../lib/api.js";
  import { lastActionError } from "../lib/stores.js";
  import { marked } from "marked";
  import ConfirmModal from "./ConfirmModal.svelte";
  import DiffModal from "./DiffModal.svelte";
  import { modal } from "../lib/modal.js";

  ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

  let { onnavigate = null } = $props();

  let gridEl = $state();
  let gridApi = null;
  let loading = $state(true);
  let error = $state("");
  let stats = $state({ total: 0, actions: {}, categories: {} });
  let loadPhase = $state("");
  let loadLog = $state("");
  let planRefreshing = $state(false);
  let activeFilters = $state(new Set()); // empty = show all
  let allRows = $state([]);

  const ACTION_COLORS = { "no-op": "#10b981", create: "#6366f1", update: "#f59e0b", destroy: "#ef4444", replace: "#ec4899" };

  // Selection
  let selectedCount = $state(0);

  // Costs
  let costsLoading = $state(false);
  let totalCost = $state(null);

  // Actions
  let actionOutput = $state("");
  let actionLines = $state([]);
  let actionRunning = $state(false);
  let actionLabel = $state("");
  let outputEl = $state();
  let varFiles = $state([]);
  let selectedVarFile = $state("");
  let showOutput = $state(false);
  let actionResult = $state(null); // null | "success" | "error"
  let lastOutputLine = $state("");
  let outputExpanded = $state(false);
  let outputAutoScroll = $state(true);
  let outputSearch = $state("");
  let showOutputSearch = $state(false);

  function appendOutput(data) {
    actionOutput += data;
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const lines = data.split("\n").filter(l => l.length > 0);
    for (const line of lines) {
      actionLines.push({ text: line, time: ts, type: classifyLine(line) });
      lastOutputLine = line;
    }
    if (outputAutoScroll) {
      tick().then(() => { if (outputEl) outputEl.scrollTop = outputEl.scrollHeight; });
    }
  }

  function classifyLine(line) {
    if (/\bError[:!]|\berror[:!]|ERRO|failed|FAILED/.test(line)) return "error";
    if (/Warning[:!]|\bwarn/i.test(line)) return "warning";
    if (/Apply complete|Creation complete|Destroy complete|Success|✓/.test(line)) return "success";
    if (/^Plan:|^  [+~-]|# /.test(line)) return "plan";
    return "normal";
  }

  function copyOutput() {
    navigator.clipboard.writeText(actionOutput);
  }

  let filteredLines = $derived(
    outputSearch.trim()
      ? actionLines.filter(l => l.text.toLowerCase().includes(outputSearch.trim().toLowerCase()))
      : actionLines
  );

  // AWS check
  let checking = $state(false);
  let checkProgress = $state(0);
  let checkTotal = $state(0);

  // AWS status
  let awsOk = $state(null); // null=loading, true=ok, false=expired
  let awsRemaining = $state(""); // "2h 30m", "expired", or ""
  let awsExpiresAt = $state(null); // ISO string
  let awsStatusInterval = null;

  // Search
  let searchText = $state("");

  // AI Diagnosis (conversational)
  let diagMessages = $state([]);
  let diagStreaming = $state(false);
  let showDiagnosis = $state(false);
  let diagController = $state(null);
  let diagInput = $state("");
  let diagEl = $state(null);
  let applyStatus = $state({}); // { filename: "applying"|"success"|"error" }

  // Plan summary
  let summaryText = $state("");
  let summaryStreaming = $state(false);
  let showSummary = $state(false);
  let summaryController = $state(null);

  // Diff modal state
  let diffOpen = $state(false);
  let diffFilename = $state("");
  let diffOldContent = $state("");
  let diffNewContent = $state("");

  // Import
  let showImport = $state(false);

  // Confirm modal
  let confirmOpen = $state(false);
  let confirmMessage = $state("");
  let confirmType = $state("");
  let importAddress = $state("");
  let importId = $state("");

  const CATEGORY_COLORS = {
    compute: "#6366f1", storage: "#f59e0b", network: "#06b6d4",
    security: "#ef4444", dns: "#8b5cf6", monitoring: "#10b981",
    messaging: "#ec4899", devtools: "#f97316", data: "#06b6d4",
    resource: "#6b7280",
  };

  const CATEGORY_LABELS = {
    compute: "Compute", storage: "Storage", network: "Network",
    security: "Security", dns: "DNS", monitoring: "Monitoring",
    messaging: "Messaging", devtools: "DevTools", data: "Data Source",
    resource: "Other",
  };

  let isDark = $state(document.documentElement.getAttribute("data-theme") !== "light");

  // Watch for theme changes
  const observer = new MutationObserver(() => {
    isDark = document.documentElement.getAttribute("data-theme") !== "light";
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const darkTheme = themeAlpine.withParams({
    fontFamily: "'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace",
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

  const lightTheme = themeAlpine.withParams({
    fontFamily: "'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace",
    backgroundColor: "transparent",
    headerBackgroundColor: "rgba(0,0,0,0.03)",
    oddRowBackgroundColor: "rgba(0,0,0,0.02)",
    rowHoverColor: "rgba(0,0,0,0.04)",
    borderColor: "rgba(0,0,0,0.08)",
    headerForegroundColor: "rgba(0,0,0,0.6)",
    foregroundColor: "rgba(0,0,0,0.85)",
    fontSize: 10.5,
    headerFontWeight: 600,
    cellHorizontalPadding: 8,
    gridSize: 3,
    rowGroupIndentSize: 24,
  });

  let gridTheme = $derived(isDark ? darkTheme : lightTheme);

  // Update grid theme when it changes
  $effect(() => {
    if (gridApi) {
      gridApi.setGridOption("theme", gridTheme);
    }
  });

  function ActionRenderer(params) {
    const action = params.value || "unknown";
    if (params.node?.group) return null;
    const styles = {
      "no-op": { color: "#10b981", label: "No Change" },
      "create": { color: "#6366f1", label: "Create" },
      "update": { color: "#f59e0b", label: "Update" },
      "destroy": { color: "#ef4444", label: "Destroy" },
      "replace": { color: "#ec4899", label: "Replace" },
      "read": { color: "#64748b", label: "Read" },
      "unknown": { color: "#6b7280", label: "Unknown" },
    };
    const s = styles[action] || styles["unknown"];
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:500;`;
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${s.color};display:inline-block;"></span>${s.label}`;
    return el;
  }

  function TagsRenderer(params) {
    if (params.node?.group) return null;
    const tags = params.value;
    if (!tags || typeof tags !== "object" || Object.keys(tags).length === 0) return null;
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

  function CostRenderer(params) {
    const cost = params.value;
    if (cost === null || cost === undefined) return null;
    if (params.node?.group) {
      if (cost === 0) return null;
      const el = document.createElement("span");
      el.style.cssText = "font-size:10px;font-weight:600;font-family:monospace;opacity:0.6;";
      el.textContent = `$${cost.toFixed(2)}`;
      return el;
    }
    const el = document.createElement("span");
    if (cost === 0) {
      el.style.cssText = "font-size:10px;opacity:0.3;";
      el.textContent = "—";
    } else {
      el.style.cssText = "font-size:10px;font-weight:500;font-family:monospace;";
      el.textContent = `$${cost.toFixed(2)}`;
      if (cost > 100) el.style.color = "#ef4444";
      else if (cost > 10) el.style.color = "#f59e0b";
      else el.style.color = "#10b981";
    }
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

  function StatusRenderer(params) {
    const status = params.value;
    if (params.node?.group || !status) return null;
    const isExisting = status === "exists";
    const el = document.createElement("span");
    el.style.cssText = "display:inline-flex;align-items:center;gap:4px;font-size:10px;";
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:${isExisting ? '50%' : '2px'};background:${isExisting ? '#10b981' : '#6366f1'};display:inline-block;"></span>${isExisting ? "Exists" : "New"}`;
    return el;
  }

  function DriftRenderer(params) {
    if (params.node?.group) return null;
    const drift = params.value;
    if (!drift || drift === "unknown") return null;
    const colors = {
      in_sync: { bg: "#10b981", label: "In Sync" },
      missing: { bg: "#ef4444", label: "Missing in AWS" },
      exists_not_in_state: { bg: "#f59e0b", label: "Not in State" },
      planned: { bg: "#6b7280", label: "Planned" },
      error: { bg: "#ef4444", label: "Error" },
    };
    const info = colors[drift] || { bg: "#6b7280", label: drift };
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;`;
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${info.bg};display:inline-block;"></span>${info.label}`;
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

  function SourceRenderer(params) {
    if (params.node?.group) return null;
    const src = params.value;
    if (!src) return null;
    const styles = {
      both: { color: "#10b981", label: "Matched" },
      aws_only: { color: "#f59e0b", label: "AWS Only" },
      tf_only: { color: "#8b5cf6", label: "TF Only" },
      terraform: { color: "#6366f1", label: "Terraform" },
    };
    const s = styles[src] || { color: "#6b7280", label: src };
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:500;`;
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:2px;background:${s.color};display:inline-block;"></span>${s.label}`;
    return el;
  }

  const columnDefs = [
    { headerName: "Service", field: "service", rowGroup: true, hide: true },
    { headerName: "Type", field: "display_type", rowGroup: true, hide: true },
    {
      headerName: "Name", field: "resource_name", flex: 2, minWidth: 160,
      filter: "agTextColumnFilter", cellStyle: { fontSize: "10.5px" },
    },
    { headerName: "Source", field: "source", width: 90, cellRenderer: SourceRenderer, filter: true },
    { headerName: "Status", field: "status", width: 80, cellRenderer: StatusRenderer, filter: true },
    { headerName: "Action", field: "action", width: 100, cellRenderer: ActionRenderer, filter: true },
    { headerName: "Drift", field: "drift", width: 110, cellRenderer: DriftRenderer, filter: true },
    { headerName: "Def", field: "tf_file", width: 130, cellRenderer: DefRenderer },
    { headerName: "AWS", field: "console_url", width: 70, cellRenderer: ConsoleUrlRenderer },
    { headerName: "ARN", field: "arn", flex: 2, minWidth: 120, cellRenderer: ArnRenderer, filter: "agTextColumnFilter" },
    { headerName: "Cost/mo", field: "cost_monthly", width: 85, cellRenderer: CostRenderer, aggFunc: "sum", sort: "desc" },
    { headerName: "Tags", field: "tags", flex: 1, minWidth: 100, cellRenderer: TagsRenderer },
    { headerName: "Deps", field: "depends_on", width: 50, cellRenderer: DepsRenderer },
  ];

  const detailColumnDefs = [
    { headerName: "Attribute", field: "key", flex: 1, filter: true, cellStyle: { fontFamily: "monospace", fontSize: "10.5px", fontWeight: 600 } },
    { headerName: "Value", field: "value", flex: 3, filter: true, cellStyle: { fontFamily: "monospace", fontSize: "10.5px" }, autoHeight: true, wrapText: true },
  ];

  // --- AI Diagnosis ---

  function hasError(output) {
    if (!output) return false;
    // Check for actual terraform errors, not warnings containing "error"/"failed"
    if (/Apply complete!/.test(output)) return false;
    if (/Plan:.*to add/.test(output) && !/\bError:/.test(output)) return false;
    return /\bError:/.test(output) || /Apply.*failed/.test(output) || /exited with non-zero/.test(output);
  }

  function triggerDiagnosis(command, output) {
    const userMsg = `The following terraform ${command} just failed. Diagnose and help me fix it:\n\n\`\`\`\n${output}\n\`\`\``;
    diagMessages = [{ role: "user", content: userMsg }];
    showDiagnosis = true;
    $lastActionError = output;
    sendDiagMessage();
  }

  function sendDiagMessage(text) {
    if (text) {
      diagMessages = [...diagMessages, { role: "user", content: text }];
    }
    diagInput = "";
    diagStreaming = true;

    let aiText = "";
    diagMessages = [...diagMessages, { role: "assistant", content: "" }];

    const history = diagMessages.slice(0, -1).map(m => ({ role: m.role, content: m.content }));

    diagController = streamChatSession(
      history,
      (chunk) => {
        aiText += chunk;
        diagMessages = [...diagMessages.slice(0, -1), { role: "assistant", content: aiText }];
        tick().then(() => { if (diagEl) diagEl.scrollTop = diagEl.scrollHeight; });
      },
      () => {
        diagStreaming = false;
        diagController = null;
      }
    );
  }

  function handleDiagKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (diagInput.trim() && !diagStreaming) sendDiagMessage(diagInput.trim());
    }
  }

  function stopDiag() {
    if (diagController) {
      diagController.abort();
      diagController = null;
      diagStreaming = false;
    }
  }

  function dismissDiagnosis() {
    showDiagnosis = false;
    diagMessages = [];
    applyStatus = {};
    stopDiag();
  }

  function runSummarize() {
    summaryText = "";
    summaryStreaming = true;
    showSummary = true;
    summaryController = streamSummarize(
      allRows,
      (chunk) => { summaryText += chunk; },
      () => { summaryStreaming = false; summaryController = null; }
    );
  }

  function dismissSummary() {
    showSummary = false;
    summaryText = "";
    if (summaryController) {
      summaryController.abort();
      summaryController = null;
    }
    summaryStreaming = false;
  }

  const VALID_TF_COMMANDS = new Set(["init", "plan", "apply", "destroy", "taint", "fmt", "validate"]);

  function runDiagCommand(cmd) {
    // Normalize multi-line bash (join \ continuations)
    const normalized = cmd.replace(/\\\n\s*/g, " ").trim();
    const match = normalized.match(/^terraform\s+(\w+)(.*)/s);
    if (!match) {
      appendOutput(`Error: Cannot run "${cmd.split("\n")[0]}" — only terraform commands are supported.\n`);
      showOutput = true;
      return;
    }
    const tfCmd = match[1];
    if (!VALID_TF_COMMANDS.has(tfCmd)) {
      appendOutput(`Error: "terraform ${tfCmd}" is not a supported command. Supported: ${[...VALID_TF_COMMANDS].join(", ")}.\n`);
      showOutput = true;
      return;
    }
    const argsStr = match[2].trim();

    // Parse -target and other args
    const body = {};
    if (argsStr) {
      const args = [];
      // Match flags like -target='...' or -auto-approve or -var='...'
      const re = /-[\w-]+(?:=(?:'[^']*'|"[^"]*"|\S+))?/g;
      let m;
      while ((m = re.exec(argsStr)) !== null) {
        args.push(m[0].replace(/['"]/g, ""));
      }
      if (args.length > 0) body.args = args;
    }

    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = `terraform ${tfCmd}`;
    showOutput = true;

    streamTerraform(tfCmd, body,
      (data) => { appendOutput(data); },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
      }
    );
  }

  function parseDiagnosisSegments(text) {
    const segments = [];
    const regex = /(?:File:\s*(\S+)\s*\n)?```(\w*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
      }
      const rawName = match[1] || null;
      const filename = rawName ? rawName.replace(/[`*_~]/g, "") : null;
      segments.push({ type: "code", filename, language: match[2], content: match[3] });
      lastIndex = regex.lastIndex;
    }
    if (lastIndex < text.length) {
      segments.push({ type: "text", content: text.slice(lastIndex) });
    }
    return segments;
  }

  function renderMarkdown(text) {
    return marked.parse(text, { breaks: true });
  }

  async function openDiffForFile(filename, proposed) {
    try {
      const data = await getFile(filename);
      diffFilename = filename;
      diffOldContent = data.content;
      diffNewContent = proposed;
      diffOpen = true;
    } catch (e) {
      diffFilename = filename;
      diffOldContent = "";
      diffNewContent = proposed;
      diffOpen = true;
    }
  }

  async function applyDiff() {
    applyStatus = { ...applyStatus, [diffFilename]: "applying" };
    try {
      await updateFile(diffFilename, diffNewContent);
      applyStatus = { ...applyStatus, [diffFilename]: "success" };
      setTimeout(() => { applyStatus = { ...applyStatus, [diffFilename]: undefined }; }, 3000);
    } catch (e) {
      applyStatus = { ...applyStatus, [diffFilename]: "error" };
    }
  }

  // --- Actions ---

  function applySelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;

    // Build -target args — use r.id which has proper quoting for for_each keys
    const targets = selected.map((r) => `-target=${r.id}`);

    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = `Apply ${selected.length} resource${selected.length > 1 ? "s" : ""}`;
    showOutput = true;
    outputExpanded = true;
    const body = { args: targets };
    if (selectedVarFile) body.var_file = selectedVarFile;

    dismissDiagnosis();
    streamTerraform("apply", body,
      (data) => {
        appendOutput(data);
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis("apply", actionOutput);
        refreshPlan();
      }
    );
  }

  function destroySelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;

    const targets = selected.map((r) => `-target=${r.id}`);

    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = `Destroy ${selected.length} resource${selected.length > 1 ? "s" : ""}`;
    showOutput = true;
    outputExpanded = true;
    dismissDiagnosis();
    const body = { args: targets };
    if (selectedVarFile) body.var_file = selectedVarFile;

    streamTerraform("destroy", body,
      (data) => {
        appendOutput(data);
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis("destroy", actionOutput);
        refreshPlan();
      }
    );
  }

  function taintSelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;

    const addresses = selected.map((r) => r.id);

    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = `Taint ${selected.length} resource${selected.length > 1 ? "s" : ""}`;
    showOutput = true;
    outputExpanded = true;
    dismissDiagnosis();

    streamTerraform("taint", { addresses },
      (data) => {
        appendOutput(data);
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis("taint", actionOutput);
        refreshPlan();
      }
    );
  }

  function runAction(command, label) {
    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = label;
    showOutput = true;
    outputExpanded = true;
    dismissDiagnosis();
    const body = {};
    if (selectedVarFile) body.var_file = selectedVarFile;

    streamTerraform(command, body,
      (data) => {
        appendOutput(data);
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis(command, actionOutput);
        if (command === "plan" || command === "apply" || command === "destroy") refreshPlan();
      }
    );
  }

  function runImport() {
    if (!importAddress.trim() || !importId.trim()) return;
    actionOutput = "";
    actionLines = [];
    lastOutputLine = "";
    actionRunning = true;
    actionResult = null;
    actionLabel = "Import";
    showOutput = true;
    outputExpanded = true;

    streamImport(importAddress.trim(), importId.trim(),
      (data) => {
        appendOutput(data);
      },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        showImport = false;
        refreshGrid();
      }
    );
  }

  async function refreshGrid() {
    try {
      const data = await getOverview();
      allRows = data;
      activeFilters = new Set();
      computeStats(data);
      gridApi?.setGridOption("rowData", data);
    } catch (_) {}
  }

  function handleCheckAws() {
    checking = true;
    checkProgress = 0;
    checkTotal = 0;
    let resultRows = null;

    streamCloudScan(
      (raw) => {
        try {
          const msg = JSON.parse(raw);
          if (msg.type === "scan_progress") {
            checkTotal = msg.total;
            checkProgress = msg.done;
          } else if (msg.type === "result") {
            resultRows = msg.data;
          }
        } catch (_) {}
      },
      () => {
        checking = false;
        if (resultRows && resultRows.length > 0) {
          // Preserve cost data from existing rows
          const costMap = {};
          for (const r of allRows) {
            if (r.cost_monthly != null) costMap[r.id] = r.cost_monthly;
          }
          const merged = resultRows.map((r) => {
            const cost = costMap[r.id];
            return cost != null ? { ...r, cost_monthly: cost } : r;
          });
          allRows = merged;
          activeFilters = new Set();
          computeStats(merged);
          gridApi?.setGridOption("rowData", merged);
        }
      }
    );
  }

  function computeStats(data) {
    const s = {
      total: data.length,
      actions: {},
      categories: {},
    };
    for (const r of data) {
      const a = r.action || "unknown";
      s.actions[a] = (s.actions[a] || 0) + 1;
      const cat = r.category || "resource";
      s.categories[cat] = (s.categories[cat] || 0) + 1;
    }
    stats = s;
  }

  function toggleFilter(action) {
    const next = new Set(activeFilters);
    if (action === "all") {
      next.clear();
    } else if (next.has(action)) {
      next.delete(action);
    } else {
      next.add(action);
    }
    activeFilters = next;
    applyFilters();
  }

  function applyFilters() {
    if (!gridApi) return;
    let filtered = allRows;
    if (activeFilters.size > 0) {
      filtered = filtered.filter((r) => activeFilters.has(r.action));
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      filtered = filtered.filter((r) =>
        (r.resource_name || "").toLowerCase().includes(q) ||
        (r.arn || "").toLowerCase().includes(q) ||
        (r.resource_type || "").toLowerCase().includes(q) ||
        (r.display_type || "").toLowerCase().includes(q) ||
        (r.service || "").toLowerCase().includes(q)
      );
    }
    gridApi.setGridOption("rowData", filtered);
  }

  $effect(() => {
    searchText;
    applyFilters();
  });

  function initGrid(data) {
    allRows = data;
    requestAnimationFrame(() => {
      if (gridEl && !gridApi) {
        gridApi = createGrid(gridEl, {
          theme: gridTheme,
          columnDefs,
          rowData: data,
          loading: data.length === 0,
          defaultColDef: { sortable: true, resizable: true },
          animateRows: true,
          groupDefaultExpanded: 0,
          groupDisplayType: "multipleColumns",
          autoGroupColumnDef: { minWidth: 200, cellStyle: { fontSize: "10.5px" } },
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
          isRowMaster: (data) => data?.attributes && Object.keys(data.attributes).length > 0,
          rowSelection: { mode: "multiRow", checkboxes: true, headerCheckbox: true, groupSelects: "descendants" },
          onSelectionChanged: () => {
            selectedCount = gridApi?.getSelectedRows()?.length || 0;
          },
          rowHeight: 34,
          headerHeight: 32,
        });
      } else if (gridApi) {
        gridApi.setGridOption("rowData", data);
      }
    });
  }

  function refreshPlan() {
    planRefreshing = true;
    loadPhase = "Running terraform plan...";
    loadLog = "";
    gridApi?.setGridOption("loading", true);
    streamOverviewFresh(
      (raw) => {
        try {
          const msg = JSON.parse(raw);
          if (msg.type === "phase") {
            loadPhase = msg.message;
            loadLog = "";
          } else if (msg.type === "log") {
            loadLog = msg.message;
          } else if (msg.type === "result") {
            computeStats(msg.data);
            initGrid(msg.data);
            gridApi?.setGridOption("loading", false);
          }
        } catch (_) {}
      },
      () => {
        planRefreshing = false;
        loadPhase = "";
        loadLog = "";
        gridApi?.setGridOption("loading", false);
        fetchCosts();
      }
    );
  }

  function updateAwsRemaining() {
    if (!awsExpiresAt) { awsRemaining = ""; return; }
    const ms = new Date(awsExpiresAt) - Date.now();
    if (ms <= 0) { awsRemaining = "expired"; awsOk = false; return; }
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    awsRemaining = h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  onMount(async () => {
    // Fetch AWS credential status in background
    getAwsStatus().then((status) => {
      awsExpiresAt = status.expires_at;
      awsOk = status.expires_at ? !status.remaining?.startsWith("expired") : true;
      updateAwsRemaining();
      awsStatusInterval = setInterval(updateAwsRemaining, 60000);
    }).catch(() => { awsOk = null; });

    try {
      // Fast load: cached plan + vars in parallel
      const [data, vars] = await Promise.all([
        getOverview(),
        getVars().catch(() => []),
      ]);
      varFiles = vars;

      if (data.length > 0) {
        computeStats(data);
        initGrid(data);
        loading = false;
        // Background tasks
        await fetchCosts();
        handleCheckAws();
      } else {
        // No cached plan — run fresh
        loading = false;
        initGrid([]);
        refreshPlan();
      }
    } catch (e) {
      error = e.message;
      loading = false;
    }
  });

  async function fetchCosts() {
    costsLoading = true;
    try {
      const costData = await getCosts();
      if (costData.resources && costData.resources.length > 0) {
        // The cost endpoint returns resources with cost_monthly already merged
        // Build a cost lookup by resource id
        const costById = {};
        for (const r of costData.resources) {
          if (r.cost_monthly != null) {
            costById[r.id] = r.cost_monthly;
            // Also map by resource_type.resource_name for matching
            const key = `${r.resource_type}.${r.resource_name}`;
            costById[key] = r.cost_monthly;
          }
        }

        // Update existing rows with cost data
        const updated = allRows.map((row) => {
          const cost = costById[row.id]
            ?? costById[`${row.resource_type}.${row.resource_name}`]
            ?? null;
          if (cost != null) {
            return { ...row, cost_monthly: cost };
          }
          return row;
        });

        allRows = updated;
        totalCost = costData.total_monthly;
        activeFilters = new Set();
        gridApi?.setGridOption("rowData", updated);
      }
    } catch (e) {
      console.error("fetchCosts error:", e);
    }
    costsLoading = false;
  }

  onDestroy(() => {
    observer.disconnect();
    gridApi?.destroy();
    if (diagController) diagController.abort();
    if (summaryController) summaryController.abort();
    if (awsStatusInterval) clearInterval(awsStatusInterval);
  });
</script>

<div class="flex flex-col h-full">
  {#if loading}
    <div class="flex flex-col items-center justify-center py-12 gap-3">
      <span class="loading loading-spinner loading-md text-primary"></span>
      {#if loadPhase}
        <span class="text-xs text-base-content/50">{loadPhase}</span>
      {/if}
      {#if loadLog}
        <span class="text-[10px] font-mono text-base-content/30 max-w-md truncate text-center">{loadLog}</span>
      {/if}
      <div class="w-48 bg-base-300 rounded-full h-1 overflow-hidden">
        <div class="bg-primary h-1 rounded-full animate-pulse" style="width: 60%"></div>
      </div>
    </div>
  {:else if error}
    <div class="p-4">
      <div class="alert alert-soft alert-error text-xs">
        <span class="icon-[tabler--alert-circle] size-4"></span>
        {error}
      </div>
    </div>
  {:else}
    <!-- Action bar -->
    <div class="flex items-center gap-2 px-4 py-2 border-b border-base-content/10 bg-base-200">
      <!-- Terraform actions -->
        <button class="btn btn-soft btn-xs" onclick={() => runAction("init", "Init")} disabled={actionRunning}>
          <span class="icon-[tabler--download] size-3.5"></span> Init
        </button>
        <button class="btn btn-primary btn-xs" onclick={() => runAction("plan", "Plan")} disabled={actionRunning}>
          <span class="icon-[tabler--list-check] size-3.5"></span> Plan
        </button>
        <button class="btn btn-soft btn-success btn-xs" onclick={() => runAction("apply", "Apply")} disabled={actionRunning}>
          <span class="icon-[tabler--rocket] size-3.5"></span> Apply All
        </button>
        {#if selectedCount > 0}
          <button class="btn btn-success btn-xs" onclick={applySelected} disabled={actionRunning}>
            <span class="icon-[tabler--target-arrow] size-3.5"></span> Apply {selectedCount}
          </button>
          <button class="btn btn-error btn-xs" onclick={() => { confirmMessage = `Destroy ${selectedCount} selected resource${selectedCount > 1 ? 's' : ''}? This cannot be undone.`; confirmType = "destroy_selected"; confirmOpen = true; }} disabled={actionRunning}>
            <span class="icon-[tabler--trash] size-3.5"></span> Destroy {selectedCount}
          </button>
          <button class="btn btn-warning btn-xs" onclick={taintSelected} disabled={actionRunning}>
            <span class="icon-[tabler--flag] size-3.5"></span> Taint {selectedCount}
          </button>
        {/if}
        <button class="btn btn-soft btn-error btn-xs" onclick={() => { confirmMessage = "Destroy ALL resources in this project? This cannot be undone."; confirmType = "destroy_all"; confirmOpen = true; }} disabled={actionRunning}>
          <span class="icon-[tabler--trash] size-3.5"></span> Destroy All
        </button>

        <div class="w-px h-5 bg-base-content/10"></div>

        <!-- Import -->
        <button
          class="btn btn-soft btn-xs"
          onclick={() => (showImport = !showImport)}
          disabled={actionRunning}
        >
          <span class="icon-[tabler--package-import] size-3.5"></span> Import
        </button>

        <div class="w-px h-5 bg-base-content/10"></div>

        <!-- Summarize -->
        <button
          class="btn btn-soft btn-xs"
          onclick={runSummarize}
          disabled={summaryStreaming || allRows.length === 0}
        >
          <span class="icon-[tabler--sparkles] size-3.5"></span> Summarize
        </button>

      <!-- Var file selector -->
      {#if varFiles.length > 0}
        <div class="w-px h-5 bg-base-content/10"></div>
        <select class="select select-xs text-xs" bind:value={selectedVarFile}>
          <option value="">No var file</option>
          {#each varFiles as vf}
            <option value={vf}>{vf}</option>
          {/each}
        </select>
      {/if}

      <div class="ms-auto flex items-center gap-2">
        <!-- AWS status -->
        {#if awsOk !== null}
          <div class="flex items-center gap-1 text-xs text-base-content/40">
            <span class="icon-[tabler--cloud] size-3.5"></span>
            {#if awsOk}
              <span class="w-1.5 h-1.5 rounded-full bg-success"></span>
              {#if awsRemaining}
                <span>{awsRemaining}</span>
              {/if}
            {:else}
              <span class="w-1.5 h-1.5 rounded-full bg-error"></span>
              <span class="text-error">expired</span>
            {/if}
          </div>
        {/if}

        {#if actionRunning}
          <span class="loading loading-spinner loading-xs text-primary"></span>
        {/if}

        {#if actionLines.length > 0 || diagMessages.length > 0}
          <button
            class="btn btn-text btn-xs gap-1"
            onclick={() => { showOutput = actionLines.length > 0; if (diagMessages.length > 0) showDiagnosis = true; }}
            aria-label="Show terminal"
          >
            <span class="icon-[tabler--terminal] size-3.5"></span>
            {#if actionResult === "error"}
              <span class="w-1.5 h-1.5 rounded-full bg-error"></span>
            {:else if actionResult === "success"}
              <span class="w-1.5 h-1.5 rounded-full bg-success"></span>
            {:else if actionRunning}
              <span class="w-1.5 h-1.5 rounded-full bg-info animate-pulse"></span>
            {/if}
          </button>
        {/if}
      </div>
    </div>

    <!-- Action status bar -->
    {#if actionRunning || planRefreshing}
      <div class="px-4 py-1 border-b border-base-content/10 bg-base-200/50 flex items-center gap-2">
        <span class="loading loading-spinner loading-xs text-primary"></span>
        <span class="text-xs text-base-content/50">{planRefreshing ? (loadPhase || "Updating overview...") : actionLabel}</span>
        {#if planRefreshing && loadLog}
          <span class="text-[10px] font-mono text-base-content/30 truncate flex-1">{loadLog}</span>
        {:else if actionRunning && lastOutputLine}
          <span class="text-[10px] font-mono text-base-content/30 truncate flex-1">{lastOutputLine}</span>
        {/if}
      </div>
    {/if}

    <!-- AWS check progress -->
    {#if checking}
      <div class="px-4 py-1 border-b border-base-content/10 bg-base-200/50">
        <div class="flex items-center gap-2 text-xs text-base-content/50 mb-1">
          <span class="icon-[tabler--cloud-search] size-3"></span>
          Checking resources against AWS... {checkProgress}/{checkTotal}
        </div>
        <div class="w-full bg-base-300 rounded-full h-1">
          <div
            class="bg-info h-1 rounded-full transition-all"
            style="width: {checkTotal > 0 ? (checkProgress / checkTotal) * 100 : 0}%"
          ></div>
        </div>
      </div>
    {/if}

    <!-- Import bar -->
    {#if showImport}
      <div class="flex items-center gap-2 px-4 py-2 border-b border-base-content/10 bg-base-200/50">
        <span class="text-xs text-base-content/50">Import:</span>
        <input
          type="text"
          class="input input-xs flex-1 font-mono"
          placeholder="aws_instance.example"
          bind:value={importAddress}
        />
        <input
          type="text"
          class="input input-xs flex-1 font-mono"
          placeholder="i-1234567890abcdef0"
          bind:value={importId}
        />
        <button
          class="btn btn-primary btn-xs"
          onclick={runImport}
          disabled={actionRunning || !importAddress.trim() || !importId.trim()}
        >
          Import
        </button>
        <button class="btn btn-text btn-xs" onclick={() => (showImport = false)} aria-label="Cancel import">
          <span class="icon-[tabler--x] size-3"></span>
        </button>
      </div>
    {/if}

    <!-- Combined Output + Diagnosis modal -->
    {#if showOutput || (showDiagnosis && diagMessages.length > 0)}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onclick={() => { if (!actionRunning && !diagStreaming) { showOutput = false; } }}>
        <div class="bg-base-100 w-[94vw] max-w-7xl h-[85vh] rounded-xl shadow-2xl flex flex-col overflow-hidden" onclick={(e) => e.stopPropagation()} use:modal={{ onclose: () => { if (!actionRunning && !diagStreaming) showOutput = false; } }}>
        <!-- Split content: console left, AI right -->
        <div class="flex flex-1 overflow-hidden">
          <!-- Console output pane -->
          {#if showOutput}
            <div class="flex flex-col flex-1 min-w-0 {showDiagnosis && diagMessages.length > 0 ? 'border-r border-base-content/10' : ''}">
              <!-- Console toolbar -->
              <div class="flex items-center justify-between px-3 py-1.5 border-b border-base-content/10 bg-base-200 shrink-0">
                <span class="text-xs text-base-content/60 flex items-center gap-1.5">
                  <span class="icon-[tabler--terminal] size-3.5"></span>
                  {actionLabel}
                  {#if actionRunning}
                    <span class="loading loading-dots loading-xs"></span>
                  {:else if actionResult === "success"}
                    <span class="flex items-center gap-1 text-success font-medium"><span class="icon-[tabler--circle-check] size-3.5"></span>Done</span>
                  {:else if actionResult === "error"}
                    <span class="flex items-center gap-1 text-error font-medium"><span class="icon-[tabler--circle-x] size-3.5"></span>Failed</span>
                  {/if}
                  {#if actionLines.length > 0}
                    <span class="text-[10px] text-base-content/30">{actionLines.length} lines</span>
                  {/if}
                </span>
                <div class="flex items-center gap-0.5">
                  <button
                    class="btn btn-text btn-xs btn-square"
                    onclick={() => { showOutputSearch = !showOutputSearch; if (!showOutputSearch) outputSearch = ""; }}
                    title="Search"
                    class:text-primary={showOutputSearch}
                  >
                    <span class="icon-[tabler--search] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={copyOutput} title="Copy output">
                    <span class="icon-[tabler--copy] size-3"></span>
                  </button>
                  <button
                    class="btn btn-text btn-xs btn-square"
                    onclick={() => (outputAutoScroll = !outputAutoScroll)}
                    title={outputAutoScroll ? "Auto-scroll on" : "Auto-scroll off"}
                    class:text-primary={outputAutoScroll}
                  >
                    <span class="icon-[tabler--arrow-bar-to-down] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={() => { showOutput = false; showOutputSearch = false; }} aria-label="Close">
                    <span class="icon-[tabler--x] size-3"></span>
                  </button>
                </div>
              </div>

              <!-- Search bar -->
              {#if showOutputSearch}
                <div class="flex items-center gap-2 px-3 py-1 border-b border-base-content/5 shrink-0">
                  <span class="icon-[tabler--search] size-3 text-base-content/30"></span>
                  <input
                    type="text"
                    class="input input-xs flex-1 text-xs bg-transparent border-none focus:outline-none"
                    placeholder="Filter output..."
                    bind:value={outputSearch}
                  />
                  {#if outputSearch}
                    <span class="text-[10px] text-base-content/30">{filteredLines.length} match{filteredLines.length !== 1 ? 'es' : ''}</span>
                  {/if}
                </div>
              {/if}

              <!-- Log lines -->
              <div bind:this={outputEl} class="overflow-auto flex-1 bg-base-200">
                {#if filteredLines.length > 0}
                  <table class="w-full">
                    <tbody>
                      {#each filteredLines as line}
                        <tr class="hover:bg-base-content/5 group">
                          <td class="px-1.5 py-0 text-[9px] font-mono text-base-content/20 select-none whitespace-nowrap align-top w-14 group-hover:text-base-content/40">{line.time}</td>
                          <td
                            class="px-1.5 py-0 font-mono text-[11px] whitespace-pre-wrap break-all"
                            class:text-error={line.type === "error"}
                            class:text-warning={line.type === "warning"}
                            class:text-success={line.type === "success"}
                            class:text-info={line.type === "plan"}
                            style={line.type === "normal" ? "color: color-mix(in oklch, var(--color-base-content) 80%, transparent);" : ""}
                          >{line.text}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
              </div>
            </div>
          {/if}

          <!-- AI Diagnosis pane (conversational) -->
          {#if showDiagnosis && diagMessages.length > 0}
            <div class="flex flex-col flex-1 min-w-0">
              <!-- AI toolbar -->
              <div class="flex items-center justify-between px-3 py-1.5 border-b border-primary/10 bg-primary/5 shrink-0">
                <span class="text-xs font-medium text-primary flex items-center gap-1.5">
                  <span class="icon-[tabler--robot] size-3.5"></span>
                  AI Diagnosis
                  {#if diagStreaming}
                    <span class="loading loading-dots loading-xs ms-1"></span>
                  {/if}
                </span>
                <div class="flex items-center gap-0.5">
                  <button class="btn btn-text btn-xs btn-square" onclick={() => navigator.clipboard.writeText(diagMessages.filter(m => m.role === 'assistant').map(m => m.content).join('\n\n'))} title="Copy AI responses">
                    <span class="icon-[tabler--copy] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={dismissDiagnosis} aria-label="Close">
                    <span class="icon-[tabler--x] size-3"></span>
                  </button>
                </div>
              </div>

              <!-- Messages -->
              <div bind:this={diagEl} class="overflow-auto flex-1 p-3 space-y-3">
                {#each diagMessages as msg, i}
                  {#if msg.role === "user"}
                    <div class="flex justify-end">
                      <div class="bg-primary/10 rounded-lg px-3 py-1.5 max-w-[90%]">
                        <pre class="whitespace-pre-wrap font-sans text-xs text-base-content/70">{msg.content.length > 300 ? msg.content.slice(0, 200) + "..." : msg.content}</pre>
                      </div>
                    </div>
                  {:else}
                    <div class="max-w-full">
                      {#each parseDiagnosisSegments(msg.content) as seg}
                        {#if seg.type === "text"}
                          <div class="diagnosis-md text-xs text-base-content/80">
                            {@html renderMarkdown(seg.content)}
                          </div>
                        {:else if seg.type === "code"}
                          <div class="rounded-lg overflow-hidden border border-base-content/10 my-2">
                            <div class="flex items-center justify-between px-2 py-1 bg-base-200">
                              <span class="text-[10px] font-mono text-base-content/50">
                                {seg.filename || seg.language || "code"}
                              </span>
                              <div class="flex gap-1">
                                {#if seg.language === "bash" || seg.language === "sh"}
                                  <button
                                    class="btn btn-xs btn-warning gap-1"
                                    onclick={() => runDiagCommand(seg.content.trim())}
                                    disabled={actionRunning}
                                  >
                                    <span class="icon-[tabler--player-play] size-3"></span> Run
                                  </button>
                                {/if}
                                {#if seg.filename}
                                  <button
                                    class="btn btn-xs btn-primary gap-1"
                                    onclick={() => openDiffForFile(seg.filename, seg.content)}
                                    disabled={applyStatus[seg.filename] === "applying"}
                                  >
                                    {#if applyStatus[seg.filename] === "applying"}
                                      <span class="loading loading-spinner loading-xs"></span>
                                    {:else if applyStatus[seg.filename] === "success"}
                                      <span class="icon-[tabler--check] size-3"></span> Applied
                                    {:else if applyStatus[seg.filename] === "error"}
                                      <span class="icon-[tabler--x] size-3"></span> Failed
                                    {:else}
                                      <span class="icon-[tabler--diff] size-3"></span> Review & Apply
                                    {/if}
                                  </button>
                                {/if}
                              </div>
                            </div>
                            <pre class="px-2 py-1.5 text-[10px] font-mono overflow-x-auto bg-base-300/50 max-h-48 overflow-y-auto">{seg.content}</pre>
                          </div>
                        {/if}
                      {/each}
                      {#if diagStreaming && i === diagMessages.length - 1}
                        <span class="loading loading-dots loading-xs text-primary"></span>
                      {/if}
                    </div>
                  {/if}
                {/each}
              </div>

              <!-- Input -->
              <div class="border-t border-base-content/10 p-2 bg-base-200/60 shrink-0">
                <div class="flex gap-1.5">
                  <textarea
                    class="textarea textarea-sm flex-1 text-xs min-h-8 max-h-20 leading-tight"
                    rows="1"
                    placeholder="Ask a follow-up or describe what to try..."
                    bind:value={diagInput}
                    onkeydown={handleDiagKeydown}
                    disabled={diagStreaming}
                  ></textarea>
                  {#if diagStreaming}
                    <button class="btn btn-soft btn-sm btn-square" onclick={stopDiag} aria-label="Stop">
                      <span class="icon-[tabler--player-stop] size-3.5"></span>
                    </button>
                  {:else}
                    <button
                      class="btn btn-primary btn-sm btn-square"
                      onclick={() => { if (diagInput.trim()) sendDiagMessage(diagInput.trim()); }}
                      disabled={!diagInput.trim()}
                      aria-label="Send"
                    >
                      <span class="icon-[tabler--send] size-3.5"></span>
                    </button>
                  {/if}
                </div>
              </div>
            </div>
          {/if}
        </div>
      </div>
      </div>
    {/if}

    <!-- Plan Summary modal -->
    {#if showSummary}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onclick={() => { if (!summaryStreaming) dismissSummary(); }}>
        <div class="bg-base-100 w-[70vw] max-w-3xl h-[70vh] rounded-xl shadow-2xl flex flex-col overflow-hidden" onclick={(e) => e.stopPropagation()} use:modal={{ onclose: () => { if (!summaryStreaming) dismissSummary(); } }}>
          <!-- Header -->
          <div class="flex items-center justify-between px-4 py-2 border-b border-primary/10 bg-primary/5 shrink-0">
            <span class="text-xs font-medium text-primary flex items-center gap-1.5">
              <span class="icon-[tabler--sparkles] size-3.5"></span>
              Plan Summary
              {#if summaryStreaming}
                <span class="loading loading-dots loading-xs ms-1"></span>
              {/if}
            </span>
            <div class="flex items-center gap-0.5">
              <button class="btn btn-text btn-xs btn-square" onclick={() => navigator.clipboard.writeText(summaryText)} title="Copy">
                <span class="icon-[tabler--copy] size-3"></span>
              </button>
              <button class="btn btn-text btn-xs btn-square" onclick={dismissSummary} aria-label="Close">
                <span class="icon-[tabler--x] size-3"></span>
              </button>
            </div>
          </div>
          <!-- Content -->
          <div class="overflow-auto flex-1 p-4">
            <div class="diagnosis-md text-xs text-base-content/80">
              {@html renderMarkdown(summaryText)}
            </div>
            {#if summaryStreaming}
              <span class="loading loading-dots loading-xs text-primary"></span>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    <!-- Stats / filter bar -->
    <div class="flex items-center gap-2 px-4 py-1.5 border-b border-base-content/10 flex-wrap">
      <button
        class="btn btn-xs {activeFilters.size === 0 ? 'btn-primary' : 'btn-soft'}"
        onclick={() => toggleFilter("all")}
      >
        All {stats.total}
      </button>
      {#each Object.entries(stats.actions || {}) as [action, count]}
        <button
          class="btn btn-xs {activeFilters.has(action) ? 'btn-primary' : 'btn-soft'}"
          style={activeFilters.has(action) ? `background:${ACTION_COLORS[action] || '#6b7280'};border-color:${ACTION_COLORS[action] || '#6b7280'};` : ''}
          onclick={() => toggleFilter(action)}
        >
          <span class="w-1.5 h-1.5 rounded-full" style="background: {ACTION_COLORS[action] || '#6b7280'}"></span>
          <span class="capitalize">{action === "no-op" ? "no change" : action}</span>
          {count}
        </button>
      {/each}
      <div class="w-px h-3 bg-base-content/10"></div>
      {#each Object.entries(stats.categories || {}).sort((a, b) => b[1] - a[1]) as [cat, count]}
        <div class="flex items-center gap-1 text-xs text-base-content/40">
          <span class="w-1.5 h-1.5 rounded-sm" style="background: {CATEGORY_COLORS[cat] || '#6b7280'}"></span>
          <span class="capitalize">{CATEGORY_LABELS[cat] || cat}</span>
          <span class="text-base-content/25">{count}</span>
        </div>
      {/each}
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
    </div>

    <!-- AG Grid -->
    <div class="flex-1" bind:this={gridEl}></div>
  {/if}
</div>

<ConfirmModal
  bind:open={confirmOpen}
  title="Confirm Destroy"
  message={confirmMessage}
  confirmLabel="Destroy"
  variant="error"
  onconfirm={() => { if (confirmType === "destroy_selected") destroySelected(); else if (confirmType === "destroy_all") runAction("destroy", "Destroy"); }}
/>

<DiffModal
  bind:open={diffOpen}
  filename={diffFilename}
  oldContent={diffOldContent}
  newContent={diffNewContent}
  onapply={applyDiff}
/>

<style>
  :global(.ag-watermark) {
    display: none !important;
  }
  :global(.diagnosis-md h1),
  :global(.diagnosis-md h2),
  :global(.diagnosis-md h3) {
    font-size: 12px;
    font-weight: 600;
    margin: 8px 0 4px;
  }
  :global(.diagnosis-md p) {
    margin: 4px 0;
    line-height: 1.5;
  }
  :global(.diagnosis-md ul),
  :global(.diagnosis-md ol) {
    padding-left: 16px;
    margin: 4px 0;
  }
  :global(.diagnosis-md li) {
    margin: 2px 0;
    line-height: 1.5;
  }
  :global(.diagnosis-md code) {
    font-size: 10px;
    padding: 1px 4px;
    border-radius: 3px;
    background: color-mix(in oklch, var(--color-base-content) 8%, transparent);
    font-family: ui-monospace, monospace;
  }
  :global(.diagnosis-md strong) {
    font-weight: 600;
  }
</style>
