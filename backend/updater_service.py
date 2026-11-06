import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional

APP_VERSION = "2.1.0"
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
                    # Look for executable asset if available
                    assets = data.get("assets", [])
                    exe_asset = None
                    for asset in assets:
                        if asset.get("name", "").endswith(".exe"):
                            exe_asset = asset.get("browser_download_url")
                            break

                    return {
                        "update_available": True,
                        "type": "github_release",
                        "current_version": APP_VERSION,
                        "latest_version": latest_tag,
                        "release_notes": body,
                        "release_url": html_url,
                        "download_url": exe_asset or html_url,
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

    # Case B: Standalone Windows .exe binary
    update_info = check_for_updates()
    download_url = update_info.get("download_url")
    if not download_url or not download_url.endswith(".exe"):
        return {
            "success": False,
            "type": "binary",
            "error": "No standalone .exe asset attached to the latest release.",
            "release_url": update_info.get("release_url", f"https://github.com/{GITHUB_REPO}/releases"),
        }

    try:
        temp_dir = Path(tempfile.gettempdir())
        new_exe_path = temp_dir / "GilgaripsPrintOps_Update.exe"
        
        req = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(new_exe_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)

        # Batch script to wait for current process exit, replace executable, and relaunch
        current_exe = Path(sys.executable).resolve()
        updater_bat = temp_dir / "printops_updater.bat"
        bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
copy /y "{new_exe_path}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
        updater_bat.write_text(bat_content, encoding="utf-8")
        subprocess.Popen(["cmd.exe", "/c", str(updater_bat)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        return {
            "success": True,
            "type": "binary",
            "message": "Update downloaded. The application is restarting with the latest release...",
            "restart_required": True,
        }
    except Exception as exc:
        return {"success": False, "type": "binary", "error": str(exc)}

