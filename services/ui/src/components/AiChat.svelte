<script>
  import { streamChat } from "../lib/api.js";

  // no props

  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);
  let messagesEl;

  function send() {
    if (!input.trim() || streaming) return;

    const userMsg = input.trim();
    messages = [...messages, { role: "user", text: userMsg }];
    input = "";
    streaming = true;

    let aiText = "";
    messages = [...messages, { role: "ai", text: "" }];

    streamChat(
      userMsg,
      "",
      (chunk) => {
        aiText += chunk;
        messages = [...messages.slice(0, -1), { role: "ai", text: aiText }];
        if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
      },
      () => {
        streaming = false;
      }
    );
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }
</script>

<div class="flex flex-col h-full">
  <div
    bind:this={messagesEl}
    class="flex-1 overflow-auto p-4 space-y-3"
  >
    {#if messages.length === 0}
      <div class="text-center py-8 text-base-content/50">
        <span class="icon-[tabler--sparkles] size-8 block mx-auto mb-2"></span>
        <p class="text-xs">Ask questions about your Terraform config, get help with errors, or request code suggestions.</p>
      </div>
    {/if}

    {#each messages as msg}
      <div class="chat {msg.role === 'user' ? 'chat-sender' : 'chat-receiver'}">
        <div class="chat-bubble text-xs {msg.role === 'user' ? 'bg-primary text-primary-content' : 'bg-base-200'}">
          <pre class="whitespace-pre-wrap font-sans">{msg.text}</pre>
          {#if msg.role === "ai" && streaming && msg === messages[messages.length - 1]}
            <span class="loading loading-dots loading-xs"></span>
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <div class="border-t border-base-content/10 p-3 bg-base-200">
    <div class="flex gap-2">
      <input
        type="text"
        class="input input-sm flex-1 text-xs"
        placeholder="Ask about your Terraform config..."
        bind:value={input}
        onkeydown={handleKeydown}
        disabled={streaming}
      />
      <button
        class="btn btn-primary btn-sm"
        onclick={send}
        disabled={!input.trim() || streaming}
        aria-label="Send message"
      >
        <span class="icon-[tabler--send] size-3.5"></span>
      </button>
    </div>
  </div>
</div>
