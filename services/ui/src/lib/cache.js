/**
 * Browser-side cache for resource data.
 * Uses both an in-memory cache (survives SPA navigation) and localStorage
 * (survives full page refresh). Heavy fields are stripped before persisting
 * to stay within the ~5 MB localStorage quota.
 */

const KEYS = {
  resources: "inframate:resources",
  totalCost: "inframate:totalCost",
};

// In-memory mirror — always works regardless of storage quota.
let _memResources = null;
let _memTotalCost = null;

function storageGet(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded — in-memory cache still works
  }
}

/** Strip heavy/redundant fields to shrink the payload for localStorage. */
function toLite(rows) {
  return rows.map(({ before, after, attributes, cloud_extra, ...rest }) => rest);
}

export function getCachedResources() {
  if (_memResources) return _memResources;
  return storageGet(KEYS.resources);
}

export function setCachedResources(rows) {
  _memResources = rows;
  storageSet(KEYS.resources, toLite(rows));
}

export function getCachedCosts() {
  const v = _memTotalCost ?? storageGet(KEYS.totalCost);
  return v != null ? { totalCost: v } : null;
}

export function setCachedCosts(totalCost) {
  _memTotalCost = totalCost;
  storageSet(KEYS.totalCost, totalCost);
}

export function clearCache() {
  _memResources = null;
  _memTotalCost = null;
  for (const key of Object.values(KEYS)) {
    localStorage.removeItem(key);
  }
}
