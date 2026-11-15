import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional

APP_VERSION = "2.3.1"
GITHUB_REPO = "joeripari-lab/gilgarips-printops"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = "GilgaripsPrintOps-Updater"


def check_for_updates() -> Dict[str, Any]:
    """
    Checks GitHub Releases or local Git repository to determine if an update is available.
    """
    is_frozen = getattr(sys, "frozen", False)
    
    # 1. First check if running from a git clone
    if not is_frozen:
        repo_root = Path(__file__).resolve().parent.parent
        git_dir = repo_root / ".git"
        if git_dir.exists():
            try:
                # Fetch remote updates quietly
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
                    out = status_res.stdout
                    behind = "Your branch is behind" in out
                    if behind:
                        return {
                            "update_available": True,
                            "type": "git",
                            "current_version": APP_VERSION,
                            "latest_version": "latest-git-commit",
                            "message": "New commits available on origin/main. Click 'Update Now' to git pull automatically.",
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
                
                # Compare semantic versions (e.g., 2.1.0 vs 2.2.0)
                if latest_tag and _is_newer_version(latest_tag, APP_VERSION):
                    # Look for installer first (GilgaripsPrintOps-Setup.exe), fallback to standalone .exe
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
    except Exception as exc:
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


def apply_update() -> Dict[str, Any]:
    """
    Applies the update:
    - If running in Git repo: executes `git pull --rebase` and notifies the client to reload.
    - If running packaged Windows .exe: downloads latest release asset and swaps or runs it.
    """
    is_frozen = getattr(sys, "frozen", False)
    repo_root = Path(__file__).resolve().parent.parent

    # Case A: Git repository (development or source install)
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
            else:
                return {
                    "success": False,
                    "type": "git",
                    "error": pull_res.stderr.strip() or pull_res.stdout.strip(),
                }
        except Exception as exc:
            return {"success": False, "type": "git", "error": str(exc)}

    # Case B: Windows application (Installer or standalone .exe)
    update_info = check_for_updates()
    download_url = update_info.get("download_url")
    is_installer = update_info.get("is_installer", False)
    if not download_url or not download_url.endswith(".exe"):
        return {
            "success": False,
            "type": "binary",
            "error": "No .exe asset attached to the latest release.",
            "release_url": update_info.get("release_url", f"https://github.com/{GITHUB_REPO}/releases"),
        }

    try:
        temp_dir = Path(tempfile.gettempdir())
        target_filename = "GilgaripsPrintOps_Setup_Update.exe" if is_installer else "GilgaripsPrintOps_Update.exe"
        new_exe_path = temp_dir / target_filename
        
        req = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=90) as resp, open(new_exe_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)

        # Batch script to wait for current process exit, replace or run installer, and restart
        current_exe = Path(sys.executable).resolve()
        current_pid = os.getpid()
        exe_name = current_exe.name
        updater_bat = temp_dir / "printops_updater.bat"

        if is_installer:
            # When an Inno Setup installer is available:
            # Run the installer silently (/SILENT /NORESTART /CLOSEAPPLICATIONS) which cleanly installs
            # into %LOCALAPPDATA%\Programs\Gilgarips PrintOps and launches the updated app.
            bat_content = f"""@echo off
setlocal enabledelayedexpansion

:: 1. Force kill current running instance so installer can update binaries cleanly
taskkill /F /T /IM "{exe_name}" >nul 2>&1
taskkill /F /T /PID {current_pid} >nul 2>&1
timeout /t 2 /nobreak >nul

:: 2. Execute the Inno Setup installer silently
start "" /wait "{new_exe_path}" /SILENT /NORESTART /CLOSEAPPLICATIONS

:: 3. Clean up the installer download and script
del /f /q "{new_exe_path}" >nul 2>&1
del "%~f0"
exit /b 0
"""
        else:
            # Standalone binary swap fallback
            bat_content = f"""@echo off
setlocal enabledelayedexpansion

:: 1. Force kill all running instances of this executable tree
taskkill /F /T /IM "{exe_name}" >nul 2>&1
taskkill /F /T /PID {current_pid} >nul 2>&1
timeout /t 2 /nobreak >nul

:: 2. Wait for current exe file lock release (up to 20 seconds)
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
echo Update copy timed out. >> "{temp_dir}\\printops_update_err.log"
del "%~f0"
exit /b 1
"""
        updater_bat.write_text(bat_content, encoding="utf-8")
        subprocess.Popen(
            ["cmd.exe", "/c", str(updater_bat)],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            close_fds=True,
        )

        def _delayed_exit():
            import time
            time.sleep(0.5)
            try:
                os._exit(0)
            except Exception:
                pass

        threading.Thread(target=_delayed_exit, daemon=True).start()

        return {
            "success": True,
            "type": "binary",
            "message": "Update downloaded. The application is installing the latest version and restarting...",
            "restart_required": True,
        }
    except Exception as exc:
        return {"success": False, "type": "binary", "error": str(exc)}

