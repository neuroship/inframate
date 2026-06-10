import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import config
from app.services import wiz_service

router = APIRouter(prefix="/api/wiz", tags=["wiz"])


def _tf_path(request: Request) -> str:
    p = request.app.state.project_dir
    if not os.path.isdir(p):
        raise HTTPException(400, f"Project directory does not exist: {p}")
    return p


@router.get("/status")
def wiz_status():
    cfg = config.get_wiz_config()
    return {
        "installed": wiz_service.wiz_available(),
        "configured": bool(cfg["client_id"] and cfg["client_secret"]),
    }


@router.get("/scan")
async def wiz_scan(request: Request):
    """Run a Wiz IaC scan, streaming progress via SSE; the final 'result'
    event carries issues mapped to resources by address."""
    import json

    from app.routers.terraform import get_overview
    from app.services.overview import get_cached_unified

    cfg = config.get_wiz_config()
    path = _tf_path(request)

    def _error_result(message: str) -> dict:
        return {
            "type": "result",
            "data": {
                "installed": wiz_service.wiz_available(),
                "error": message,
                "findings": {},
            },
        }

    async def event_stream():
        if not cfg["client_id"] or not cfg["client_secret"]:
            yield f"data: {json.dumps(_error_result('Wiz credentials not set. Add wiz.client_id / wiz.client_secret to config.'))}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'phase', 'message': 'Loading resource list...'})}\n\n"
        cached_unified = get_cached_unified(path)
        rows = (
            list(cached_unified)
            if cached_unified
            else list(await get_overview(request))
        )

        try:
            async for event in wiz_service.run_scan_events(
                path, cfg["client_id"], cfg["client_secret"], rows
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # noqa: BLE001 - surface any wizcli failure to the UI
            yield f"data: {json.dumps(_error_result(str(e)[:500]))}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
