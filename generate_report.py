"""
generate_report.py  (UNIVERSAL v5)
-------------------------------------
Works with ANY inspection/audit PDF — not just waterproofing reports.

WHAT'S NEW vs v4:
  - Step 0: Auto-detect domain from PDF text (1 cheap LLM call, ~500 tokens)
  - Domain-adaptive prompts: waterproofing, structural, electrical, fire safety,
    MEP, general property, or fully generic fallback
  - Neg/pos language replaced with domain-neutral "issue area" / "source area"
    for non-waterproofing domains
  - Split A/B call architecture retained (prevents truncation)
  - All fields default to "Not Available" — LLM never invents domain concepts
"""

import os
import re
import json
import time
from dotenv import load_dotenv

load_dotenv()

MAX_TEXT_CHARS = 24_000

# ── KNOWN DOMAINS ─────────────────────────────────────────────────────────
DOMAINS = {
    "waterproofing": "Waterproofing / Leakage / Dampness Inspection",
    "structural":    "Structural / Civil Engineering Inspection",
    "electrical":    "Electrical / Wiring / Power Systems Audit",
    "fire_safety":   "Fire Safety / Fire Protection Inspection",
    "mep":           "MEP (Mechanical, Electrical, Plumbing) Audit",
    "property":      "General Property / Home Inspection",
    "generic":       "General Inspection / Audit Report",
}


# ── LLM CLIENT ────────────────────────────────────────────────────────────

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


# ── JSON REPAIR ───────────────────────────────────────────────────────────

def _repair_json(raw: str) -> str:
    if "```" in raw:
        raw = "\n".join(
            ln for ln in raw.split("\n")
            if not ln.strip().startswith("```")
        ).strip()

    brace = raw.find("{")
    if brace > 0:
        raw = raw[brace:]

    raw = re.sub(r'\bNone\b',  'null',  raw)
    raw = re.sub(r'\bTrue\b',  'true',  raw)
    raw = re.sub(r'\bFalse\b', 'false', raw)

    for old, new in [("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'")]:
        raw = raw.replace(old, new)

    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    raw = re.sub(r'\[\s*"Not Available"\s*\]', '[]', raw)
    raw = re.sub(r'\[\s*Not Available\s*\]',   '[]', raw)

    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    stack, in_str, escape = [], False, False
    for ch in raw:
        if escape:               escape = False; continue
        if ch == "\\" and in_str: escape = True; continue
        if ch == '"':            in_str = not in_str; continue
        if not in_str:
            if ch in "{[":       stack.append(ch)
            elif ch == "}" and stack and stack[-1] == "{": stack.pop()
            elif ch == "]" and stack and stack[-1] == "[": stack.pop()

    closers = {"{": "}", "[": "]"}
    for opener in reversed(stack):
        raw = raw.rstrip().rstrip(",") + "\n" + closers[opener]

    return raw


def _parse(raw: str, label: str) -> dict | None:
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        print(f"[LLM] ✗ {label} parse failed: {e}")
        print(f"[LLM]   First 600:\n{repaired[:600]}")
        print(f"[LLM]   Line 37: {repaired.splitlines()[36] if len(repaired.splitlines()) > 36 else 'N/A'}")
        return None


def _truncate(full: str) -> str:
    if len(full) <= MAX_TEXT_CHARS:
        return full
    head = int(MAX_TEXT_CHARS * 0.82)
    tail = MAX_TEXT_CHARS - head
    return (full[:head]
            + f"\n\n[...{len(full)-MAX_TEXT_CHARS} chars truncated...]\n\n"
            + full[-tail:])


# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────

_SYSTEM = (
    "You are a professional inspection report writer. "
    "Write in plain English that any client can understand. "
    "NEVER invent facts — only use what is in the provided report text. "
    "Respond with valid JSON only — no markdown fences, no text outside the JSON."
)


# ── STEP 0: DOMAIN DETECTION ──────────────────────────────────────────────

def detect_domain(text: str) -> str:
    """
    Single cheap LLM call (~300 input + ~20 output tokens) to classify
    the PDF domain. Falls back to 'generic' if uncertain.
    """
    sample = text[:3000]   # only first 3000 chars needed for classification
    prompt = f"""Read the start of this inspection report and return ONE JSON key identifying its domain.

REPORT START:
{sample}

Return exactly this JSON with one of these domain values:
{{"domain": "waterproofing | structural | electrical | fire_safety | mep | property | generic"}}

Rules:
- waterproofing = leakage, dampness, seepage, waterproofing, moisture
- structural = cracks, RCC, beams, columns, load-bearing, foundation, concrete
- electrical = wiring, circuits, panels, earthing, load, MCB, switchgear
- fire_safety = fire alarm, sprinkler, extinguisher, exit, evacuation, NOC
- mep = HVAC, plumbing, ducting, mechanical, combined services
- property = general home/flat/commercial inspection not dominated by one system
- generic = anything else (use this if truly unsure)

Return ONLY the JSON. No explanation."""

    raw = _call_llm(prompt, "You classify inspection reports. Return only valid JSON.", max_tokens=50)
    try:
        result = json.loads(_repair_json(raw))
        domain = result.get("domain", "generic").lower().strip()
        if domain not in DOMAINS:
            domain = "generic"
        return domain
    except Exception:
        return "generic"


# ── DOMAIN-SPECIFIC FIELD DEFINITIONS ─────────────────────────────────────

def _area_fields_for_domain(domain: str) -> str:
    """
    Returns the domain-appropriate field definitions for section_2 and section_3
    so the LLM doesn't try to fill in waterproofing concepts on an electrical report.
    """
    if domain == "waterproofing":
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "negative_side_description": "2-3 sentences: what dampness/damage was found on the impacted side.",
      "positive_side_description": "2-3 sentences: what was found on the source/exposed side causing the problem.",
      "leakage_timing": "All time / Monsoon only / Not sure / Not Available",
      "thermal_findings": "What thermal imaging shows for this area, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "What was observed at the damaged/impacted location.",
      "source_observation": "What was found at the source/cause location.",
      "root_cause": "2-3 sentences: WHY this problem exists. Connect source finding to damage effect.",
      "water_path": "One sentence: journey of water from entry point to visible symptom."
    }}
  ]"""

    elif domain == "structural":
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "observation_description": "2-3 sentences: what structural defect was found and where.",
      "affected_elements": "Which structural elements are involved (column, beam, slab, wall, foundation).",
      "crack_pattern": "Type and pattern of cracks if any (hairline, diagonal, vertical, horizontal), or Not Available.",
      "thermal_findings": "Thermal imaging findings if available, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "Exact description of the structural defect found.",
      "likely_cause": "What is most likely causing this structural issue.",
      "root_cause": "2-3 sentences: WHY this structural problem exists.",
      "structural_risk": "One sentence on what risk this poses if left unaddressed."
    }}
  ]"""

    elif domain == "electrical":
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "observation_description": "2-3 sentences: what electrical issue was found and where.",
      "affected_components": "Which components are involved (wiring, panel, MCB, earthing, socket, etc.).",
      "compliance_status": "Compliant / Non-compliant / Partially compliant / Not Available",
      "thermal_findings": "Thermal imaging findings for hotspots if available, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "What electrical fault or non-compliance was observed.",
      "applicable_standard": "Relevant code or standard if mentioned in report, or Not Available.",
      "root_cause": "2-3 sentences: WHY this electrical problem exists.",
      "safety_risk": "One sentence on the safety risk if this is left unaddressed."
    }}
  ]"""

    elif domain == "fire_safety":
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "observation_description": "2-3 sentences: what fire safety issue was found and where.",
      "affected_system": "Which fire safety system is involved (alarm, sprinkler, extinguisher, exit, signage).",
      "compliance_status": "Compliant / Non-compliant / Partially compliant / Not Available",
      "last_service_date": "Last service or inspection date if mentioned, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "What fire safety deficiency was observed.",
      "applicable_standard": "Relevant fire code or NBC clause if mentioned, or Not Available.",
      "root_cause": "2-3 sentences: WHY this fire safety issue exists.",
      "life_safety_risk": "One sentence on the life safety risk if unaddressed."
    }}
  ]"""

    elif domain == "mep":
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "observation_description": "2-3 sentences: what MEP issue was found and where.",
      "service_type": "Which service is affected: Mechanical / Electrical / Plumbing / HVAC / Other",
      "affected_components": "Specific components involved.",
      "thermal_findings": "Thermal imaging findings if available, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "What MEP fault was observed.",
      "service_impact": "How this affects building services or occupants.",
      "root_cause": "2-3 sentences: WHY this MEP problem exists.",
      "urgency_note": "One sentence on what happens if this is not fixed soon."
    }}
  ]"""

    else:
        # property, generic — neutral language
        return """
  "section_2_area_wise_observations": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "observation_description": "2-3 sentences: what issue was found and where.",
      "condition": "Good / Fair / Poor / Critical",
      "additional_findings": "Any other relevant detail found at this location, or Not Available.",
      "thermal_findings": "Thermal imaging findings if available, or Not Available."
    }}
  ],
  "section_3_issue_analysis": [
    {{
      "area_id": "IA1",
      "area_title": "",
      "problem_observation": "What problem was observed.",
      "contributing_factors": "What conditions or factors are contributing to this problem.",
      "root_cause": "2-3 sentences: WHY this problem exists.",
      "impact": "One sentence on the impact of this issue on the property or occupants."
    }}
  ]"""


def _recommendations_label(domain: str) -> str:
    """Domain-appropriate label for the recommended actions section."""
    labels = {
        "waterproofing": "waterproofing repair and sealing",
        "structural":    "structural repair or reinforcement",
        "electrical":    "electrical rectification or replacement",
        "fire_safety":   "fire safety compliance action",
        "mep":           "MEP service repair or replacement",
        "property":      "repair or maintenance",
        "generic":       "corrective action",
    }
    return labels.get(domain, "corrective action")


# ── CALL A: meta + sections 1-3 ──────────────────────────────────────────

# ── CALL A1: meta + section 1 only ──────────────────────────────────────

def _prompt_A1(text, thermal_note, photo_count, domain, domain_label):
    return f"""You are writing Part A1 of a DDR. Domain: {domain_label}

RULES: Only use facts from the report. Missing → "Not Available". Return ONLY valid JSON.

REPORT TEXT:
{text}

CONTEXT: {thermal_note} Total photos: {photo_count}

Return exactly this JSON:
{{
  "report_title": "Detailed Diagnostic Report (DDR)",
  "domain": "{domain}",
  "domain_label": "{domain_label}",
  "report_meta": {{
    "company_name": "", "report_date": "", "report_number": "", "property_address": ""
  }},
  "property_info": {{
    "property_type": "", "floors": "", "inspection_date": "", "inspected_by": "",
    "inspection_score": "", "previous_audit": "Yes / No / Not Available",
    "previous_repairs": "Yes / No / Not Available",
    "flagged_items": "", "total_impacted_areas": ""
  }},
  "impacted_areas_map": [
    {{
      "area_id": "IA1",
      "area_title": "Full descriptive title",
      "primary_desc": "Short label for main issue",
      "source_desc": "Short label for cause/source",
      "primary_photos": [1, 2, 3],
      "source_photos": [4, 5],
      "has_thermal": false
    }}
  ],
  "section_1_summary": {{
    "overview": "3 paragraphs...",
    "total_affected_areas": 0,
    "high_severity_count": 0,
    "moderate_severity_count": 0,
    "low_severity_count": 0,
    "primary_problem": "One sentence: biggest issue."
  }}
}}
No empty strings — use "Not Available". Photo arrays contain integers only.
"""


# ── CALL A2: sections 2 + 3 ──────────────────────────────────────────────

def _prompt_A2(text, areas_summary, domain, domain_label):
    area_fields = _area_fields_for_domain(domain)
    # Strip the outer braces from area_fields snippet so it fits in a new prompt
    return f"""You are writing Part A2 of a DDR. Domain: {domain_label}

RULES: Only use facts from the report. Missing → "Not Available". Return ONLY valid JSON.

REPORT TEXT:
{text}

ISSUE AREAS TO COVER (one entry each):
{areas_summary}

Return exactly this JSON:
{{{area_fields}
}}

VERIFY: Both arrays have exactly one entry per area listed above.
No empty strings — use "Not Available". Photo arrays contain integers only.
"""

# ── CALL B: sections 4-7 ─────────────────────────────────────────────────

def _prompt_B(text: str, areas_summary: str,
              domain: str, domain_label: str, rec_label: str) -> str:
    return f"""You are writing Part B of a Detailed Diagnostic Report (DDR).
Domain: {domain_label}

RULES:
- Only use facts from the report text. Missing info → "Not Available".
- Plain English. Return ONLY valid JSON. No markdown.

REPORT TEXT:
{text}

ISSUE AREAS (from Part A):
{areas_summary}

Return exactly this JSON (one entry per issue area listed above):

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
      "action_title": "Short clear name of the {rec_label} needed.",
      "treatment_method": "Numbered step-by-step instructions in plain English.",
      "estimated_cost_range": "Not Available",
      "expected_outcome": "What will be fixed and roughly when."
    }}
  ],
  "section_6_additional_notes": {{
    "general_observations": "Overall property condition not tied to one specific area. Not Available if nothing notable.",
    "preventive_measures": "3-5 practical things the owner/manager can do to prevent recurrence.",
    "monitoring_advice": "What to check after repairs to confirm they worked.",
    "contractor_note": "What type of specialist to hire and what to ask for.",
    "warranty_note": "Any warranty or guarantee info from the report, or Not Available."
  }},
  "section_7_missing_or_unclear_information": [
    {{
      "item": "What specific information is absent or unclear in the report.",
      "impact": "How this gap reduces diagnostic confidence.",
      "recommendation": "What additional test or inspection would fill this gap."
    }}
  ]
}}

VERIFY: severity_score is an integer. Sections 4 and 5 have one entry per area. No empty strings.
"""


# ── MAIN ──────────────────────────────────────────────────────────────────

def generate_ddr(payload: dict) -> dict:
    provider = os.getenv("REPORT_LLM_PROVIDER", "groq").lower()
    print(f"\n[LLM] Provider  : {provider.upper()}")

    text         = _truncate(payload["report_text"]["full_text"])
    n_thermal    = len(payload["thermal_images"])
    thermal_note = f"{n_thermal} thermal images captured." if n_thermal else "No thermal images."
    photo_count  = payload["photo_count"]

    # ── STEP 0: DOMAIN DETECTION ─────────────────────────────────────────
    print(f"[LLM] Detecting domain...")
    domain = detect_domain(text)
    domain_label = DOMAINS.get(domain, "General Inspection / Audit Report")
    print(f"[LLM] Domain    : {domain} → {domain_label}")
    time.sleep(1)

    rec_label = _recommendations_label(domain)

    # ── CALL A ───────────────────────────────────────────────────────────
    # ── CALL A1 ──────────────────────────────────────────────────────────
    prompt_a1 = _prompt_A1(text, thermal_note, photo_count, domain, domain_label)
    print(f"[LLM] Call A1 prompt: {len(prompt_a1):,} chars")
    raw_a1 = _call_llm(prompt_a1, _SYSTEM, max_tokens=4000)
    print(f"[LLM] Call A1 response: {len(raw_a1):,} chars")

    part_a1 = _parse(raw_a1, "Call A1")
    if part_a1 is None:
        return {"error": "Call A1 JSON parse failed", "raw_response": raw_a1}

    areas = part_a1.get("impacted_areas_map", [])
    areas_summary = "\n".join(
        f'- {ia["area_id"]}: {ia["area_title"]} '
        f'(issue: {ia.get("primary_desc","?")}, source: {ia.get("source_desc","?")})'
        for ia in areas
    )
    print(f"[LLM] {len(areas)} issue areas found")
    time.sleep(1)

    # ── CALL A2 ──────────────────────────────────────────────────────────
    prompt_a2 = _prompt_A2(text, areas_summary, domain, domain_label)
    print(f"[LLM] Call A2 prompt: {len(prompt_a2):,} chars")
    raw_a2 = _call_llm(prompt_a2, _SYSTEM, max_tokens=4000)
    print(f"[LLM] Call A2 response: {len(raw_a2):,} chars")

    part_a2 = _parse(raw_a2, "Call A2")
    if part_a2 is None:
        return {"error": "Call A2 JSON parse failed", "raw_response": raw_a2}

    time.sleep(2)

    # ── CALL B ───────────────────────────────────────────────────────────
    prompt_b = _prompt_B(text, areas_summary, domain, domain_label, rec_label)
    print(f"[LLM] Call B prompt : {len(prompt_b):,} chars")

    raw_b = _call_llm(prompt_b, _SYSTEM, max_tokens=4000)
    print(f"[LLM] Call B response: {len(raw_b):,} chars")

    part_b = _parse(raw_b, "Call B")
    if part_b is None:
        return {"error": "Call B JSON parse failed", "raw_response": raw_b}

    # ── MERGE ─────────────────────────────────────────────────────────────
    ddr = {**part_a1, **part_a2, **part_b}

    required = [
        "property_info", "impacted_areas_map",
        "section_1_summary",
        "section_2_area_wise_observations",
        "section_3_issue_analysis",
        "section_4_severity_assessment",
        "section_5_recommended_actions",
        "section_6_additional_notes",
    ]
    missing = [k for k in required if k not in ddr]
    if missing:
        print(f"[LLM] ✗ Missing keys: {missing}")
        return {"error": f"Missing keys: {missing}", "raw_a1": raw_a1, "raw_a2": raw_a2, "raw_b": raw_b}

    # Backfill root cause fields from observations if missing
    obs_map = {o["area_id"]: o for o in ddr.get("section_2_area_wise_observations", [])}
    for rc in ddr.get("section_3_issue_analysis", []):
        for fill_key in ("problem_observation", "source_observation", "root_cause",
                         "water_path", "structural_risk", "safety_risk",
                         "life_safety_risk", "urgency_note", "impact"):
            if not rc.get(fill_key):
                # Try to pull from observations as a fallback
                obs = obs_map.get(rc.get("area_id", ""), {})
                rc[fill_key] = obs.get("observation_description",
                               obs.get("negative_side_description", "Not Available"))

    # Force severity_score to int
    for s in ddr.get("section_4_severity_assessment", []):
        try:
            s["severity_score"] = int(s["severity_score"])
        except (TypeError, ValueError, KeyError):
            s["severity_score"] = 5

    n_rc = len(ddr.get("section_3_issue_analysis", []))
    print(f"[LLM] ✓ Merged DDR  : {len(areas)} areas, {n_rc} analysis entries, domain={domain}")
    return ddr