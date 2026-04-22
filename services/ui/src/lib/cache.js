/**
 * Browser-side cache for resource data using sessionStorage.
 * Avoids re-fetching terraform plan/cloud scan/costs on page refresh.
 * Data is cleared when the browser tab is closed (sessionStorage behavior).
 */

const KEYS = {
  resources: "inframate:resources",
  costs: "inframate:costs",
  totalCost: "inframate:totalCost",
};

function get(key) {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function set(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or unavailable — silently ignore
  }
}

export function getCachedResources() {
  return get(KEYS.resources);
}

export function setCachedResources(rows) {
  set(KEYS.resources, rows);
}

export function getCachedCosts() {
  const totalCost = get(KEYS.totalCost);
  return totalCost != null ? { totalCost } : null;
}

export function setCachedCosts(totalCost) {
  set(KEYS.totalCost, totalCost);
}

export function clearCache() {
  for (const key of Object.values(KEYS)) {
    sessionStorage.removeItem(key);
  }
}
