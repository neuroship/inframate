<script>
  import { streamChatSession, getFile, updateFile, streamTerraform } from "../lib/api.js";
  import { marked } from "marked";
  import DiffModal from "./DiffModal.svelte";

  let { onclose, actionContext = "", onaction = null } = $props();

  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);
  let messagesEl;
  let controller = $state(null);

  // Track if we've already offered to help with the current error
  let offeredContext = $state("");
  $effect(() => {
    if (actionContext && actionContext !== offeredContext && messages.length === 0) {
      offeredContext = actionContext;
      sendMessage(`The following terraform command just failed. Help me fix it:\n\n\`\`\`\n${actionContext}\n\`\`\``);
    }
  });

  function sendMessage(text) {
    if (!text.trim() || streaming) return;

    const userMsg = text.trim();
    messages = [...messages, { role: "user", content: userMsg }];
    input = "";
    streaming = true;

    let aiText = "";
    messages = [...messages, { role: "assistant", content: "" }];

    const history = messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content }));

    controller = streamChatSession(
      history,
      (chunk) => {
        aiText += chunk;
        messages = [...messages.slice(0, -1), { role: "assistant", content: aiText }];
        if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
      },
      () => {
        streaming = false;
        controller = null;
      }
    );
  }

  function send() {
    sendMessage(input);
  }

  function stop() {
    if (controller) {
      controller.abort();
      controller = null;
      streaming = false;
    }
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function parseSegments(text) {
    const segments = [];
    const regex = /(?:File:\s*(\S+)\s*\n)?```(\w*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
      }
      segments.push({
        type: "code",
        filename: match[1] ? match[1].replace(/[`*_~]/g, "") : null,
        language: match[2],
        content: match[3],
      });
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

  // Diff modal state
  let diffOpen = $state(false);
  let diffFilename = $state("");
  let diffOldContent = $state("");
  let diffNewContent = $state("");
  let applyStatus = $state({});

  async function openDiff(filename, proposed) {
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

  // Run terraform commands
  const VALID_TF_COMMANDS = new Set(["init", "plan", "apply", "destroy", "taint", "fmt", "validate"]);
  let cmdRunning = $state(false);

  function runCommand(cmd) {
    const normalized = cmd.replace(/\\\n\s*/g, " ").trim();
    const match = normalized.match(/^terraform\s+(\w+)(.*)/s);
    if (!match || !VALID_TF_COMMANDS.has(match[1])) return;

    const tfCmd = match[1];
    const argsStr = match[2].trim();
    const body = {};
    if (argsStr) {
      const args = [];
      const re = /-[\w-]+(?:=(?:'[^']*'|"[^"]*"|\S+))?/g;
      let m;
      while ((m = re.exec(argsStr)) !== null) {
        args.push(m[0].replace(/['"]/g, ""));
      }
      if (args.length > 0) body.args = args;
    }

    cmdRunning = true;
    let output = "";
    messages = [...messages, { role: "assistant", content: `Running \`terraform ${tfCmd}\`...\n\`\`\`\n` }];

    streamTerraform(tfCmd, body,
      (data) => {
        output += data;
        messages = [...messages.slice(0, -1), { role: "assistant", content: `Running \`terraform ${tfCmd}\`...\n\`\`\`\n${output}\`\`\`` }];
        if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
      },
      () => {
        cmdRunning = false;
        messages = [...messages.slice(0, -1), { role: "assistant", content: `\`terraform ${tfCmd}\` completed.\n\`\`\`\n${output}\`\`\`` }];
        if (onaction) onaction();
      }
    );
  }

  function clearChat() {
    messages = [];
    offeredContext = "";
    applyStatus = {};
  }
</script>

<div class="flex flex-col h-full w-80 border-l border-base-content/10 bg-base-100">
  <!-- Header -->
  <div class="flex items-center justify-between px-3 py-2 border-b border-base-content/10 bg-base-200">
    <span class="text-xs font-medium flex items-center gap-1.5">
      <span class="icon-[tabler--robot] size-3.5 text-primary"></span>
      AI Assistant
    </span>
    <div class="flex gap-1">
      <button class="btn btn-text btn-xs btn-square" onclick={clearChat} aria-label="Clear chat" title="Clear chat">
        <span class="icon-[tabler--eraser] size-3"></span>
      </button>
      <button class="btn btn-text btn-xs btn-square" onclick={onclose} aria-label="Close sidebar">
        <span class="icon-[tabler--x] size-3.5"></span>
      </button>
    </div>
  </div>

  <!-- Messages -->
  <div
    bind:this={messagesEl}
    class="flex-1 overflow-auto p-3 space-y-3"
  >
    {#if messages.length === 0}
      <div class="text-center py-6 text-base-content/40">
        <span class="icon-[tabler--sparkles] size-6 block mx-auto mb-2"></span>
        <p class="text-xs">Ask about your Terraform config, get help with errors, or request code fixes.</p>
        <p class="text-[10px] mt-1 text-base-content/30">I can read your .tf files and apply changes directly.</p>
      </div>
    {/if}

    {#each messages as msg, i}
      {#if msg.role === "user"}
        <div class="flex justify-end">
          <div class="bg-primary/10 rounded-lg px-3 py-1.5 max-w-[90%]">
            <pre class="whitespace-pre-wrap font-sans text-xs text-base-content/70">{msg.content.length > 300 ? msg.content.slice(0, 200) + "..." : msg.content}</pre>
          </div>
        </div>
      {:else}
        <div class="max-w-full">
          {#each parseSegments(msg.content) as seg}
            {#if seg.type === "text"}
              <div class="sidebar-md text-xs text-base-content/80">
                {@html renderMarkdown(seg.content)}
              </div>
            {:else if seg.type === "code"}
              <div class="my-2 rounded-lg overflow-hidden border border-base-content/10">
                <div class="flex items-center justify-between px-2 py-1 bg-base-200">
                  <span class="text-[10px] font-mono text-base-content/50">
                    {seg.filename || seg.language || "code"}
                  </span>
                  <div class="flex gap-1">
                    {#if (seg.language === "bash" || seg.language === "sh") && seg.content.trim().startsWith("terraform")}
                      <button
                        class="btn btn-xs btn-warning gap-1"
                        onclick={() => runCommand(seg.content.trim())}
                        disabled={cmdRunning || streaming}
                      >
                        <span class="icon-[tabler--player-play] size-3"></span> Run
                      </button>
                    {/if}
                    {#if seg.filename}
                      <button
                        class="btn btn-xs btn-primary gap-1"
                        onclick={() => openDiff(seg.filename, seg.content)}
                        disabled={applyStatus[seg.filename] === "applying"}
                      >
                        {#if applyStatus[seg.filename] === "applying"}
                          <span class="loading loading-spinner loading-xs"></span>
                        {:else if applyStatus[seg.filename] === "success"}
                          <span class="icon-[tabler--check] size-3"></span> Applied
                        {:else if applyStatus[seg.filename] === "error"}
                          <span class="icon-[tabler--x] size-3"></span> Failed
                        {:else}
                          <span class="icon-[tabler--diff] size-3"></span> Review
                        {/if}
                      </button>
                    {/if}
                  </div>
                </div>
                <pre class="px-2 py-1.5 text-[10px] font-mono overflow-x-auto bg-base-300/50 max-h-48 overflow-y-auto">{seg.content}</pre>
              </div>
            {/if}
          {/each}
          {#if (streaming || cmdRunning) && i === messages.length - 1}
            <span class="loading loading-dots loading-xs text-primary"></span>
          {/if}
        </div>
      {/if}
    {/each}
  </div>

  <!-- Input -->
  <div class="border-t border-base-content/10 p-2 bg-base-200">
    <div class="flex gap-1.5">
      <textarea
        class="textarea textarea-sm flex-1 text-xs min-h-8 max-h-24 leading-tight"
        rows="1"
        placeholder="Ask about your config..."
        bind:value={input}
        onkeydown={handleKeydown}
        disabled={streaming || cmdRunning}
      ></textarea>
      {#if streaming}
        <button class="btn btn-soft btn-sm btn-square" onclick={stop} aria-label="Stop">
          <span class="icon-[tabler--player-stop] size-3.5"></span>
        </button>
      {:else}
        <button
          class="btn btn-primary btn-sm btn-square"
          onclick={send}
          disabled={!input.trim() || cmdRunning}
          aria-label="Send"
        >
          <span class="icon-[tabler--send] size-3.5"></span>
        </button>
      {/if}
    </div>
  </div>
</div>

<DiffModal
  bind:open={diffOpen}
  filename={diffFilename}
  oldContent={diffOldContent}
  newContent={diffNewContent}
  onapply={applyDiff}
/>

<style>
  :global(.sidebar-md h1),
  :global(.sidebar-md h2),
  :global(.sidebar-md h3) {
    font-size: 11px;
    font-weight: 600;
    margin: 6px 0 3px;
  }
  :global(.sidebar-md p) {
    margin: 3px 0;
    line-height: 1.5;
  }
  :global(.sidebar-md ul),
  :global(.sidebar-md ol) {
    padding-left: 14px;
    margin: 3px 0;
  }
  :global(.sidebar-md li) {
    margin: 2px 0;
    line-height: 1.4;
  }
  :global(.sidebar-md code) {
    font-size: 10px;
    padding: 1px 3px;
    border-radius: 3px;
    background: rgba(128, 128, 128, 0.12);
    font-family: ui-monospace, monospace;
  }
  :global(.sidebar-md strong) {
    font-weight: 600;
  }
</style>
