<script>
  import { modal } from "../lib/modal.js";

  let { open = $bindable(false), filename = "", oldContent = "", newContent = "", ...rest } = $props();

  function computeDiff(oldText, newText) {
    // Normalize trailing newlines to avoid phantom diffs
    const oldLines = oldText.replace(/\n+$/, "").split("\n");
    const newLines = newText.replace(/\n+$/, "").split("\n");
    let rows = [];

    const lcs = buildLCS(oldLines, newLines);
    let oi = 0, ni = 0, li = 0;

    while (oi < oldLines.length || ni < newLines.length) {
      if (li < lcs.length && oi < oldLines.length && ni < newLines.length && oldLines[oi] === lcs[li] && newLines[ni] === lcs[li]) {
        rows.push({ type: "same", oldLine: oi + 1, newLine: ni + 1, oldText: oldLines[oi], newText: newLines[ni], oldHtml: null, newHtml: null });
        oi++; ni++; li++;
      } else if (li < lcs.length && oi < oldLines.length && oldLines[oi] !== lcs[li]) {
        rows.push({ type: "removed", oldLine: oi + 1, newLine: null, oldText: oldLines[oi], newText: "", oldHtml: null, newHtml: null });
        oi++;
      } else if (li < lcs.length && ni < newLines.length && newLines[ni] !== lcs[li]) {
        rows.push({ type: "added", oldLine: null, newLine: ni + 1, oldText: "", newText: newLines[ni], oldHtml: null, newHtml: null });
        ni++;
      } else if (oi < oldLines.length) {
        rows.push({ type: "removed", oldLine: oi + 1, newLine: null, oldText: oldLines[oi], newText: "", oldHtml: null, newHtml: null });
        oi++;
      } else if (ni < newLines.length) {
        rows.push({ type: "added", oldLine: null, newLine: ni + 1, oldText: "", newText: newLines[ni], oldHtml: null, newHtml: null });
        ni++;
      }
    }

    // Pair consecutive removed+added as "modified" and compute inline highlights
    rows = pairModifiedLines(rows);
    return rows;
  }

  function pairModifiedLines(rows) {
    const result = [];
    let i = 0;
    while (i < rows.length) {
      if (rows[i].type === "removed" && i + 1 < rows.length && rows[i + 1].type === "added") {
        // Pair them as modified
        const old = rows[i];
        const nw = rows[i + 1];
        const [oldHtml, newHtml] = inlineDiff(old.oldText, nw.newText);
        result.push({ ...old, type: "modified-old", oldHtml });
        result.push({ ...nw, type: "modified-new", newHtml });
        i += 2;
      } else {
        result.push(rows[i]);
        i++;
      }
    }
    return result;
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function inlineDiff(oldStr, newStr) {
    const oldChars = [...oldStr];
    const newChars = [...newStr];
    const charLcs = buildCharLCS(oldChars, newChars);

    let oldHtml = "", newHtml = "";
    let oi = 0, ni = 0, li = 0;

    while (oi < oldChars.length || ni < newChars.length) {
      if (li < charLcs.length && oi < oldChars.length && oldChars[oi] === charLcs[li] && ni < newChars.length && newChars[ni] === charLcs[li]) {
        oldHtml += esc(oldChars[oi]);
        newHtml += esc(newChars[ni]);
        oi++; ni++; li++;
      } else {
        // Collect removed chars
        let removedChunk = "";
        while (oi < oldChars.length && (li >= charLcs.length || oldChars[oi] !== charLcs[li])) {
          removedChunk += esc(oldChars[oi]);
          oi++;
        }
        // Collect added chars
        let addedChunk = "";
        while (ni < newChars.length && (li >= charLcs.length || newChars[ni] !== charLcs[li])) {
          addedChunk += esc(newChars[ni]);
          ni++;
        }
        if (removedChunk) oldHtml += `<span class="diff-inline-del">${removedChunk}</span>`;
        if (addedChunk) newHtml += `<span class="diff-inline-add">${addedChunk}</span>`;
      }
    }

    return [oldHtml, newHtml];
  }

  function buildCharLCS(a, b) {
    const m = a.length, n = b.length;
    if (m * n > 500000) {
      // Greedy fallback for huge lines
      const result = [];
      let bi = 0;
      for (let ai = 0; ai < m && bi < n; ai++) {
        for (let j = bi; j < n; j++) {
          if (a[ai] === b[j]) { result.push(a[ai]); bi = j + 1; break; }
        }
      }
      return result;
    }
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
    const result = [];
    let i = m, j = n;
    while (i > 0 && j > 0) {
      if (a[i - 1] === b[j - 1]) { result.unshift(a[i - 1]); i--; j--; }
      else if (dp[i - 1][j] > dp[i][j - 1]) i--;
      else j--;
    }
    return result;
  }

  function buildLCS(a, b) {
    const m = a.length, n = b.length;
    if (m * n > 1000000) {
      const result = [];
      let bi = 0;
      for (let ai = 0; ai < m && bi < n; ai++) {
        for (let j = bi; j < n; j++) {
          if (a[ai] === b[j]) { result.push(a[ai]); bi = j + 1; break; }
        }
      }
      return result;
    }
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
    const result = [];
    let i = m, j = n;
    while (i > 0 && j > 0) {
      if (a[i - 1] === b[j - 1]) { result.unshift(a[i - 1]); i--; j--; }
      else if (dp[i - 1][j] > dp[i][j - 1]) i--;
      else j--;
    }
    return result;
  }

  let diffRows = $derived(computeDiff(oldContent, newContent));
  let stats = $derived({
    added: diffRows.filter(r => r.type === "added" || r.type === "modified-new").length,
    removed: diffRows.filter(r => r.type === "removed" || r.type === "modified-old").length,
  });

  function handleApply() {
    const cb = rest.onapply;
    if (cb) cb();
    open = false;
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onclick={() => (open = false)}>
    <div class="bg-base-100 w-[92vw] max-w-6xl h-[85vh] shadow-2xl rounded-lg flex flex-col" onclick={(e) => e.stopPropagation()} use:modal={{ onclose: () => (open = false) }}>
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-2.5 border-b border-base-content/10 shrink-0">
        <div class="flex items-center gap-2">
          <span class="icon-[tabler--file-diff] size-4 text-primary"></span>
          <span class="text-xs font-medium">Review changes</span>
          <span class="font-mono text-xs text-base-content/50">{filename}</span>
          {#if stats.added > 0}
            <span class="text-[10px] font-mono text-success">+{stats.added}</span>
          {/if}
          {#if stats.removed > 0}
            <span class="text-[10px] font-mono text-error">-{stats.removed}</span>
          {/if}
        </div>
        <div class="flex items-center gap-2">
          <button class="btn btn-soft btn-xs" onclick={() => (open = false)}>Cancel</button>
          <button class="btn btn-primary btn-xs gap-1" onclick={handleApply}>
            <span class="icon-[tabler--check] size-3"></span> Apply
          </button>
        </div>
      </div>

      <!-- Column headers -->
      <div class="grid grid-cols-2 shrink-0 border-b border-base-content/10">
        <div class="px-3 py-1 border-r border-base-content/10" style="background: rgba(239, 68, 68, 0.06);">
          <span class="text-[10px] font-semibold" style="color: #ef4444;">Current</span>
        </div>
        <div class="px-3 py-1" style="background: rgba(34, 197, 94, 0.06);">
          <span class="text-[10px] font-semibold" style="color: #22c55e;">Proposed</span>
        </div>
      </div>

      <!-- Diff body -->
      <div class="overflow-auto flex-1">
        {#if stats.added === 0 && stats.removed === 0}
          <div class="flex items-center justify-center h-full text-base-content/40">
            <div class="text-center">
              <span class="icon-[tabler--check] size-8 block mx-auto mb-2"></span>
              <p class="text-sm">No changes detected</p>
              <p class="text-xs mt-1">The proposed content matches the current file.</p>
            </div>
          </div>
        {:else}
        <div class="grid grid-cols-2 min-w-0">
          {#each diffRows as row}
            <!-- Left (old) -->
            <div class="diff-row diff-left border-r border-base-content/10"
              class:diff-removed={row.type === "removed" || row.type === "modified-old"}
              class:diff-same={row.type === "same" || row.type === "added" || row.type === "modified-new"}
            >
              {#if row.type === "removed" || row.type === "modified-old"}
                <span class="diff-gutter diff-gutter-removed">-</span>
              {:else}
                <span class="diff-gutter">&nbsp;</span>
              {/if}
              <span class="diff-linenum">{row.oldLine ?? ""}</span>
              {#if row.oldHtml}
                <pre class="diff-text diff-text-removed">{@html row.oldHtml}</pre>
              {:else}
                <pre class="diff-text" class:diff-text-removed={row.type === "removed"}>{row.oldText}</pre>
              {/if}
            </div>
            <!-- Right (new) -->
            <div class="diff-row diff-right"
              class:diff-added={row.type === "added" || row.type === "modified-new"}
              class:diff-same={row.type === "same" || row.type === "removed" || row.type === "modified-old"}
            >
              {#if row.type === "added" || row.type === "modified-new"}
                <span class="diff-gutter diff-gutter-added">+</span>
              {:else}
                <span class="diff-gutter">&nbsp;</span>
              {/if}
              <span class="diff-linenum">{row.newLine ?? ""}</span>
              {#if row.newHtml}
                <pre class="diff-text diff-text-added">{@html row.newHtml}</pre>
              {:else}
                <pre class="diff-text" class:diff-text-added={row.type === "added"}>{row.newText}</pre>
              {/if}
            </div>
          {/each}
        </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .diff-row {
    display: flex;
    min-height: 22px;
    border-bottom: 1px solid rgba(128, 128, 128, 0.08);
  }
  .diff-gutter {
    width: 20px;
    flex-shrink: 0;
    text-align: center;
    font-size: 10px;
    font-family: ui-monospace, monospace;
    line-height: 22px;
    color: rgba(128, 128, 128, 0.3);
    user-select: none;
  }
  .diff-gutter-removed {
    background: rgba(239, 68, 68, 0.3);
    color: #ef4444;
    font-weight: 700;
  }
  .diff-gutter-added {
    background: rgba(34, 197, 94, 0.3);
    color: #22c55e;
    font-weight: 700;
  }
  .diff-linenum {
    width: 36px;
    flex-shrink: 0;
    text-align: right;
    padding-right: 6px;
    font-size: 10px;
    font-family: ui-monospace, monospace;
    line-height: 22px;
    color: rgba(128, 128, 128, 0.3);
    user-select: none;
  }
  .diff-text {
    flex: 1;
    font-size: 11px;
    font-family: ui-monospace, monospace;
    line-height: 22px;
    padding: 0 6px;
    margin: 0;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .diff-removed {
    background: rgba(239, 68, 68, 0.12);
  }
  .diff-added {
    background: rgba(34, 197, 94, 0.12);
  }
  .diff-text-removed {
    color: #ef4444;
  }
  .diff-text-added {
    color: #22c55e;
  }
  .diff-same .diff-text {
    color: rgba(128, 128, 128, 0.7);
  }
  .diff-same .diff-linenum {
    color: rgba(128, 128, 128, 0.2);
  }
  :global(.diff-inline-del) {
    background: rgba(239, 68, 68, 0.35);
    border-radius: 2px;
    padding: 1px 2px;
  }
  :global(.diff-inline-add) {
    background: rgba(34, 197, 94, 0.35);
    border-radius: 2px;
    padding: 1px 2px;
  }
</style>
