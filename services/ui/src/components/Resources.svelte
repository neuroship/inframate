<script>
  import { onMount, onDestroy, tick } from "svelte";
  import { createGrid, ModuleRegistry, AllCommunityModule, themeAlpine } from "ag-grid-community";
  import { AllEnterpriseModule } from "ag-grid-enterprise";
  import {
    streamOverviewFresh, getOverview, getCosts, streamTerraform, streamImport,
    streamCloudScan, streamChatSession, getFile, updateFile,
    streamAwsDelete, checkAwsDeletePreconditions,
  } from "../lib/api.js";
  import { lastActionError } from "../lib/stores.js";
  import { getCachedResources, setCachedResources, setCachedCosts, getCachedCosts } from "../lib/cache.js";
  import { marked } from "marked";
  import ConfirmModal from "./ConfirmModal.svelte";
  import DiffModal from "./DiffModal.svelte";

  ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

  let { onnavigate = null } = $props();

  // --- State ---
  let gridEl = $state();
  let gridApi = null;
  let loading = $state(true);
  let error = $state("");
  let allRows = $state([]);
  let stats = $state({ total: 0, statuses: {} });

  // Status filter
  let activeStatusFilter = $state("all");
  const STATUS_FILTERS = [
    { id: "all", label: "All", color: null, hint: "Show all resources from every source" },
    { id: "managed", label: "Managed", color: "#10b981", hint: "In code, state, and cloud — fully tracked by Terraform" },
    { id: "pending", label: "Pending", color: "#6366f1", hint: "Declared in code but not yet applied" },
    { id: "drift", label: "Drift", color: "#f59e0b", hint: "Expected in cloud but missing or changed outside Terraform" },
    { id: "unmanaged", label: "Unmanaged", color: "#f97316", hint: "Exists in cloud but not managed by Terraform" },
    { id: "orphaned", label: "Orphaned", color: "#ef4444", hint: "In Terraform state but code definition was removed" },
  ];

  // Plan refresh
  let loadPhase = $state("");
  let loadLog = $state("");
  let planRefreshing = $state(false);

  // Cloud scan
  let cloudScanning = $state(false);
  let cloudScanDone = $state(0);
  let cloudScanTotal = $state(0);
  let cloudScanLabel = $state("");
  let cloudScanned = $state(false);

  // Selection
  let selectedCount = $state(0);

  // Costs
  let costsLoading = $state(false);
  let totalCost = $state(null);
  let filteredCost = $state(0);

  // Terraform actions
  let actionOutput = $state("");
  let actionLines = $state([]);
  let actionRunning = $state(false);
  let actionLabel = $state("");
  let outputEl = $state();
  let showOutput = $state(false);
  let actionResult = $state(null);
  let lastOutputLine = $state("");
  let outputAutoScroll = $state(true);
  let outputSearch = $state("");
  let showOutputSearch = $state(false);

  // Import
  let showImport = $state(false);
  let importAddress = $state("");
  let importId = $state("");

  // Confirm modal
  let confirmOpen = $state(false);
  let confirmMessage = $state("");
  let confirmType = $state("");
  let preconditionWarnings = $state([]);

  // AI Diagnosis
  let diagMessages = $state([]);
  let diagStreaming = $state(false);
  let showDiagnosis = $state(false);
  let diagController = $state(null);
  let diagInput = $state("");
  let diagEl = $state(null);
  let applyStatus = $state({});

  // Diff modal
  let diffOpen = $state(false);
  let diffFilename = $state("");
  let diffOldContent = $state("");
  let diffNewContent = $state("");

  // Action filter
  let activeActionFilter = $state("all");
  const ACTION_FILTERS = [
    { id: "all", label: "All", color: null },
    { id: "create", label: "Create", color: "#6366f1" },
    { id: "update", label: "Update", color: "#f59e0b" },
    { id: "destroy", label: "Destroy", color: "#ef4444" },
    { id: "replace", label: "Replace", color: "#ec4899" },
  ];

  // Resource detail modal
  let detailOpen = $state(false);
  let detailResource = $state(null);

  // Search
  let searchText = $state("");

  // --- Theme ---
  let isDark = $state(document.documentElement.getAttribute("data-theme") !== "light");
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

  // --- Cell Renderers ---

  function PresenceRenderer(params) {
    if (params.node?.group) return null;
    const d = params.data;
    if (!d) return null;
    const el = document.createElement("div");
    el.style.cssText = "display:flex;gap:5px;align-items:center;height:100%;";
    const dots = [
      { key: "in_state", color: "#3b82f6", label: "State" },
      { key: "in_code", color: "#8b5cf6", label: "Code" },
      { key: "in_cloud", color: "#06b6d4", label: "Cloud" },
    ];
    for (const dot of dots) {
      const span = document.createElement("span");
      const val = d[dot.key];
      if (val === true) {
        span.style.cssText = `width:7px;height:7px;border-radius:50%;background:${dot.color};display:inline-block;`;
      } else if (val === false) {
        span.style.cssText = `width:7px;height:7px;border-radius:50%;border:1.5px solid ${dot.color};opacity:0.25;display:inline-block;`;
      } else {
        span.style.cssText = `width:7px;height:7px;border-radius:50%;border:1.5px dashed rgba(107,114,128,0.3);display:inline-block;`;
      }
      span.title = `${dot.label}: ${val === true ? "Yes" : val === false ? "No" : "Not scanned"}`;
      el.appendChild(span);
    }
    return el;
  }

  function StatusRenderer(params) {
    if (params.node?.group) return null;
    const status = params.value;
    if (!status) return null;
    const styles = {
      managed: { color: "#10b981", label: "Managed" },
      pending: { color: "#6366f1", label: "Pending" },
      drift: { color: "#f59e0b", label: "Drift" },
      unmanaged: { color: "#f97316", label: "Unmanaged" },
      orphaned: { color: "#ef4444", label: "Orphaned" },
    };
    const s = styles[status] || { color: "#6b7280", label: status };
    const el = document.createElement("span");
    el.style.cssText = `display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:500;height:100%;`;
    el.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${s.color};display:inline-block;"></span>${s.label}`;
    return el;
  }

  function ActionRenderer(params) {
    const action = params.value;
    if (params.node?.group || !action) return null;
    const styles = {
      "no-op": { color: "#10b981", label: "No Change" },
      create: { color: "#6366f1", label: "Create" },
      update: { color: "#f59e0b", label: "Update" },
      destroy: { color: "#ef4444", label: "Destroy" },
      replace: { color: "#ec4899", label: "Replace" },
      read: { color: "#64748b", label: "Read" },
    };
    const s = styles[action] || { color: "#6b7280", label: action };
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
    el.textContent = arn.length > 50 ? "\u2026" + arn.slice(-45) : arn;
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

  function DefRenderer(params) {
    if (params.node?.group) return null;
    const file = params.data?.tf_file;
    const line = params.data?.tf_line;
    if (!file) return null;
    const el = document.createElement("button");
    el.style.cssText = "font-size:10px;color:#8b5cf6;background:none;border:none;cursor:pointer;display:inline-flex;align-items:center;gap:3px;padding:0;";
    el.innerHTML = `<span style="font-size:12px;">\u2316</span>${file}:${line}`;
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
    el.innerHTML = `<span style="font-size:12px;">\u2197</span>Console`;
    return el;
  }

  // --- Column Definitions ---

  const columnDefs = [
    { headerName: "Service", field: "service", rowGroup: true, hide: true },
    { headerName: "Type", field: "display_type", rowGroup: true, hide: true },
    {
      headerName: "Name", field: "resource_name", flex: 2, minWidth: 160,
      filter: "agTextColumnFilter", cellStyle: { fontSize: "10.5px" },
    },
    { headerName: "Presence", field: "in_code", width: 80, cellRenderer: PresenceRenderer },
    { headerName: "Status", field: "status", width: 100, cellRenderer: StatusRenderer, filter: true },
    { headerName: "Action", field: "action", width: 100, cellRenderer: ActionRenderer, filter: true },
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

  // --- Output helpers ---

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
    if (/Apply complete|Creation complete|Destroy complete|Success|\u2713/.test(line)) return "success";
    if (/^Plan:|^  [+~-]|# /.test(line)) return "plan";
    return "normal";
  }

  function copyOutput() { navigator.clipboard.writeText(actionOutput); }

  let filteredLines = $derived(
    outputSearch.trim()
      ? actionLines.filter(l => l.text.toLowerCase().includes(outputSearch.trim().toLowerCase()))
      : actionLines
  );

  function hasError(output) {
    if (!output) return false;
    if (/Apply complete!/.test(output)) return false;
    if (/Plan:.*to add/.test(output) && !/\bError:/.test(output)) return false;
    return /\bError:/.test(output) || /Apply.*failed/.test(output) || /exited with non-zero/.test(output);
  }

  // --- AI Diagnosis ---

  function triggerDiagnosis(command, output) {
    const userMsg = `The following terraform ${command} just failed. Diagnose and help me fix it:\n\n\`\`\`\n${output}\n\`\`\``;
    diagMessages = [{ role: "user", content: userMsg }];
    showDiagnosis = true;
    $lastActionError = output;
    sendDiagMessage();
  }

  function sendDiagMessage(text) {
    if (text) diagMessages = [...diagMessages, { role: "user", content: text }];
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
      () => { diagStreaming = false; diagController = null; }
    );
  }

  function handleDiagKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (diagInput.trim() && !diagStreaming) sendDiagMessage(diagInput.trim());
    }
  }
  function stopDiag() { if (diagController) { diagController.abort(); diagController = null; diagStreaming = false; } }
  function dismissDiagnosis() { showDiagnosis = false; diagMessages = []; applyStatus = {}; stopDiag(); }

  const VALID_TF_COMMANDS = new Set(["init", "plan", "apply", "destroy", "taint", "fmt", "validate"]);

  function runDiagCommand(cmd) {
    const normalized = cmd.replace(/\\\n\s*/g, " ").trim();
    const match = normalized.match(/^terraform\s+(\w+)(.*)/s);
    if (!match) { appendOutput(`Error: Cannot run "${cmd.split("\n")[0]}" \u2014 only terraform commands are supported.\n`); showOutput = true; return; }
    const tfCmd = match[1];
    if (!VALID_TF_COMMANDS.has(tfCmd)) { appendOutput(`Error: "terraform ${tfCmd}" is not supported. Supported: ${[...VALID_TF_COMMANDS].join(", ")}.\n`); showOutput = true; return; }
    const argsStr = match[2].trim();
    const body = {};
    if (argsStr) {
      const args = [];
      const re = /-[\w-]+(?:=(?:'[^']*'|"[^"]*"|\S+))?/g;
      let m;
      while ((m = re.exec(argsStr)) !== null) args.push(m[0].replace(/['"]/g, ""));
      if (args.length > 0) body.args = args;
    }
    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = `terraform ${tfCmd}`; showOutput = true;
    streamTerraform(tfCmd, body, (data) => { appendOutput(data); }, () => { actionRunning = false; actionResult = hasError(actionOutput) ? "error" : "success"; });
  }

  function parseDiagnosisSegments(text) {
    const segments = [];
    const regex = /(?:File:\s*(\S+)\s*\n)?```(\w*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
      const rawName = match[1] || null;
      const filename = rawName ? rawName.replace(/[`*_~]/g, "") : null;
      segments.push({ type: "code", filename, language: match[2], content: match[3] });
      lastIndex = regex.lastIndex;
    }
    if (lastIndex < text.length) segments.push({ type: "text", content: text.slice(lastIndex) });
    return segments;
  }
  function renderMarkdown(text) { return marked.parse(text, { breaks: true }); }

  async function openDiffForFile(filename, proposed) {
    try { const data = await getFile(filename); diffFilename = filename; diffOldContent = data.content; diffNewContent = proposed; diffOpen = true; }
    catch (e) { diffFilename = filename; diffOldContent = ""; diffNewContent = proposed; diffOpen = true; }
  }
  async function applyDiff() {
    applyStatus = { ...applyStatus, [diffFilename]: "applying" };
    try { await updateFile(diffFilename, diffNewContent); applyStatus = { ...applyStatus, [diffFilename]: "success" }; setTimeout(() => { applyStatus = { ...applyStatus, [diffFilename]: undefined }; }, 3000); }
    catch (e) { applyStatus = { ...applyStatus, [diffFilename]: "error" }; }
  }

  // --- Terraform Actions ---

  function runAction(command, label) {
    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = label; showOutput = true; dismissDiagnosis();
    const body = {};

    streamTerraform(command, body,
      (data) => { appendOutput(data); },
      () => {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis(command, actionOutput);
        if (command === "plan" || command === "apply" || command === "destroy") refreshPlan();
      }
    );
  }

  function applySelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;
    const targets = selected.filter(r => r.in_code || r.in_state).map(r => `-target=${r.id}`);
    if (targets.length === 0) return;
    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = `Apply ${targets.length} resource${targets.length > 1 ? "s" : ""}`;
    showOutput = true; dismissDiagnosis();
    const body = { args: targets };

    streamTerraform("apply", body,
      (data) => { appendOutput(data); },
      () => { actionRunning = false; actionResult = hasError(actionOutput) ? "error" : "success"; if (actionResult === "error") triggerDiagnosis("apply", actionOutput); refreshPlan(); }
    );
  }

  function destroySelected() {
    const selected = gridApi?.getSelectedRows() || [];
    if (selected.length === 0) return;

    const tfTargets = selected.filter(r => r.in_code || r.in_state).map(r => `-target=${r.id}`);
    const awsOnly = selected.filter(r => r.status === "unmanaged");

    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = `Destroy ${selected.length} resource${selected.length > 1 ? "s" : ""}`;
    showOutput = true; dismissDiagnosis();

    let pending = 0;
    function onPartDone() {
      pending--;
      if (pending === 0) {
        actionRunning = false;
        actionResult = hasError(actionOutput) ? "error" : "success";
        if (actionResult === "error") triggerDiagnosis("destroy", actionOutput);
        refreshPlan();
      }
    }

    if (tfTargets.length > 0) {
      pending++;
      const body = { args: tfTargets };
  
      streamTerraform("destroy", body, (data) => { appendOutput(data); }, onPartDone);
    }

    if (awsOnly.length > 0) {
      pending++;
      streamAwsDelete(awsOnly, (data) => { appendOutput(data + "\n"); }, onPartDone);
    }
  }

  function taintSelected() {
    const selected = gridApi?.getSelectedRows() || [];
    const addresses = selected.filter(r => r.in_code || r.in_state).map(r => r.id);
    if (addresses.length === 0) return;
    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = `Taint ${addresses.length} resource${addresses.length > 1 ? "s" : ""}`;
    showOutput = true; dismissDiagnosis();
    streamTerraform("taint", { addresses },
      (data) => { appendOutput(data); },
      () => { actionRunning = false; actionResult = hasError(actionOutput) ? "error" : "success"; if (actionResult === "error") triggerDiagnosis("taint", actionOutput); refreshPlan(); }
    );
  }

  function runImport() {
    if (!importAddress.trim() || !importId.trim()) return;
    actionOutput = ""; actionLines = []; lastOutputLine = ""; actionRunning = true; actionResult = null;
    actionLabel = "Import"; showOutput = true;
    streamImport(importAddress.trim(), importId.trim(),
      (data) => { appendOutput(data); },
      () => { actionRunning = false; actionResult = hasError(actionOutput) ? "error" : "success"; showImport = false; refreshGrid(); }
    );
  }

  async function handleDestroyClick() {
    const sel = gridApi?.getSelectedRows() || [];
    const awsOnly = sel.filter(r => r.status === "unmanaged");
    const tfN = sel.length - awsOnly.length;
    const parts = [];
    if (tfN > 0) parts.push(`${tfN} via terraform`);
    if (awsOnly.length > 0) parts.push(`${awsOnly.length} via AWS API`);

    preconditionWarnings = [];
    if (awsOnly.length > 0) {
      try { preconditionWarnings = await checkAwsDeletePreconditions(awsOnly); } catch (_) {}
    }

    let msg = `Delete ${sel.length} resource${sel.length > 1 ? "s" : ""} (${parts.join(", ")})? This cannot be undone.`;
    if (preconditionWarnings.length > 0) {
      msg += "\n\nThe following resources require additional steps:";
      for (const w of preconditionWarnings) msg += `\n\u2022 ${w.name}: ${w.warning}`;
    }
    confirmMessage = msg;
    confirmType = "destroy_selected";
    confirmOpen = true;
  }

  // --- Data loading ---

  async function refreshGrid() {
    try {
      const data = await getOverview();
      allRows = data;
      activeStatusFilter = "all";
      computeStats(data);
      gridApi?.setGridOption("rowData", data);
      setCachedResources(data);
      triggerCloudScan();
    } catch (_) {}
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
          if (msg.type === "phase") { loadPhase = msg.message; loadLog = ""; }
          else if (msg.type === "log") { loadLog = msg.message; }
          else if (msg.type === "result") {
             allRows = msg.data;
             computeStats(msg.data);
             activeStatusFilter = "all";
             gridApi?.setGridOption("rowData", msg.data);
             gridApi?.setGridOption("loading", false);
             setCachedResources(msg.data);
           }
        } catch (_) {}
      },
      () => {
        planRefreshing = false; loadPhase = ""; loadLog = "";
        gridApi?.setGridOption("loading", false);
        triggerCloudScan();
        fetchCosts();
      }
    );
  }

  function triggerCloudScan() {
    cloudScanning = true;
    cloudScanDone = 0;
    cloudScanTotal = 0;
    cloudScanLabel = "";

    streamCloudScan(
      (raw) => {
        try {
          const msg = JSON.parse(raw);
          if (msg.type === "phase") {
            cloudScanLabel = msg.message;
          } else if (msg.type === "scan_progress") {
            cloudScanDone = msg.done;
            cloudScanTotal = msg.total;
            cloudScanLabel = msg.label;
          } else if (msg.type === "result") {
            allRows = msg.data;
            computeStats(msg.data);
            applyFilters();
            cloudScanned = true;
            setCachedResources(msg.data);
          }
        } catch (_) {}
      },
      () => {
        cloudScanning = false;
        cloudScanLabel = "";
        fetchCosts();
      }
    );
  }

  async function fetchCosts() {
    costsLoading = true;
    try {
      const costData = await getCosts();
      if (costData.resources && costData.resources.length > 0) {
        const costById = {};
        for (const r of costData.resources) {
          if (r.cost_monthly != null) {
            costById[r.id] = r.cost_monthly;
            const key = `${r.resource_type}.${r.resource_name}`;
            costById[key] = r.cost_monthly;
          }
        }
        const updated = allRows.map((row) => {
          const cost = costById[row.id] ?? costById[`${row.resource_type}.${row.resource_name}`] ?? null;
          return cost != null ? { ...row, cost_monthly: cost } : row;
        });
        allRows = updated;
        totalCost = updated.reduce((sum, r) => sum + (r.cost_monthly || 0), 0);
        filteredCost = totalCost;
        applyFilters();
        setCachedResources(updated);
        setCachedCosts(totalCost);
      }
    } catch (e) {
      console.error("fetchCosts error:", e);
    }
    costsLoading = false;
  }

  // --- Filters ---

  function computeStats(data) {
    const s = { total: data.length, statuses: {}, actions: {} };
    for (const r of data) {
      const st = r.status || "managed";
      s.statuses[st] = (s.statuses[st] || 0) + 1;
      const a = r.action || "";
      if (a && a !== "no-op" && a !== "read") s.actions[a] = (s.actions[a] || 0) + 1;
    }
    stats = s;
  }

  function setStatusFilter(statusId) {
    activeStatusFilter = statusId;
    applyFilters();
  }

  function setActionFilter(actionId) {
    activeActionFilter = actionId;
    applyFilters();
  }

  function applyFilters() {
    if (!gridApi) return;
    let filtered = allRows;
    if (activeStatusFilter !== "all") {
      filtered = filtered.filter(r => r.status === activeStatusFilter);
    }
    if (activeActionFilter !== "all") {
      filtered = filtered.filter(r => r.action === activeActionFilter);
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      filtered = filtered.filter(r =>
        (r.resource_name || "").toLowerCase().includes(q) ||
        (r.arn || "").toLowerCase().includes(q) ||
        (r.resource_type || "").toLowerCase().includes(q) ||
        (r.display_type || "").toLowerCase().includes(q) ||
        (r.service || "").toLowerCase().includes(q)
      );
    }
    gridApi.setGridOption("rowData", filtered);
    filteredCost = filtered.reduce((sum, r) => sum + (r.cost_monthly || 0), 0);
  }

  function openResourceDetail(resource) {
    detailResource = resource;
    detailOpen = true;
  }

  $effect(() => { searchText; activeActionFilter; applyFilters(); });

  // --- Grid ---

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
              const extra = params.data?.cloud_extra || {};
              const merged = { ...attrs, ...extra };
              const detail = Object.entries(merged)
                .filter(([_, v]) => v !== null && v !== "")
                .map(([key, value]) => ({ key, value: typeof value === "object" ? JSON.stringify(value, null, 2) : String(value) }));
              params.successCallback(detail);
            },
          },
          isRowMaster: (data) => {
            const attrs = data?.attributes || {};
            const extra = data?.cloud_extra || {};
            return Object.keys(attrs).length > 0 || Object.keys(extra).length > 0;
          },
          rowSelection: { mode: "multiRow", checkboxes: true, headerCheckbox: true, groupSelects: "descendants" },
          onSelectionChanged: () => { selectedCount = gridApi?.getSelectedRows()?.length || 0; },
          onRowDoubleClicked: (params) => { if (params.data && !params.node?.group) openResourceDetail(params.data); },
          rowHeight: 34,
          headerHeight: 32,
        });
      } else if (gridApi) {
        gridApi.setGridOption("rowData", data);
      }
    });
  }

  // --- Lifecycle ---

  onMount(async () => {
    // Try browser cache first to avoid re-fetching on page refresh
    const cached = getCachedResources();
    if (cached && cached.length > 0) {
      const cachedCosts = getCachedCosts();
      if (cachedCosts) totalCost = cachedCosts.totalCost;
      filteredCost = totalCost;
      allRows = cached;
      computeStats(cached);
      initGrid(cached);
      loading = false;
      return;
    }

    // No cache — fetch from API
    try {
      const data = await getOverview();

      if (data.length > 0) {
        computeStats(data);
        initGrid(data);
        loading = false;
        setCachedResources(data);
        triggerCloudScan();
        fetchCosts();
      } else {
        loading = false;
        initGrid([]);
        refreshPlan();
      }
    } catch (e) {
      error = e.message;
      loading = false;
    }
  });

  onDestroy(() => {
    observer.disconnect();
    gridApi?.destroy();
    if (diagController) diagController.abort();
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
        {@const tfSelected = (gridApi?.getSelectedRows() || []).filter(r => r.in_code || r.in_state).length}
        {#if tfSelected > 0}
          <button class="btn btn-success btn-xs" onclick={applySelected} disabled={actionRunning}>
            <span class="icon-[tabler--target-arrow] size-3.5"></span> Apply {tfSelected}
          </button>
        {/if}
        <button class="btn btn-error btn-xs" onclick={handleDestroyClick} disabled={actionRunning}>
          <span class="icon-[tabler--trash] size-3.5"></span> Destroy {selectedCount}
        </button>
        {#if tfSelected > 0}
          <button class="btn btn-warning btn-xs" onclick={taintSelected} disabled={actionRunning}>
            <span class="icon-[tabler--flag] size-3.5"></span> Taint {tfSelected}
          </button>
        {/if}
      {/if}
      <button class="btn btn-soft btn-error btn-xs" onclick={() => { confirmMessage = "Destroy ALL resources in this project? This cannot be undone."; confirmType = "destroy_all"; confirmOpen = true; }} disabled={actionRunning}>
        <span class="icon-[tabler--trash] size-3.5"></span> Destroy All
      </button>

      <div class="w-px h-5 bg-base-content/10"></div>

      <button class="btn btn-soft btn-xs" onclick={() => (showImport = !showImport)} disabled={actionRunning}>
        <span class="icon-[tabler--package-import] size-3.5"></span> Import
      </button>

      <div class="ms-auto flex items-center gap-2">
        {#if cloudScanning}
          <span class="flex items-center gap-1.5 text-xs text-base-content/40">
            <span class="loading loading-spinner loading-xs"></span>
            Scanning cloud...
          </span>
        {:else if cloudScanned}
          <button
            class="btn btn-text btn-xs"
            onclick={triggerCloudScan}
            title="Rescan cloud resources"
          >
            <span class="icon-[tabler--cloud-search] size-3.5"></span>
            Rescan
          </button>
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

    <!-- Progress bars -->
    {#if actionRunning || planRefreshing}
      <div class="px-4 py-1 border-b border-base-content/10 bg-base-200/50 flex items-center gap-2">
        <span class="loading loading-spinner loading-xs text-primary"></span>
        <span class="text-xs text-base-content/50">{planRefreshing ? (loadPhase || "Updating...") : actionLabel}</span>
        {#if planRefreshing && loadLog}
          <span class="text-[10px] font-mono text-base-content/30 truncate flex-1">{loadLog}</span>
        {:else if actionRunning && lastOutputLine}
          <span class="text-[10px] font-mono text-base-content/30 truncate flex-1">{lastOutputLine}</span>
        {/if}
      </div>
    {/if}

    <!-- Cloud scan progress -->
    {#if cloudScanning}
      <div class="px-4 py-1 border-b border-base-content/10 bg-base-200/50">
        <div class="flex items-center gap-2 text-xs text-base-content/50 mb-1">
          <span class="icon-[tabler--cloud-search] size-3"></span>
          Scanning cloud resources... {cloudScanLabel}
          {#if cloudScanTotal > 0}
            <span class="text-[10px] text-base-content/30">{cloudScanDone}/{cloudScanTotal}</span>
          {/if}
        </div>
        <div class="w-full bg-base-300 rounded-full h-1">
          <div
            class="bg-info h-1 rounded-full transition-all"
            style="width: {cloudScanTotal > 0 ? (cloudScanDone / cloudScanTotal) * 100 : 0}%"
          ></div>
        </div>
      </div>
    {/if}

    <!-- Import bar -->
    {#if showImport}
      <div class="flex items-center gap-2 px-4 py-2 border-b border-base-content/10 bg-base-200/50">
        <span class="text-xs text-base-content/50">Import:</span>
        <input type="text" class="input input-xs flex-1 font-mono" placeholder="aws_instance.example" bind:value={importAddress} />
        <input type="text" class="input input-xs flex-1 font-mono" placeholder="i-1234567890abcdef0" bind:value={importId} />
        <button class="btn btn-primary btn-xs" onclick={runImport} disabled={actionRunning || !importAddress.trim() || !importId.trim()}>Import</button>
        <button class="btn btn-text btn-xs" onclick={() => (showImport = false)} aria-label="Cancel import">
          <span class="icon-[tabler--x] size-3"></span>
        </button>
      </div>
    {/if}

    <!-- Output + Diagnosis modal -->
    {#if showOutput || (showDiagnosis && diagMessages.length > 0)}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onclick={() => { if (!actionRunning && !diagStreaming) { showOutput = false; } }}>
        <div class="bg-base-100 w-[94vw] max-w-7xl h-[85vh] rounded-xl shadow-2xl flex flex-col overflow-hidden" onclick={(e) => e.stopPropagation()}>
        <div class="flex flex-1 overflow-hidden">
          {#if showOutput}
            <div class="flex flex-col flex-1 min-w-0 {showDiagnosis && diagMessages.length > 0 ? 'border-r border-base-content/10' : ''}">
              <div class="flex items-center justify-between px-3 py-1.5 border-b border-base-content/10 bg-base-200 shrink-0">
                <span class="text-xs text-base-content/60 flex items-center gap-1.5">
                  <span class="icon-[tabler--terminal] size-3.5"></span>
                  {actionLabel}
                  {#if actionRunning}<span class="loading loading-dots loading-xs"></span>
                  {:else if actionResult === "success"}<span class="flex items-center gap-1 text-success font-medium"><span class="icon-[tabler--circle-check] size-3.5"></span>Done</span>
                  {:else if actionResult === "error"}<span class="flex items-center gap-1 text-error font-medium"><span class="icon-[tabler--circle-x] size-3.5"></span>Failed</span>{/if}
                  {#if actionLines.length > 0}<span class="text-[10px] text-base-content/30">{actionLines.length} lines</span>{/if}
                </span>
                <div class="flex items-center gap-0.5">
                  <button class="btn btn-text btn-xs btn-square" onclick={() => { showOutputSearch = !showOutputSearch; if (!showOutputSearch) outputSearch = ""; }} title="Search" class:text-primary={showOutputSearch}>
                    <span class="icon-[tabler--search] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={copyOutput} title="Copy output">
                    <span class="icon-[tabler--copy] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={() => (outputAutoScroll = !outputAutoScroll)} title={outputAutoScroll ? "Auto-scroll on" : "Auto-scroll off"} class:text-primary={outputAutoScroll}>
                    <span class="icon-[tabler--arrow-bar-to-down] size-3"></span>
                  </button>
                  <button class="btn btn-text btn-xs btn-square" onclick={() => { showOutput = false; showOutputSearch = false; }} aria-label="Close">
                    <span class="icon-[tabler--x] size-3"></span>
                  </button>
                </div>
              </div>
              {#if showOutputSearch}
                <div class="flex items-center gap-2 px-3 py-1 border-b border-base-content/5 shrink-0">
                  <span class="icon-[tabler--search] size-3 text-base-content/30"></span>
                  <input type="text" class="input input-xs flex-1 text-xs bg-transparent border-none focus:outline-none" placeholder="Filter output..." bind:value={outputSearch} />
                  {#if outputSearch}<span class="text-[10px] text-base-content/30">{filteredLines.length} match{filteredLines.length !== 1 ? "es" : ""}</span>{/if}
                </div>
              {/if}
              <div bind:this={outputEl} class="overflow-auto flex-1 bg-base-200">
                {#if filteredLines.length > 0}
                  <table class="w-full"><tbody>
                    {#each filteredLines as line}
                      <tr class="hover:bg-base-content/5 group">
                        <td class="px-1.5 py-0 text-[9px] font-mono text-base-content/20 select-none whitespace-nowrap align-top w-14 group-hover:text-base-content/40">{line.time}</td>
                        <td class="px-1.5 py-0 font-mono text-[11px] whitespace-pre-wrap break-all"
                          class:text-error={line.type === "error"}
                          class:text-warning={line.type === "warning"}
                          class:text-success={line.type === "success"}
                          class:text-info={line.type === "plan"}
                          style={line.type === "normal" ? "color: oklch(var(--bc) / 0.8);" : ""}
                        >{line.text}</td>
                      </tr>
                    {/each}
                  </tbody></table>
                {/if}
              </div>
            </div>
          {/if}

          {#if showDiagnosis && diagMessages.length > 0}
            <div class="flex flex-col flex-1 min-w-0">
              <div class="flex items-center justify-between px-3 py-1.5 border-b border-primary/10 bg-primary/5 shrink-0">
                <span class="text-xs font-medium text-primary flex items-center gap-1.5">
                  <span class="icon-[tabler--robot] size-3.5"></span>
                  AI Diagnosis
                  {#if diagStreaming}<span class="loading loading-dots loading-xs ms-1"></span>{/if}
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
                          <div class="diagnosis-md text-xs text-base-content/80">{@html renderMarkdown(seg.content)}</div>
                        {:else if seg.type === "code"}
                          <div class="rounded-lg overflow-hidden border border-base-content/10 my-2">
                            <div class="flex items-center justify-between px-2 py-1 bg-base-200">
                              <span class="text-[10px] font-mono text-base-content/50">{seg.filename || seg.language || "code"}</span>
                              <div class="flex gap-1">
                                {#if seg.language === "bash" || seg.language === "sh"}
                                  <button class="btn btn-xs btn-warning gap-1" onclick={() => runDiagCommand(seg.content.trim())} disabled={actionRunning}>
                                    <span class="icon-[tabler--player-play] size-3"></span> Run
                                  </button>
                                {/if}
                                {#if seg.filename}
                                  <button class="btn btn-xs btn-primary gap-1" onclick={() => openDiffForFile(seg.filename, seg.content)} disabled={applyStatus[seg.filename] === "applying"}>
                                    {#if applyStatus[seg.filename] === "applying"}<span class="loading loading-spinner loading-xs"></span>
                                    {:else if applyStatus[seg.filename] === "success"}<span class="icon-[tabler--check] size-3"></span> Applied
                                    {:else if applyStatus[seg.filename] === "error"}<span class="icon-[tabler--x] size-3"></span> Failed
                                    {:else}<span class="icon-[tabler--diff] size-3"></span> Review & Apply{/if}
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
              <div class="border-t border-base-content/10 p-2 bg-base-200/60 shrink-0">
                <div class="flex gap-1.5">
                  <textarea class="textarea textarea-sm flex-1 text-xs min-h-8 max-h-20 leading-tight" rows="1"
                    placeholder="Ask a follow-up or describe what to try..."
                    bind:value={diagInput} onkeydown={handleDiagKeydown} disabled={diagStreaming}
                  ></textarea>
                  {#if diagStreaming}
                    <button class="btn btn-soft btn-sm btn-square" onclick={stopDiag} aria-label="Stop">
                      <span class="icon-[tabler--player-stop] size-3.5"></span>
                    </button>
                  {:else}
                    <button class="btn btn-primary btn-sm btn-square" onclick={() => { if (diagInput.trim()) sendDiagMessage(diagInput.trim()); }} disabled={!diagInput.trim()} aria-label="Send">
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

    <!-- Status filter bar -->
    <div class="flex items-center gap-2 px-4 py-1.5 border-b border-base-content/10 flex-wrap">
      {#each STATUS_FILTERS as sf}
        {@const count = sf.id === "all" ? stats.total : (stats.statuses[sf.id] || 0)}
        <button
          class="btn btn-xs {activeStatusFilter === sf.id ? 'btn-primary' : 'btn-soft'} {count === 0 && sf.id !== 'all' ? 'opacity-40' : ''}"
          style={activeStatusFilter === sf.id && sf.color ? `background:${sf.color};border-color:${sf.color};` : ""}
          onclick={() => setStatusFilter(sf.id)}
          title={sf.hint}
        >
          {#if sf.color}
            <span class="w-1.5 h-1.5 rounded-full" style="background: {sf.color}"></span>
          {/if}
          {sf.label}
          {count}
        </button>
      {/each}

      <div class="w-px h-4 bg-base-content/10"></div>
      {#each ACTION_FILTERS as af}
        {@const count = af.id === "all" ? Object.values(stats.actions || {}).reduce((a, b) => a + b, 0) : (stats.actions?.[af.id] || 0)}
        <button
          class="btn btn-xs {activeActionFilter === af.id ? 'btn-primary' : 'btn-soft'} {count === 0 && af.id !== 'all' ? 'opacity-40' : ''}"
          style={activeActionFilter === af.id && af.color ? `background:${af.color};border-color:${af.color};` : ""}
          onclick={() => setActionFilter(af.id)}
        >
          {#if af.color}
            <span class="w-1.5 h-1.5 rounded-full" style="background: {af.color}"></span>
          {/if}
          {af.label}
          {count}
        </button>
      {/each}

      {#if !cloudScanned && !cloudScanning}
        <span class="text-[10px] text-base-content/30 flex items-center gap-1">
          <span class="icon-[tabler--cloud-off] size-3"></span>
          Cloud not scanned
        </span>
      {/if}

      <div class="ms-auto flex items-center gap-2">
        <div class="relative">
          <span class="icon-[tabler--search] size-3 absolute left-2 top-1/2 -translate-y-1/2 text-base-content/30"></span>
          <input type="text" class="input input-xs pl-7 w-44 text-xs" placeholder="Search name or ARN..." bind:value={searchText} />
        </div>
        {#if totalCost !== null || costsLoading}
          <div class="flex items-center gap-1.5 text-xs">
            <span class="icon-[tabler--currency-dollar] size-3.5 text-base-content/40"></span>
            {#if costsLoading}
              <span class="loading loading-spinner loading-xs"></span>
            {:else}
              {@const isFiltered = activeStatusFilter !== "all" || activeActionFilter !== "all" || searchText.trim()}
              <span class="font-mono font-medium">${filteredCost.toFixed(2)}</span>
              {#if isFiltered && totalCost !== filteredCost}
                <span class="text-base-content/20">/</span>
                <span class="font-mono text-base-content/40">${totalCost?.toFixed(2)}</span>
              {/if}
              <span class="text-base-content/30">/mo</span>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    <!-- Presence legend -->
    <div class="flex items-center gap-3 px-4 py-1 border-b border-base-content/5 text-[10px] text-base-content/30">
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background:#3b82f6"></span> State</span>
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background:#8b5cf6"></span> Code</span>
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background:#06b6d4"></span> Cloud</span>
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

<!-- Resource detail modal -->
{#if detailOpen && detailResource}
  {@const r = detailResource}
  {@const statusStyles = { managed: { color: "#10b981", label: "Managed" }, pending: { color: "#6366f1", label: "Pending" }, drift: { color: "#f59e0b", label: "Drift" }, unmanaged: { color: "#f97316", label: "Unmanaged" }, orphaned: { color: "#ef4444", label: "Orphaned" } }}
  {@const actionStyles = { "no-op": { color: "#10b981", label: "No Change" }, create: { color: "#6366f1", label: "Create" }, update: { color: "#f59e0b", label: "Update" }, destroy: { color: "#ef4444", label: "Destroy" }, replace: { color: "#ec4899", label: "Replace" } }}
  {@const ss = statusStyles[r.status] || { color: "#6b7280", label: r.status }}
  {@const as_ = actionStyles[r.action] || { color: "#6b7280", label: r.action }}
  {@const before = r.before || {}}
  {@const after = r.after || {}}
  {@const attrs = r.attributes || {}}
  {@const tags = r.tags || {}}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onclick={() => (detailOpen = false)}>
    <div class="bg-base-100 w-[80vw] max-w-3xl max-h-[85vh] rounded-xl shadow-2xl flex flex-col overflow-hidden" onclick={(e) => e.stopPropagation()}>
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-2.5 border-b border-base-content/10 bg-base-200/50">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold">{r.display_type || r.resource_type}: {r.resource_name}</span>
          <span class="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded" style="background: {ss.color}20; color: {ss.color}">
            <span class="w-1.5 h-1.5 rounded-full" style="background: {ss.color}"></span> {ss.label}
          </span>
          {#if r.action && r.action !== "no-op"}
            <span class="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded" style="background: {as_.color}20; color: {as_.color}">
              <span class="w-1.5 h-1.5 rounded-full" style="background: {as_.color}"></span> {as_.label}
            </span>
          {/if}
        </div>
        <button class="btn btn-text btn-xs btn-square" onclick={() => (detailOpen = false)}>
          <span class="icon-[tabler--x] size-4"></span>
        </button>
      </div>

      <!-- Body -->
      <div class="overflow-y-auto flex-1 p-4 space-y-4 text-xs">
        <!-- Info grid -->
        <div class="grid grid-cols-2 gap-x-6 gap-y-1.5">
          <div><span class="text-base-content/40">Address</span></div>
          <div class="font-mono text-[11px]">{r.id}</div>

          <div><span class="text-base-content/40">Presence</span></div>
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full" style="background: {r.in_state ? '#3b82f6' : 'transparent'}; border: 1px solid #3b82f6; opacity: {r.in_state ? 1 : 0.3}"></span>
              State
            </span>
            <span class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full" style="background: {r.in_code ? '#8b5cf6' : 'transparent'}; border: 1px solid #8b5cf6; opacity: {r.in_code ? 1 : 0.3}"></span>
              Code
            </span>
            <span class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full" style="background: {r.in_cloud === true ? '#06b6d4' : 'transparent'}; border: 1px solid #06b6d4; opacity: {r.in_cloud === true ? 1 : r.in_cloud === false ? 0.3 : 0.15}"></span>
              Cloud{r.in_cloud === null ? " ?" : ""}
            </span>
          </div>

          {#if r.tf_file}
            <div><span class="text-base-content/40">File</span></div>
            <div>
              <button class="text-purple-400 hover:underline font-mono text-[11px]" onclick={() => { detailOpen = false; if (onnavigate) onnavigate({ file: r.tf_file, line: r.tf_line }); }}>
                {r.tf_file}{r.tf_line ? `:${r.tf_line}` : ""}
              </button>
            </div>
          {/if}

          {#if r.arn}
            <div><span class="text-base-content/40">ARN</span></div>
            <div class="font-mono text-[10px] break-all text-base-content/60">{r.arn}</div>
          {/if}

          {#if r.cloud_id}
            <div><span class="text-base-content/40">Cloud ID</span></div>
            <div class="font-mono text-[11px]">{r.cloud_id}</div>
          {/if}

          {#if r.console_url}
            <div><span class="text-base-content/40">Console</span></div>
            <div><a href={r.console_url} target="_blank" rel="noopener" class="text-cyan-400 hover:underline text-[11px]">Open in AWS Console <span class="icon-[tabler--external-link] size-3 inline"></span></a></div>
          {/if}

          {#if r.cost_monthly != null && r.cost_monthly > 0}
            <div><span class="text-base-content/40">Cost</span></div>
            <div class="font-mono font-medium" style="color: {r.cost_monthly > 100 ? '#ef4444' : r.cost_monthly > 10 ? '#f59e0b' : '#10b981'}">${r.cost_monthly.toFixed(2)}/mo</div>
          {/if}
        </div>

        <!-- Tags -->
        {#if tags && typeof tags === "object" && Object.keys(tags).length > 0}
          <div>
            <div class="font-semibold text-base-content/60 mb-1.5">Tags</div>
            <div class="flex flex-wrap gap-1.5">
              {#each Object.entries(tags) as [k, v]}
                <span class="text-[10px] px-2 py-0.5 rounded bg-base-content/5 font-mono">
                  <span class="text-base-content/40">{k}:</span> {v}
                </span>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Changes (before/after) -->
        {#if r.action === "create" && Object.keys(after).length > 0}
          <div>
            <div class="font-semibold mb-1.5" style="color: #6366f1">Will be created with</div>
            <div class="bg-base-200/50 rounded-lg overflow-hidden border border-base-content/5">
              <table class="w-full">
                <tbody>
                  {#each Object.entries(after).filter(([k, v]) => v != null && !["tags", "tags_all", "timeouts"].includes(k)) as [k, v]}
                    <tr class="border-b border-base-content/5 last:border-0">
                      <td class="px-3 py-1 font-mono text-[10px] font-semibold text-base-content/50 w-48 align-top">{k}</td>
                      <td class="px-3 py-1 font-mono text-[10px] break-all">{typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {:else if r.action === "destroy" && Object.keys(before).length > 0}
          <div>
            <div class="font-semibold mb-1.5" style="color: #ef4444">Will be destroyed</div>
            <div class="bg-base-200/50 rounded-lg overflow-hidden border border-base-content/5">
              <table class="w-full">
                <tbody>
                  {#each Object.entries(before).filter(([k, v]) => v != null && !["tags", "tags_all", "timeouts"].includes(k)) as [k, v]}
                    <tr class="border-b border-base-content/5 last:border-0">
                      <td class="px-3 py-1 font-mono text-[10px] font-semibold text-base-content/50 w-48 align-top">{k}</td>
                      <td class="px-3 py-1 font-mono text-[10px] break-all">{typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {:else if (r.action === "update" || r.action === "replace") && (Object.keys(before).length > 0 || Object.keys(after).length > 0)}
          <div>
            <div class="font-semibold mb-1.5" style="color: {r.action === 'replace' ? '#ec4899' : '#f59e0b'}">
              {r.action === "replace" ? "Replace (destroy + create)" : "Changes"}
            </div>
            <div class="bg-base-200/50 rounded-lg overflow-hidden border border-base-content/5">
              <table class="w-full">
                <tbody>
                  {#each [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(k => !["tags", "tags_all", "timeouts"].includes(k) && before[k] !== after[k]).sort() as k}
                    {@const bv = before[k]}
                    {@const av = after[k]}
                    <tr class="border-b border-base-content/5 last:border-0">
                      <td class="px-3 py-1 font-mono text-[10px] font-semibold text-base-content/50 w-48 align-top">
                        {#if bv == null}<span style="color:#6366f1">+</span>{:else if av == null}<span style="color:#ef4444">-</span>{:else}<span style="color:#f59e0b">~</span>{/if}
                        {k}
                      </td>
                      <td class="px-3 py-1 font-mono text-[10px] break-all">
                        {#if bv == null}
                          <span style="color:#6366f1">{typeof av === "object" ? JSON.stringify(av) : String(av)}</span>
                        {:else if av == null}
                          <span style="color:#ef4444" class="line-through">{typeof bv === "object" ? JSON.stringify(bv) : String(bv)}</span>
                        {:else}
                          <span style="color:#ef4444" class="line-through">{typeof bv === "object" ? JSON.stringify(bv) : String(bv)}</span>
                          <span class="mx-1 text-base-content/20">&rarr;</span>
                          <span style="color:#10b981">{typeof av === "object" ? JSON.stringify(av) : String(av)}</span>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {:else if Object.keys(attrs).length > 0}
          <div>
            <div class="font-semibold text-base-content/60 mb-1.5">Attributes</div>
            <div class="bg-base-200/50 rounded-lg overflow-hidden border border-base-content/5 max-h-64 overflow-y-auto">
              <table class="w-full">
                <tbody>
                  {#each Object.entries(attrs).filter(([k, v]) => v != null && v !== "" && !["tags", "tags_all", "timeouts"].includes(k)).sort() as [k, v]}
                    <tr class="border-b border-base-content/5 last:border-0">
                      <td class="px-3 py-1 font-mono text-[10px] font-semibold text-base-content/50 w-48 align-top">{k}</td>
                      <td class="px-3 py-1 font-mono text-[10px] break-all">{typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {/if}

        <!-- Dependencies -->
        {#if r.depends_on && r.depends_on.length > 0}
          <div>
            <div class="font-semibold text-base-content/60 mb-1.5">Dependencies ({r.depends_on.length})</div>
            <div class="flex flex-wrap gap-1.5">
              {#each r.depends_on as dep}
                <span class="text-[10px] px-2 py-0.5 rounded bg-base-content/5 font-mono">{dep}</span>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

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
    background: oklch(var(--bc) / 0.08);
    font-family: ui-monospace, monospace;
  }
  :global(.diagnosis-md strong) {
    font-weight: 600;
  }
</style>
