from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers import terraform, ai


def create_app(project_dir: str) -> FastAPI:
    app = FastAPI(title="inframate", version="0.1.0")
    app.state.project_dir = project_dir

    app.include_router(terraform.router)
    app.include_router(ai.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/project")
    def project_info():
        return {"project_dir": config.PROJECT_DIR}

    # Serve bundled UI (production)
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            file_path = static_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_dir / "index.html")

    return app
