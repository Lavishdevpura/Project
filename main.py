"""
main.py  — DDR Generator entry point
--------------------------------------
Run:  python3 main.py
      REPORT_LLM_PROVIDER=groq python3 main.py

What it does:
  1. Extracts text + photos + thermal from PDF
  2. Calls LLM to generate DDR JSON
  3. Saves JSON  → <report_name>_ddr.json
  4. Renders HTML → <report_name>_ddr.html   ← was silently skipped on error
"""

import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from extract_data    import build_extraction_payload
from generate_report import generate_ddr
from render_html     import render_html_report

# ── CONFIG ──────────────────────────────────────────────────────────────────
REPORT_PATH  = os.getenv("SAMPLE_REPORT_PATH",
               "/Users/lavishdevoura/Downloads/ProjectFoWork/data/Sample Report.pdf")
THERMAL_PATH = os.getenv("THERMAL_REPORT_PATH",
               "/Users/lavishdevoura/Downloads/ProjectFoWork/data/Thermal Images.pdf")
OUTPUT_DIR   = os.getenv("OUTPUT_DIR", ".")   # set to "output" if you want a subfolder


def main():
    stem = Path(REPORT_PATH).stem   # e.g. "Sample Report"
    out  = Path(OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stem}_ddr.json"
    html_path = out / f"{stem}_ddr.html"

    print("=" * 62)
    print("  DDR Generator — Dynamic Mode")
    print(f"  Report  : {REPORT_PATH}")
    print(f"  Thermal : {THERMAL_PATH}")
    print(f"  LLM     : {os.getenv('REPORT_LLM_PROVIDER','groq').upper()}")
    print("=" * 62)

    # ── STEP 1: EXTRACT ──────────────────────────────────────────────────
    t0 = time.time()
    payload = build_extraction_payload(REPORT_PATH, THERMAL_PATH)
    print(f"[✓] Extraction: {time.time()-t0:.1f}s  "
          f"({payload['photo_count']} photos, "
          f"{payload['report_text']['page_count']} pages)")

    # ── STEP 2: GENERATE DDR JSON ─────────────────────────────────────────
    t1 = time.time()
    ddr = generate_ddr(payload)
    print(f"[✓] LLM response: {time.time()-t1:.1f}s")

    # ── STEP 3: SAVE JSON ─────────────────────────────────────────────────
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ddr, f, indent=2, ensure_ascii=False)
    print(f"[✓] JSON saved → {json_path}")

    # ── STEP 4: CHECK FOR ERROR ──────────────────────────────────────────
    if "error" in ddr:
        print(f"\n[✗] LLM returned an error — HTML will NOT be generated.")
        print(f"    Error  : {ddr['error']}")
        print(f"    Raw JSON saved to: {json_path}")
        print("\n── Troubleshooting ──────────────────────────────────────────")
        print("  • Open the JSON file and find the broken line.")
        print("  • Common causes: LLM truncated output, invalid null/None value.")
        print("  • Try re-running — Groq sometimes fixes itself on retry.")
        print("  • If persistent: reduce MAX_TEXT_CHARS in generate_report.py")
        print("    (currently 28000) to give the LLM more room for output.")
        return

    # ── STEP 5: RENDER HTML ───────────────────────────────────────────────
    t2 = time.time()
    try:
        html = render_html_report(ddr, payload)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[✓] HTML rendered: {time.time()-t2:.1f}s → {html_path}")
        print(f"\n{'='*62}")
        print(f"  DONE!  Open this file in your browser:")
        print(f"  {html_path.resolve()}")
        print(f"{'='*62}\n")
    except Exception as e:
        print(f"[✗] HTML rendering failed: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()