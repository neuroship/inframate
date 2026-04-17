<script>
  let { open = $bindable(false), title = "Confirm", message = "", confirmLabel = "Confirm", variant = "error", ...rest } = $props();

  function handleConfirm() {
    const cb = rest.onconfirm;
    open = false;
    if (cb) cb();
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onclick={() => (open = false)}>
    <div class="card bg-base-100 w-96 shadow-xl" onclick={(e) => e.stopPropagation()}>
      <div class="card-body p-5 gap-3">
        <h3 class="text-sm font-medium flex items-center gap-2">
          <span class="icon-[tabler--alert-triangle] size-4 text-{variant}"></span>
          {title}
        </h3>
        <p class="text-xs text-base-content/60 whitespace-pre-line">{message}</p>
        <div class="flex justify-end gap-2 mt-1">
          <button class="btn btn-soft btn-sm" onclick={() => (open = false)}>Cancel</button>
          <button class="btn btn-{variant} btn-sm" onclick={handleConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  </div>
{/if}
