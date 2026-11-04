import json
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class ListingPackSchema(BaseModel):
    title: str = Field(
        description="SEO-optimized marketplace listing title for Etsy, eBay, and Mayhem Marketplace. Must be 140 characters or fewer."
    )
    tags: List[str] = Field(
        description="Exactly 13 unique Etsy/marketplace search tags. Every tag must be 20 characters or fewer."
    )
    mayhem_description: str = Field(
        description="Markdown-formatted product description and technical spec sheet including box dimensions, weight, filament type, design source, shipping, and PLA heat care disclaimer."
    )
    social_hook: str = Field(
        description="A punchy 2-sentence script / hook for short-form video (TikTok, Instagram Reels, YouTube Shorts) showcasing the 3D-printed item."
    )


def generate_static_fallback_listing(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preserves the exact existing static template from cockpit_v2_1.html as an instant offline fallback,
    plus a default 2-sentence social_hook.
    """
    name = item.get("name") or "Gothic Skull Dice Tower"
    box_l = item.get("boxLength") or 9
    box_w = item.get("boxWidth") or 6
    box_h = item.get("boxHeight") or 4
    weight_oz = item.get("packageWeight") or 14
    material = item.get("materialType") or "PLA Pro / Tough PLA"
    source = item.get("patreonSource") or "Gilgarips 3D"

    base_title = f"{name} - Gothic Tabletop Gaming Decor & Dice Accessory, 3D Printed"
    if len(base_title) > 140:
        base_title = base_title[:137] + "..."

    tags = [
        "dice tower",
        "gothic home decor",
        "dnd accessory",
        "tabletop rpg",
        "dungeons and dragons",
        "dm gift",
        "3d printed decor",
        "dice tray",
        "gothic shelf",
        "geek gaming gift",
        "fantasy tabletop",
        "resin print",
        "rpg dice vault",
    ]

    desc = (
        f"Elevate your game table or altar with the {name}, precision crafted by Gilgarips 3D Studio in St. Clair Shores, Michigan.\n\n"
        f"SPECIFICATIONS & DIMENSIONS:\n"
        f'• Box Dimensions: {box_l}" x {box_w}" x {box_h}"\n'
        f"• Package Weight: {weight_oz} oz\n"
        f"• Material: High-grade {material} (Durable, matte artisan finish)\n"
        f"• Sourced & Designed by: {source}\n\n"
        f"SHIPPING & PACKAGING:\n"
        f"Ships securely cushioned via USPS Ground Advantage with full tracking.\n\n"
        f"DISCLAIMER:\n"
        f"Keep away from extreme heat (>125°F). Dice and tabletop miniatures shown in photos are for scale demonstration only."
    )

    social_hook = (
        f"Stop rolling critical fails on a flat table—watch how the {name} transforms every D&D session right off the print bed! "
        f"Precision printed in Michigan with {material} and available now in the Gilgarips 3D shop."
    )

    return {
        "title": base_title,
        "tags": tags,
        "mayhem_description": desc,
        "social_hook": social_hook,
        "source": "static_fallback",
    }


def _sanitize_listing_output(raw: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    fallback = generate_static_fallback_listing(item)

    title = (raw.get("title") or fallback["title"]).strip()
    if len(title) > 140:
        title = title[:137].rstrip() + "..."

    raw_tags = raw.get("tags") or []
    cleaned_tags: List[str] = []
    seen = set()
    for t in raw_tags:
        clean_t = str(t).strip().lower()[:20].strip()
        if clean_t and clean_t not in seen:
            seen.add(clean_t)
            cleaned_tags.append(clean_t)
        if len(cleaned_tags) == 13:
            break

    # Pad up to 13 unique tags from fallback if Gemini returned fewer than 13
    for ft in fallback["tags"]:
        if len(cleaned_tags) >= 13:
            break
        if ft.lower() not in seen:
            seen.add(ft.lower())
            cleaned_tags.append(ft[:20])

    mayhem_desc = (raw.get("mayhem_description") or fallback["mayhem_description"]).strip()
    social_hook = (raw.get("social_hook") or fallback["social_hook"]).strip()

    return {
        "title": title,
        "tags": cleaned_tags[:13],
        "mayhem_description": mayhem_desc,
        "social_hook": social_hook,
    }


def generate_gemini_listing_pack(
    item: Dict[str, Any],
    settings: Dict[str, Any],
    force_static: bool = False,
) -> Dict[str, Any]:
    """
    Calls Google Gemini using the official `google-genai` SDK with a structured JSON output schema.
    Automatically falls back to the static template if no API key is configured or if offline.
    """
    if force_static:
        return generate_static_fallback_listing(item)

    api_key = (settings.get("gemini_api_key") or "").strip()
    if not api_key:
        res = generate_static_fallback_listing(item)
        res["note"] = "No Gemini API Key configured in Admin Center; using instant static fallback."
        return res

    model_name = (settings.get("gemini_model") or "gemini-2.5-flash").strip()
    brand_persona = (
        settings.get("brand_persona")
        or "You are the copywriter for Gilgarips 3D Studio in Michigan, crafting tabletop gaming gear and gothic home decor."
    ).strip()

    prompt = (
        f"Generate a complete multi-channel e-commerce listing pack for the following 3D printed product:\n"
        f"- Product Name: {item.get('name', 'Gothic Skull Dice Tower')}\n"
        f"- Sale Price: ${item.get('salePrice', 38.00):.2f}\n"
        f"- Material / Filament Type: {item.get('materialType', 'PLA Pro / Tough PLA')}\n"
        f"- Filament Weight: {item.get('filamentGrams', 165)}g\n"
        f"- Print Duration: {item.get('printHours', 6.5)} hours\n"
        f"- Shipping Box Dimensions: {item.get('boxLength', 9)}\" x {item.get('boxWidth', 6)}\" x {item.get('boxHeight', 4)}\"\n"
        f"- Package Weight: {item.get('packageWeight', 14)} oz\n"
        f"- Design Source / Artist: {item.get('patreonSource', 'Gilgarips 3D')}\n\n"
        f"Requirements:\n"
        f"1. `title`: High-converting SEO title <= 140 characters suitable for Etsy, eBay, and Mayhem Marketplace.\n"
        f"2. `tags`: Array of EXACTLY 13 unique search tags, each <= 20 characters.\n"
        f"3. `mayhem_description`: Markdown spec sheet including an evocative hook, bulleted dimensions & filament specs, USPS Ground Advantage shipping note, and PLA heat care disclaimer (>125°F).\n"
        f"4. `social_hook`: Exactly 2 sentences designed as a short-form video hook for TikTok / Reels."
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=brand_persona,
                response_mime_type="application/json",
                response_schema=ListingPackSchema,
                temperature=0.7,
            ),
        )
        parsed = json.loads(response.text)
        sanitized = _sanitize_listing_output(parsed, item)
        sanitized["source"] = "gemini"
        sanitized["model"] = model_name
        return sanitized
    except Exception as exc:
        fallback = generate_static_fallback_listing(item)
        fallback["source"] = "static_fallback"
        fallback["error"] = f"Gemini API fallback triggered: {str(exc)}"
        return fallback

