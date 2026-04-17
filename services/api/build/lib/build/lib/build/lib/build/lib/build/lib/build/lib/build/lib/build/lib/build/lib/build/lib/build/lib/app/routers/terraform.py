import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import TerraformCommand, FileContent
from app.services.terraform_cli import (
    stream_terraform,
    stream_plan_with_output,
    get_state,
    get_graph_dot,
    get_providers,
)
from app.services.terraform_parser import (
    list_tf_files,
    read_file,
    write_file,
    list_tfvars,
    parse_tf_files,
    extract_resources_from_state,
    parse_dot_graph,
)
from app.services.overview import compute_overview, parse_plan_resources, build_overview_rows

router = APIRouter(prefix="/api/terraform", tags=["terraform"])


def _tf_path(request: Request) -> str:
    p = request.app.state.project_dir
    if not os.path.isdir(p):
        raise HTTPException(400, f"Project directory does not exist: {p}")
    return p


def _aws_region() -> str:
    return os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"


# --- Terraform commands (SSE streaming) ---


async def _sse_stream(workspace_path: str, args: list[str], var_file: str | None):
    async for line in stream_terraform(workspace_path, args, var_file):
        yield f"data: {line}\n\n"
    yield "data: [DONE]\n\n"


def _init_args(cmd: TerraformCommand | None) -> list[str]:
    return ["init"] + (cmd.args if cmd else [])


@router.post("/init")
async def terraform_init(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    return StreamingResponse(_sse_stream(tf, _init_args(cmd), None), media_type="text/event-stream")


@router.post("/plan")
async def terraform_plan(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    args = ["plan"] + (cmd.args if cmd else [])
    return StreamingResponse(_sse_stream(tf, args, cmd.var_file if cmd else None), media_type="text/event-stream")


@router.post("/apply")
async def terraform_apply(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    args = ["apply"] + (cmd.args if cmd else [])
    return StreamingResponse(_sse_stream(tf, args, cmd.var_file if cmd else None), media_type="text/event-stream")


@router.post("/destroy")
async def terraform_destroy(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    args = ["destroy"] + (cmd.args if cmd else [])
    return StreamingResponse(_sse_stream(tf, args, cmd.var_file if cmd else None), media_type="text/event-stream")


@router.post("/fmt")
async def terraform_fmt(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    args = ["fmt"] + (cmd.args if cmd else [])
    return StreamingResponse(_sse_stream(tf, args, None), media_type="text/event-stream")


@router.post("/validate")
async def terraform_validate(request: Request, cmd: TerraformCommand | None = None):
    tf = _tf_path(request)
    args = ["validate"] + (cmd.args if cmd else [])
    return StreamingResponse(_sse_stream(tf, args, None), media_type="text/event-stream")


@router.post("/taint")
async def terraform_taint(request: Request, body: dict):
    tf = _tf_path(request)
    addresses = body.get("addresses", [])
    if not addresses:
        raise HTTPException(400, "addresses list is required")

    async def event_stream():
        for addr in addresses:
            async for line in stream_terraform(tf, ["taint", addr]):
                yield f"data: {line}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/import")
async def terraform_import(request: Request, body: dict):
    tf = _tf_path(request)
    address = body.get("address", "")
    resource_id = body.get("id", "")
    if not address or not resource_id:
        raise HTTPException(400, "address and id are required")
    return StreamingResponse(_sse_stream(tf, ["import", address, resource_id], None), media_type="text/event-stream")


# --- Plan JSON ---


@router.get("/plan-json")
async def get_plan_json_route(request: Request, var_file: str | None = None):
    return await get_plan_json(_tf_path(request), var_file)


# --- State & Resources ---


@router.get("/state")
async def get_state_route(request: Request):
    state = await get_state(_tf_path(request))
    if state is None:
        return {"resources": [], "empty": True}
    return state


@router.get("/resources")
async def get_resources(request: Request):
    state = await get_state(_tf_path(request))
    if not state:
        return []
    return extract_resources_from_state(state.get("values", {}).get("root_module", {}))


# --- Graph ---


@router.get("/graph")
async def get_graph(request: Request):
    dot = await get_graph_dot(_tf_path(request))
    return parse_dot_graph(dot)


# --- Overview (combined graph + state for table view) ---


@router.get("/overview")
async def get_overview(request: Request):
    return await compute_overview(_tf_path(request))


@router.get("/overview-stream")
async def get_overview_stream(request: Request):
    import json as _json

    tf_path = _tf_path(request)

    async def event_stream():
        yield f"data: {_json.dumps({'type': 'phase', 'message': 'Reading terraform graph...'})}\n\n"
        dot = await get_graph_dot(tf_path)
        graph = parse_dot_graph(dot)
        node_count = len(graph["nodes"])
        yield f"data: {_json.dumps({'type': 'phase', 'message': f'Found {node_count} resources. Running terraform plan...'})}\n\n"

        import asyncio as _asyncio
        plan_lines_queue = _asyncio.Queue()
        plan_result = {}

        async def on_plan_line(text):
            await plan_lines_queue.put(text)

        async def run_plan():
            result = await stream_plan_with_output(tf_path, on_line=on_plan_line)
            plan_result["data"] = result
            await plan_lines_queue.put(None)

        plan_task = _asyncio.create_task(run_plan())

        while True:
            line = await plan_lines_queue.get()
            if line is None:
                break
            yield f"data: {_json.dumps({'type': 'log', 'message': line})}\n\n"

        await plan_task
        plan_data = plan_result.get("data", {"error": "Plan failed"})

        from app.services.plan_cache import save_cached_plan
        cache_entry = save_cached_plan(tf_path, plan_data)

        yield f"data: {_json.dumps({'type': 'phase', 'message': 'Processing plan output...'})}\n\n"

        from app.services.terraform_parser import get_resource_locations
        plan_resources = parse_plan_resources(plan_data)
        locations = get_resource_locations(tf_path)
        rows = build_overview_rows(graph, plan_resources, locations)

        yield f"data: {_json.dumps({'type': 'result', 'data': rows, 'plan_timestamp': cache_entry['timestamp']})}\n\n"
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/cloud-scan")
async def cloud_scan(request: Request):
    import json
    from app.services.aws_inventory import scan_all
    from app.services.unified import merge_with_cloud

    tf_path = _tf_path(request)
    region = _aws_region()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'phase', 'message': 'Loading terraform state...'})}\n\n"
        overview_rows = await compute_overview(tf_path)

        yield f"data: {json.dumps({'type': 'phase', 'message': 'Scanning cloud resources...'})}\n\n"

        import asyncio
        loop = asyncio.get_event_loop()
        progress_queue = asyncio.Queue()

        def on_progress(done, total, label):
            loop.call_soon_threadsafe(progress_queue.put_nowait, (done, total, label))

        scan_task = asyncio.create_task(scan_all({}, region, on_progress=on_progress))
        while not scan_task.done():
            try:
                done, total, label = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                yield f"data: {json.dumps({'type': 'scan_progress', 'done': done, 'total': total, 'label': label})}\n\n"
            except asyncio.TimeoutError:
                continue
        aws_resources = scan_task.result()
        while not progress_queue.empty():
            done, total, label = progress_queue.get_nowait()
            yield f"data: {json.dumps({'type': 'scan_progress', 'done': done, 'total': total, 'label': label})}\n\n"

        yield f"data: {json.dumps({'type': 'phase', 'message': 'Matching resources...'})}\n\n"
        unified = merge_with_cloud(overview_rows, aws_resources, region)

        yield f"data: {json.dumps({'type': 'result', 'data': unified})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/aws-delete-check")
async def aws_delete_check(body: dict):
    from app.services.aws_delete import get_delete_preconditions
    resources = body.get("resources", [])
    return get_delete_preconditions(resources)


@router.post("/aws-delete")
async def aws_delete_resources(request: Request, body: dict):
    import json
    import aioboto3
    from app.services.aws_delete import delete_resource

    resources = body.get("resources", [])
    if not resources:
        raise HTTPException(400, "No resources specified")

    region = _aws_region()

    async def event_stream():
        session = aioboto3.Session(region_name=region)
        total = len(resources)
        ok_count = 0
        fail_count = 0

        for i, res in enumerate(resources):
            name = res.get("name", res.get("type", "unknown"))
            yield f"data: Deleting {name} ({res.get('type', '')})...\n\n"

            progress_lines = []

            async def on_progress(msg):
                progress_lines.append(msg)

            result = await delete_resource(session, region, res, on_progress)

            for line in progress_lines:
                yield f"data: {line}\n\n"

            if result["ok"]:
                ok_count += 1
                yield f"data: {result['message']}\n\n"
            else:
                fail_count += 1
                yield f"data: {result['message']}\n\n"

        summary = f"\nDone: {ok_count}/{total} deleted"
        if fail_count:
            summary += f", {fail_count} failed"
        yield f"data: {summary}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/costs")
async def get_costs(request: Request, days: int = 30):
    from app.services.aws_costs import get_costs_by_resource, get_costs_by_service, match_costs_to_resources

    region = _aws_region()
    rows = await get_overview(request)

    resource_costs, service_costs = await asyncio.gather(
        get_costs_by_resource({}, region, [], days),
        get_costs_by_service({}, days),
    )

    if "_error" in resource_costs:
        return {
            "resources": rows,
            "service_costs": service_costs,
            "error": resource_costs["_error"],
        }

    enriched = match_costs_to_resources(resource_costs, service_costs, rows)
    total = sum(r.get("cost_monthly") or 0 for r in enriched)

    return {
        "resources": enriched,
        "service_costs": {k: v for k, v in service_costs.items() if not k.startswith("_")},
        "total_monthly": round(total, 2),
        "currency": "USD",
        "days": days,
    }


# --- Files ---


@router.get("/files")
def list_files(request: Request):
    return list_tf_files(_tf_path(request))


@router.get("/files/{filename:path}")
def get_file(filename: str, request: Request):
    content = read_file(_tf_path(request), filename)
    if content is None:
        raise HTTPException(404, "File not found")
    return {"filename": filename, "content": content}


@router.put("/files/{filename:path}")
def update_file(filename: str, body: FileContent, request: Request):
    if not write_file(_tf_path(request), filename, body.content):
        raise HTTPException(400, "Could not write file")
    return {"ok": True}


# --- Vars ---


@router.get("/vars")
def get_vars(request: Request):
    return list_tfvars(_tf_path(request))


# --- Parsed config ---


@router.get("/parsed")
def get_parsed(request: Request):
    return parse_tf_files(_tf_path(request))


# --- Providers ---


@router.get("/providers")
async def get_providers_route(request: Request):
    output = await get_providers(_tf_path(request))
    return {"output": output}
