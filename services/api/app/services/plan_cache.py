"""Cache terraform plan JSON per project directory."""

import json
import os
import time

# In-memory cache: tf_path -> {plan_data, timestamp, tf_path}
_cache: dict[str, dict] = {}

CACHE_DIR = ".inframate"
CACHE_FILE = os.path.join(CACHE_DIR, "plan-cache.json")


def _is_valid_plan(plan_data: dict) -> bool:
    """Check that cached plan data is non-empty and not an error."""
    if not plan_data:
        return False
    if plan_data.get("error"):
        return False
    # A valid plan should have at least one of these keys
    if not plan_data.get("resource_changes") and not plan_data.get("prior_state"):
        return False
    return True


def get_cached_plan(tf_path: str) -> dict | None:
    """Return cached plan if still fresh (no .tf files changed since cache)."""
    entry = _cache.get(tf_path)
    if not entry:
        cache_path = os.path.join(tf_path, CACHE_FILE)
        if os.path.isfile(cache_path):
            try:
                with open(cache_path) as f:
                    data = json.load(f)
                entry = {
                    "plan_data": data.get("plan_data", {}),
                    "timestamp": data.get("timestamp", 0),
                    "tf_path": tf_path,
                }
                _cache[tf_path] = entry
            except Exception:
                return None
        else:
            return None

    # Reject empty/failed cached plans
    if not _is_valid_plan(entry.get("plan_data", {})):
        _cache.pop(tf_path, None)
        return None

    # Invalidate if any .tf file is newer than the cache
    cache_ts = entry.get("timestamp", 0)
    try:
        for f in os.listdir(tf_path):
            if f.endswith((".tf", ".tfvars")) and os.path.isfile(os.path.join(tf_path, f)):
                if os.path.getmtime(os.path.join(tf_path, f)) > cache_ts:
                    _cache.pop(tf_path, None)
                    return None
    except OSError:
        pass

    return entry


def save_cached_plan(tf_path: str, plan_data: dict) -> dict:
    """Save plan to cache (memory + disk)."""
    entry = {
        "plan_data": plan_data,
        "timestamp": time.time(),
        "tf_path": tf_path,
    }
    _cache[tf_path] = entry

    cache_dir = os.path.join(tf_path, CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(tf_path, CACHE_FILE)
    try:
        with open(cache_path, "w") as f:
            json.dump({"plan_data": plan_data, "timestamp": entry["timestamp"]}, f)
    except Exception:
        pass

    return entry


def invalidate_cache(tf_path: str):
    """Clear cached plan (memory + disk)."""
    _cache.pop(tf_path, None)
    cache_path = os.path.join(tf_path, CACHE_FILE)
    if os.path.isfile(cache_path):
        try:
            os.remove(cache_path)
        except OSError:
            pass
