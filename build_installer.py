import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PROJECT_DIR / "assets"
LOGO_SOURCE_JPG = ASSETS_DIR / "logo_full.jpg"
LOGO_PNG_PATH = ASSETS_DIR / "logo.png"
ICON_PATH = ASSETS_DIR / "icon.ico"
SPEC_PATH = PROJECT_DIR / "GilgaripsPrintOps.spec"
DIST_APP_DIR = PROJECT_DIR / "dist" / "GilgaripsPrintOps"


def _build_icon_from_source_jpg(source_jpg: Path) -> bool:
    """
    Uses .NET System.Drawing (included with pythonnet/pywebview on Windows)
    to crop the squircle badge from assets/logo_full.jpg, apply a rounded-corner
    transparency mask, save assets/logo.png (512x512), and pack a multi-resolution
    Windows icon at assets/icon.ico (256, 128, 64, 48, 32, 16).
    """
    try:
        import clr

        clr.AddReference("System.Drawing")
        from System.Drawing import (
            Bitmap,
            Graphics,
            Rectangle,
            GraphicsUnit,
        )
        from System.Drawing.Drawing2D import (
            GraphicsPath,
            InterpolationMode,
            SmoothingMode,
            PixelOffsetMode,
        )
        from System.Drawing.Imaging import ImageFormat, PixelFormat
        from System.IO import MemoryStream

        src_bmp = Bitmap(str(source_jpg))
        w, h = src_bmp.Width, src_bmp.Height
        # The squircle badge sits centered from ~132..892 on the 1024x1024 image
        crop_margin = int(round(w * 0.129))
        crop_size = w - (2 * crop_margin)
        src_rect = Rectangle(crop_margin, crop_margin, crop_size, crop_size)

        def render_resized_png_bytes(target_size: int) -> bytes:
            dst_bmp = Bitmap(target_size, target_size, PixelFormat.Format32bppArgb)
            g = Graphics.FromImage(dst_bmp)
            g.SmoothingMode = SmoothingMode.AntiAlias
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            g.PixelOffsetMode = PixelOffsetMode.HighQuality

            # Rounded squircle clip path (~22% corner radius)
            r = int(round(target_size * 0.22))
            d = r * 2
            path = GraphicsPath()
            path.AddArc(0, 0, d, d, 180, 90)
            path.AddArc(target_size - d, 0, d, d, 270, 90)
            path.AddArc(target_size - d, target_size - d, d, d, 0, 90)
            path.AddArc(0, target_size - d, d, d, 90, 90)
            path.CloseFigure()
            g.SetClip(path)

            dest_rect = Rectangle(0, 0, target_size, target_size)
            g.DrawImage(src_bmp, dest_rect, src_rect, GraphicsUnit.Pixel)
            g.Dispose()

            ms = MemoryStream()
            dst_bmp.Save(ms, ImageFormat.Png)
            png_bytes = bytes(ms.ToArray())
            ms.Dispose()
            dst_bmp.Dispose()
            return png_bytes

        # Save 512x512 high-DPI UI logo PNG
        LOGO_PNG_PATH.write_bytes(render_resized_png_bytes(512))

        # Pack multi-resolution Windows .ico (256, 128, 64, 48, 32, 16)
        sizes = [256, 128, 64, 48, 32, 16]
        images = [(sz, render_resized_png_bytes(sz)) for sz in sizes]
        src_bmp.Dispose()

        ico_header = struct.pack("<HHH", 0, 1, len(images))
        offset = 6 + (16 * len(images))
        dir_entries = []
        blobs = []

        for sz, png_bytes in images:
            w_byte = 0 if sz >= 256 else sz
            h_byte = 0 if sz >= 256 else sz
            entry = struct.pack(
                "<BBBBHHII",
                w_byte,
                h_byte,
                0,
                0,
                1,
                32,
                len(png_bytes),
                offset,
            )
            dir_entries.append(entry)
            blobs.append(png_bytes)
            offset += len(png_bytes)

        ICON_PATH.write_bytes(ico_header + b"".join(dir_entries) + b"".join(blobs))
        return True
    except Exception as exc:
        print(f"      [Notice] System.Drawing conversion fallback ({exc})")
        return False


def ensure_app_icon() -> Path:
    """Ensures assets/logo.png and assets/icon.ico exist using the custom Gilgarips crest logo."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if LOGO_SOURCE_JPG.exists():
        if _build_icon_from_source_jpg(LOGO_SOURCE_JPG):
            return ICON_PATH
    if ICON_PATH.exists():
        return ICON_PATH
    raise RuntimeError("Could not generate assets/icon.ico")


def get_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
    return base / "Programs" / "GilgaripsPrintOps"


def create_windows_shortcut(
    shortcut_path: Path,
    target_exe: Path,
    working_dir: Path,
    icon_path: Path,
    description: str,
) -> None:
    """Uses PowerShell WScript.Shell COM object to create a native Windows .lnk shortcut."""
    ps_script = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target_exe}'; "
        f"$s.WorkingDirectory = '{working_dir}'; "
        f"$s.IconLocation = '{icon_path},0'; "
        f"$s.Description = '{description}'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=True,
    )


def write_uninstaller(install_dir: Path, desktop_lnk: Path, startmenu_lnk: Path) -> None:
    uninstall_cmd = install_dir / "Uninstall Gilgarips PrintOps.cmd"
    content = (
        "@echo off\r\n"
        "echo Uninstalling Gilgarips PrintOps shortcuts and application binaries...\r\n"
        f'if exist "{desktop_lnk}" del /f /q "{desktop_lnk}"\r\n'
        f'if exist "{startmenu_lnk}" del /f /q "{startmenu_lnk}"\r\n'
        "echo Your catalog data and settings in Gilgarips_Catalog have been preserved.\r\n"
        f'start /b "" cmd /c rmdir /s /q "{install_dir}"\r\n'
    )
    uninstall_cmd.write_text(content, encoding="utf-8")


def main() -> None:
    skip_build = "--skip-build" in sys.argv
    print("============================================================")
    print("  Gilgarips PrintOps - Desktop App Builder & Installer")
    print("============================================================")

    print("[1/4] Generating custom Windows application icon & UI logo from assets/logo_full.jpg...")
    icon_path = ensure_app_icon()
    print(f"      Created: {icon_path} and {LOGO_PNG_PATH}")

    if not skip_build:
        print("[2/4] Building standalone Windows application with PyInstaller (--onedir, noconsole)...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                str(SPEC_PATH),
            ],
            cwd=str(PROJECT_DIR),
            check=True,
        )
    else:
        print("[2/4] Using existing PyInstaller build in dist/GilgaripsPrintOps...")

    built_exe = DIST_APP_DIR / "GilgaripsPrintOps.exe"
    if not built_exe.exists():
        raise RuntimeError(f"Expected built executable not found at {built_exe}")

    install_dir = get_install_dir()
    print(f"[3/4] Installing application to {install_dir}...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "GilgaripsPrintOps.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DIST_APP_DIR, install_dir, dirs_exist_ok=True)

    installed_exe = install_dir / "GilgaripsPrintOps.exe"
    installed_icon = install_dir / "gilgarips_crest.ico"
    shutil.copy2(icon_path, installed_icon)
    shutil.copy2(icon_path, install_dir / "icon.ico")

    print("[4/4] Creating Desktop and Windows Start Menu shortcuts...")
    try:
        real_desktop = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            text=True,
        ).strip()
        desktop_dir = Path(real_desktop) if real_desktop else Path(os.path.expanduser("~/Desktop"))
    except Exception:
        desktop_dir = Path(os.path.expanduser("~/Desktop"))
    desktop_lnk = desktop_dir / "Gilgarips PrintOps.lnk"

    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    start_menu_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    start_menu_lnk = start_menu_dir / "Gilgarips PrintOps.lnk"

    if desktop_dir.exists():
        create_windows_shortcut(
            shortcut_path=desktop_lnk,
            target_exe=installed_exe,
            working_dir=install_dir,
            icon_path=installed_icon,
            description="Gilgarips PrintOps - Production Cockpit & Cost Calculator",
        )
        print(f"      Desktop Shortcut:    {desktop_lnk}")

    if start_menu_dir.exists():
        create_windows_shortcut(
            shortcut_path=start_menu_lnk,
            target_exe=installed_exe,
            working_dir=install_dir,
            icon_path=installed_icon,
            description="Gilgarips PrintOps - Production Cockpit & Cost Calculator",
        )
        print(f"      Start Menu Shortcut: {start_menu_lnk}")

    write_uninstaller(install_dir, desktop_lnk, start_menu_lnk)

    print("\n[SUCCESS] Installation Complete!")
    print(f"   * Installed Executable: {installed_exe}")
    print(f"   * Start Menu & Desktop shortcuts updated with new crest logo.")


if __name__ == "__main__":
    main()
