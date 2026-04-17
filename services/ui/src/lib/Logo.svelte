<script>
  let { size = 36, className = "" } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 64 64"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
  class={className}
>
  <!-- Back layer - infrastructure block -->
  <rect
    x="14"
    y="8"
    width="36"
    height="36"
    rx="6"
    fill="oklch(0.65 0.18 250)"
    opacity="0.35"
  />
  <!-- Middle layer -->
  <rect
    x="8"
    y="16"
    width="36"
    height="36"
    rx="6"
    fill="oklch(0.65 0.18 250)"
    opacity="0.55"
  />
  <!-- Front layer -->
  <rect
    x="20"
    y="20"
    width="36"
    height="36"
    rx="6"
    fill="oklch(0.7 0.17 250)"
  />
  <!-- Grid lines on front layer -->
  <line x1="38" y1="22" x2="38" y2="54" stroke="oklch(0.85 0.1 250)" stroke-width="1" opacity="0.5" />
  <line x1="22" y1="38" x2="54" y2="38" stroke="oklch(0.85 0.1 250)" stroke-width="1" opacity="0.5" />
  <!-- Check mark / mate symbol -->
  <path
    d="M30 38 L36 44 L48 30"
    stroke="white"
    stroke-width="3.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    fill="none"
  />
</svg>
