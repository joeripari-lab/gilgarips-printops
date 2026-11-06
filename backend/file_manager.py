import json
import os
import re
import shutil
import sys
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
        If new_root doesn't have catalog_state.json or settings.json yet,
        copies existing state over so user data is never lost when switching directories.
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
                }
            else:
                state = {
                    "catalog": raw.get("catalog", []),
                    "uploadedMonths": {**DEFAULT_MONTHS, **raw.get("uploadedMonths", {})},
                }
        except Exception:
            state = {
                "catalog": [],
                "uploadedMonths": dict(DEFAULT_MONTHS),
            }

        # Enrich every item with its slug, photos list, and gcode files from disk
        for item in state["catalog"]:
            self._enrich_item_disk_assets(item)

        return state

    def save_catalog_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        catalog_list = state.get("catalog", [])
        uploaded_months = {**DEFAULT_MONTHS, **(state.get("uploadedMonths") or {})}

        for item in catalog_list:
            self.scaffold_product_directory(item)

        payload = {
            "catalog": catalog_list,
            "uploadedMonths": uploaded_months,
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

        prod_dir.mkdir(parents=True, exist_ok=True)
        gcode_dir.mkdir(parents=True, exist_ok=True)
        photos_dir.mkdir(parents=True, exist_ok=True)

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

        item["photos"] = photos
        item["thumbnail"] = photos[0] if photos else None
        item["gcodeFiles"] = gcodes
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

