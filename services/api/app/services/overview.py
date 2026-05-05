"""Shared overview logic used by both API routes and CLI commands."""

import logging
import re

logger = logging.getLogger(__name__)

# In-memory cache for unified overview (post-cloud-scan rows including unmanaged).
# Keyed by tf_path.
_unified_cache: dict[str, list[dict]] = {}


def get_cached_unified(tf_path: str) -> list[dict] | None:
    """Return cached unified overview rows (with unmanaged resources) if available."""
    return _unified_cache.get(tf_path)


def save_cached_unified(tf_path: str, rows: list[dict]):
    """Cache unified overview rows after cloud scan."""
    _unified_cache[tf_path] = rows


def clear_cached_unified(tf_path: str):
    """Clear cached unified overview."""
    _unified_cache.pop(tf_path, None)


from app.services.plan_cache import get_cached_plan, save_cached_plan
from app.services.terraform_cli import get_plan_json, get_graph_dot, get_state
from app.services.terraform_parser import (
    parse_dot_graph,
    get_resource_locations,
    _enrich_node,
    _extract_service,
    AWS_RESOURCES,
)
from app.services.unified import derive_status


# Resource block names that are generic module conventions and convey
# no useful identity on their own — fall back to the enclosing module name.
_GENERIC_RES_NAMES = {"this", "default", "main"}


def _friendly_resource_name(addr: str, res_name: str) -> str:
    """Replace generic block names like `this` with the enclosing module name.

    Many Terraform modules name their primary resource `this`, which makes the
    UI show duplicate `this[0]` rows when multiple module instances exist. Use
    the last `module.<name>` segment from the address to disambiguate.
    """
    if res_name not in _GENERIC_RES_NAMES:
        return res_name
    matches = re.findall(r"module\.([^.\[]+)", addr)
    if matches:
        return matches[-1]
    return res_name


def parse_plan_resources(plan_data: dict) -> dict:
    """Parse plan JSON into a lookup of address -> {action, attributes, before, after}."""
    plan_resources = {}
    if plan_data.get("error"):
        return plan_resources

    for rc in plan_data.get("resource_changes", []):
        addr = rc.get("address", "")
        actions = rc.get("change", {}).get("actions", [])
        if actions == ["no-op"] or actions == ["read"]:
            action = "no-op"
        elif actions == ["create"]:
            action = "create"
        elif actions == ["delete"]:
            action = "destroy"
        elif actions == ["update"]:
            action = "update"
        elif set(actions) == {"delete", "create"}:
            action = "replace"
        else:
            action = ",".join(actions) if actions else "unknown"

        after = rc.get("change", {}).get("after", {}) or {}
        before = rc.get("change", {}).get("before", {}) or {}
        attrs = after if after else before

        plan_resources[addr] = {
            "action": action,
            "attributes": attrs,
            "before": before,
            "after": after,
        }

    for res in (
        plan_data.get("prior_state", {})
        .get("values", {})
        .get("root_module", {})
        .get("resources", [])
    ):
        base_addr = f"{res.get('type')}.{res.get('name')}"
        index = res.get("index")
        if index is not None:
            if isinstance(index, str):
                addr = f'{base_addr}["{index}"]'
            else:
                addr = f"{base_addr}[{index}]"
        else:
            addr = base_addr
        if addr not in plan_resources:
            attrs = res.get("values", {})
            plan_resources[addr] = {
                "action": "no-op",
                "attributes": attrs,
                "before": attrs,
                "after": attrs,
            }

    return plan_resources


def build_overview_rows(
    graph: dict, plan_resources: dict, locations: dict | None = None
) -> list[dict]:
    locations = locations or {}
    indexed_lookup: dict[str, list[tuple[str, dict]]] = {}
    for addr, info in plan_resources.items():
        match = re.match(r"^(.+?)\[", addr)
        if match:
            base = match.group(1)
            indexed_lookup.setdefault(base, []).append((addr, info))

    verbose = logger.isEnabledFor(logging.DEBUG)
    rows = []
    matched = 0
    skipped_no_addr = 0
    unmatched = 0
    unmatched_ids = []
    for node in graph["nodes"]:
        res_type = node.get("resource_type", "")
        res_name = node.get("resource_name", "")
        # Use the full node id (which includes module prefix) for plan matching,
        # since plan keys are fully qualified (e.g. module.foo.aws_instance.bar)
        base_addr = node.get("id", "") if res_type and res_name else ""

        if not base_addr:
            skipped_no_addr += 1
            if verbose and len(unmatched_ids) < 5:
                unmatched_ids.append(
                    f"  no resource_type/name: id={node.get('id', '?')}, type={node.get('type', '?')}"
                )
            continue

        loc = locations.get(base_addr)

        plan_info = plan_resources.get(base_addr)
        if plan_info is not None:
            friendly = _friendly_resource_name(base_addr, res_name)
            rows.append(
                _make_row(node, base_addr, res_type, friendly, plan_info, location=loc)
            )
            matched += 1
            continue

        instances = indexed_lookup.get(base_addr, [])
        if instances:
            for full_addr, inst_info in instances:
                idx_match = re.search(r'\["?([^"\]]+)"?\]$', full_addr)
                idx_label = idx_match.group(1) if idx_match else full_addr
                friendly = _friendly_resource_name(full_addr, res_name)
                display_name = f"{friendly}[{idx_label}]"
                rows.append(
                    _make_row(
                        node,
                        full_addr,
                        res_type,
                        display_name,
                        inst_info,
                        instance_key=idx_label,
                        location=loc,
                    )
                )
            matched += 1
            continue

        unmatched += 1

    if verbose:
        plan_sample = list(plan_resources.keys())[:5]
        logger.debug(
            "build_overview_rows: graph_nodes=%d, plan_keys=%d, matched=%d, "
            "skipped_no_addr=%d, unmatched=%d",
            len(graph["nodes"]),
            len(plan_resources),
            matched,
            skipped_no_addr,
            unmatched,
        )
        if skipped_no_addr:
            logger.debug(
                "  skipped nodes lack resource_type/resource_name (likely module nodes parsed as opaque):"
            )
            for line in unmatched_ids:
                logger.debug(line)
        if plan_sample:
            logger.debug("  sample plan_resources keys: %s", plan_sample)

    if not rows and (skipped_no_addr or unmatched):
        logger.warning(
            "build_overview_rows produced 0 rows: %d graph nodes skipped "
            "(no resource_type/name — likely module-prefixed resources), "
            "%d unmatched. Plan has %d keys. Use --verbose for details.",
            skipped_no_addr,
            unmatched,
            len(plan_resources),
        )

    deps = {}
    for e in graph["edges"]:
        deps.setdefault(e["target"], []).append(e["source"])
    for row in rows:
        row["depends_on"] = deps.get(row["id"], [])

    return rows


def _make_row(
    node, addr, res_type, res_name, plan_info, instance_key=None, location=None
):
    attrs = plan_info.get("attributes", {})
    action = plan_info.get("action", "no-op")

    in_code = action != "destroy"
    in_state = action != "create"

    row = {
        "id": addr,
        "label": node.get("label", node["id"]),
        "source": "terraform",
        "display_type": node.get("display_type", res_type),
        "service": node.get("service", ""),
        "category": node.get("category", "resource"),
        "resource_type": res_type,
        "resource_name": res_name,
        "instance_key": instance_key,
        "in_code": in_code,
        "in_state": in_state,
        "in_cloud": None,
        "status": derive_status(in_code, in_state, None, action),
        "action": action,
        "attributes": attrs,
        "before": plan_info.get("before", {}),
        "after": plan_info.get("after", {}),
        "arn": attrs.get("arn", ""),
        "tags": attrs.get("tags", {}),
    }
    if location:
        row["tf_file"] = location.get("file", "")
        row["tf_line"] = location.get("line", 0)
    return row


class OverviewResult:
    """Result of compute_overview with diagnostic info."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.graph_nodes = 0
        self.plan_resources = 0
        self.plan_error: str | None = None
        self.plan_raw_output: str = ""
        self.source = "plan"  # "plan" or "state"
        self.warnings: list[str] = []

    # Make it behave like a list for backward compat
    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, idx):
        return self.rows[idx]

    def __bool__(self):
        return bool(self.rows)


async def compute_overview(tf_path: str, var_file: str | None = None) -> OverviewResult:
    """Compute overview rows for a terraform project directory.

    Tries graph + plan first. Falls back to state if both fail.
    Returns OverviewResult with rows and diagnostic info.
    """
    result = OverviewResult([])

    dot = await get_graph_dot(tf_path)
    graph = parse_dot_graph(dot)
    result.graph_nodes = len(graph["nodes"])

    if not graph["nodes"]:
        result.warnings.append("terraform graph returned 0 nodes")

    cached = get_cached_plan(tf_path)
    if cached and not cached["plan_data"].get("error"):
        plan_data = cached["plan_data"]
    else:
        plan_data = await get_plan_json(tf_path, var_file=var_file)
        # Only cache successful plans
        if not plan_data.get("error"):
            save_cached_plan(tf_path, plan_data)

    if plan_data.get("error"):
        result.plan_error = plan_data["error"]
        result.warnings.append(plan_data["error"])

    plan_resources = parse_plan_resources(plan_data)
    result.plan_resources = len(plan_resources)
    locations = get_resource_locations(tf_path)
    rows = build_overview_rows(graph, plan_resources, locations)

    # Fallback: if graph+plan produced nothing, try reading state directly
    if not rows:
        rows = await _rows_from_state(tf_path, locations)
        if rows:
            result.source = "state"
            result.warnings.append(f"using state fallback ({len(rows)} resources)")

    result.rows = rows
    return result


async def _rows_from_state(tf_path: str, locations: dict | None = None) -> list[dict]:
    """Build rows from terraform state when graph/plan are unavailable."""
    state = await get_state(tf_path)
    if not state:
        return []

    locations = locations or {}
    rows = []

    def _walk_module(mod: dict, module_prefix: str = ""):
        for res in mod.get("resources", []):
            if res.get("mode") == "data":
                continue
            res_type = res.get("type", "")
            res_name = res.get("name", "")
            addr = f"{module_prefix}{res_type}.{res_name}" if res_type else ""
            if not addr:
                continue

            attrs = res.get("values", {})
            loc = locations.get(addr)
            friendly_name = _friendly_resource_name(addr, res_name)

            aws_info = AWS_RESOURCES.get(res_type)
            display_type = aws_info[0] if aws_info else res_type
            category = aws_info[1] if aws_info else "resource"
            service = _extract_service(res_type)

            row = {
                "id": addr,
                "label": f"{display_type}: {friendly_name}",
                "source": "terraform",
                "display_type": display_type,
                "service": service,
                "category": category,
                "resource_type": res_type,
                "resource_name": friendly_name,
                "instance_key": None,
                "in_code": True,
                "in_state": True,
                "in_cloud": None,
                "status": derive_status(True, True, None, "no-op"),
                "action": "no-op",
                "attributes": attrs,
                "arn": attrs.get("arn", ""),
                "tags": attrs.get("tags", {}),
                "depends_on": [],
            }
            if loc:
                row["tf_file"] = loc.get("file", "")
                row["tf_line"] = loc.get("line", 0)
            rows.append(row)

        # Recurse into child modules
        for child in mod.get("child_modules", []):
            child_prefix = child.get("address", "")
            if child_prefix:
                child_prefix += "."
            _walk_module(child, child_prefix)

    root = state.get("values", {}).get("root_module", {})
    _walk_module(root)
    return rows
