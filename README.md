<p align="center">
  <img src="assets/logo.png" alt="Gilgarips PrintOps Logo" width="140" />
</p>

# Gilgarips PrintOps (v2.1.0 Desktop)

**Operational 3D print-farm pricing, live slicer ingestion, 3D spatial packaging solver, local Google Drive sync, and Gemini AI multi-channel listing packs.**

---

## Features

- **Real Local File Management & Auto-Scaffolding**:
  - Configurable **Master Storage Directory** (e.g., `G:\My Drive\Gilgarips_Catalog`) with `catalog_state.json` and `settings.json`.
  - Automatically scaffolds `<root>/products/<item-slug>/{meta.json, gcode/, photos/}` when creating or updating items.
  - Drag-and-drop photo ingestion automatically renames product photos (`01_hero.jpg`, `02_detail.jpg`, `03_angle.jpg`, etc.) and serves thumbnails directly from disk.
- **Slicer Parser & 3D Spatial Packaging Engine**:
  - Parses dropped `.gcode` and `.3mf` files (OrcaSlicer, Bambu Studio, PrusaSlicer, Cura) for filament grams, print hours, bed temperature (`°C`), and 3D bounding box (`X × Y × Z`).
  - Adds `+2.0"` clearance padding (`1"` all sides) and tests all **6 3D rotational orientations** against active stock boxes (**UPS Blank Security Small/Medium**, **Poshmark / USPS Priority Suite**, and standard corrugated boxes).
- **Dynamic Marketplace Registry & Backed Patreons Manager**:
  - Toggle active channels (**Mayhem Marketplace, Etsy, eBay, Poshmark, Depop, TikTok Shop**) and manage backed 3D design Patreons & monthly subscription ROI.
  - Platform fee formulas are locked by default with an unlock confirmation guard to prevent accidental margin drift.
- **Native Gemini AI Listing Engine (`google-genai`)**:
  - Generates structured JSON listing packs (`title` <= 140 chars, 13 `tags` <= 20 chars, Markdown `mayhem_description`, and 2-sentence `social_hook` for Reels/TikTok) with instant offline template fallback.
- **Printable 4×6 Mayhem Conversion Insert Slip**:
  - 1-click printable 4×6 package insert with configurable VIP coupon code (`DIRECT15`), discount percentage, and storefront callout.

---

## Download & Run (Windows)

Download **`GilgaripsPrintOps.exe`** directly from the [**Releases**](../../releases) page to run the standalone Windows desktop application, or run `python build_installer.py` to build and install to `%LOCALAPPDATA%\Programs\GilgaripsPrintOps` with Desktop & Start Menu shortcuts.
