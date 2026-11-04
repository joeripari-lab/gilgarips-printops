import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _ensure_gui_streams() -> None:
    """
    When packaged with PyInstaller --noconsole on Windows, sys.stdout and sys.stderr are None,
    which causes uvicorn's logging formatter to fail when checking stream.isatty().
    Redirect None streams to a log file in %LOCALAPPDATA%/GilgaripsPrintOps/printops.log.
    """
    if sys.stdout is None or sys.stderr is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
        log_dir = base / "GilgaripsPrintOps"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "printops.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file


_ensure_gui_streams()

import uvicorn
from backend.main import app

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def find_available_port(host: str, preferred_port: int) -> int:
    """Returns preferred_port if free, otherwise binds an ephemeral free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, preferred_port))
            return preferred_port
        except OSError:
            s.bind((host, 0))
            return int(s.getsockname()[1])


def wait_for_server(host: str, port: int, timeout: float = 12.0) -> bool:
    """Polls until the FastAPI uvicorn server is listening on host:port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_uvicorn_server(host: str, port: int) -> None:
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gilgarips PrintOps Desktop Launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port for FastAPI")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open in system browser instead of native pywebview window",
    )
    args, _ = parser.parse_known_args()

    port = find_available_port(HOST, args.port)
    url = f"http://{HOST}:{port}"

    server_thread = threading.Thread(
        target=run_uvicorn_server,
        args=(HOST, port),
        daemon=True,
    )
    server_thread.start()

    if not wait_for_server(HOST, port):
        print(f"[Error] FastAPI server failed to start on {url}", file=sys.stderr)
        sys.exit(1)

    print(f"Gilgarips PrintOps backend listening at {url}")

    if not args.browser:
        try:
            import webview

            webview.create_window(
                title="Gilgarips PrintOps — Production Cockpit v2.1.0",
                url=url,
                width=1280,
                height=850,
                min_size=(980, 680),
                text_select=True,
            )
            webview.start()
            return
        except Exception as exc:
            print(
                f"[Notice] pywebview native window unavailable ({exc}); opening local browser view instead."
            )

    webbrowser.open(url)
    try:
        while server_thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
