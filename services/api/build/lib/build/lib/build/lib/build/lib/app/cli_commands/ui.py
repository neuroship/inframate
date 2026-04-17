import webbrowser


def run_ui(project_dir: str, port: int, no_browser: bool):
    from app.main import create_app

    app = create_app(project_dir)

    url = f"http://localhost:{port}"
    print(f"inframate running at {url}  (project: {project_dir})")

    if not no_browser:
        webbrowser.open(url)

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
