import os

from fastapi import APIRouter, HTTPException, Request

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
    """Run a Wiz IaC scan and return issues mapped to resources by address."""
    from app.routers.terraform import get_overview
    from app.services.overview import get_cached_unified

    cfg = config.get_wiz_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        return {
            "installed": wiz_service.wiz_available(),
            "error": "Wiz credentials not set. Add wiz.client_id / wiz.client_secret to config.",
            "findings": {},
        }

    path = _tf_path(request)
    cached_unified = get_cached_unified(path)
    rows = list(cached_unified) if cached_unified else list(await get_overview(request))

    try:
        return await wiz_service.run_scan(
            path, cfg["client_id"], cfg["client_secret"], rows
        )
    except Exception as e:  # noqa: BLE001 - surface any wizcli failure to the UI
        return {
            "installed": wiz_service.wiz_available(),
            "error": str(e)[:500],
            "findings": {},
        }
