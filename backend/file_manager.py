import io
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from backend.packaging import STOCK_BOXES


def _get_writable_app_root() -> Path:
    """
    Returns a writable directory for bootstrap state and staging files.
    When packaged as a desktop .exe (sys.frozen), uses %LOCALAPPDATA%/GilgaripsPrintOps.
    """
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
        app_dir = base / "GilgaripsPrintOps"
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _get_writable_app_root()
BOOTSTRAP_FILE = PROJECT_ROOT / ".printops_bootstrap.json"
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "Gilgarips_Catalog"
STAGING_GCODE_DIR = PROJECT_ROOT / ".staging_gcode"

PHOTO_ROLE_SUFFIXES = [
    "hero",
    "detail",
    "angle",
    "scale",
    "lifestyle",
    "packaging",
    "closeup",
    "back",
]

DEFAULT_MONTHS = {
    "Jan": False,
    "Feb": False,
    "Mar": False,
    "Apr": False,
    "May": False,
    "Jun": False,
    "Jul": False,
    "Aug": False,
    "Sep": False,
    "Oct": False,
    "Nov": False,
    "Dec": False,
}

DEFAULT_CHANNELS: List[Dict[str, Any]] = [
    {
        "key": "Mayhem",
        "name": "Mayhem Marketplace",
        "short": "My",
        "active": True,
        "fee_model": "subscription",
        "listing_fee": 0.00,
        "commission_pct": 0.0,
        "processing_pct": 0.0,
        "fixed_fee": 0.00,
        "monthly_sub": 10.00,
        "under_15_flat": 0.00,
        "buyer_pays_label": False,
        "color": "emerald",
        "subtitle": "$10.00/mo flat ($0 cut)",
    },
    {
        "key": "Etsy",
        "name": "Etsy",
        "short": "Et",
        "active": True,
        "fee_model": "standard",
        "listing_fee": 0.20,
        "commission_pct": 6.5,
        "processing_pct": 3.0,
        "fixed_fee": 0.25,
        "monthly_sub": 0.00,
        "under_15_flat": 0.00,
        "buyer_pays_label": False,
        "color": "indigo",
        "subtitle": "6.5% + 3% + $0.45",
    },
    {
        "key": "eBay",
        "name": "eBay",
        "short": "eB",
        "active": True,
        "fee_model": "standard",
        "listing_fee": 0.00,
        "commission_pct": 13.25,
        "processing_pct": 0.0,
        "fixed_fee": 0.40,
        "monthly_sub": 0.00,
        "under_15_flat": 0.00,
        "buyer_pays_label": False,
        "color": "indigo",
        "subtitle": "13.25% + $0.40",
    },
    {
        "key": "Poshmark",
        "name": "Poshmark",
        "short": "Po",
        "active": True,
        "fee_model": "poshmark",
        "listing_fee": 0.00,
        "commission_pct": 20.0,
        "processing_pct": 0.0,
        "fixed_fee": 0.00,
        "monthly_sub": 0.00,
        "under_15_flat": 2.95,
        "buyer_pays_label": True,
        "color": "indigo",
        "subtitle": "20% Flat Cut ($2.95 <$15)",
    },
    {
        "key": "Depop",
        "name": "Depop",
        "short": "Dp",
        "active": True,
        "fee_model": "standard",
        "listing_fee": 0.00,
        "commission_pct": 3.3,
        "processing_pct": 0.0,
        "fixed_fee": 0.45,
        "monthly_sub": 0.00,
        "under_15_flat": 0.00,
        "buyer_pays_label": False,
        "color": "rose",
        "subtitle": "3.3% + $0.45",
    },
    {
        "key": "TikTok",
        "name": "TikTok Shop",
        "short": "TT",
        "active": True,
        "fee_model": "standard",
        "listing_fee": 0.00,
        "commission_pct": 6.0,
        "processing_pct": 0.0,
        "fixed_fee": 0.30,
        "monthly_sub": 0.00,
        "under_15_flat": 0.00,
        "buyer_pays_label": False,
        "color": "cyan",
        "subtitle": "6.0% + $0.30",
    },
]

DEFAULT_PATREONS: List[Dict[str, Any]] = [
    {"name": "Gilgarips 3D", "subCost": 0.0, "color": "text-emerald-400", "active": True},
    {"name": "Fates End", "subCost": 15.0, "color": "text-purple-400", "active": True},
    {"name": "Lightspeed", "subCost": 9.0, "color": "text-amber-400", "active": True},
    {"name": "Akshan Designs", "subCost": 16.0, "color": "text-cyan-400", "active": True},
    {"name": "SkyPrints", "subCost": 15.0, "color": "text-blue-400", "active": True},
    {"name": "None", "subCost": 0.0, "color": "text-slate-400", "active": True},
]


def slugify_item_name(name: str) -> str:
    """Converts an item title into a clean filesystem-safe slug."""
    if not name:
        return "unnamed-item"
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed-item"


class FileManager:
    """
    Manages the Master Storage Directory (<root>), catalog_state.json, settings.json,
    and per-product directories (<root>/products/<item-slug>/{meta.json, gcode/, photos/}).
    """

    def __init__(self) -> None:
        self.storage_root: Path = self._load_bootstrap_root()
        self.ensure_root_structure()

    def _load_bootstrap_root(self) -> Path:
        if BOOTSTRAP_FILE.exists():
            try:
                data = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
                custom_path = data.get("storage_root")
                if custom_path:
                    p = Path(custom_path)
                    p.mkdir(parents=True, exist_ok=True)
                    return p
            except Exception:
                pass
        DEFAULT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_STORAGE_DIR

    def _save_bootstrap_root(self, new_root: Path) -> None:
        BOOTSTRAP_FILE.write_text(
            json.dumps({"storage_root": str(new_root)}, indent=2),
            encoding="utf-8",
        )

    def ensure_root_structure(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        (self.storage_root / "products").mkdir(parents=True, exist_ok=True)
        (self.storage_root / "unprinted_stls").mkdir(parents=True, exist_ok=True)
        STAGING_GCODE_DIR.mkdir(parents=True, exist_ok=True)

        if not self.settings_path.exists():
            self.save_settings(self.get_default_settings())
        if not self.catalog_path.exists():
            self.save_catalog_state(
                {
                    "catalog": [],
                    "uploadedMonths": dict(DEFAULT_MONTHS),
                    "updatedAt": datetime.now().isoformat(),
                }
            )

    @property
    def settings_path(self) -> Path:
        return self.storage_root / "settings.json"

    @property
    def catalog_path(self) -> Path:
        return self.storage_root / "catalog_state.json"

    @property
    def products_dir(self) -> Path:
        return self.storage_root / "products"

    @property
    def unprinted_dir(self) -> Path:
        return self.storage_root / "unprinted_stls"

    def get_default_settings(self) -> Dict[str, Any]:
        return {
            "storage_root": str(self.storage_root),
            "auto_download_json": False,
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
            "gemini_model": "gemini-2.5-flash",
            "brand_persona": (
                "You are the lead copywriter for Gilgarips 3D Studio in St. Clair Shores, Michigan. "
                "We craft precision 3D-printed tabletop RPG gaming gear, dice towers, miniatures accessories, "
                "and gothic home decor using high-grade PLA Pro, Matte PLA, PETG, and Dual-Color Silk filaments. "
                "Write evocative, high-converting, SEO-optimized copy that appeals to D&D dungeon masters, "
                "tabletop gamers, and gothic decor collectors."
            ),
            "slip_config": {
                "studio_name": "Gilgarips 3D Studio",
                "tagline": "Tabletop Gaming Gear & Gothic Home Decor",
                "coupon_code": "DIRECT15",
                "discount_pct": 15,
                "store_url": "Mayhem Marketplace / Gilgarips3D",
            },
            "channels": [dict(c) for c in DEFAULT_CHANNELS],
            "patreons": [dict(p) for p in DEFAULT_PATREONS],
            "stock_boxes": [dict(b) for b in STOCK_BOXES],
        }

    def get_settings(self) -> Dict[str, Any]:
        defaults = self.get_default_settings()
        if not self.settings_path.exists():
            self.save_settings(defaults)
            return defaults
        try:
            loaded = json.loads(self.settings_path.read_text(encoding="utf-8"))
            merged = {**defaults, **loaded}
            merged["storage_root"] = str(self.storage_root)
            if "slip_config" not in merged or not isinstance(merged["slip_config"], dict):
                merged["slip_config"] = defaults["slip_config"]
            else:
                merged["slip_config"] = {**defaults["slip_config"], **merged["slip_config"]}

            # Ensure all 6 channels exist
            existing_by_key = {c["key"]: c for c in merged.get("channels", []) if "key" in c}
            merged_channels = []
            for def_ch in DEFAULT_CHANNELS:
                if def_ch["key"] in existing_by_key:
                    merged_channels.append({**def_ch, **existing_by_key[def_ch["key"]]})
                else:
                    merged_channels.append(dict(def_ch))
            merged["channels"] = merged_channels

            if not merged.get("patreons") or not isinstance(merged.get("patreons"), list):
                merged["patreons"] = [dict(p) for p in DEFAULT_PATREONS]
            if not merged.get("stock_boxes"):
                merged["stock_boxes"] = [dict(b) for b in STOCK_BOXES]
            return merged
        except Exception:
            return defaults

    def save_settings(self, settings_data: Dict[str, Any]) -> Dict[str, Any]:
        new_root_str = settings_data.get("storage_root")
        if new_root_str and str(new_root_str).strip():
            candidate = Path(str(new_root_str).strip())
            if candidate != self.storage_root:
                self.change_storage_root(candidate)

        current = self.get_default_settings()
        updated = {**current, **settings_data}
        updated["storage_root"] = str(self.storage_root)

        self.settings_path.write_text(
            json.dumps(updated, indent=2), encoding="utf-8"
        )
        return updated

    def change_storage_root(self, new_root: Path) -> Path:
        """
        Switches the Master Storage Directory to new_root.
        If new_root doesn't have catalog_state.json, settings.json, or product files yet,
        copies existing state and product assets over so user data is never lost when switching directories.
        """
        old_root = self.storage_root
        new_root.mkdir(parents=True, exist_ok=True)
        (new_root / "products").mkdir(parents=True, exist_ok=True)

        old_catalog = old_root / "catalog_state.json"
        new_catalog = new_root / "catalog_state.json"
        if old_catalog.exists() and not new_catalog.exists():
            shutil.copy2(old_catalog, new_catalog)

        old_settings = old_root / "settings.json"
        new_settings = new_root / "settings.json"
        if old_settings.exists() and not new_settings.exists():
            shutil.copy2(old_settings, new_settings)

        # Copy existing product files (photos, gcodes, metadata) if destination is empty
        old_products = old_root / "products"
        new_products = new_root / "products"
        if old_products.exists():
            for item_dir in old_products.iterdir():
                if item_dir.is_dir():
                    dest_item_dir = new_products / item_dir.name
                    if not dest_item_dir.exists():
                        shutil.copytree(item_dir, dest_item_dir)

        self.storage_root = new_root
        self._save_bootstrap_root(new_root)
        self.ensure_root_structure()
        return self.storage_root

    def get_catalog_state(self) -> Dict[str, Any]:
        self.ensure_root_structure()
        try:
            raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                state = {
                    "catalog": raw,
                    "uploadedMonths": dict(DEFAULT_MONTHS),
                    "printQueue": [],
                }
            else:
                state = {
                    "catalog": raw.get("catalog", []),
                    "uploadedMonths": {**DEFAULT_MONTHS, **raw.get("uploadedMonths", {})},
                    "printQueue": raw.get("printQueue", []),
                }
        except Exception:
            state = {
                "catalog": [],
                "uploadedMonths": dict(DEFAULT_MONTHS),
                "printQueue": [],
            }

        # Enrich every item with its slug, photos list, and gcode files from disk
        for item in state["catalog"]:
            self._enrich_item_disk_assets(item)

        return state

    def save_catalog_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        catalog_list = state.get("catalog", [])
        uploaded_months = {**DEFAULT_MONTHS, **(state.get("uploadedMonths") or {})}
        print_queue = state.get("printQueue", [])

        for item in catalog_list:
            self.scaffold_product_directory(item)

        payload = {
            "catalog": catalog_list,
            "uploadedMonths": uploaded_months,
            "printQueue": print_queue,
            "updatedAt": datetime.now().isoformat(),
        }
        self.catalog_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return payload

    def scaffold_product_directory(
        self,
        item: Dict[str, Any],
        staged_gcode_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ensures <root>/products/<item-slug>/ exists with:
        ├── meta.json
        ├── gcode/
        └── photos/
        """
        slug = item.get("slug") or slugify_item_name(item.get("name", "unnamed-item"))
        # If item name changed, update slug
        expected_slug = slugify_item_name(item.get("name", "unnamed-item"))
        if slug != expected_slug:
            old_dir = self.products_dir / slug
            new_dir = self.products_dir / expected_slug
            if old_dir.exists() and not new_dir.exists():
                shutil.move(str(old_dir), str(new_dir))
            slug = expected_slug

        item["slug"] = slug
        prod_dir = self.products_dir / slug
        gcode_dir = prod_dir / "gcode"
        photos_dir = prod_dir / "photos"
        stl_dir = prod_dir / "stl"

        prod_dir.mkdir(parents=True, exist_ok=True)
        gcode_dir.mkdir(parents=True, exist_ok=True)
        photos_dir.mkdir(parents=True, exist_ok=True)
        stl_dir.mkdir(parents=True, exist_ok=True)

        # If there are staged gcode files from dropzone, move/copy them into gcode/
        staged_names = item.get("stagedGcodeFiles") or []
        staged_name = staged_gcode_filename or item.get("stagedGcodeFile")
        if staged_name and staged_name not in staged_names:
            staged_names.append(staged_name)

        for s_name in staged_names:
            if s_name:
                staged_path = STAGING_GCODE_DIR / s_name
                if staged_path.exists():
                    dest_path = gcode_dir / s_name
                    shutil.copy2(staged_path, dest_path)

        self._enrich_item_disk_assets(item)

        # Save meta.json inside <root>/products/<item-slug>/meta.json
        meta_path = prod_dir / "meta.json"
        meta_payload = {
            **item,
            "lastSyncedAt": datetime.now().isoformat(),
        }
        meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
        return item

    def _enrich_item_disk_assets(self, item: Dict[str, Any]) -> None:
        slug = item.get("slug") or slugify_item_name(item.get("name", "unnamed-item"))
        item["slug"] = slug
        prod_dir = self.products_dir / slug
        photos_dir = prod_dir / "photos"
        gcode_dir = prod_dir / "gcode"
        stl_dir = prod_dir / "stl"

        photos: List[str] = []
        if photos_dir.exists():
            for f in sorted(photos_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                    photos.append(f"/media/products/{slug}/photos/{f.name}")

        gcodes: List[str] = []
        if gcode_dir.exists():
            for f in sorted(gcode_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in {".gcode", ".3mf"}:
                    gcodes.append(f.name)

        stls: List[str] = []
        if stl_dir.exists():
            for f in sorted(stl_dir.rglob("*")):
                if f.is_file() and f.suffix.lower() in {".stl", ".3mf", ".obj"}:
                    stls.append(str(f.relative_to(stl_dir)).replace("\\", "/"))

        item["photos"] = photos
        item["thumbnail"] = photos[0] if photos else None
        item["gcodeFiles"] = gcodes
        item["stlFiles"] = stls
        item["productFolder"] = str(prod_dir)

    def save_slicer_file(
        self,
        file_bytes: bytes,
        filename: str,
        item_name_or_slug: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Saves a dropped .gcode/.3mf file to staging AND directly to
        <root>/products/<item-slug>/gcode/ if an item slug or name is provided.
        """
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
        STAGING_GCODE_DIR.mkdir(parents=True, exist_ok=True)
        staged_path = STAGING_GCODE_DIR / safe_name
        staged_path.write_bytes(file_bytes)

        saved_product_path = None
        if item_name_or_slug:
            slug = slugify_item_name(item_name_or_slug)
            gcode_dir = self.products_dir / slug / "gcode"
            gcode_dir.mkdir(parents=True, exist_ok=True)
            dest = gcode_dir / safe_name
            dest.write_bytes(file_bytes)
            saved_product_path = str(dest)

        return {
            "staged_filename": safe_name,
            "product_gcode_path": saved_product_path or str(staged_path),
        }

    def ingest_product_photos(
        self,
        slug: str,
        files_data: List[ Tuple[str, bytes] ],
    ) -> List[str]:
        """
        Saves uploaded/dropped photos directly to <root>/products/<slug>/photos/
        renamed cleanly as 01_hero.jpg, 02_detail.jpg, 03_angle.jpg, etc.
        Updates catalog_state.json and meta.json if the item exists in catalog.
        """
        clean_slug = slugify_item_name(slug)
        prod_dir = self.products_dir / clean_slug
        photos_dir = prod_dir / "photos"
        gcode_dir = prod_dir / "gcode"
        photos_dir.mkdir(parents=True, exist_ok=True)
        gcode_dir.mkdir(parents=True, exist_ok=True)

        existing_photos = sorted(
            [
                f
                for f in photos_dir.iterdir()
                if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
            ]
        )
        next_index = len(existing_photos) + 1

        for orig_name, content_bytes in files_data:
            role_idx = next_index - 1
            role_name = (
                PHOTO_ROLE_SUFFIXES[role_idx]
                if role_idx < len(PHOTO_ROLE_SUFFIXES)
                else "detail"
            )
            clean_filename = f"{next_index:02d}_{role_name}.jpg"
            dest_path = photos_dir / clean_filename
            dest_path.write_bytes(content_bytes)
            next_index += 1

        # Refresh item in catalog_state.json if present
        state = self.get_catalog_state()
        for item in state["catalog"]:
            if slugify_item_name(item.get("name", "")) == clean_slug or item.get("slug") == clean_slug:
                self.scaffold_product_directory(item)
        self.catalog_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        all_urls = [
            f"/media/products/{clean_slug}/photos/{f.name}"
            for f in sorted(photos_dir.iterdir())
            if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        ]
        return all_urls

    # ==================== STL ORGANIZATION (PRINTED & NOT PRINTED) ====================

    @staticmethod
    def _sanitize_folder_label(name: str, fallback: str = "Unsorted") -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]+', "_", (name or "").strip()).strip(". ")
        return cleaned[:100] if cleaned else fallback

    @staticmethod
    def _safe_extract_zip(
        zip_bytes: bytes,
        dest_dir: Path,
        allowed_exts: Optional[set] = None,
    ) -> int:
        """
        Safely extracts a .zip archive into dest_dir, preventing Zip Slip path traversal.
        If all entries share a single top-level directory, unwraps that redundant wrapper.
        Returns count of extracted files.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        extracted_count = 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            members = [
                m for m in zf.infolist()
                if not m.is_dir()
                and not m.filename.startswith("__MACOSX")
                and not Path(m.filename).name.startswith("._")
            ]
            if not members:
                return 0

            # Detect single top-level wrapper folder so we don't double-nest
            top_parts = {
                Path(m.filename).parts[0]
                for m in members
                if len(Path(m.filename).parts) > 1
            }
            all_have_sub = all(len(Path(m.filename).parts) > 1 for m in members)
            strip_prefix = len(top_parts) == 1 and all_have_sub

            for member in members:
                rel_parts = Path(member.filename).parts
                if strip_prefix:
                    rel_parts = rel_parts[1:]
                if not rel_parts:
                    continue
                if allowed_exts and Path(rel_parts[-1]).suffix.lower() not in allowed_exts:
                    continue

                # Prevent path traversal
                safe_parts = [p for p in rel_parts if p not in ("", ".", "..")]
                if not safe_parts:
                    continue
                target_path = (dest_dir / Path(*safe_parts)).resolve()
                if not str(target_path).startswith(str(dest_dir.resolve())):
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_count += 1
        return extracted_count

    def ingest_product_stls(
        self,
        slug: str,
        files_data: List[Tuple[str, bytes]],
    ) -> List[str]:
        """
        Copies dropped .stl / .3mf / .obj files (or extracts .zip archives containing them)
        into <root>/products/<slug>/stl/.
        """
        clean_slug = slugify_item_name(slug)
        prod_dir = self.products_dir / clean_slug
        stl_dir = prod_dir / "stl"
        stl_dir.mkdir(parents=True, exist_ok=True)

        model_exts = {".stl", ".3mf", ".obj"}
        for orig_name, content_bytes in files_data:
            p = Path(orig_name)
            ext = p.suffix.lower()
            if ext == ".zip":
                self._safe_extract_zip(content_bytes, stl_dir, allowed_exts=model_exts)
            elif ext in model_exts:
                safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", p.name)
                (stl_dir / safe_name).write_bytes(content_bytes)

        # Refresh item in catalog_state.json
        state = self.get_catalog_state()
        for item in state["catalog"]:
            if slugify_item_name(item.get("name", "")) == clean_slug or item.get("slug") == clean_slug:
                self.scaffold_product_directory(item)
        self.save_catalog_state(state)

        return [
            str(f.relative_to(stl_dir)).replace("\\", "/")
            for f in sorted(stl_dir.rglob("*"))
            if f.is_file() and f.suffix.lower() in model_exts
        ]

    def list_unprinted_stls(self) -> List[Dict[str, Any]]:
        """
        Scans <root>/unprinted_stls/<Creator>/<Model Name>/ and returns grouped model entries.
        """
        self.unprinted_dir.mkdir(parents=True, exist_ok=True)
        model_exts = {".stl", ".3mf", ".obj"}
        entries: List[Dict[str, Any]] = []

        for creator_dir in sorted(self.unprinted_dir.iterdir()):
            if not creator_dir.is_dir():
                continue
            creator_name = creator_dir.name
            for model_dir in sorted(creator_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                files: List[str] = []
                total_size = 0
                for f in sorted(model_dir.rglob("*")):
                    if f.is_file() and f.suffix.lower() in model_exts:
                        files.append(str(f.relative_to(model_dir)).replace("\\", "/"))
                        total_size += f.stat().st_size

                # Include folder even if it has non-STL files (e.g., images/docs), or show count
                all_files_count = sum(1 for f in model_dir.rglob("*") if f.is_file())
                if all_files_count == 0:
                    continue

                entries.append(
                    {
                        "creator": creator_name,
                        "model_name": model_dir.name,
                        "folder_path": str(model_dir),
                        "stl_files": files,
                        "stl_count": len(files),
                        "total_files": all_files_count,
                        "total_size_mb": round(total_size / (1024 * 1024), 2),
                    }
                )
        return entries

    def ingest_unprinted_upload(
        self,
        creator: str,
        model_name: str,
        files_data: List[Tuple[str, bytes, Optional[str]]],
    ) -> Dict[str, Any]:
        """
        Organizes uploaded files, folders (via relative_path), or .zip archives into:
        <root>/unprinted_stls/<Creator>/<Model Name>/
        Always copies (never deletes user originals).
        """
        self.unprinted_dir.mkdir(parents=True, exist_ok=True)
        safe_creator = self._sanitize_folder_label(creator, "Unsorted")
        creator_dir = self.unprinted_dir / safe_creator
        creator_dir.mkdir(parents=True, exist_ok=True)

        explicit_model = (model_name or "").strip()
        added_count = 0

        for orig_name, content_bytes, rel_path in files_data:
            p = Path(orig_name)
            ext = p.suffix.lower()

            if ext == ".zip":
                target_model = self._sanitize_folder_label(explicit_model or p.stem, "Untitled_Model")
                model_dir = creator_dir / target_model
                added_count += self._safe_extract_zip(content_bytes, model_dir)
                continue

            # If dropped as a folder via webkitGetAsEntry, rel_path looks like "FolderName/sub/part.stl"
            if rel_path and "/" in rel_path.replace("\\", "/"):
                parts = [part for part in rel_path.replace("\\", "/").split("/") if part not in ("", ".", "..")]
                if len(parts) >= 2:
                    folder_root = self._sanitize_folder_label(explicit_model or parts[0], "Untitled_Model")
                    sub_parts = parts[1:]
                    target_path = creator_dir / folder_root / Path(*sub_parts)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(content_bytes)
                    added_count += 1
                    continue

            # Loose file(s)
            target_model = self._sanitize_folder_label(explicit_model or p.stem, "Untitled_Model")
            model_dir = creator_dir / target_model
            model_dir.mkdir(parents=True, exist_ok=True)
            safe_file = self._sanitize_folder_label(p.name, "model.stl")
            (model_dir / safe_file).write_bytes(content_bytes)
            added_count += 1

        return {
            "creator": safe_creator,
            "added_count": added_count,
            "unprinted": self.list_unprinted_stls(),
        }

    def ingest_unprinted_folder_from_disk(self, creator: str, source_folder: Path) -> Dict[str, Any]:
        """
        Copies an entire folder from disk into <root>/unprinted_stls/<Creator>/<FolderName>/
        without streaming large files over HTTP.
        """
        self.unprinted_dir.mkdir(parents=True, exist_ok=True)
        safe_creator = self._sanitize_folder_label(creator, "Unsorted")
        safe_model = self._sanitize_folder_label(source_folder.name, "Untitled_Model")
        dest_dir = self.unprinted_dir / safe_creator / safe_model

        if dest_dir.exists():
            # Merge/copy into existing folder without clobbering
            for src_file in source_folder.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(source_folder)
                    dst_file = dest_dir / rel
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
        else:
            shutil.copytree(source_folder, dest_dir)

        return {
            "creator": safe_creator,
            "model_name": safe_model,
            "unprinted": self.list_unprinted_stls(),
        }

    def promote_unprinted_to_printed(
        self,
        creator: str,
        model_name: str,
        target_slug: str,
        remove_from_unprinted: bool = True,
    ) -> Dict[str, Any]:
        """
        Copies STL/3MF/OBJ files from unprinted_stls/<creator>/<model_name>/
        into products/<target_slug>/stl/, and optionally removes the unprinted folder.
        """
        safe_creator = self._sanitize_folder_label(creator, "Unsorted")
        safe_model = self._sanitize_folder_label(model_name, "")
        src_dir = self.unprinted_dir / safe_creator / safe_model
        if not src_dir.exists():
            raise FileNotFoundError(f"Unprinted folder not found: {src_dir}")

        clean_slug = slugify_item_name(target_slug)
        dest_stl_dir = self.products_dir / clean_slug / "stl"
        dest_stl_dir.mkdir(parents=True, exist_ok=True)

        model_exts = {".stl", ".3mf", ".obj"}
        copied_files: List[str] = []
        for f in src_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in model_exts:
                rel = f.relative_to(src_dir)
                dst = dest_stl_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                copied_files.append(str(rel).replace("\\", "/"))

        if remove_from_unprinted:
            shutil.rmtree(src_dir, ignore_errors=True)
            # Remove creator folder if empty
            creator_dir = self.unprinted_dir / safe_creator
            if creator_dir.exists() and not any(creator_dir.iterdir()):
                creator_dir.rmdir()

        # Refresh catalog state
        state = self.get_catalog_state()
        for item in state["catalog"]:
            if slugify_item_name(item.get("name", "")) == clean_slug or item.get("slug") == clean_slug:
                self.scaffold_product_directory(item)
        self.save_catalog_state(state)

        return {
            "copied_files": copied_files,
            "catalog": state["catalog"],
            "unprinted": self.list_unprinted_stls(),
        }

    def delete_unprinted_model(self, creator: str, model_name: str) -> List[Dict[str, Any]]:
        safe_creator = self._sanitize_folder_label(creator, "Unsorted")
        safe_model = self._sanitize_folder_label(model_name, "")
        target_dir = self.unprinted_dir / safe_creator / safe_model
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        creator_dir = self.unprinted_dir / safe_creator
        if creator_dir.exists() and not any(creator_dir.iterdir()):
            creator_dir.rmdir()
        return self.list_unprinted_stls()

