// Svelte action for modal dialogs: moves keyboard focus into the dialog on
// open, traps Tab within it, closes on Escape, and restores focus on close.
// Mirrors the TUI fix where popups must capture the keyboard instead of letting
// it act on the screen underneath.
//
// Usage: <div use:modal={{ onclose: () => (open = false) }}>...</div>
export function modal(node, params = {}) {
  let onclose = params.onclose;
  const prevFocus = document.activeElement;

  function focusable() {
    return [
      ...node.querySelectorAll(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
      ),
    ].filter((el) => el.offsetParent !== null);
  }

  function onkeydown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onclose?.();
      return;
    }
    if (e.key !== "Tab") return;
    const f = focusable();
    if (f.length === 0) {
      e.preventDefault();
      node.focus();
      return;
    }
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  if (!node.hasAttribute("tabindex")) node.setAttribute("tabindex", "-1");
  node.addEventListener("keydown", onkeydown);
  // Move focus into the dialog so the keyboard is captured by the popup.
  (focusable()[0] ?? node).focus();

  return {
    update(p) {
      onclose = p.onclose;
    },
    destroy() {
      node.removeEventListener("keydown", onkeydown);
      if (prevFocus instanceof HTMLElement) prevFocus.focus();
    },
  };
}
