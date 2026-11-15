import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, Any

from backend.version import APP_VERSION, GITHUB_REPO

GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = "GilgaripsPrintOps-Updater"


def _get_updater_log_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
    log_dir = base / "GilgaripsPrintOps"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "updater.log"


def check_for_updates() -> Dict[str, Any]:
    """
    Checks GitHub Releases or local Git repository to determine if an update is available.
    """
    is_frozen = getattr(sys, "frozen", False)

    # 1. Check if running from a local git clone
    if not is_frozen:
        repo_root = Path(__file__).resolve().parent.parent
        git_dir = repo_root / ".git"
        if git_dir.exists():
            try:
                fetch_res = subprocess.run(
                    ["git", "fetch", "--quiet"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if fetch_res.returncode == 0:
                    status_res = subprocess.run(
                        ["git", "status", "-uno"],
                        cwd=str(repo_root),
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if "Your branch is behind" in status_res.stdout:
                        return {
                            "update_available": True,
                            "type": "git",
                            "current_version": APP_VERSION,
                            "latest_version": "latest-git-commit",
                            "message": "New commits available on origin/main. Click to pull updates automatically.",
                        }
            except Exception:
                pass

    # 2. Check GitHub Releases API
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").lstrip("v")
                body = data.get("body", "")
                html_url = data.get("html_url", "")

                if latest_tag and _is_newer_version(latest_tag, APP_VERSION):
                    assets = data.get("assets", [])
                    installer_asset = None
                    exe_asset = None
                    for asset in assets:
                        name = asset.get("name", "")
                        if "setup" in name.lower() and name.endswith(".exe"):
                            installer_asset = asset.get("browser_download_url")
                        elif name.endswith(".exe"):
                            exe_asset = asset.get("browser_download_url")

                    download_target = installer_asset or exe_asset
                    is_installer = bool(installer_asset)

                    return {
                        "update_available": True,
                        "type": "github_release",
                        "current_version": APP_VERSION,
                        "latest_version": latest_tag,
                        "release_notes": body,
                        "release_url": html_url,
                        "download_url": download_target or html_url,
                        "is_installer": is_installer,
                        "message": f"Version v{latest_tag} is available!",
                    }
    except Exception:
        pass

    return {
        "update_available": False,
        "type": "none",
        "current_version": APP_VERSION,
        "message": f"You are running the latest version (v{APP_VERSION}).",
    }


def _is_newer_version(latest: str, current: str) -> bool:
    try:
        def parse_parts(v: str):
            parts = []
            for p in v.split("."):
                nums = "".join(filter(str.isdigit, p))
                parts.append(int(nums) if nums else 0)
            return parts

        return parse_parts(latest) > parse_parts(current)
    except Exception:
        return latest != current


def _graceful_shutdown() -> None:
    """
    Waits briefly for the HTTP response to flush to the frontend,
    then closes any active pywebview windows cleanly before exiting.
    """
    time.sleep(0.45)
    try:
        import webview

        for win in list(webview.windows):
            try:
                win.destroy()
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.2)
    os._exit(0)


def apply_update() -> Dict[str, Any]:
    """
    Applies the update:
    - Git repo: runs `git pull --rebase` and notifies client to reload.
    - Packaged Windows app: downloads the latest Inno Setup installer (or exe),
      verifies the download, spawns a detached updater script that waits for
      clean exit, installs silently, and relaunches the updated app.
    """
    is_frozen = getattr(sys, "frozen", False)
    repo_root = Path(__file__).resolve().parent.parent

    # Case A: Git repository (development / source install)
    if not is_frozen and (repo_root / ".git").exists():
        try:
            pull_res = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if pull_res.returncode == 0:
                return {
                    "success": True,
                    "type": "git",
                    "output": pull_res.stdout.strip(),
                    "message": "Git pull completed successfully! Refreshing app window...",
                    "restart_required": True,
                }
            return {
                "success": False,
                "type": "git",
                "error": pull_res.stderr.strip() or pull_res.stdout.strip(),
            }
        except Exception as exc:
            return {"success": False, "type": "git", "error": str(exc)}

    # Case B: Packaged Windows application
    update_info = check_for_updates()
    download_url = update_info.get("download_url")
    is_installer = update_info.get("is_installer", False)
    if not download_url or not download_url.endswith(".exe"):
        return {
            "success": False,
            "type": "binary",
            "error": "No .exe installer asset attached to the latest release.",
            "release_url": update_info.get("release_url", f"https://github.com/{GITHUB_REPO}/releases"),
        }

    try:
        temp_dir = Path(tempfile.gettempdir())
        target_filename = (
            "GilgaripsPrintOps_Setup_Update.exe" if is_installer else "GilgaripsPrintOps_Update.exe"
        )
        new_exe_path = temp_dir / target_filename
        log_path = _get_updater_log_path()

        req = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp, open(new_exe_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)

        # Verify downloaded executable is non-empty and has valid Windows PE ('MZ') header
        file_size = new_exe_path.stat().st_size if new_exe_path.exists() else 0
        with open(new_exe_path, "rb") as f:
            magic = f.read(2)
        if file_size < 1_000_000 or magic != b"MZ":
            new_exe_path.unlink(missing_ok=True)
            return {
                "success": False,
                "type": "binary",
                "error": "Downloaded update file was incomplete or invalid. Please try again or download from GitHub Releases.",
                "release_url": update_info.get("release_url", f"https://github.com/{GITHUB_REPO}/releases"),
            }

        current_exe = Path(sys.executable).resolve()
        current_pid = os.getpid()
        exe_name = current_exe.name
        updater_bat = temp_dir / "printops_updater.bat"

        # Default installed executable path for Inno Setup per-user install
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        installed_exe = (
            Path(local_app_data) / "Programs" / "Gilgarips PrintOps" / "GilgaripsPrintOps.exe"
            if local_app_data
            else current_exe
        )

        if is_installer:
            relaunch_target = installed_exe if "programs" in str(current_exe).lower() else installed_exe
            bat_content = f"""@echo off
setlocal enabledelayedexpansion
echo [%date% %time%] Starting Gilgarips PrintOps update... > "{log_path}"

:: 1. Wait gracefully for the running app PID to exit (up to 8 seconds)
set WAIT_COUNT=0
:WAIT_EXIT
tasklist /FI "PID eq {current_pid}" 2>nul | find "{current_pid}" >nul
if errorlevel 1 goto RUN_INSTALLER
set /a WAIT_COUNT+=1
if !WAIT_COUNT! geq 8 (
    echo [%date% %time%] Graceful exit timed out, terminating process... >> "{log_path}"
    taskkill /F /T /PID {current_pid} >nul 2>&1
    taskkill /F /T /IM "{exe_name}" >nul 2>&1
    timeout /t 1 /nobreak >nul
    goto RUN_INSTALLER
)
timeout /t 1 /nobreak >nul
goto WAIT_EXIT

:RUN_INSTALLER
echo [%date% %time%] Running silent installer... >> "{log_path}"
start "" /wait "{new_exe_path}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS
set INSTALL_RC=!errorlevel!
echo [%date% %time%] Installer exited with code !INSTALL_RC! >> "{log_path}"

del /f /q "{new_exe_path}" >nul 2>&1

if exist "{relaunch_target}" (
    echo [%date% %time%] Relaunching "{relaunch_target}" >> "{log_path}"
    start "" "{relaunch_target}"
) else if exist "{current_exe}" (
    echo [%date% %time%] Relaunching "{current_exe}" >> "{log_path}"
    start "" "{current_exe}"
) else (
    echo [%date% %time%] ERROR: Could not locate executable to relaunch. >> "{log_path}"
)

del "%~f0"
exit /b !INSTALL_RC!
"""
        else:
            # Standalone binary swap fallback
            bat_content = f"""@echo off
setlocal enabledelayedexpansion
echo [%date% %time%] Starting standalone binary update... > "{log_path}"

set WAIT_COUNT=0
:WAIT_EXIT
tasklist /FI "PID eq {current_pid}" 2>nul | find "{current_pid}" >nul
if errorlevel 1 goto RETRY_COPY
set /a WAIT_COUNT+=1
if !WAIT_COUNT! geq 8 (
    taskkill /F /T /PID {current_pid} >nul 2>&1
    taskkill /F /T /IM "{exe_name}" >nul 2>&1
    timeout /t 1 /nobreak >nul
    goto RETRY_COPY
)
timeout /t 1 /nobreak >nul
goto WAIT_EXIT

set RETRIES=0
:RETRY_COPY
copy /y "{new_exe_path}" "{current_exe}" >nul 2>&1
if not errorlevel 1 goto LAUNCH
set /a RETRIES+=1
if !RETRIES! geq 20 goto FAILED
timeout /t 1 /nobreak >nul
goto RETRY_COPY

:LAUNCH
del /f /q "{new_exe_path}" >nul 2>&1
timeout /t 1 /nobreak >nul
start "" "{current_exe}"
del "%~f0"
exit /b 0

:FAILED
echo [%date% %time%] Update copy timed out. >> "{log_path}"
del "%~f0"
exit /b 1
"""

        updater_bat.write_text(bat_content, encoding="utf-8")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(
            ["cmd.exe", "/c", str(updater_bat)],
            creationflags=creation_flags,
            close_fds=True,
        )

        threading.Thread(target=_graceful_shutdown, daemon=True).start()

        return {
            "success": True,
            "type": "binary",
            "message": "Update downloaded. Installing and restarting Gilgarips PrintOps...",
            "restart_required": True,
        }
    except Exception as exc:
        return {"success": False, "type": "binary", "error": str(exc)}
