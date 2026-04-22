"""
extract_data.py  (DYNAMIC VERSION)
------------------------------------
Extracts ALL data from ANY building inspection report PDF.
- No hardcoded impacted areas, photo ranges, or structure
- Auto-detects photo layout from any appendix
- Auto-detects thermal images from any thermal PDF
- Raw text is passed to LLM to infer all structure dynamically
"""

import fitz
import re
import base64
import io
import os
from PIL import Image

# ---------------------------------------------------------------------------
# CONFIG — set via environment or direct assignment
# ---------------------------------------------------------------------------
SAMPLE_REPORT_PATH  = os.getenv("SAMPLE_REPORT_PATH",  "/Users/lavishdevoura/Downloads/ProjectFoWork/data/Sample Report.pdf")
THERMAL_REPORT_PATH = os.getenv("THERMAL_REPORT_PATH", "/Users/lavishdevoura/Downloads/ProjectFoWork/data/Thermal Images.pdf")   # optional

MAX_PHOTOS     = 200       # safety cap
PHOTO_SCALE    = 2.2       # rasterization scale (~158 DPI)
THERMAL_SCALE  = 1.4
THUMB_MAX      = 400       # thumbnail max px
THERMAL_THUMB  = 700

MIN_IMG_W      = 80        # px — skip tiny decorative images
MIN_IMG_H      = 80
MIN_BBOX_W     = 80
MIN_BBOX_H     = 80
BANNER_W_MIN   = 1500      # wide short header banners
BANNER_H_MAX   = 300


# ---------------------------------------------------------------------------
# LOW-LEVEL HELPERS
# ---------------------------------------------------------------------------

def _img_to_b64(img: Image.Image, max_dim: int = THUMB_MAX, quality: int = 82) -> str:
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _crop_b64(doc: fitz.Document, page_idx: int,
              bbox: tuple, scale: float = PHOTO_SCALE) -> str:
    page = doc[page_idx]
    pw, ph = page.rect.width, page.rect.height
    pad  = 3
    clip = fitz.Rect(
        max(0,  bbox[0] - pad), max(0,  bbox[1] - pad),
        min(pw, bbox[2] + pad), min(ph, bbox[3] + pad),
    )
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return _img_to_b64(img)


def _sorted_bboxes(doc: fitz.Document, page_idx: int) -> list[dict]:
    """
    Return de-duplicated photo bboxes on a page, sorted reading-order.
    Works for any PDF regardless of photo grid layout.
    """
    seen, result = set(), []
    for info in doc[page_idx].get_image_info(xrefs=True):
        bbox = info.get("bbox", ())
        w, h = info.get("width", 0), info.get("height", 0)
        if len(bbox) != 4:
            continue
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        key = (round(bbox[0]), round(bbox[1]))
        if key in seen:
            continue
        if w < MIN_IMG_W or h < MIN_IMG_H:
            continue
        if bw < MIN_BBOX_W or bh < MIN_BBOX_H:
            continue
        if w > BANNER_W_MIN and h < BANNER_H_MAX:
            continue
        seen.add(key)
        result.append({"bbox": bbox, "y": bbox[1], "x": bbox[0], "page_idx": page_idx})

    result.sort(key=lambda p: (round(p["y"] / 40) * 40, p["x"]))
    return result


# ---------------------------------------------------------------------------
# STEP 1 — EXTRACT FULL TEXT FROM REPORT
# ---------------------------------------------------------------------------

def extract_report_text(pdf_path: str) -> dict:
    """
    Extract all text from each page of the PDF.
    Returns:
        {
          "pages":     {1: "text...", 2: "text...", ...},
          "full_text": "concatenated text",
          "page_count": N,
          "meta": { author, title, subject, creator, keywords }
        }
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

    print(f"  [Text] {len(pages_text)} pages extracted, "
          f"{len(full_text)} chars total")

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


# ---------------------------------------------------------------------------
# STEP 2 — AUTO-DETECT AND EXTRACT PHOTOS
# ---------------------------------------------------------------------------

def _find_appendix_start(doc: fitz.Document, full_text: str) -> int:
    """
    Find the page where the full-size photo appendix begins.
    Key insight: appendix pages have images but very little text
    (just 'Photo N' labels = under 15 words).
    Body pages with thumbnails have images AND descriptions (50+ words).
    """
    pages_text = {}
    for i in range(len(doc)):
        pages_text[i] = doc[i].get_text().lower().strip()

    # Strategy 1: page whose first meaningful line is exactly "appendix"
    for i, txt in pages_text.items():
        lines    = [l.strip() for l in txt.split('\n') if l.strip()]
        meaningful = [l for l in lines if len(l) > 2]
        if meaningful and meaningful[0] == "appendix":
            return i

    # Strategy 2: first page with 2+ images AND word count under 15
    # Body thumbnail pages: 50+ words
    # Pure appendix photo pages: just "Photo N" labels = under 15 words
    for i in range(len(doc)):
        bboxes     = _sorted_bboxes(doc, i)
        word_count = len(pages_text[i].split())
        if len(bboxes) >= 2 and word_count < 15:
            return i

    # Strategy 3: keyword match anywhere on page (last resort)
    appendix_keywords = ["appendix", "photographs", "photo evidence",
                         "site photos", "photo documentation", "annexure"]
    for i, txt in pages_text.items():
        if any(kw in txt for kw in appendix_keywords):
            return i

    # Fallback
    return int(len(doc) * 0.55)

def extract_all_photos(pdf_path: str) -> dict:
    """
    Auto-detect the appendix and extract all photos.
    Returns {photo_number: base64_data_uri}
    Works for any PDF regardless of photos per page or total count.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    appendix_start = _find_appendix_start(doc, "")
    print(f"  [Photos] Appendix detected starting at page {appendix_start + 1} "
          f"of {total_pages}")

    all_bboxes = []
    for page_idx in range(appendix_start, total_pages):
        all_bboxes.extend(_sorted_bboxes(doc, page_idx))

    # Cap to safety limit
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


# ---------------------------------------------------------------------------
# STEP 3 — EXTRACT THERMAL IMAGES (auto-detect)
# ---------------------------------------------------------------------------

def _is_thermal_page(page: fitz.Page) -> bool:
    """
    Heuristic: a thermal page typically has:
      - Temperature values (e.g. "28.5°C", "Hotspot", "Emissivity")
      - At least one image
    """
    text = page.get_text().lower()
    thermal_signals = ["hotspot", "coldspot", "emissivity", "°c",
                       "thermal", "infrared", "flir", "temperature"]
    has_signal = sum(1 for s in thermal_signals if s in text) >= 2
    has_images = len(page.get_image_info()) > 0
    return has_signal and has_images


def _parse_thermal_meta(text: str) -> dict:
    """
    Try to extract hotspot/coldspot/emissivity from thermal page text.
    Returns best-effort dict; missing fields default to "N/A".
    """
    def find(patterns, default="N/A"):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return default

    hotspot = find([
        r"(?:hotspot|max|maximum)[^\d]*([\d.]+\s*°C)",
        r"([\d.]+\s*°C)\s*(?:max|hotspot)",
        r"Max\s*Temp[.:\s]*([\d.]+)",
    ])
    coldspot = find([
        r"(?:coldspot|min|minimum)[^\d]*([\d.]+\s*°C)",
        r"([\d.]+\s*°C)\s*(?:min|coldspot)",
        r"Min\s*Temp[.:\s]*([\d.]+)",
    ])
    emissivity = find([
        r"emissivity[:\s]*([\d.]+)",
        r"e\s*=\s*([\d.]+)",
    ])
    file_id = find([
        r"([A-Z]{2}\d{5,}[A-Z]?)",
        r"File[:\s]*([A-Z0-9_\-]+)",
        r"Image[:\s]*([A-Z0-9_\-]+)",
    ])
    date = find([
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        r"Date[:\s]*([\d/\-]+)",
    ])
    area = find([
        r"(?:area|room|location)[:\s]+([A-Za-z\s]+?)(?:\n|,|;|\d)",
        r"(hall|bedroom|kitchen|bathroom|parking|balcony|living)",
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
    Auto-detect and extract ALL thermal images from a thermal PDF.
    Returns a flat list of {"b64": ..., "meta": {...}} dicts.
    Works with any thermal report regardless of page count or layout.
    """
    if not thermal_path or not os.path.exists(thermal_path):
        print("  [Thermal] No thermal report provided — skipping.")
        return []

    doc = fitz.open(thermal_path)
    results = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        if not _is_thermal_page(page):
            continue

        text = page.get_text()
        meta = _parse_thermal_meta(text)
        meta["page"] = page_idx + 1

        pix = page.get_pixmap(matrix=fitz.Matrix(THERMAL_SCALE, THERMAL_SCALE),
                              alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        b64 = _img_to_b64(img, max_dim=THERMAL_THUMB, quality=80)
        results.append({"b64": b64, "meta": meta})

        print(f"  [Thermal] Page {page_idx+1}: H={meta['hotspot']}, "
              f"C={meta['coldspot']}, Area={meta['area']}")

    doc.close()
    print(f"  [Thermal] {len(results)} thermal images extracted.")
    return results


# ---------------------------------------------------------------------------
# PUBLIC ENTRY POINT
# ---------------------------------------------------------------------------

def build_extraction_payload(
    report_path:  str = SAMPLE_REPORT_PATH,
    thermal_path: str = THERMAL_REPORT_PATH,
) -> dict:
    """
    Fully dynamic extraction — works with any building inspection PDF.

    Returns:
        {
          "report_text":     {pages, full_text, page_count, meta},
          "photo_b64":       {1: "data:...", 2: "data:...", ...},
          "thermal_images":  [{"b64": ..., "meta": {...}}, ...],
          "report_path":     str,
          "thermal_path":    str,
          "photo_count":     int,
        }
    """
    print("\n[1/3] Extracting text from report...")
    report_text = extract_report_text(report_path)

    print("\n[2/3] Extracting photos from appendix...")
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
    print(f"    Pages           : {report_text['page_count']}")
    print(f"    Text chars      : {len(report_text['full_text'])}")
    print(f"    Photos          : {len(photo_b64)}")
    print(f"    Thermal images  : {len(thermal_images)}")
    return payload