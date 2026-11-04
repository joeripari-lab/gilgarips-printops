import itertools
import math
from typing import Dict, Any, List, Optional, Tuple

STOCK_BOXES: List[Dict[str, Any]] = [
    {
        "id": "ups_small",
        "name": "UPS Blank Security - Small (9 × 6 × 3 in)",
        "carrier": "UPS / Ground",
        "l": 9.0,
        "w": 6.0,
        "h": 3.0,
        "active": True,
    },
    {
        "id": "ups_medium",
        "name": "UPS Blank Security - Medium (10.5 × 12 × 3 in)",
        "carrier": "UPS / Ground",
        "l": 12.0,
        "w": 10.5,
        "h": 3.0,
        "active": True,
    },
    {
        "id": "usps_box4_square",
        "name": "Poshmark / USPS Box 4 Square (7 × 7 × 6 in)",
        "carrier": "USPS Priority",
        "l": 7.0,
        "w": 7.0,
        "h": 6.0,
        "active": True,
    },
    {
        "id": "usps_o1092",
        "name": "Poshmark / USPS Box 4 O-1092 (12.125 × 13.375 × 2.75 in)",
        "carrier": "USPS Priority",
        "l": 13.375,
        "w": 12.125,
        "h": 2.75,
        "active": True,
    },
    {
        "id": "usps_o1097",
        "name": "Poshmark / USPS Box 7 O-1097 (11.25 × 14 × 2.25 in)",
        "carrier": "USPS Priority",
        "l": 14.0,
        "w": 11.25,
        "h": 2.25,
        "active": True,
    },
    {
        "id": "usps_shoebox",
        "name": "Poshmark / USPS Priority Shoe Box (14.375 × 7.5 × 5.125 in)",
        "carrier": "USPS Priority",
        "l": 14.375,
        "w": 7.5,
        "h": 5.125,
        "active": True,
    },
    {
        "id": "usps_mfrb1",
        "name": "USPS Medium Flat Rate Box 1 (11 × 8.5 × 5.5 in)",
        "carrier": "USPS Priority Flat Rate",
        "l": 11.0,
        "w": 8.5,
        "h": 5.5,
        "active": True,
    },
    {
        "id": "usps_mfrb2",
        "name": "USPS Medium Flat Rate Box 2 (13.625 × 11.875 × 3.375 in)",
        "carrier": "USPS Priority Flat Rate",
        "l": 13.625,
        "w": 11.875,
        "h": 3.375,
        "active": True,
    },
    {
        "id": "usps_lfrb",
        "name": "Poshmark / USPS Large Flat Rate Box (12 × 12 × 8 in)",
        "carrier": "USPS Priority",
        "l": 12.0,
        "w": 12.0,
        "h": 8.0,
        "active": True,
    },
    {
        "id": "7x5x4",
        "name": "Box #1: 7 × 5 × 4 in (Small Accessories)",
        "carrier": "Standard Corrugated",
        "l": 7.0,
        "w": 5.0,
        "h": 4.0,
        "active": True,
    },
    {
        "id": "9x6x4",
        "name": "Box #2: 9 × 6 × 4 in (Dice Towers / Trays)",
        "carrier": "Standard Corrugated",
        "l": 9.0,
        "w": 6.0,
        "h": 4.0,
        "active": True,
    },
    {
        "id": "12x9x4",
        "name": "Box #3: 12 × 9 × 4 in (Medium Decor / Plaques)",
        "carrier": "Standard Corrugated",
        "l": 12.0,
        "w": 9.0,
        "h": 4.0,
        "active": True,
    },
]

ORIENTATION_LABELS = [
    "X-Y-Z (Standard upright)",
    "X-Z-Y (Rolled 90° on X)",
    "Y-X-Z (Rotated 90° on Z)",
    "Y-Z-X (Tilted Y-forward)",
    "Z-X-Y (Laid flat on side A)",
    "Z-Y-X (Laid flat on side B)",
]


def solve_3d_box_fit(
    obj_x_in: float,
    obj_y_in: float,
    obj_z_in: float,
    clearance_padding_in: float = 2.0,
    boxes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Adds +2.0 inches clearance padding (1 inch on all sides) to object dimensions (in inches)
    and tests all 6 3D rotational orientations against active stock boxes.
    Selects the tightest-fitting box (minimum internal volume).
    """
    stock = boxes if boxes is not None else STOCK_BOXES
    active_boxes = [b for b in stock if b.get("active", True)]

    padded_x = round(obj_x_in + clearance_padding_in, 2)
    padded_y = round(obj_y_in + clearance_padding_in, 2)
    padded_z = round(obj_z_in + clearance_padding_in, 2)

    raw_perms: List[Tuple[float, float, float]] = list(
        itertools.permutations([padded_x, padded_y, padded_z], 3)
    )

    candidate_matches: List[Dict[str, Any]] = []

    for box in active_boxes:
        bl = float(box["l"])
        bw = float(box["w"])
        bh = float(box["h"])
        box_volume = round(bl * bw * bh, 2)

        valid_orientations = []
        for idx, (px, py, pz) in enumerate(raw_perms):
            if px <= bl + 1e-6 and py <= bw + 1e-6 and pz <= bh + 1e-6:
                valid_orientations.append(
                    {
                        "orientation_index": idx,
                        "label": ORIENTATION_LABELS[idx],
                        "aligned_dims_in": [px, py, pz],
                        "margin_in": [
                            round(bl - px, 2),
                            round(bw - py, 2),
                            round(bh - pz, 2),
                        ],
                    }
                )

        if valid_orientations:
            part_vol = padded_x * padded_y * padded_z
            fill_ratio = round((part_vol / box_volume) * 100, 1) if box_volume > 0 else 0.0
            candidate_matches.append(
                {
                    "box": box,
                    "box_volume_in3": box_volume,
                    "fill_efficiency_pct": fill_ratio,
                    "best_orientation": valid_orientations[0],
                    "valid_orientation_count": len(valid_orientations),
                }
            )

    candidate_matches.sort(key=lambda m: (m["box_volume_in3"], -m["fill_efficiency_pct"]))

    if candidate_matches:
        best = candidate_matches[0]
        return {
            "fits_stock_box": True,
            "exceeds_all_boxes": False,
            "object_dims_in": {
                "x": round(obj_x_in, 2),
                "y": round(obj_y_in, 2),
                "z": round(obj_z_in, 2),
            },
            "padded_dims_in": {
                "x": padded_x,
                "y": padded_y,
                "z": padded_z,
            },
            "clearance_added_in": clearance_padding_in,
            "selected_box": best["box"],
            "selected_orientation": best["best_orientation"],
            "box_volume_in3": best["box_volume_in3"],
            "fill_efficiency_pct": best["fill_efficiency_pct"],
            "all_fitting_boxes": [
                {
                    "id": m["box"]["id"],
                    "name": m["box"]["name"],
                    "l": m["box"]["l"],
                    "w": m["box"]["w"],
                    "h": m["box"]["h"],
                    "volume_in3": m["box_volume_in3"],
                    "fill_efficiency_pct": m["fill_efficiency_pct"],
                    "orientation": m["best_orientation"]["label"],
                }
                for m in candidate_matches
            ],
        }
    else:
        custom_l = math.ceil(max(padded_x, padded_y, padded_z))
        sorted_dims = sorted([padded_x, padded_y, padded_z], reverse=True)
        return {
            "fits_stock_box": False,
            "exceeds_all_boxes": True,
            "object_dims_in": {
                "x": round(obj_x_in, 2),
                "y": round(obj_y_in, 2),
                "z": round(obj_z_in, 2),
            },
            "padded_dims_in": {
                "x": padded_x,
                "y": padded_y,
                "z": padded_z,
            },
            "clearance_added_in": clearance_padding_in,
            "selected_box": {
                "id": "custom",
                "name": f"OVERSIZE / Custom Box Required ({math.ceil(sorted_dims[0])} × {math.ceil(sorted_dims[1])} × {math.ceil(sorted_dims[2])} in)",
                "carrier": "Custom Corrugated",
                "l": float(math.ceil(sorted_dims[0])),
                "w": float(math.ceil(sorted_dims[1])),
                "h": float(math.ceil(sorted_dims[2])),
            },
            "selected_orientation": {
                "orientation_index": 0,
                "label": "Exceeds all stock boxes - custom box needed",
                "aligned_dims_in": [padded_x, padded_y, padded_z],
                "margin_in": [0.0, 0.0, 0.0],
            },
            "box_volume_in3": round(
                math.ceil(sorted_dims[0]) * math.ceil(sorted_dims[1]) * math.ceil(sorted_dims[2]),
                2,
            ),
            "fill_efficiency_pct": 100.0,
            "all_fitting_boxes": [],
        }


def compute_shipping_details(
    weight_oz: float, length: float, width: float, height: float
) -> Dict[str, Any]:
    """Preserves exact USPS Ground Advantage Weight & DIM Logic from cockpit_v2_1.html."""
    l = math.ceil(length or 0)
    w = math.ceil(width or 0)
    h = math.ceil(height or 0)
    cubic_inches = l * w * h

    is_dim = False
    dim_weight_lbs = 0
    billable_weight_oz = weight_oz

    if cubic_inches > 1728:
        is_dim = True
        dim_weight_lbs = math.ceil(cubic_inches / 139)
        dim_weight_oz = dim_weight_lbs * 16
        if dim_weight_oz > weight_oz:
            billable_weight_oz = dim_weight_oz

    cost = 4.50
    if billable_weight_oz <= 4:
        cost = 4.50
    elif billable_weight_oz <= 8:
        cost = 4.90
    elif billable_weight_oz <= 12:
        cost = 5.50
    elif billable_weight_oz <= 15.9:
        cost = 6.20
    elif billable_weight_oz <= 32:
        cost = 8.50
    elif billable_weight_oz <= 48:
        cost = 10.50
    elif billable_weight_oz <= 64:
        cost = 12.50
    elif billable_weight_oz <= 80:
        cost = 14.50
    elif billable_weight_oz <= 112:
        cost = 17.50
    elif billable_weight_oz <= 160:
        cost = 21.00
    else:
        cost = 25.00 + (math.ceil((billable_weight_oz - 160) / 16) * 1.50)

    if cubic_inches > 3456:
        cost += 15.00

    return {
        "cubicInches": cubic_inches,
        "isDim": is_dim,
        "dimWeightLbs": dim_weight_lbs,
        "actualWeightOz": weight_oz,
        "billableWeightOz": billable_weight_oz,
        "shippingCost": cost,
    }

