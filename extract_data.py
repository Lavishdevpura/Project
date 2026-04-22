"""
extract_data.py  (UNIVERSAL v2)
---------------------------------
Extracts ALL data from ANY PDF — not just building inspection reports.

FIXES vs original:
  1. Thermal detection: requires 3+ signals AND rejects pages where the
     dominant text is non-thermal, preventing false positives
  2. Appendix detection: 30+ keywords across languages + fallback to
     image-density scan across the whole document
  3. Banner filter: dynamic — computes median image area and skips
     outlier-large images rather than using hardcoded pixel thresholds
  4. Photo sort: uses a smarter row-grouping that adapts to actual row
     height rather than assuming 40px rows
  5. Thermal metadata: brand-agnostic regex covering FLIR, Testo, Seek,
     InfiRec, Hikmicro label formats
  6. MIN_IMG size: computed from page DPI estimate, not hardcoded pixels
"""

import fitz
import re
import base64
import io
import os
import statistics
from PIL import Image

# ── CONFIG (tunable via env) ──────────────────────────────────────────────
SAMPLE_REPORT_PATH  = os.getenv("SAMPLE_REPORT_PATH",  "data/Sample Report.pdf")
THERMAL_REPORT_PATH = os.getenv("THERMAL_REPORT_PATH", "data/Thermal Images.pdf")

MAX_PHOTOS     = 200
PHOTO_SCALE    = 2.2
THERMAL_SCALE  = 1.4
THUMB_MAX      = 400
THERMAL_THUMB  = 700


# ── LOW-LEVEL HELPERS ─────────────────────────────────────────────────────

def _img_to_b64(img: Image.Image, max_dim: int = THUMB_MAX, quality: int = 82) -> str:
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _crop_b64(doc: fitz.Document, page_idx: int,
              bbox: tuple, scale: float = PHOTO_SCALE) -> str:
    page = doc[page_idx]
    pw, ph = page.rect.width, page.rect.height
    pad = 3
    clip = fitz.Rect(
        max(0,  bbox[0] - pad), max(0,  bbox[1] - pad),
        min(pw, bbox[2] + pad), min(ph, bbox[3] + pad),
    )
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return _img_to_b64(img)


def _estimate_min_image_size(doc: fitz.Document, sample_pages: int = 5) -> tuple[int, int]:
    """
    FIX #6: Estimate a sensible minimum image size from the document itself
    rather than using hardcoded 80px. Samples early pages to find the
    typical text-block height and derives a proportional threshold.
    """
    areas = []
    for i in range(min(sample_pages, len(doc))):
        for info in doc[i].get_image_info():
            w, h = info.get("width", 0), info.get("height", 0)
            if w > 10 and h > 10:
                areas.append(w * h)
    if not areas:
        return 60, 60
    median_area = statistics.median(areas)
    # Minimum = 1/20th of median area, clamped between 40 and 200px
    side = int((median_area / 20) ** 0.5)
    side = max(40, min(side, 200))
    return side, side


def _sorted_bboxes(doc: fitz.Document, page_idx: int,
                   min_w: int, min_h: int,
                   median_area: float) -> list[dict]:
    """
    FIX #3 + #4: Dynamic banner filter using median area; adaptive row grouping.
    Returns de-duplicated photo bboxes sorted in reading order.
    """
    seen, result = set(), []
    page = doc[page_idx]
    page_w, page_h = page.rect.width, page.rect.height

    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox", ())
        w, h = info.get("width", 0), info.get("height", 0)
        if len(bbox) != 4:
            continue

        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        area = bw * bh

        # Skip too-small images
        if w < min_w or h < min_h or bw < min_w or bh < min_h:
            continue

        # FIX #3: Skip banner-like images dynamically:
        # an image is a banner if it spans >80% of page width AND <15% of page height
        is_banner = (bw > page_w * 0.80) and (bh < page_h * 0.15)
        if is_banner:
            continue

        # Skip images that are more than 8× the median area (likely full-page decoratives)
        if median_area > 0 and area > median_area * 8:
            continue

        key = (round(bbox[0]), round(bbox[1]))
        if key in seen:
            continue
        seen.add(key)
        result.append({"bbox": bbox, "y": bbox[1], "x": bbox[0], "page_idx": page_idx})

    # FIX #4: Adaptive row grouping — use 1/10 of page height as row bucket size
    row_bucket = max(20, int(page_h / 10))
    result.sort(key=lambda p: (round(p["y"] / row_bucket) * row_bucket, p["x"]))
    return result


# ── STEP 1: EXTRACT TEXT ──────────────────────────────────────────────────

def extract_report_text(pdf_path: str) -> dict:
    """
    Extract all text from every page of any PDF.
    Returns pages dict, full concatenated text, page count, and PDF metadata.
    """
    doc = fitz.open(pdf_path)
    pages_text = {}
    for i in range(len(doc)):
        pages_text[i + 1] = doc[i].get_text()

    meta = doc.metadata or {}
    doc.close()

    full_text = "\n\n".join(
        f"--- Page {p} ---\n{t}"
        for p, t in pages_text.items()
        if t.strip()
    )

    print(f"  [Text] {len(pages_text)} pages, {len(full_text):,} chars total")
    return {
        "pages":      pages_text,
        "full_text":  full_text,
        "page_count": len(pages_text),
        "meta": {
            "title":    meta.get("title", ""),
            "author":   meta.get("author", ""),
            "subject":  meta.get("subject", ""),
            "creator":  meta.get("creator", ""),
            "keywords": meta.get("keywords", ""),
        }
    }


# ── STEP 2: EXTRACT PHOTOS ────────────────────────────────────────────────

# FIX #2: 30+ appendix keywords across formats and languages
_APPENDIX_KEYWORDS = [
    # English
    "appendix", "annex", "annexure", "attachment", "exhibit",
    "photographs", "photograph", "photo evidence", "photo documentation",
    "site photos", "site photographs", "site images", "field photos",
    "image gallery", "figure gallery", "figures", "plates",
    "photo appendix", "image appendix", "visual documentation",
    "inspection photos", "documentation", "pictorial",
    # Common non-English / mixed
    "annexe", "pièces jointes", "imágenes", "fotos", "fotografías",
    "bilder", "anhang", "allegato", "foto",
]

def _find_appendix_start(doc: fitz.Document) -> int:
    """
    FIX #2: Multi-strategy appendix detection.
    Strategy 1: keyword scan on all pages (not just first half)
    Strategy 2: image-density scan — first page with 3+ images that
                is in the latter 40% of the document
    Strategy 3: fallback to 55% of document length
    """
    n = len(doc)

    # Strategy 1: keyword match on any page
    for i in range(n):
        txt = doc[i].get_text().lower()
        if any(kw in txt for kw in _APPENDIX_KEYWORDS):
            # Make sure this page actually has images too
            if len(doc[i].get_image_info()) >= 1:
                return i
            # Or that the NEXT page has images
            if i + 1 < n and len(doc[i + 1].get_image_info()) >= 1:
                return i + 1

    # Strategy 2: first image-dense page in latter 40% of doc
    cutoff = int(n * 0.40)
    for i in range(cutoff, n):
        if len(doc[i].get_image_info()) >= 3:
            return i

    # Strategy 3: scan entire doc for first image-dense page
    for i in range(n):
        if len(doc[i].get_image_info()) >= 3:
            return i

    # Last resort
    return int(n * 0.55)


def extract_all_photos(pdf_path: str) -> dict:
    """
    Auto-detect appendix and extract all photos from any PDF.
    Returns {photo_number: base64_data_uri}
    """
    doc = fitz.open(pdf_path)
    n   = len(doc)

    min_w, min_h = _estimate_min_image_size(doc)

    # Compute median bbox area across whole document for banner filter
    all_areas = []
    for i in range(n):
        for info in doc[i].get_image_info():
            bbox = info.get("bbox", ())
            if len(bbox) == 4:
                all_areas.append((bbox[2]-bbox[0]) * (bbox[3]-bbox[1]))
    median_area = statistics.median(all_areas) if all_areas else 0

    appendix_start = _find_appendix_start(doc)
    print(f"  [Photos] Appendix at page {appendix_start + 1}/{n}  "
          f"(min_img={min_w}px, median_area={int(median_area)}px²)")

    all_bboxes = []
    for page_idx in range(appendix_start, n):
        all_bboxes.extend(_sorted_bboxes(doc, page_idx, min_w, min_h, median_area))

    all_bboxes = all_bboxes[:MAX_PHOTOS]
    print(f"  [Photos] {len(all_bboxes)} photo positions detected")

    photo_b64 = {}
    for i, item in enumerate(all_bboxes):
        num = i + 1
        try:
            photo_b64[num] = _crop_b64(doc, item["page_idx"], item["bbox"])
        except Exception as e:
            print(f"  [Photos] Warning: photo {num} failed: {e}")
        if num % 16 == 0:
            print(f"  [Photos] {num}/{len(all_bboxes)} extracted...")

    doc.close()
    print(f"  [Photos] Complete — {len(photo_b64)} photos extracted.")
    return photo_b64


# ── STEP 3: EXTRACT THERMAL IMAGES ───────────────────────────────────────

# FIX #1: Tighter thermal signal set — require 3+ AND exclude common false-positive words
_THERMAL_SIGNALS = [
    "hotspot", "coldspot", "emissivity", "infrared", "ir image",
    "thermal image", "flir", "testo", "seek thermal", "hikmicro",
    "infiray", "thermal camera", "radiometric",
]
_THERMAL_TEMP_PATTERN = re.compile(
    r'\d+\.?\d*\s*°[CF]|\d+\.?\d*\s*deg\s*[CF]', re.IGNORECASE
)
_NON_THERMAL_DOMINATORS = [
    "checklist", "summary table", "scope of work",
    "terms and conditions", "disclaimer",
]

def _is_thermal_page(page: fitz.Page) -> bool:
    """
    FIX #1: A thermal page must have:
      - 3+ thermal signal keywords (not just 2)
      - At least one temperature value (number + degree symbol)
      - At least one image
      - NOT dominated by non-thermal section headers
    """
    text = page.get_text().lower()

    # Reject pages dominated by non-thermal content
    if any(nd in text for nd in _NON_THERMAL_DOMINATORS):
        return False

    signal_count = sum(1 for s in _THERMAL_SIGNALS if s in text)
    has_temp     = bool(_THERMAL_TEMP_PATTERN.search(page.get_text()))
    has_image    = len(page.get_image_info()) > 0

    return signal_count >= 3 and has_temp and has_image


# FIX #5: Brand-agnostic thermal metadata patterns
def _parse_thermal_meta(text: str) -> dict:
    """
    Extracts hotspot/coldspot/emissivity from thermal pages produced by
    FLIR, Testo, Seek, InfiRec, Hikmicro, and generic IR camera software.
    """
    def find(patterns, default="N/A"):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return default

    hotspot = find([
        r"(?:hotspot|hot spot|max(?:imum)?|high(?:est)?)\s*[:\-=]?\s*([\d.]+\s*°[CF])",
        r"([\d.]+\s*°[CF])\s*(?:max|hotspot|high)",
        r"(?:sp\d+|spot\d+)\s*[:\-]?\s*([\d.]+\s*°[CF])",   # Testo-style Sp1, Sp2
        r"ar\d+\s+max\s*[:\-]?\s*([\d.]+)",                   # FLIR area max
        r"max\s+temp[.\s:]*?([\d.]+)",
    ])
    coldspot = find([
        r"(?:coldspot|cold spot|min(?:imum)?|low(?:est)?)\s*[:\-=]?\s*([\d.]+\s*°[CF])",
        r"([\d.]+\s*°[CF])\s*(?:min|coldspot|low)",
        r"ar\d+\s+min\s*[:\-]?\s*([\d.]+)",
        r"min\s+temp[.\s:]*?([\d.]+)",
    ])
    emissivity = find([
        r"emissivity\s*[:\-=]\s*([\d.]+)",
        r"\be\s*=\s*([\d.]+)",
        r"ε\s*[:\-=]\s*([\d.]+)",
    ])
    file_id = find([
        r"([A-Z]{2,4}\d{4,}[A-Z]?)",
        r"(?:file|image|img|ir)[_\s:\-]?([A-Z0-9_\-]{4,})",
        r"(\d{8}_\d{6})",   # timestamp-style filenames
    ])
    date = find([
        r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        r"(\d{4}[/\-\.]\d{2}[/\-\.]\d{2})",
        r"date\s*[:\-]?\s*(\d[\d/\-\.]+)",
    ])
    area = find([
        r"(?:area|room|location|zone|spot)\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|,|;|\d)",
        r"(hall|bedroom|kitchen|bathroom|toilet|parking|balcony|terrace|"
        r"living|lobby|corridor|staircase|roof|basement|ceiling|wall|floor)",
    ]).strip().title()

    return {
        "file":       file_id,
        "hotspot":    hotspot,
        "coldspot":   coldspot,
        "emissivity": emissivity,
        "date":       date,
        "area":       area,
    }


def extract_thermal_images(thermal_path: str) -> list[dict]:
    """
    Extract thermal images from any thermal PDF.
    Works with FLIR, Testo, Seek, InfiRec, Hikmicro report formats.
    Returns [] if no thermal path is provided or file doesn't exist.
    """
    if not thermal_path or not os.path.exists(thermal_path):
        print("  [Thermal] No thermal report — skipping.")
        return []

    doc     = fitz.open(thermal_path)
    results = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        if not _is_thermal_page(page):
            continue

        text = page.get_text()
        meta = _parse_thermal_meta(text)
        meta["page"] = page_idx + 1

        pix = page.get_pixmap(
            matrix=fitz.Matrix(THERMAL_SCALE, THERMAL_SCALE), alpha=False
        )
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        b64 = _img_to_b64(img, max_dim=THERMAL_THUMB, quality=80)
        results.append({"b64": b64, "meta": meta})

        print(f"  [Thermal] Page {page_idx+1}: "
              f"H={meta['hotspot']}, C={meta['coldspot']}, Area={meta['area']}")

    doc.close()
    print(f"  [Thermal] {len(results)} thermal images extracted.")
    return results


# ── PUBLIC ENTRY POINT ────────────────────────────────────────────────────

def build_extraction_payload(
    report_path:  str = SAMPLE_REPORT_PATH,
    thermal_path: str = THERMAL_REPORT_PATH,
) -> dict:
    """
    Universal extraction — works with any PDF document.

    Returns:
        {
          "report_text":    {pages, full_text, page_count, meta},
          "photo_b64":      {1: "data:...", 2: "data:...", ...},
          "thermal_images": [{"b64": ..., "meta": {...}}, ...],
          "report_path":    str,
          "thermal_path":   str,
          "photo_count":    int,
        }
    """
    print("\n[1/3] Extracting text...")
    report_text = extract_report_text(report_path)

    print("\n[2/3] Extracting photos...")
    photo_b64 = extract_all_photos(report_path)

    print("\n[3/3] Extracting thermal images...")
    thermal_images = extract_thermal_images(thermal_path)

    payload = {
        "report_text":    report_text,
        "photo_b64":      photo_b64,
        "thermal_images": thermal_images,
        "report_path":    report_path,
        "thermal_path":   thermal_path,
        "photo_count":    len(photo_b64),
    }

    print(f"\n[✓] Extraction complete:")
    print(f"    Pages          : {report_text['page_count']}")
    print(f"    Text chars     : {len(report_text['full_text']):,}")
    print(f"    Photos         : {len(photo_b64)}")
    print(f"    Thermal images : {len(thermal_images)}")
    return payload