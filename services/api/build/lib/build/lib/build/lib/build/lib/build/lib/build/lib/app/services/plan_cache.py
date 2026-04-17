"""Cache terraform plan JSON per project directory."""

import json
import os
import time

# In-memory cache: tf_path -> {plan_data, timestamp, tf_path}
_cache: dict[str, dict] = {}

CACHE_FILE = ".inframate-plan-cache.json"


def get_cached_plan(tf_path: str) -> dict | None:
    """Return cached plan if available."""
    entry = _cache.get(tf_path)
    if entry:
        return entry

    cache_path = os.path.join(tf_path, CACHE_FILE)
    if os.path.isfile(cache_path):
        try:
            with open(cache_path) as f:
                data = json.load(f)
            _cache[tf_path] = {
                "plan_data": data.get("plan_data", {}),
                "timestamp": data.get("timestamp", 0),
                "tf_path": tf_path,
            }
            return _cache[tf_path]
        except Exception:
            pass

    return None


def save_cached_plan(tf_path: str, plan_data: dict) -> dict:
    """Save plan to cache (memory + disk)."""
    entry = {
        "plan_data": plan_data,
        "timestamp": time.time(),
        "tf_path": tf_path,
    }
    _cache[tf_path] = entry

    cache_path = os.path.join(tf_path, CACHE_FILE)
    try:
        with open(cache_path, "w") as f:
            json.dump({"plan_data": plan_data, "timestamp": entry["timestamp"]}, f)
    except Exception:
        pass

    return entry


def invalidate_cache(tf_path: str):
    """Clear cached plan."""
    _cache.pop(tf_path, None)
