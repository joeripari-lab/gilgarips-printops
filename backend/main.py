import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from backend.file_manager import FileManager, slugify_item_name
from backend.gemini_service import generate_gemini_listing_pack
from backend.packaging import solve_3d_box_fit
from backend.slicer_engine import analyze_slicer_upload, analyze_multiple_slicer_uploads
from backend.etsy_service import fetch_etsy_listing_images, download_image_bytes
from backend.updater_service import check_for_updates, apply_update


def _resolve_frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and (Path(meipass) / "frontend").exists():
            return Path(meipass) / "frontend"
        exe_parent = Path(sys.executable).resolve().parent
        if (exe_parent / "frontend").exists():
            return exe_parent / "frontend"
    return Path(__file__).resolve().parent.parent / "frontend"


def _resolve_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and (Path(meipass) / "assets").exists():
            return Path(meipass) / "assets"
        exe_parent = Path(sys.executable).resolve().parent
        if (exe_parent / "assets").exists():
            return exe_parent / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


app = FastAPI(
    title="Gilgarips PrintOps Desktop API",
    version="2.2.2",
    description="Local print-farm pricing, 3D slicer & spatial box solver, local Google Drive sync, and Gemini listing engine.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

file_manager = FileManager()
FRONTEND_DIR = _resolve_frontend_dir()
ASSETS_DIR = _resolve_assets_dir()


class SaveItemRequest(BaseModel):
    item: Dict[str, Any]
    index: int = -1
    staged_gcode_filename: Optional[str] = None
    staged_gcode_filenames: Optional[List[str]] = None


class EtsyFetchRequest(BaseModel):
    url: Optional[str] = None
    raw_html: Optional[str] = None


class EtsyIngestRequest(BaseModel):
    slug: str
    image_urls: List[str]


class CatalogSyncRequest(BaseModel):
    catalog: List[Dict[str, Any]]
    uploadedMonths: Optional[Dict[str, bool]] = None


class MonthsUpdateRequest(BaseModel):
    uploadedMonths: Dict[str, bool]


class BoxFitRequest(BaseModel):
    x_in: float
    y_in: float
    z_in: float
    padding_in: float = 2.0


class ListingGenerateRequest(BaseModel):
    item: Dict[str, Any]
    force_static: bool = False


class OpenFolderRequest(BaseModel):
    slug: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html not found")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/assets/{filename}")
async def serve_asset(filename: str):
    safe_filename = Path(filename).name
    asset_path = ASSETS_DIR / safe_filename
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(asset_path)


@app.get("/media/products/{slug}/photos/{filename}")
async def serve_product_photo(slug: str, filename: str):
    """
    Serves product thumbnails & photos dynamically from the active Master Storage Directory:
    <root>/products/<slug>/photos/<filename>
    """
    clean_slug = slugify_item_name(slug)
    safe_filename = Path(filename).name
    photo_path = file_manager.products_dir / clean_slug / "photos" / safe_filename
    if not photo_path.exists() or not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(photo_path)


@app.get("/api/state")
async def get_full_state():
    """Returns catalog_state.json and settings.json in a single initialization payload."""
    catalog_state = file_manager.get_catalog_state()
    settings = file_manager.get_settings()
    return {
        "catalog": catalog_state["catalog"],
        "uploadedMonths": catalog_state["uploadedMonths"],
        "settings": settings,
    }


@app.post("/api/catalog")
async def save_catalog(req: CatalogSyncRequest):
    """Persists full catalog array and uploadedMonths to <root>/catalog_state.json and scaffolds product folders."""
    current_state = file_manager.get_catalog_state()
    months = req.uploadedMonths if req.uploadedMonths is not None else current_state["uploadedMonths"]
    saved = file_manager.save_catalog_state(
        {
            "catalog": req.catalog,
            "uploadedMonths": months,
        }
    )
    return saved


@app.post("/api/items")
async def save_single_item(req: SaveItemRequest):
    """
    Creates or updates a single item, scaffolds <root>/products/<item-slug>/{meta.json, gcode/, photos/},
    and persists <root>/catalog_state.json.
    """
    state = file_manager.get_catalog_state()
    catalog = state["catalog"]
    item = req.item

    # Consolidate staged gcode filenames if multiple provided
    if req.staged_gcode_filenames:
        existing_staged = item.setdefault("stagedGcodeFiles", [])
        for fn in req.staged_gcode_filenames:
            if fn and fn not in existing_staged:
                existing_staged.append(fn)

    if 0 <= req.index < len(catalog):
        existing = catalog[req.index]
        item.setdefault("activePlatforms", existing.get("activePlatforms", {}))
        item.setdefault("ytdSales", existing.get("ytdSales", {}))
        item.setdefault("etsyMonthlySales", existing.get("etsyMonthlySales", {}))
        file_manager.scaffold_product_directory(item, req.staged_gcode_filename)
        catalog[req.index] = item
    else:
        item.setdefault(
            "activePlatforms",
            {"Mayhem": True, "Etsy": True, "eBay": True, "Poshmark": False, "Depop": True, "TikTok": True},
        )
        item.setdefault(
            "ytdSales",
            {"Mayhem": 0, "Etsy": 0, "eBay": 0, "Poshmark": 0, "Depop": 0, "TikTok": 0},
        )
        item.setdefault("etsyMonthlySales", {})
        file_manager.scaffold_product_directory(item, req.staged_gcode_filename)
        catalog.append(item)

    saved = file_manager.save_catalog_state(
        {
            "catalog": catalog,
            "uploadedMonths": state["uploadedMonths"],
        }
    )
    return {"item": item, "catalog": saved["catalog"]}


@app.delete("/api/items/{index}")
async def delete_item(index: int):
    state = file_manager.get_catalog_state()
    catalog = state["catalog"]
    if index < 0 or index >= len(catalog):
        raise HTTPException(status_code=404, detail="Item index out of range")
    removed = catalog.pop(index)
    saved = file_manager.save_catalog_state(
        {
            "catalog": catalog,
            "uploadedMonths": state["uploadedMonths"],
        }
    )
    return {"deleted": removed, "catalog": saved["catalog"]}


@app.post("/api/months")
async def update_months(req: MonthsUpdateRequest):
    state = file_manager.get_catalog_state()
    state["uploadedMonths"] = req.uploadedMonths
    saved = file_manager.save_catalog_state(state)
    return {"uploadedMonths": saved["uploadedMonths"]}


@app.get("/api/settings")
async def get_settings():
    return file_manager.get_settings()


@app.post("/api/settings")
async def update_settings(settings_payload: Dict[str, Any]):
    """
    Saves settings to <root>/settings.json.
    If storage_root was changed, switches Master Storage Directory and returns the catalog state from that root.
    """
    updated_settings = file_manager.save_settings(settings_payload)
    catalog_state = file_manager.get_catalog_state()
    return {
        "settings": updated_settings,
        "catalog": catalog_state["catalog"],
        "uploadedMonths": catalog_state["uploadedMonths"],
    }


@app.post("/api/admin/pick-directory")
async def pick_storage_directory():
    """Opens native OS folder picker dialog via pywebview or tkinter."""
    selected_dir = None

    # 1. Try active pywebview window if running inside desktop shell
    try:
        import webview

        if webview.windows:
            result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                selected_dir = result[0]
    except Exception:
        pass

    # 2. Fallback to tkinter directory dialog
    if not selected_dir:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            chosen = filedialog.askdirectory(
                initialdir=str(file_manager.storage_root),
                title="Select Gilgarips Master Storage Directory",
            )
            root.destroy()
            if chosen:
                selected_dir = str(Path(chosen))
        except Exception:
            pass

    if not selected_dir:
        return {"selected": False, "storage_root": str(file_manager.storage_root)}

    settings = file_manager.get_settings()
    settings["storage_root"] = selected_dir
    updated_settings = file_manager.save_settings(settings)
    catalog_state = file_manager.get_catalog_state()

    return {
        "selected": True,
        "storage_root": str(file_manager.storage_root),
        "settings": updated_settings,
        "catalog": catalog_state["catalog"],
        "uploadedMonths": catalog_state["uploadedMonths"],
    }


@app.post("/api/admin/open-folder")
async def open_local_folder(req: OpenFolderRequest):
    """Opens the Master Storage Directory or a specific product folder in Windows Explorer."""
    target = file_manager.storage_root
    if req.slug:
        prod_target = file_manager.products_dir / slugify_item_name(req.slug)
        prod_target.mkdir(parents=True, exist_ok=True)
        target = prod_target

    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target))
        return {"opened": True, "path": str(target)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/slicer/parse")
async def parse_slicer_file(
    file: UploadFile = File(...),
    item_name: str = Form(""),
):
    """
    Parses a dropped .gcode or .3mf file:
    1. Extracts filament weight (g), print hours, bed temperature (°C), and 3D bounding box (X, Y, Z).
    2. Adds +2.0 inches clearance padding (1 inch all sides).
    3. Tests 3D rotational fit across all 6 orientations against active stock boxes.
    4. Copies the file into staging and <root>/products/<item-slug>/gcode/.
    """
    content = await file.read()
    filename = file.filename or "upload.gcode"

    settings = file_manager.get_settings()
    custom_boxes = settings.get("stock_boxes")

    analysis = analyze_slicer_upload(
        file_bytes=content,
        filename=filename,
        custom_boxes=custom_boxes,
    )

    target_name = item_name.strip()
    if not target_name or target_name == "Gothic Skull Dice Tower":
        target_name = analysis.get("suggested_title") or "Gothic Skull Dice Tower"

    saved_paths = file_manager.save_slicer_file(
        file_bytes=content,
        filename=filename,
        item_name_or_slug=target_name,
    )

    analysis["saved_gcode"] = saved_paths
    return analysis


@app.post("/api/slicer/parse-multiple")
async def parse_multiple_slicer_files(
    files: List[UploadFile] = File(...),
    item_name: str = Form(""),
):
    """
    Parses multiple dropped/selected .gcode or .3mf files (multi-part/multi-plate prints):
    1. Extracts individual filament grams, print times, bed temperatures, and bounding boxes.
    2. Sums total filament weight (g) and total print hours.
    3. Retains highest bed temperature.
    4. Calculates largest individual part dimensions for packaging fit.
    5. Saves all uploaded files into staging and the target product's gcode folder.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No slicer files provided")

    file_tuples = []
    for uf in files:
        content = await uf.read()
        fname = uf.filename or "upload.gcode"
        if content:
            file_tuples.append((fname, content))

    if not file_tuples:
        raise HTTPException(status_code=400, detail="Uploaded files were empty")

    settings = file_manager.get_settings()
    custom_boxes = settings.get("stock_boxes")

    analysis = analyze_multiple_slicer_uploads(
        files=file_tuples,
        custom_boxes=custom_boxes,
    )

    target_name = item_name.strip()
    if not target_name or target_name == "Gothic Skull Dice Tower":
        target_name = analysis.get("suggested_title") or "Multi-Part 3D Print"

    saved_staged_filenames = []
    saved_paths = []
    for fname, fbytes in file_tuples:
        sp = file_manager.save_slicer_file(
            file_bytes=fbytes,
            filename=fname,
            item_name_or_slug=target_name,
        )
        saved_staged_filenames.append(sp["staged_filename"])
        saved_paths.append(sp)

    analysis["saved_gcode_files"] = saved_paths
    analysis["staged_filenames"] = saved_staged_filenames
    analysis["saved_gcode"] = saved_paths[0] if saved_paths else {}
    return analysis


@app.post("/api/etsy/fetch-photos")
async def fetch_etsy_photos(req: EtsyFetchRequest):
    """
    Fetches product photos and listing info from an Etsy listing URL or pasted HTML.
    Bypasses anti-bot by accepting pasted HTML or extracts from public CDN images.
    """
    result = fetch_etsy_listing_images(listing_url=req.url or "", raw_html=req.raw_html)
    return result


@app.post("/api/etsy/ingest-photos")
async def ingest_etsy_photos(req: EtsyIngestRequest):
    """
    Downloads selected photos from Etsy CDN (i.etsystatic.com) and saves them
    directly into <root>/products/<slug>/photos/ renamed sequentially (01_hero.jpg, etc.).
    """
    clean_slug = slugify_item_name(req.slug)
    if not req.image_urls:
        raise HTTPException(status_code=400, detail="No image URLs provided")

    files_payload: List[Tuple[str, bytes]] = []
    for idx, img_url in enumerate(req.image_urls, start=1):
        img_bytes = download_image_bytes(img_url)
        if img_bytes:
            # Determine extension
            ext = ".jpg"
            if ".png" in img_url.lower():
                ext = ".png"
            elif ".webp" in img_url.lower():
                ext = ".webp"
            files_payload.append((f"etsy_photo_{idx}{ext}", img_bytes))

    if not files_payload:
        raise HTTPException(
            status_code=400,
            detail="Could not download any images from the provided URLs. Check network connection or URLs.",
        )

    photo_urls = file_manager.ingest_product_photos(clean_slug, files_payload)
    state = file_manager.get_catalog_state()
    return {
        "slug": clean_slug,
        "photos": photo_urls,
        "thumbnail": photo_urls[0] if photo_urls else None,
        "downloaded_count": len(files_payload),
        "catalog": state["catalog"],
    }


@app.post("/api/packaging/solve")
async def solve_packaging_fit(req: BoxFitRequest):
    settings = file_manager.get_settings()
    return solve_3d_box_fit(
        obj_x_in=req.x_in,
        obj_y_in=req.y_in,
        obj_z_in=req.z_in,
        clearance_padding_in=req.padding_in,
        boxes=settings.get("stock_boxes"),
    )


@app.post("/api/products/{slug}/photos")
async def upload_product_photos(
    slug: str,
    files: List[UploadFile] = File(...),
):
    """
    Ingests dropped/uploaded product photos into <root>/products/<slug>/photos/
    renamed cleanly as 01_hero.jpg, 02_detail.jpg, etc.
    """
    files_payload = []
    for uf in files:
        data = await uf.read()
        if data:
            files_payload.append((uf.filename or "photo.jpg", data))

    if not files_payload:
        raise HTTPException(status_code=400, detail="No valid photo files uploaded")

    photo_urls = file_manager.ingest_product_photos(slug, files_payload)
    state = file_manager.get_catalog_state()
    return {
        "slug": slugify_item_name(slug),
        "photos": photo_urls,
        "thumbnail": photo_urls[0] if photo_urls else None,
        "catalog": state["catalog"],
    }


@app.post("/api/listings/generate")
async def generate_listing_pack(req: ListingGenerateRequest):
    """
    Generates a multi-channel listing pack via Google Gemini (google-genai structured output)
    with instant static fallback.
    """
    settings = file_manager.get_settings()
    return generate_gemini_listing_pack(
        item=req.item,
        settings=settings,
        force_static=req.force_static,
    )


@app.get("/api/update/check")
async def api_check_update():
    """Checks whether a newer release or git commit is available."""
    return check_for_updates()


@app.post("/api/update/apply")
async def api_apply_update():
    """Pulls the latest code/binary update automatically."""
    return apply_update()

