"""
generate_report.py  (SPLIT-CALL v4)
--------------------------------------
WHY TWO CALLS?
  The LLM was truncating mid-JSON because the full DDR for 7 impacted areas
  is ~17 000 chars ≈ 4 500 output tokens, right at the limit.
  Solution: split into two smaller calls that each finish comfortably.

  Call A (~3 000 output tokens): report_meta, property_info, impacted_areas_map,
                                  section_1, section_2, section_3
  Call B (~2 000 output tokens): section_4, section_5, section_6, section_7

  Both calls receive the same report text so the LLM has full context.
  Results are merged into one DDR dict before returning.

  Total tokens per report: ~22 000 input + ~5 000 output = ~27 000 tokens
  (2 API calls, but each one safely finishes within max_tokens=4000)
"""

import os
import re
import json
import time
from dotenv import load_dotenv

load_dotenv()

MAX_TEXT_CHARS = 24_000   # shared report text sent to BOTH calls


# ── LLM CLIENT ──────────────────────────────────────────────────────────────

def _get_groq_client():
    from groq import Groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY not set in .env")
    return Groq(api_key=key)


def _call_llm(prompt: str, system: str, max_tokens: int = 4000) -> str:
    provider = os.getenv("REPORT_LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.10,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()

    # elif provider == "openai":
    #     from openai import OpenAI
    #     client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    #     resp = client.chat.completions.create(
    #         model="gpt-4o",
    #         messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
    #         temperature=0.10, max_tokens=max_tokens,
    #     )
    #     return resp.choices[0].message.content.strip()

    # elif provider == "anthropic":
    #     import anthropic
    #     client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    #     resp = client.messages.create(
    #         model="claude-sonnet-4-6", max_tokens=max_tokens, system=system,
    #         messages=[{"role":"user","content":prompt}],
    #     )
    #     return resp.content[0].text.strip()

    else:
        raise ValueError(f"Unknown provider '{provider}'.")

def _call_llm_with_retry(prompt: str, system: str, 
                          max_tokens: int = 4000, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            result = _call_llm(prompt, system, max_tokens)
            stripped = result.strip()
            if stripped.endswith("}") or stripped.endswith("]"):
                return result
            print(f"[LLM] Attempt {attempt+1}: response didn't close cleanly, retrying...")
            time.sleep(2)
        except Exception as e:
            print(f"[LLM] Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    return result


# ── JSON REPAIR ──────────────────────────────────────────────────────────────

def _repair_json(raw: str) -> str:
    """Clean and repair common LLM JSON mistakes."""
    # Strip markdown fences
    if "```" in raw:
        raw = "\n".join(
            ln for ln in raw.split("\n")
            if not ln.strip().startswith("```")
        ).strip()

    # Strip preamble before first {
    brace = raw.find("{")
    if brace > 0:
        raw = raw[brace:]

    # Python literals → JSON
    raw = re.sub(r'\bNone\b',  'null',  raw)
    raw = re.sub(r'\bTrue\b',  'true',  raw)
    raw = re.sub(r'\bFalse\b', 'false', raw)

    # Smart quotes → straight
    for old, new in [("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'")]:
        raw = raw.replace(old, new)

    # Trailing commas before } or ]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)

    # Try parsing as-is first
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # Close any unclosed brackets/braces (truncation recovery)
    stack, in_str, escape = [], False, False
    for ch in raw:
        if escape:              escape = False; continue
        if ch == "\\" and in_str: escape = True; continue
        if ch == '"':           in_str = not in_str; continue
        if not in_str:
            if ch in "{[":      stack.append(ch)
            elif ch == "}" and stack and stack[-1] == "{": stack.pop()
            elif ch == "]" and stack and stack[-1] == "[": stack.pop()
    if in_str:
        raw = raw.rstrip() + '"'

    closers = {"{": "}", "[": "]"}
    for opener in reversed(stack):
        raw = raw.rstrip().rstrip(",") + "\n" + closers[opener]

    return raw


def _parse(raw: str, label: str) -> dict | None:
    """Repair and parse JSON; return None on failure."""
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        print(f"[LLM] ✗ {label} parse failed: {e}")
        print(f"[LLM]   First 600 chars:\n{repaired[:600]}")
        return None


# ── SHARED TEXT TRUNCATION ───────────────────────────────────────────────────

def _truncate(full: str) -> str:
    if len(full) <= MAX_TEXT_CHARS:
        return full
    head = int(MAX_TEXT_CHARS * 0.82)
    tail = MAX_TEXT_CHARS - head
    return (full[:head]
            + f"\n\n[...{len(full)-MAX_TEXT_CHARS} chars truncated...]\n\n"
            + full[-tail:])


# ── SYSTEM PROMPT ────────────────────────────────────────────────────────────

_SYSTEM = (
    "You are a professional building inspection report writer. "
    "Write plain English any homeowner understands. "
    "NEVER invent facts — only use what is in the provided report text. "
    "Respond with valid JSON only — no markdown fences, no text before or after the JSON."
)

# ── CALL A1: meta + impacted_areas_map only ──────────────────────────────────

def _prompt_A1(text: str, thermal_note: str, photo_count: int) -> str:
    return f"""Extract ONLY the metadata and area map from this report.
Return ONLY valid JSON. No markdown.

REPORT TEXT:
{text}

CONTEXT: {thermal_note} Total photos: {photo_count}

Return exactly this JSON:

{{
  "report_title": "Detailed Diagnostic Report (DDR)",
  "report_meta": {{
    "company_name": "",
    "report_date": "",
    "report_number": "",
    "property_address": ""
  }},
  "property_info": {{
    "property_type": "", "floors": "", "inspection_date": "",
    "inspected_by": "", "inspection_score": "",
    "previous_audit": "Yes/No/Not Available",
    "previous_repairs": "Yes/No/Not Available",
    "flagged_items": "", "total_impacted_areas": ""
  }},
  "impacted_areas_map": [
    {{
      "area_id": "IA1",
      "area_title": "Full title",
      "neg_desc": "Short label for damaged side",
      "pos_desc": "Short label for source side",
      "neg_photos": [1,2,3],
      "pos_photos": [4,5],
      "has_thermal": false
    }}
  ]
}}"""


# ── CALL A2: sections 1-3 ────────────────────────────────────────────────────

def _prompt_A2(text: str, areas_summary: str) -> str:
    return f"""You are writing sections 1-3 of a Detailed Diagnostic Report (DDR).

RULES: Only use facts from the report text. Missing info → "Not Available".
Plain English. Return ONLY valid JSON. No markdown.

REPORT TEXT:
{text}

IMPACTED AREAS (for reference):
{areas_summary}

Return exactly this JSON:

{{
  "section_1_property_issue_summary": {{
    "overview": "3 paragraphs: (1) property type/date/inspector/score/prior audits. (2) number of areas affected, common themes, general severity. (3) key checklist findings in plain English.",
    "total_affected_areas": 0,
    "high_severity_count": 0,
    "moderate_severity_count": 0,
    "low_severity_count": 0,
    "primary_problem": "One sentence: biggest root cause across all areas."
  }},
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "negative_side_description": "2-3 sentences: what was physically found on the damaged side.",
      "positive_side_description": "2-3 sentences: condition of source side and why it causes the problem.",
      "leakage_timing": "All time / Monsoon / Not sure / Not Available",
      "thermal_findings": "What thermal camera shows for this area, or Not Available."
    }}
  ],
  "section_3_probable_root_cause": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "neg_observation": "Exact impacted-side text from the report summary table.",
      "pos_observation": "Exact source-side text from the report summary table.",
      "root_cause": "2-3 sentences: WHY this problem exists.",
      "moisture_path": "One sentence: water journey from entry point to visible symptom."
    }}
  ]
}}"""

# ── CALL A: meta + sections 1-3 ─────────────────────────────────────────────

def _prompt_A(text: str, thermal_note: str, photo_count: int) -> str:
    return f"""You are writing Part A of a Detailed Diagnostic Report (DDR).

RULES: Only use facts from the report text. Missing info → "Not Available".
Plain English. Root cause = WHY, not just what was observed.
Return ONLY valid JSON. No markdown.

REPORT TEXT:
{text}

CONTEXT: {thermal_note} Total photos: {photo_count}

Return exactly this JSON (one entry per impacted area in the report):

{{
  "report_title": "Detailed Diagnostic Report (DDR)",
  "report_meta": {{
    "company_name": "",
    "report_date": "",
    "report_number": "",
    "property_address": ""
  }},
  "property_info": {{
    "property_type": "",
    "floors": "",
    "inspection_date": "",
    "inspected_by": "",
    "inspection_score": "",
    "previous_audit": "Yes/No/Not Available",
    "previous_repairs": "Yes/No/Not Available",
    "flagged_items": "",
    "total_impacted_areas": ""
  }},
  "impacted_areas_map": [
    {{
      "area_id": "IA1",
      "area_title": "Full title of this impacted area",
      "neg_desc": "Short label for damaged side",
      "pos_desc": "Short label for source side",
      "neg_photos": [1, 2, 3],
      "pos_photos": [4, 5],
      "has_thermal": false
    }}
  ],
  "section_1_property_issue_summary": {{
    "overview": "3 paragraphs: (1) property type/date/inspector/score/prior audits. (2) number of areas affected, common themes, general severity. (3) key checklist findings in plain English.",
    "total_affected_areas": 0,
    "high_severity_count": 0,
    "moderate_severity_count": 0,
    "low_severity_count": 0,
    "primary_problem": "One sentence: biggest root cause across all areas."
  }},
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "negative_side_description": "2-3 sentences: what was physically found on the damaged side.",
      "positive_side_description": "2-3 sentences: condition of source side and why it causes the problem.",
      "leakage_timing": "All time / Monsoon / Not sure / Not Available",
      "thermal_findings": "What thermal camera shows for this area, or Not Available."
    }}
  ],
  "section_3_probable_root_cause": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "neg_observation": "Exact impacted-side text from the report summary table.",
      "pos_observation": "Exact source-side text from the report summary table.",
      "root_cause": "2-3 sentences: WHY this problem exists. Connect source finding to damage effect.",
      "moisture_path": "One sentence: water journey from entry point to visible symptom."
    }}
  ]
}}

VERIFY: section_3 has one entry per area. No empty strings — use "Not Available". Photo arrays use integers only.
"""


# ── CALL B: sections 4-7 ────────────────────────────────────────────────────

def _prompt_B(text: str, areas_summary: str) -> str:
    return f"""You are writing Part B of a Detailed Diagnostic Report (DDR).

RULES: Only use facts from the report text. Missing info → "Not Available".
Plain English. Return ONLY valid JSON. No markdown.

REPORT TEXT:
{text}

IMPACTED AREAS (from Part A, for reference):
{areas_summary}

Return exactly this JSON (one entry per impacted area listed above):

{{
  "section_4_severity_assessment": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "severity": "High / Moderate / Low",
      "severity_score": 7,
      "reasoning": "2-3 specific fact-based reasons from the report.",
      "urgency": "Immediate Action Required / Repairs Needed Soon / Monitor and Review"
    }}
  ],
  "section_5_recommended_actions": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "priority": "P1 / P2 / P3",
      "action_title": "Short clear repair name.",
      "treatment_method": "Numbered step-by-step repair in plain English.",
      "estimated_cost_range": "Not Available",
      "expected_outcome": "What will be resolved and roughly when."
    }}
  ],
  "section_6_additional_notes": {{
    "general_observations": "Overall property condition not tied to one area. Not Available if nothing notable.",
    "preventive_measures": "3-5 practical things the owner can do to prevent recurrence.",
    "monitoring_advice": "What to watch for after repairs to confirm success.",
    "contractor_note": "What type of contractor to hire and what to ask for.",
    "warranty_note": "Warranty info from report, or Not Available."
  }},
  "section_7_missing_or_unclear_information": [
    {{
      "item": "Specific information that is absent or unclear.",
      "impact": "How this gap reduces diagnostic confidence.",
      "recommendation": "What additional test or inspection would fill this gap."
    }}
  ]
}}

VERIFY: severity_score is an integer. One entry per area in sections 4 and 5. No empty strings.
"""


# ── MAIN ─────────────────────────────────────────────────────────────────────

def generate_ddr(payload: dict) -> dict:
    provider = os.getenv("REPORT_LLM_PROVIDER", "groq").lower()
    print(f"\n[LLM] Provider  : {provider.upper()}")

    text         = _truncate(payload["report_text"]["full_text"])
    n_thermal    = len(payload["thermal_images"])
    thermal_note = f"{n_thermal} thermal images captured." if n_thermal else "No thermal images."
    photo_count  = payload["photo_count"]

    # ── CALL A1: meta + impacted_areas_map ──────────────────────────────────
    prompt_a1 = _prompt_A1(text, thermal_note, photo_count)
    print(f"[LLM] Call A1 prompt : {len(prompt_a1):,} chars")

    raw_a1 = _call_llm_with_retry(prompt_a1, _SYSTEM, max_tokens=2000)
    print(f"[LLM] Call A1 response: {len(raw_a1):,} chars")

    part_a1 = _parse(raw_a1, "Call A1")
    if part_a1 is None:
        return {"error": "Call A1 JSON parse failed", "raw_response": raw_a1}

    # ── BUILD AREAS SUMMARY FOR A2 AND B ────────────────────────────────────
    areas = part_a1.get("impacted_areas_map", [])
    areas_summary = "\n".join(
        f'- {ia["area_id"]}: {ia["area_title"]} '
        f'(neg: {ia.get("neg_desc","?")}, pos: {ia.get("pos_desc","?")})'
        for ia in areas
    )
    print(f"[LLM] {len(areas)} impacted areas found in Call A1")

    # ── CALL A2: sections 1-3 ────────────────────────────────────────────────
    time.sleep(2)

    prompt_a2 = _prompt_A2(text, areas_summary)
    print(f"[LLM] Call A2 prompt : {len(prompt_a2):,} chars")

    raw_a2 = _call_llm_with_retry(prompt_a2, _SYSTEM, max_tokens=3000)
    print(f"[LLM] Call A2 response: {len(raw_a2):,} chars")

    part_a2 = _parse(raw_a2, "Call A2")
    if part_a2 is None:
        return {"error": "Call A2 JSON parse failed", "raw_response": raw_a2}

    # ── CALL B: sections 4-7 ─────────────────────────────────────────────────
    time.sleep(2)

    prompt_b = _prompt_B(text, areas_summary)
    print(f"[LLM] Call B prompt : {len(prompt_b):,} chars")

    raw_b  = _call_llm_with_retry(prompt_b,  _SYSTEM, max_tokens=3000)
    print(f"[LLM] Call B response: {len(raw_b):,} chars")

    part_b = _parse(raw_b, "Call B")
    if part_b is None:
        return {"error": "Call B JSON parse failed", "raw_response": raw_b}

    # ── MERGE all 3 parts ────────────────────────────────────────────────────
    ddr = {**part_a1, **part_a2, **part_b}

    # Validate all required keys exist
    required = [
        "property_info", "impacted_areas_map",
        "section_1_property_issue_summary",
        "section_2_area_wise_observations",
        "section_3_probable_root_cause",
        "section_4_severity_assessment",
        "section_5_recommended_actions",
        "section_6_additional_notes",
    ]
    missing = [k for k in required if k not in ddr]
    if missing:
        print(f"[LLM] ✗ Missing keys after merge: {missing}")
        return {"error": f"Missing keys: {missing}", "raw_a1": raw_a1,
                "raw_a2": raw_a2, "raw_b": raw_b}

    # Backfill missing root cause fields
    obs_map = {o["area_id"]: o for o in ddr.get("section_2_area_wise_observations", [])}
    for rc in ddr.get("section_3_probable_root_cause", []):
        if not rc.get("neg_observation"):
            rc["neg_observation"] = obs_map.get(rc["area_id"], {}).get(
                "negative_side_description", "Not Available")
        if not rc.get("pos_observation"):
            rc["pos_observation"] = obs_map.get(rc["area_id"], {}).get(
                "positive_side_description", "Not Available")
        rc.setdefault("moisture_path", "Not Available")

    # Force severity_score to int
    for s in ddr.get("section_4_severity_assessment", []):
        try:
            s["severity_score"] = int(s["severity_score"])
        except (TypeError, ValueError, KeyError):
            s["severity_score"] = 5

    n_rc = len(ddr.get("section_3_probable_root_cause", []))
    print(f"[LLM] ✓ Merged DDR : {len(areas)} areas, {n_rc} root cause entries")
    return ddr