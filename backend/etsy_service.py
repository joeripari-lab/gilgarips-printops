import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class EtsyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image_urls: List[str] = []
        self.listing_title: Optional[str] = None
        self.in_title: bool = False
        self.json_ld_blocks: List[str] = []
        self.in_script: bool = False
        self.script_type: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}
        
        # 1. Meta og:image or twitter:image
        if tag == "meta":
            prop = attr_dict.get("property") or attr_dict.get("name")
            content = attr_dict.get("content")
            if prop in ("og:image", "twitter:image") and content:
                self._add_image_url(content)
            elif prop in ("og:title", "twitter:title") and content and not self.listing_title:
                self.listing_title = content.replace(" | Etsy", "").strip()

        # 2. img tags (src, data-src, data-full-image-href, etc.)
        elif tag == "img":
            for attr in ("data-full-image-href", "data-src-zoom-image", "data-src", "src"):
                val = attr_dict.get(attr)
                if val:
                    self._add_image_url(val)

        # 3. Scripts (especially application/ld+json or next data)
        elif tag == "script":
            self.script_type = attr_dict.get("type", "")
            if "json" in self.script_type:
                self.in_script = True

        elif tag == "title" and not self.listing_title:
            self.in_title = True

    def handle_endtag(self, tag: str):
        if tag == "script":
            self.in_script = False
            self.script_type = None
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data: str):
        if self.in_title and not self.listing_title:
            cleaned = data.replace(" | Etsy", "").strip()
            if cleaned:
                self.listing_title = cleaned
        elif self.in_script and data:
            self.json_ld_blocks.append(data)

    def _add_image_url(self, url: str):
        if not url:
            return
        if "etsystatic.com" in url or "etsy.com" in url:
            # Upgrade thumbnail URLs to high-res il_fullxfull
            upgraded = re.sub(r"/il_\d+x[N\d]+\.", "/il_fullxfull.", url)
            if upgraded not in self.image_urls:
                self.image_urls.append(upgraded)


def parse_etsy_content(html: str) -> Dict[str, Any]:
    """
    Extracts image URLs and title from raw HTML (scraped or pasted by user).
    """
    parser = EtsyHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    images: List[str] = list(parser.image_urls)
    title: Optional[str] = parser.listing_title

    # Inspect JSON-LD blocks
    for block in parser.json_ld_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                if not title and data.get("name"):
                    title = str(data["name"]).strip()
                img = data.get("image")
                if isinstance(img, list):
                    for u in img:
                        if isinstance(u, str):
                            upgraded = re.sub(r"/il_\d+x[N\d]+\.", "/il_fullxfull.", u)
                            if upgraded not in images:
                                images.append(upgraded)
                elif isinstance(img, str):
                    upgraded = re.sub(r"/il_\d+x[N\d]+\.", "/il_fullxfull.", img)
                    if upgraded not in images:
                        images.append(upgraded)
        except Exception:
            continue

    # Regex scan as fallback for any etsystatic images embedded in raw JS / HTML
    pattern = r'https://i\.etsystatic\.com/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)'
    for match in re.findall(pattern, html, re.IGNORECASE):
        # Ignore tiny avatar/shop icons if possible
        if "/isla_" in match or "/iusa_" in match:
            continue
        upgraded = re.sub(r"/il_\d+x[N\d]+\.", "/il_fullxfull.", match)
        if upgraded not in images:
            images.append(upgraded)

    return {
        "title": title,
        "images": images,
    }


def fetch_etsy_listing_images(
    listing_url: str,
    raw_html: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pulls photo URLs and metadata from an Etsy listing link or pasted HTML.
    If raw_html is provided, parses it directly (bypassing any anti-bot).
    Otherwise attempts an HTTP request with modern browser headers.
    """
    clean_url = listing_url.strip() if listing_url else ""
    
    # If raw_html is supplied, parse directly!
    if raw_html and raw_html.strip():
        parsed = parse_etsy_content(raw_html)
        return {
            "success": True,
            "url": clean_url,
            "title": parsed["title"],
            "images": parsed["images"],
            "count": len(parsed["images"]),
            "source": "pasted_html",
        }

    if not clean_url:
        return {
            "success": False,
            "error": "No Etsy URL or HTML provided.",
            "images": [],
        }

    # Normalize listing URL
    # Can accept formats like https://www.etsy.com/listing/123456789/... or just 123456789
    m = re.search(r"(\d{8,12})", clean_url)
    listing_id = m.group(1) if m else None

    # Attempt fetch
    req = urllib.request.Request(
        clean_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
            parsed = parse_etsy_content(html)
            return {
                "success": True,
                "url": clean_url,
                "listing_id": listing_id,
                "title": parsed["title"],
                "images": parsed["images"],
                "count": len(parsed["images"]),
                "source": "live_request",
            }
    except urllib.error.HTTPError as http_err:
        return {
            "success": False,
            "status_code": http_err.code,
            "listing_id": listing_id,
            "error": f"Etsy returned HTTP {http_err.code} ({http_err.reason}). Etsy anti-bot protection is active.",
            "is_blocked": http_err.code in (403, 429),
            "images": [],
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "listing_id": listing_id,
            "images": [],
        }


def download_image_bytes(image_url: str) -> Optional[bytes]:
    """
    Downloads an image from Etsy's CDN (i.etsystatic.com) or any public URL.
    Returns bytes or None on failure.
    """
    req = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.etsy.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status == 200:
                return res.read()
    except Exception:
        # Fallback to standard request without referer
        try:
            req2 = urllib.request.Request(image_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req2, timeout=15) as res2:
                if res2.status == 200:
                    return res2.read()
        except Exception:
            return None
    return None

