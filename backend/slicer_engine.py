import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, Any, Optional, List, Tuple

from backend.packaging import solve_3d_box_fit

MM_PER_INCH = 25.4


def _parse_time_string_to_hours(raw_time: str) -> float:
    """Converts strings like '1d 6h 30m 15s' or '6h 15m' into decimal hours."""
    total_h = 0.0
    d_match = re.search(r"(\d+)\s*d", raw_time, re.IGNORECASE)
    h_match = re.search(r"(\d+)\s*h", raw_time, re.IGNORECASE)
    m_match = re.search(r"(\d+)\s*m", raw_time, re.IGNORECASE)
    s_match = re.search(r"(\d+)\s*s", raw_time, re.IGNORECASE)

    if d_match:
        total_h += int(d_match.group(1)) * 24.0
    if h_match:
        total_h += int(h_match.group(1))
    if m_match:
        total_h += int(m_match.group(1)) / 60.0
    if s_match:
        total_h += int(s_match.group(1)) / 3600.0

    return round(total_h, 2)


def parse_gcode_text(text: str, filename: str = "upload.gcode") -> Dict[str, Any]:
    """
    Extracts filament weight (g), print hours, bed temperature (°C),
    and 3D bounding box (mm and inches) from OrcaSlicer / Bambu Studio / PrusaSlicer / Cura G-code.
    """
    filament_grams = 0.0
    print_hours = 0.0
    bed_temp_c = 60
    material_type = None

    # 1. Filament weight [g]
    filament_patterns = [
        r"total filament used \[g\]\s*=\s*([\d\.,\s]+)",
        r"filament used \[g\]\s*=\s*([\d\.,\s]+)",
        r";\s*filament used\s*=\s*([\d\.]+)\s*g",
        r"total filament weight\s*[:=]\s*([\d\.]+)",
    ]
    for pat in filament_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw_vals = [
                float(x.strip())
                for x in m.group(1).split(",")
                if re.match(r"^\d+(\.\d+)?$", x.strip())
            ]
            if raw_vals:
                total_g = sum(raw_vals)
                if total_g > 0:
                    filament_grams = round(total_g, 1)
                    break

    # 2. Print time (hours)
    time_patterns = [
        r"model printing time:\s*([0-9dhms\s]+);",
        r"estimated printing time \(normal mode\)\s*=\s*([0-9dhms\s]+)",
        r";\s*total estimated time:\s*([0-9dhms\s]+)",
        r";\s*estimated printing time\s*=\s*([0-9dhms\s]+)",
    ]
    for pat in time_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            parsed_h = _parse_time_string_to_hours(m.group(1))
            if parsed_h > 0:
                print_hours = parsed_h
                break

    if print_hours <= 0:
        sec_match = re.search(r";TIME:\s*(\d+)", text, re.IGNORECASE)
        if sec_match:
            secs = int(sec_match.group(1))
            if secs > 0:
                print_hours = round(secs / 3600.0, 2)

    # 3. Bed temperature (°C)
    bed_patterns = [
        r";\s*(?:hot_plate_temp|bed_temperature|textured_plate_temp|cool_plate_temp|eng_plate_temp|first_layer_bed_temperature)\s*=\s*(\d+)",
        r"M190\s+S(\d+)",
        r"M140\s+S([1-9]\d+)",
    ]
    for pat in bed_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 25 <= val <= 130:
                bed_temp_c = val
                break

    # Optional material type detection
    mat_match = re.search(r";\s*filament_type\s*=\s*([^\r\n;]+)", text, re.IGNORECASE)
    if mat_match:
        material_type = mat_match.group(1).strip().strip('"')

    # 4. Bounding Box Extraction (mm)
    bbox_mm = _extract_gcode_bbox_mm(text)

    obj_x_in = round(bbox_mm["x_mm"] / MM_PER_INCH, 2)
    obj_y_in = round(bbox_mm["y_mm"] / MM_PER_INCH, 2)
    obj_z_in = round(bbox_mm["z_mm"] / MM_PER_INCH, 2)

    # Package weight estimate (filament grams to oz + 4 oz packaging buffer)
    estimated_package_oz = (
        math.ceil((filament_grams * 0.035274) + 4) if filament_grams > 0 else 12
    )

    clean_title = re.sub(r"\.[^/.]+$", "", filename)
    clean_title = re.sub(r"[_-]+", " ", clean_title).strip()

    return {
        "filename": filename,
        "suggested_title": clean_title,
        "filament_grams": round(filament_grams),
        "print_hours": print_hours,
        "bed_temp_c": bed_temp_c,
        "material_type": material_type,
        "estimated_package_oz": estimated_package_oz,
        "bbox_mm": bbox_mm,
        "bbox_in": {
            "x": obj_x_in,
            "y": obj_y_in,
            "z": obj_z_in,
        },
    }


def _extract_gcode_bbox_mm(text: str) -> Dict[str, float]:
    """
    Determines the X, Y, Z bounding box in millimeters from G-code metadata comments,
    EXCLUDE_OBJECT_DEFINE polygons, or actual G1 extrusion coordinates.
    """
    # Strategy A: Explicit MINX/MAXX comments (Cura, IdeaMaker, some Bambu/Orca post-processors)
    minx_m = re.search(r";\s*MINX\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)
    maxx_m = re.search(r";\s*MAXX\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)
    miny_m = re.search(r";\s*MINY\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)
    maxy_m = re.search(r";\s*MAXY\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)
    minz_m = re.search(r";\s*MINZ\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)
    maxz_m = re.search(r";\s*MAXZ\s*[:=]\s*([-\d\.]+)", text, re.IGNORECASE)

    if minx_m and maxx_m and miny_m and maxy_m and maxz_m:
        dx = abs(float(maxx_m.group(1)) - float(minx_m.group(1)))
        dy = abs(float(maxy_m.group(1)) - float(miny_m.group(1)))
        min_z = float(minz_m.group(1)) if minz_m else 0.0
        dz = abs(float(maxz_m.group(1)) - min_z)
        if dx > 1.0 and dy > 1.0 and dz > 1.0:
            return {
                "x_mm": round(dx, 2),
                "y_mm": round(dy, 2),
                "z_mm": round(dz, 2),
                "source": "header_minmax",
            }

    # Check max_layer_z comment common in Orca / Bambu / PrusaSlicer
    max_layer_z = 0.0
    mlz_match = re.search(r";\s*max_layer_z\s*=\s*([\d\.]+)", text, re.IGNORECASE)
    if mlz_match:
        max_layer_z = float(mlz_match.group(1))

    # Strategy B: EXCLUDE_OBJECT_DEFINE polygons (Klipper / OrcaSlicer / Bambu)
    poly_matches = re.findall(r"POLYGON=\[\[([^\]]+(?:\]\s*,\s*\[[^\]]+)*)\]\]", text)
    if poly_matches:
        xs: List[float] = []
        ys: List[float] = []
        for poly_str in poly_matches:
            pairs = re.findall(r"([-\d\.]+)\s*,\s*([-\d\.]+)", poly_str)
            for px, py in pairs:
                xs.append(float(px))
                ys.append(float(py))
        if xs and ys:
            dx = max(xs) - min(xs)
            dy = max(ys) - min(ys)
            dz = max_layer_z if max_layer_z > 0 else _scan_max_z_from_moves(text)
            if dx > 1.0 and dy > 1.0 and dz > 0.5:
                return {
                    "x_mm": round(dx, 2),
                    "y_mm": round(dy, 2),
                    "z_mm": round(dz, 2),
                    "source": "exclude_object_polygon",
                }

    # Strategy C: Scan G0/G1 extrusion moves (skipping initial purge line before first layer marker if present)
    layer_start_idx = 0
    for marker in ["; LAYER_CHANGE", ";LAYER:0", "; layer 1", "; CHANGE_LAYER", "EXCLUDE_OBJECT_START"]:
        pos = text.find(marker)
        if pos != -1:
            layer_start_idx = pos
            break

    body = text[layer_start_idx:]
    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")
    max_z = max_layer_z

    move_re = re.compile(
        r"^G[01]\s+.*?X([-\d\.]+).*?Y([-\d\.]+).*?E([-\d\.]+)", re.MULTILINE
    )
    z_re = re.compile(r"^G[01]\s+[^;\r\n]*?Z([\d\.]+)", re.MULTILINE)

    for m in move_re.finditer(body):
        e_val = float(m.group(3))
        if e_val > 0:
            x_val = float(m.group(1))
            y_val = float(m.group(2))
            if x_val < min_x:
                min_x = x_val
            if x_val > max_x:
                max_x = x_val
            if y_val < min_y:
                min_y = y_val
            if y_val > max_y:
                max_y = y_val

    if max_z <= 0:
        for zm in z_re.finditer(body):
            zv = float(zm.group(1))
            if 0 < zv < 500 and zv > max_z:
                max_z = zv

    if min_x != float("inf") and max_x > min_x and max_y > min_y:
        dx = max_x - min_x
        dy = max_y - min_y
        dz = max_z if max_z > 0 else 50.0
        return {
            "x_mm": round(dx, 2),
            "y_mm": round(dy, 2),
            "z_mm": round(dz, 2),
            "source": "gcode_extrusion_scan",
        }

    # Fallback default if G-code only had summary comments and no moves
    return {
        "x_mm": 127.0,
        "y_mm": 101.6,
        "z_mm": 50.8,
        "source": "fallback_default",
    }


def _scan_max_z_from_moves(text: str) -> float:
    max_z = 0.0
    for zm in re.finditer(r"^G[01]\s+[^;\r\n]*?Z([\d\.]+)", text, re.MULTILINE):
        zv = float(zm.group(1))
        if 0 < zv < 500 and zv > max_z:
            max_z = zv
    return max_z if max_z > 0 else 50.0


def parse_3mf_bytes(file_bytes: bytes, filename: str = "upload.3mf") -> Dict[str, Any]:
    """
    Parses a .3mf archive (OrcaSlicer / Bambu Studio / PrusaSlicer / raw 3MF).
    Extracts embedded G-code and/or Metadata/slice_info.config and/or 3D mesh vertices.
    """
    result: Optional[Dict[str, Any]] = None
    mesh_bbox_mm: Optional[Dict[str, float]] = None
    slice_info_data: Dict[str, Any] = {}

    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
        namelist = zf.namelist()

        # 1. Check for embedded G-code files first
        for name in namelist:
            if name.lower().endswith(".gcode"):
                gcode_text = zf.read(name).decode("utf-8", errors="ignore")
                if "filament" in gcode_text.lower() or "g1" in gcode_text.lower():
                    result = parse_gcode_text(gcode_text, filename)
                    break

        # 2. Check Metadata/slice_info.config (Bambu / Orca 3MF metadata)
        for name in namelist:
            if "slice_info" in name.lower() or (
                name.lower().startswith("metadata/plate_") and name.lower().endswith(".json")
            ):
                content = zf.read(name).decode("utf-8", errors="ignore")
                slice_info_data.update(_parse_slice_info_content(content))

        # 3. Parse 3D mesh (.model files) if bounding box is still missing or fallback
        if result is None or result["bbox_mm"].get("source") == "fallback_default":
            mesh_bbox_mm = _extract_3mf_mesh_bbox_mm(zf, namelist)

    if result is None:
        clean_title = re.sub(r"\.[^/.]+$", "", filename)
        clean_title = re.sub(r"[_-]+", " ", clean_title).strip()
        filament_g = round(slice_info_data.get("filament_grams", 0.0))
        print_h = slice_info_data.get("print_hours", 0.0)
        bed_t = slice_info_data.get("bed_temp_c", 60)
        bbox = (
            mesh_bbox_mm
            or slice_info_data.get("bbox_mm")
            or {"x_mm": 127.0, "y_mm": 101.6, "z_mm": 50.8, "source": "fallback_default"}
        )
        result = {
            "filename": filename,
            "suggested_title": clean_title,
            "filament_grams": filament_g,
            "print_hours": print_h,
            "bed_temp_c": bed_t,
            "material_type": slice_info_data.get("material_type"),
            "estimated_package_oz": math.ceil((filament_g * 0.035274) + 4) if filament_g > 0 else 12,
            "bbox_mm": bbox,
            "bbox_in": {
                "x": round(bbox["x_mm"] / MM_PER_INCH, 2),
                "y": round(bbox["y_mm"] / MM_PER_INCH, 2),
                "z": round(bbox["z_mm"] / MM_PER_INCH, 2),
            },
        }
    else:
        # Enrich G-code result with slice_info or mesh bbox if needed
        if result["filament_grams"] <= 0 and slice_info_data.get("filament_grams", 0) > 0:
            result["filament_grams"] = round(slice_info_data["filament_grams"])
            result["estimated_package_oz"] = math.ceil((result["filament_grams"] * 0.035274) + 4)
        if result["print_hours"] <= 0 and slice_info_data.get("print_hours", 0) > 0:
            result["print_hours"] = slice_info_data["print_hours"]
        if (
            result["bbox_mm"].get("source") == "fallback_default"
            and mesh_bbox_mm is not None
        ):
            result["bbox_mm"] = mesh_bbox_mm
            result["bbox_in"] = {
                "x": round(mesh_bbox_mm["x_mm"] / MM_PER_INCH, 2),
                "y": round(mesh_bbox_mm["y_mm"] / MM_PER_INCH, 2),
                "z": round(mesh_bbox_mm["z_mm"] / MM_PER_INCH, 2),
            }

    return result


def _parse_slice_info_content(content: str) -> Dict[str, Any]:
    """Parses Bambu / Orca slice_info.config XML or JSON metadata."""
    info: Dict[str, Any] = {}

    # Check XML key/value pairs: <metadata key="weight" value="142.3"/>, <metadata key="prediction" value="18450"/>
    weight_matches = re.findall(r'key="weight"\s+value="([\d\.]+)"', content)
    if weight_matches:
        total_w = sum(float(w) for w in weight_matches)
        if total_w > 0:
            info["filament_grams"] = round(total_w, 1)

    pred_match = re.search(r'key="prediction"\s+value="([\d\.]+)"', content)
    if pred_match:
        secs = float(pred_match.group(1))
        if secs > 0:
            info["print_hours"] = round(secs / 3600.0, 2)

    bed_match = re.search(r'bed_temp\w*"\s*[:=]\s*"?(\d+)', content)
    if bed_match:
        info["bed_temp_c"] = int(bed_match.group(1))

    # Also run text patterns in case slice_info has standard comments
    parsed_text = parse_gcode_text(content, "slice_info")
    if not info.get("filament_grams") and parsed_text["filament_grams"] > 0:
        info["filament_grams"] = parsed_text["filament_grams"]
    if not info.get("print_hours") and parsed_text["print_hours"] > 0:
        info["print_hours"] = parsed_text["print_hours"]

    return info


def _extract_3mf_mesh_bbox_mm(
    zf: zipfile.ZipFile, namelist: List[str]
) -> Optional[Dict[str, float]]:
    """Computes the 3D bounding box across vertices in 3D/*.model files inside a .3MF archive."""
    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")
    min_z, max_z = float("inf"), float("-inf")

    vertex_re = re.compile(
        r'<vertex\s+x="([-\d\.eE]+)"\s+y="([-\d\.eE]+)"\s+z="([-\d\.eE]+)"'
    )

    found_vertices = False
    for name in namelist:
        if name.lower().endswith(".model"):
            model_text = zf.read(name).decode("utf-8", errors="ignore")
            for vm in vertex_re.finditer(model_text):
                vx = float(vm.group(1))
                vy = float(vm.group(2))
                vz = float(vm.group(3))
                found_vertices = True
                if vx < min_x:
                    min_x = vx
                if vx > max_x:
                    max_x = vx
                if vy < min_y:
                    min_y = vy
                if vy > max_y:
                    max_y = vy
                if vz < min_z:
                    min_z = vz
                if vz > max_z:
                    max_z = vz

    if found_vertices and max_x > min_x and max_y > min_y and max_z > min_z:
        return {
            "x_mm": round(max_x - min_x, 2),
            "y_mm": round(max_y - min_y, 2),
            "z_mm": round(max_z - min_z, 2),
            "source": "3mf_mesh_vertices",
        }
    return None


def analyze_slicer_upload(
    file_bytes: bytes,
    filename: str,
    custom_boxes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Parse filament weight (g), print hours, bed temperature, and object X/Y/Z bounding box.
    2. Add +2.0 inches clearance padding (1 inch on all sides).
    3. Test 3D rotational fit across all 6 orientations against active stock boxes.
    4. Return combined slicer metadata and optimal packaging fit.
    """
    lower_name = filename.lower()
    if lower_name.endswith(".3mf"):
        slicer_meta = parse_3mf_bytes(file_bytes, filename)
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        slicer_meta = parse_gcode_text(text, filename)

    bbox_in = slicer_meta["bbox_in"]
    packaging_fit = solve_3d_box_fit(
        obj_x_in=bbox_in["x"],
        obj_y_in=bbox_in["y"],
        obj_z_in=bbox_in["z"],
        clearance_padding_in=2.0,
        boxes=custom_boxes,
    )

    slicer_meta["packaging_fit"] = packaging_fit
    return slicer_meta

