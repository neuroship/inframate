<script>
  import { onMount, onDestroy, tick } from "svelte";
  import { getFiles, getFile, updateFile } from "../lib/api.js";

  import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightSpecialChars, drawSelection, highlightActiveLine, rectangularSelection, crosshairCursor, dropCursor, Decoration } from "@codemirror/view";
  import { EditorState, StateEffect, StateField } from "@codemirror/state";
  import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
  import { syntaxHighlighting, indentOnInput, bracketMatching, foldGutter, foldKeymap, defaultHighlightStyle, HighlightStyle } from "@codemirror/language";
  import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
  import { closeBrackets, closeBracketsKeymap, autocompletion, completionKeymap } from "@codemirror/autocomplete";
  import { json } from "@codemirror/lang-json";
  import { tags } from "@lezer/highlight";
  import { hclLanguage } from "../lib/lang-hcl.js";

  // Blink highlight effect for "go to definition"
  const addHighlight = StateEffect.define();
  const clearHighlight = StateEffect.define();
  const highlightDeco = Decoration.line({ class: "cm-highlight-line" });
  const highlightField = StateField.define({
    create: () => Decoration.none,
    update(decos, tr) {
      for (const e of tr.effects) {
        if (e.is(addHighlight)) return Decoration.set([highlightDeco.range(e.value)]);
        if (e.is(clearHighlight)) return Decoration.none;
      }
      return decos;
    },
    provide: (f) => EditorView.decorations.from(f),
  });

  let { openFile = null, openLine = null, openSeq = 0 } = $props();

  let files = $state([]);
  let selectedFile = $state(null);
  let originalContent = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let error = $state("");
  let success = $state("");
  let isDirty = $state(false);
  let editorEl = $state(null);
  let cursorInfo = $state({ line: 1, col: 1 });

  /** @type {EditorView | null} */
  let view = null;

  // Theme that blends with the app
  const editorTheme = EditorView.theme({
    "&": {
      fontSize: "12px",
      height: "100%",
    },
    ".cm-content": {
      fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
      padding: "8px 0",
    },
    ".cm-gutters": {
      borderRight: "1px solid color-mix(in oklch, var(--color-base-content) 10%, transparent)",
      backgroundColor: "var(--color-base-200)",
      color: "color-mix(in oklch, var(--color-base-content) 30%, transparent)",
      minWidth: "40px",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "var(--color-base-300)",
      color: "color-mix(in oklch, var(--color-base-content) 60%, transparent)",
    },
    ".cm-activeLine": {
      backgroundColor: "color-mix(in oklch, var(--color-base-content) 4%, transparent)",
    },
    ".cm-selectionMatch": {
      backgroundColor: "color-mix(in oklch, var(--color-primary) 15%, transparent)",
    },
    "&.cm-focused .cm-matchingBracket": {
      backgroundColor: "color-mix(in oklch, var(--color-primary) 20%, transparent)",
      outline: "1px solid color-mix(in oklch, var(--color-primary) 40%, transparent)",
    },
    ".cm-cursor": {
      borderLeftColor: "var(--color-base-content)",
    },
    ".cm-foldGutter span": {
      fontSize: "10px",
      lineHeight: "1.4",
      color: "color-mix(in oklch, var(--color-base-content) 30%, transparent)",
    },
    ".cm-foldGutter span:hover": {
      color: "color-mix(in oklch, var(--color-base-content) 70%, transparent)",
    },
    ".cm-searchMatch": {
      backgroundColor: "color-mix(in oklch, var(--color-warning) 30%, transparent)",
    },
    ".cm-searchMatch.cm-searchMatch-selected": {
      backgroundColor: "color-mix(in oklch, var(--color-success) 30%, transparent)",
    },
    ".cm-tooltip": {
      backgroundColor: "var(--color-base-200)",
      border: "1px solid color-mix(in oklch, var(--color-base-content) 10%, transparent)",
      borderRadius: "6px",
      boxShadow: "0 4px 12px oklch(0 0 0 / 0.15)",
    },
    ".cm-tooltip-autocomplete ul li[aria-selected]": {
      backgroundColor: "color-mix(in oklch, var(--color-primary) 15%, transparent)",
    },
    ".cm-panels": {
      backgroundColor: "var(--color-base-200)",
      borderTop: "1px solid color-mix(in oklch, var(--color-base-content) 10%, transparent)",
    },
    ".cm-panels input, .cm-panels button": {
      fontSize: "12px",
    },
  });

  // HCL-aware syntax colors
  const hclHighlight = HighlightStyle.define([
    { tag: tags.keyword, color: "oklch(0.7 0.15 280)" },
    { tag: tags.string, color: "oklch(0.7 0.14 150)" },
    { tag: tags.number, color: "oklch(0.72 0.14 50)" },
    { tag: tags.atom, color: "oklch(0.72 0.14 50)" },
    { tag: tags.comment, color: "oklch(0.55 0 0)", fontStyle: "italic" },
    { tag: tags.blockComment, color: "oklch(0.55 0 0)", fontStyle: "italic" },
    { tag: tags.lineComment, color: "oklch(0.55 0 0)", fontStyle: "italic" },
    { tag: tags.propertyName, color: "oklch(0.7 0.12 220)" },
    { tag: tags.variableName, color: "var(--color-base-content)" },
    { tag: tags.function(tags.variableName), color: "oklch(0.72 0.15 80)" },
    { tag: tags.typeName, color: "oklch(0.68 0.14 190)" },
    { tag: tags.operator, color: "oklch(0.65 0.1 30)" },
    { tag: tags.punctuation, color: "color-mix(in oklch, var(--color-base-content) 60%, transparent)" },
  ]);

  // Terraform keyword/function completions
  const terraformCompletions = autocompletion({
    override: [
      (context) => {
        const word = context.matchBefore(/\w*/);
        if (!word || (word.from === word.to && !context.explicit)) return null;
        return {
          from: word.from,
          options: [
            { label: "resource", type: "keyword", detail: "block" },
            { label: "data", type: "keyword", detail: "block" },
            { label: "variable", type: "keyword", detail: "block" },
            { label: "output", type: "keyword", detail: "block" },
            { label: "module", type: "keyword", detail: "block" },
            { label: "provider", type: "keyword", detail: "block" },
            { label: "terraform", type: "keyword", detail: "block" },
            { label: "locals", type: "keyword", detail: "block" },
            { label: "moved", type: "keyword", detail: "block" },
            { label: "import", type: "keyword", detail: "block" },
            { label: "for_each", type: "keyword", detail: "meta-argument" },
            { label: "count", type: "keyword", detail: "meta-argument" },
            { label: "depends_on", type: "keyword", detail: "meta-argument" },
            { label: "lifecycle", type: "keyword", detail: "meta-argument" },
            { label: "source", type: "keyword", detail: "meta-argument" },
            { label: "version", type: "keyword", detail: "meta-argument" },
            { label: "description", type: "property", detail: "attribute" },
            { label: "default", type: "property", detail: "attribute" },
            { label: "type", type: "property", detail: "attribute" },
            { label: "sensitive", type: "property", detail: "attribute" },
            { label: "nullable", type: "property", detail: "attribute" },
            { label: "validation", type: "property", detail: "attribute" },
            { label: "create_before_destroy", type: "property", detail: "lifecycle" },
            { label: "prevent_destroy", type: "property", detail: "lifecycle" },
            { label: "ignore_changes", type: "property", detail: "lifecycle" },
            { label: "replace_triggered_by", type: "property", detail: "lifecycle" },
            { label: "string", type: "type" },
            { label: "number", type: "type" },
            { label: "bool", type: "type" },
            { label: "list", type: "type" },
            { label: "map", type: "type" },
            { label: "set", type: "type" },
            { label: "object", type: "type" },
            { label: "tuple", type: "type" },
            { label: "any", type: "type" },
            { label: "optional", type: "type" },
            { label: "lookup", type: "function", detail: "(map, key, default)" },
            { label: "merge", type: "function", detail: "(maps...)" },
            { label: "concat", type: "function", detail: "(lists...)" },
            { label: "join", type: "function", detail: "(sep, list)" },
            { label: "split", type: "function", detail: "(sep, string)" },
            { label: "length", type: "function", detail: "(value)" },
            { label: "element", type: "function", detail: "(list, index)" },
            { label: "keys", type: "function", detail: "(map)" },
            { label: "values", type: "function", detail: "(map)" },
            { label: "flatten", type: "function", detail: "(list)" },
            { label: "toset", type: "function", detail: "(value)" },
            { label: "tolist", type: "function", detail: "(value)" },
            { label: "tomap", type: "function", detail: "(value)" },
            { label: "try", type: "function", detail: "(expressions...)" },
            { label: "can", type: "function", detail: "(expression)" },
            { label: "file", type: "function", detail: "(path)" },
            { label: "templatefile", type: "function", detail: "(path, vars)" },
            { label: "jsonencode", type: "function", detail: "(value)" },
            { label: "jsondecode", type: "function", detail: "(string)" },
            { label: "format", type: "function", detail: "(spec, values...)" },
            { label: "replace", type: "function", detail: "(string, substr, replace)" },
            { label: "regex", type: "function", detail: "(pattern, string)" },
            { label: "trimspace", type: "function", detail: "(string)" },
            { label: "lower", type: "function", detail: "(string)" },
            { label: "upper", type: "function", detail: "(string)" },
            { label: "contains", type: "function", detail: "(list, value)" },
            { label: "cidrsubnet", type: "function", detail: "(prefix, newbits, netnum)" },
          ],
        };
      },
    ],
  });

  function getLanguageExtension(filename) {
    if (filename.endsWith(".json")) return json();
    return hclLanguage;
  }

  function createEditor(content, filename) {
    if (view) {
      view.destroy();
      view = null;
    }
    if (!editorEl) return;

    const extensions = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      foldGutter(),
      drawSelection(),
      dropCursor(),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      rectangularSelection(),
      crosshairCursor(),
      syntaxHighlighting(hclHighlight),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      getLanguageExtension(filename),
      terraformCompletions,
      highlightField,
      editorTheme,
      keymap.of([
        ...closeBracketsKeymap,
        ...defaultKeymap,
        ...searchKeymap,
        ...historyKeymap,
        ...foldKeymap,
        ...completionKeymap,
        indentWithTab,
        {
          key: "Mod-s",
          run: () => {
            if (isDirty) save();
            return true;
          },
        },
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const currentContent = update.state.doc.toString();
          isDirty = currentContent !== originalContent;
        }
        if (update.selectionSet) {
          const pos = update.state.selection.main.head;
          const line = update.state.doc.lineAt(pos);
          cursorInfo = { line: line.number, col: pos - line.from + 1 };
        }
      }),
    ];

    view = new EditorView({
      state: EditorState.create({ doc: content, extensions }),
      parent: editorEl,
    });
  }

  function scrollToLine(line) {
    if (!view || !line) return;
    const lineInfo = view.state.doc.line(Math.min(line, view.state.doc.lines));
    view.dispatch({
      selection: { anchor: lineInfo.from },
      effects: [
        EditorView.scrollIntoView(lineInfo.from, { y: "center" }),
        addHighlight.of(lineInfo.from),
      ],
    });
    // Blink: remove highlight after a delay
    setTimeout(() => {
      if (view) view.dispatch({ effects: clearHighlight.of(null) });
    }, 1500);
  }

  onMount(async () => {
    try {
      files = await getFiles();
    } catch (e) {
      error = e.message;
    }
    loading = false;
  });

  onDestroy(() => {
    if (view) {
      view.destroy();
      view = null;
    }
  });

  let pendingLine = null;
  let lastConsumedSeq = -1;

  async function selectFile(filename) {
    error = "";
    success = "";
    try {
      const data = await getFile(filename);
      selectedFile = filename;
      originalContent = data.content;
      isDirty = false;
      await tick();
      createEditor(data.content, filename);
      if (pendingLine) {
        scrollToLine(pendingLine);
        pendingLine = null;
      }
    } catch (e) {
      error = e.message;
    }
  }

  async function save() {
    if (!view) return;
    saving = true;
    error = "";
    success = "";
    try {
      const content = view.state.doc.toString();
      await updateFile(selectedFile, content);
      originalContent = content;
      isDirty = false;
      success = "Saved";
      setTimeout(() => (success = ""), 2000);
    } catch (e) {
      error = e.message;
    }
    saving = false;
  }

  $effect(() => {
    if (openSeq > lastConsumedSeq && openFile && files.includes(openFile)) {
      lastConsumedSeq = openSeq;
      pendingLine = openLine;
      if (selectedFile !== openFile) {
        selectFile(openFile);
      } else {
        scrollToLine(openLine);
      }
    }
  });
</script>

<div class="flex h-full">
  <!-- File list sidebar -->
  <div class="w-48 border-r border-base-content/10 bg-base-200/60 overflow-auto flex-shrink-0">
    {#if loading}
      <div class="flex justify-center py-4">
        <span class="loading loading-spinner loading-xs"></span>
      </div>
    {:else if files.length === 0}
      <p class="text-xs text-base-content/50 p-3">No .tf files found</p>
    {:else}
      <div class="px-2 py-1.5 text-[10px] uppercase tracking-wider text-base-content/40 font-semibold">
        Files
      </div>
      {#each Object.entries(files.reduce((groups, f) => {
        const idx = f.lastIndexOf('/');
        const dir = idx === -1 ? '.' : f.substring(0, idx);
        (groups[dir] ??= []).push(f);
        return groups;
      }, {})).sort(([a], [b]) => a === '.' ? -1 : b === '.' ? 1 : a.localeCompare(b)) as [dir, groupFiles]}
        {#if dir !== '.'}
          <div class="px-2 pt-2 pb-0.5 text-[10px] uppercase tracking-wider text-base-content/40 font-semibold flex items-center gap-1">
            <span class="icon-[tabler--folder] size-3 flex-shrink-0 text-amber-400/60"></span>
            {dir}
          </div>
        {/if}
        {#each groupFiles as file}
          <button
            class="w-full text-left py-1 text-xs font-mono hover:bg-base-300/60 transition-colors flex items-center gap-1.5 {selectedFile === file ? 'bg-base-300 text-primary' : 'text-base-content/70'} {dir !== '.' ? 'pl-4 pr-2' : 'px-2'}"
            onclick={() => selectFile(file)}
          >
            {#if file.endsWith('.tf')}
              <span class="icon-[tabler--file-code] size-3.5 flex-shrink-0 text-violet-400/70"></span>
            {:else if file.endsWith('.json')}
              <span class="icon-[tabler--braces] size-3.5 flex-shrink-0 text-amber-400/70"></span>
            {:else}
              <span class="icon-[tabler--file-text] size-3.5 flex-shrink-0 text-emerald-400/70"></span>
            {/if}
            <span class="truncate">{file.split('/').pop()}</span>
            {#if selectedFile === file && isDirty}
              <span class="size-1.5 rounded-full bg-warning flex-shrink-0 ms-auto"></span>
            {/if}
          </button>
        {/each}
      {/each}
    {/if}
  </div>

  <!-- Editor pane -->
  <div class="flex-1 flex flex-col min-w-0">
    {#if selectedFile}
      <!-- Toolbar -->
      <div class="flex items-center gap-2 px-3 py-1 border-b border-base-content/10 bg-base-200/60">
        <span class="text-xs font-mono text-base-content/60 truncate">{selectedFile}</span>
        {#if isDirty}
          <span class="badge badge-xs badge-warning">modified</span>
        {/if}
        <div class="ms-auto flex items-center gap-2">
          {#if success}
            <span class="text-xs text-success flex items-center gap-1">
              <span class="icon-[tabler--check] size-3"></span>{success}
            </span>
          {/if}
          {#if error}
            <span class="text-xs text-error flex items-center gap-1">
              <span class="icon-[tabler--alert-triangle] size-3"></span>{error}
            </span>
          {/if}
          <button
              class="btn btn-primary btn-xs"
              onclick={save}
              disabled={!isDirty || saving}
            >
              <span class="icon-[tabler--device-floppy] size-3"></span>
              {saving ? "Saving..." : "Save"}
            </button>
        </div>
      </div>

      <!-- CodeMirror editor -->
      <div class="flex-1 overflow-hidden" bind:this={editorEl}></div>

      <!-- Status bar -->
      <div class="flex items-center gap-3 px-3 py-0.5 border-t border-base-content/10 bg-base-200/60 text-[10px] text-base-content/40">
        <span>Ln {cursorInfo.line}, Col {cursorInfo.col}</span>
        <span>{selectedFile.endsWith('.json') ? 'JSON' : 'HCL'}</span>
        <span class="ms-auto">
          <kbd class="kbd kbd-xs">Ctrl+F</kbd> search
          <span class="mx-1">·</span>
          <kbd class="kbd kbd-xs">Ctrl+S</kbd> save
        </span>
      </div>
    {:else}
      <div class="flex-1 flex flex-col items-center justify-center text-base-content/40 gap-2">
        <span class="icon-[tabler--code] size-8 opacity-30"></span>
        <p class="text-xs">Select a file to edit</p>
      </div>
    {/if}
  </div>
</div>

<style>
  :global(.cm-editor) {
    height: 100%;
  }
  :global(.cm-scroller) {
    overflow: auto;
  }
  :global(.cm-highlight-line) {
    background-color: color-mix(in oklch, var(--color-warning) 25%, transparent);
    animation: highlight-fade 1.5s ease-out forwards;
  }
  @keyframes highlight-fade {
    0% { background-color: color-mix(in oklch, var(--color-warning) 35%, transparent); }
    50% { background-color: color-mix(in oklch, var(--color-warning) 20%, transparent); }
    100% { background-color: transparent; }
  }
</style>
