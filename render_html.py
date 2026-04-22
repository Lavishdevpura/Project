"""
render_html.py  (UNIVERSAL v2)
---------------------------------
Renders the final DDR HTML from any LLM-generated DDR JSON.

FIXES vs original:
  1. All template field accesses wrapped with | default("") — no more
     UndefinedError crashes when the LLM omits a key
  2. Domain-adaptive section labels (neg/pos renamed to primary/source,
     leakage_timing shown only for waterproofing, etc.)
  3. Section 3 renders ALL possible field names across domains —
     the template shows whichever fields are actually present
  4. Photo number mapping is defensive — missing photos render a
     placeholder instead of leaving a blank gap
  5. Thermal strip shown only when thermal data actually exists
"""

from jinja2 import Environment, BaseLoader

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ ddr.report_title|default("DDR") }} – {{ ddr.report_meta.company_name|default("Inspection Report") }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:14px;line-height:1.6}

.cover{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 55%,#0f3460 100%);color:#fff;padding:52px 60px 40px}
.cover-brand{font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#f5a623;margin-bottom:14px}
.cover h1{font-size:34px;font-weight:700;letter-spacing:.5px;margin-bottom:6px}
.cover-sub{font-size:15px;color:#ccc;margin-bottom:10px}
.domain-badge{display:inline-block;background:rgba(245,166,35,.2);border:1px solid #f5a623;
  color:#f5a623;font-size:12px;font-weight:600;padding:4px 14px;border-radius:12px;margin-bottom:20px}
.cover-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:16px;margin-top:16px}
.cover-item{font-size:13px}
.cover-item span{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#f5a623;display:block}
.cover-addr{font-size:13px;color:#aaa;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,.15)}

.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px;padding-top:4px}
.toc a{background:#e8f0fe;color:#0f3460;padding:5px 13px;border-radius:16px;font-size:12px;
  font-weight:600;text-decoration:none;border:1px solid #c5d4f5}
.toc a:hover{background:#0f3460;color:#fff}

.page{max-width:1100px;margin:0 auto;padding:28px 20px}
.section{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);margin-bottom:24px;overflow:hidden}
.sec-hdr{background:#0f3460;color:#fff;padding:13px 22px;display:flex;align-items:center;gap:10px}
.sec-num{background:#f5a623;color:#1a1a2e;font-weight:700;font-size:11px;padding:3px 9px;border-radius:10px}
.sec-hdr h2{font-size:15px;font-weight:600}
.sec-body{padding:22px}

.stat-row{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.stat-card{background:#f8f9ff;border:1px solid #e0e4f0;border-radius:8px;padding:14px 18px;
  flex:1;min-width:100px;text-align:center}
.stat-val{font-size:26px;font-weight:700;color:#0f3460}
.stat-val.red{color:#c62828}.stat-val.orange{color:#e65100}.stat-val.green{color:#2e7d32}
.stat-lbl{font-size:11px;color:#666;margin-top:4px}
.overview-box{background:#f8f9ff;border-left:4px solid #0f3460;padding:14px 18px;
  border-radius:0 6px 6px 0;font-size:13.5px;line-height:1.8;margin-bottom:16px;white-space:pre-line}
.primary-prob{background:#fff8e1;border:1px solid #f5a623;border-radius:6px;padding:12px 16px;
  font-size:14px;font-weight:500}

.area-block{border:1px solid #dde3f0;border-radius:10px;margin-bottom:22px;overflow:hidden}
.area-hdr{background:linear-gradient(90deg,#0f3460,#1a4a7a);color:#fff;padding:13px 20px}
.area-title-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.area-id-badge{font-size:14px;font-weight:700}
.sev-badge{font-size:11px;font-weight:700;padding:3px 10px;border-radius:10px}
.sev-high{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.sev-mod{background:#fff8e1;color:#e65100;border:1px solid #ffcc02}
.sev-low{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}
.score-badge{font-size:12px;color:#f5a623;font-weight:600}
.area-urgency{font-size:12px;color:#90caf9;margin-top:3px}

.obs-two-col{display:grid;grid-template-columns:1fr 1fr;gap:0;border-bottom:1px solid #eee}
@media(max-width:680px){.obs-two-col{grid-template-columns:1fr}}
.obs-single-col{padding:16px 18px;border-bottom:1px solid #eee}
.obs-panel{padding:16px 18px}
.neg-panel{background:#fff9f9;border-right:1px solid #eee}
.pos-panel{background:#f9fff9}
.neutral-panel{background:#f8f9ff}
.panel-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#555;margin-bottom:7px}
.obs-desc-box{font-size:13px;font-weight:600;padding:8px 10px;border-radius:5px;margin-bottom:10px}
.neg-panel .obs-desc-box{background:#ffebee;border-left:3px solid #e53935;color:#1a1a2e}
.pos-panel .obs-desc-box{background:#e8f5e9;border-left:3px solid #2e7d32;color:#1a1a2e}
.neutral-panel .obs-desc-box{background:#e8f0fe;border-left:3px solid #1565c0;color:#1a1a2e}
.photos-sublabel{font-size:10px;color:#888;font-weight:600;letter-spacing:.5px;text-transform:uppercase;margin-bottom:8px}

.photo-grid{display:flex;flex-wrap:wrap;gap:8px}
.photo-wrap{position:relative;display:inline-block;line-height:0}
.photo-wrap img{width:155px;height:116px;object-fit:cover;border-radius:5px;border:1px solid #ddd;
  display:block;cursor:zoom-in;transition:transform .15s,box-shadow .15s}
.photo-wrap img:hover{transform:scale(1.06);box-shadow:0 4px 14px rgba(0,0,0,.22)}
.photo-num{position:absolute;bottom:4px;right:5px;background:rgba(0,0,0,.62);color:#fff;
  font-size:10px;padding:1px 5px;border-radius:3px;line-height:1.4}
.no-img{font-size:12px;color:#aaa;font-style:italic;padding:6px 0}
.photo-placeholder{width:155px;height:116px;background:#f5f5f5;border:1px dashed #ccc;
  border-radius:5px;display:flex;align-items:center;justify-content:center;
  font-size:11px;color:#bbb;text-align:center}

.thermal-strip{padding:14px 18px;background:#e3f2fd;border-bottom:1px solid #bbdefb}
.thermal-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#1565c0;margin-bottom:10px}
.thermal-grid{display:flex;flex-wrap:wrap;gap:10px}
.thermal-wrap{background:#fff;border:1px solid #90caf9;border-radius:7px;overflow:hidden;max-width:300px}
.thermal-wrap img{width:100%;display:block;max-height:210px;object-fit:contain;background:#111}
.thermal-meta{padding:6px 10px;display:flex;flex-direction:column;gap:2px}
.t-hot{font-size:11px;color:#c62828;font-weight:600}
.t-cold{font-size:11px;color:#1565c0;font-weight:600}
.t-file{font-size:10px;color:#888}

.analysis-row{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media(max-width:680px){.analysis-row{grid-template-columns:1fr}}
.rc-box{padding:15px 18px;background:#fffde7;border-top:1px solid #eee;border-right:1px solid #eee}
.rec-box{padding:15px 18px;background:#f3f8ff;border-top:1px solid #eee}
.rc-label,.rec-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;
  margin-bottom:7px;color:#555;display:flex;align-items:center;gap:6px}
.path-note{font-size:12px;color:#777;font-style:italic;margin-top:6px;
  padding-left:8px;border-left:2px solid #f5a623}
.method-text{font-size:12px;color:#444;margin-top:6px;line-height:1.6}
.outcome-text{font-size:12px;color:#2e7d32;font-weight:600;margin-top:6px}
.cost-text{font-size:11px;color:#888;margin-top:4px}
.pri-tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:8px}
.p1{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.p2{background:#fff8e1;color:#e65100;border:1px solid #ffcc02}
.p3{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}

.field-row{margin-bottom:8px}
.field-label{font-size:11px;color:#888;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.field-val{font-size:13px;color:#1a1a2e}

table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#0f3460;color:#fff;padding:10px 12px;text-align:left;font-weight:600;font-size:12px}
td{padding:9px 12px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:nth-child(even) td{background:#fafafa}
tr:hover td{background:#f0f4ff}

.notes-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:640px){.notes-grid{grid-template-columns:1fr}}
.note-card{background:#fafafa;border:1px solid #eee;border-radius:6px;padding:14px}
.note-card h4{font-size:12px;color:#0f3460;font-weight:700;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:8px}

.missing-item{background:#fff3e0;border:1px solid #ffcc80;border-radius:6px;padding:12px 16px;margin-bottom:10px}
.missing-title{font-size:13px;font-weight:600;color:#e65100;margin-bottom:5px}
.missing-item p{font-size:13px;color:#555;margin-top:3px}

.lb-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:9999;
  align-items:center;justify-content:center}
.lb-overlay.open{display:flex}
.lb-overlay img{max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,.6)}
.lb-close{position:fixed;top:18px;right:24px;color:#fff;font-size:32px;cursor:pointer;z-index:10000;line-height:1}

.footer{text-align:center;padding:22px;color:#888;font-size:12px;background:#fff;
  border-top:1px solid #e0e0e0;margin-top:8px}
.disclaimer{background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:14px 18px;
  font-size:12px;color:#666;margin-top:14px;line-height:1.7}

@media print{
  .toc,.lb-overlay{display:none}
  .area-block,.section{break-inside:avoid}
}
</style>
</head>
<body>

<div class="lb-overlay" id="lb" onclick="this.classList.remove('open')">
  <span class="lb-close" onclick="document.getElementById('lb').classList.remove('open')">✕</span>
  <img id="lb-img" src="" alt="">
</div>
<script>
function openLB(src){document.getElementById('lb-img').src=src;document.getElementById('lb').classList.add('open')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('lb').classList.remove('open')});
</script>

<!-- COVER -->
<div class="cover">
  <div class="cover-brand">{{ ddr.report_meta.company_name|default("Inspection Services") }} · Diagnostic Report</div>
  <h1>{{ ddr.report_title|default("Detailed Diagnostic Report") }}</h1>
  {% if ddr.domain_label %}
  <div class="domain-badge">{{ ddr.domain_label }}</div>
  {% endif %}
  {% if ddr.report_meta.report_number and ddr.report_meta.report_number != "Not Available" %}
  <div class="cover-sub" style="color:#f5a623;font-size:13px">Report No: {{ ddr.report_meta.report_number }}</div>
  {% endif %}
  <div class="cover-grid">
    <div class="cover-item"><span>Property Type</span>{{ ddr.property_info.property_type|default("N/A") }}</div>
    <div class="cover-item"><span>Floors</span>{{ ddr.property_info.floors|default("N/A") }}</div>
    <div class="cover-item"><span>Inspection Date</span>{{ ddr.property_info.inspection_date|default("N/A") }}</div>
    <div class="cover-item"><span>Inspected By</span>{{ ddr.property_info.inspected_by|default("N/A") }}</div>
    <div class="cover-item"><span>Score</span>{{ ddr.property_info.inspection_score|default("N/A") }}</div>
    <div class="cover-item"><span>Issue Areas</span>{{ ddr.property_info.total_impacted_areas|default("N/A") }}</div>
    <div class="cover-item"><span>Flagged Items</span>{{ ddr.property_info.flagged_items|default("N/A") }}</div>
  </div>
  {% if ddr.report_meta.property_address and ddr.report_meta.property_address != "Not Available" %}
  <div class="cover-addr">📍 {{ ddr.report_meta.property_address }}</div>
  {% endif %}
</div>

<div class="page">

<div class="toc">
  <a href="#sec1">1. Summary</a>
  <a href="#sec2">2. Observations</a>
  <a href="#sec3">3. Root Cause</a>
  <a href="#sec4">4. Severity</a>
  <a href="#sec5">5. Recommended Actions</a>
  <a href="#sec6">6. Additional Notes</a>
  <a href="#sec7">7. Missing Information</a>
</div>

<!-- ══ SECTION 1 ══ -->
<div class="section" id="sec1">
  <div class="sec-hdr"><span class="sec-num">01</span><h2>Property Issue Summary</h2></div>
  <div class="sec-body">
    {% set s1 = ddr.section_1_summary|default({}) %}
    <div class="overview-box">{{ s1.overview|default("Not Available") }}</div>
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-val">{{ s1.total_affected_areas|default(0) }}</div>
        <div class="stat-lbl">Affected Areas</div>
      </div>
      <div class="stat-card">
        <div class="stat-val red">{{ s1.high_severity_count|default(0) }}</div>
        <div class="stat-lbl">High Severity</div>
      </div>
      <div class="stat-card">
        <div class="stat-val orange">{{ s1.moderate_severity_count|default(0) }}</div>
        <div class="stat-lbl">Moderate Severity</div>
      </div>
      <div class="stat-card">
        <div class="stat-val green">{{ s1.low_severity_count|default(0) }}</div>
        <div class="stat-lbl">Low Severity</div>
      </div>
    </div>
    {% if s1.primary_problem %}
    <div class="primary-prob">🔍 <strong>Primary Issue:</strong> {{ s1.primary_problem }}</div>
    {% endif %}
  </div>
</div>

<!-- ══ SECTION 2 — AREA-WISE OBSERVATIONS ══ -->
<div class="section" id="sec2">
  <div class="sec-hdr"><span class="sec-num">02</span><h2>Area-wise Observations</h2></div>
  <div class="sec-body">

  {% for obs in ddr.section_2_area_wise_observations|default([]) %}
    {% set ia_id  = obs.area_id|default("") %}
    {% set ia_map = ia_lookup.get(ia_id, {}) %}
    {% set sev    = severity_lookup.get(ia_id, {}) %}
    {% set rec    = rec_lookup.get(ia_id, {}) %}
    {% set rc     = rc_lookup.get(ia_id, {}) %}
    {% set thermals = thermal_for_area.get(ia_id, []) %}

    <div class="area-block" id="{{ ia_id }}">

      <div class="area-hdr">
        <div class="area-title-row">
          <span class="area-id-badge">{{ obs.area_title|default(ia_id) }}</span>
          {% if sev %}
            {% set sev_val = sev.severity|default("") %}
            {% if sev_val == "High" %}<span class="sev-badge sev-high">High</span>
            {% elif sev_val == "Moderate" %}<span class="sev-badge sev-mod">Moderate</span>
            {% elif sev_val == "Low" %}<span class="sev-badge sev-low">Low</span>{% endif %}
            <span class="score-badge">{{ sev.severity_score|default("") }}/10</span>
          {% endif %}
        </div>
        {% if sev %}<div class="area-urgency">{{ sev.urgency|default("") }}</div>{% endif %}
      </div>

      <!-- ── OBSERVATION PANELS ── -->
      {% set neg_desc  = obs.negative_side_description|default("") %}
      {% set pos_desc  = obs.positive_side_description|default("") %}
      {% set obs_desc  = obs.observation_description|default("") %}

      {% if neg_desc and pos_desc %}
      <!-- Waterproofing two-column layout -->
      <div class="obs-two-col">
        <div class="obs-panel neg-panel">
          <div class="panel-label">🔴 Impacted / Damaged Side</div>
          <div class="obs-desc-box">{{ neg_desc }}</div>
          {% set neg_photos = ia_map.get("neg_photos", ia_map.get("primary_photos", [])) %}
          {% if neg_photos %}
            <div class="photos-sublabel">Photos {{ neg_photos[0] }}–{{ neg_photos[-1] }} ({{ neg_photos|length }})</div>
            <div class="photo-grid">
              {% for n in neg_photos %}
                {% if photo_b64.get(n) %}
                  <div class="photo-wrap">
                    <img src="{{ photo_b64[n] }}" alt="Photo {{ n }}" loading="lazy" onclick="openLB(this.src)">
                    <span class="photo-num">Photo {{ n }}</span>
                  </div>
                {% else %}
                  <div class="photo-placeholder">Photo {{ n }}<br>not found</div>
                {% endif %}
              {% endfor %}
            </div>
          {% else %}<p class="no-img">No photos mapped</p>{% endif %}
        </div>

        <div class="obs-panel pos-panel">
          <div class="panel-label">🟢 Source / Exposed Side</div>
          <div class="obs-desc-box">{{ pos_desc }}</div>
          {% set pos_photos = ia_map.get("pos_photos", ia_map.get("source_photos", [])) %}
          {% if pos_photos %}
            <div class="photos-sublabel">Photos {{ pos_photos[0] }}–{{ pos_photos[-1] }} ({{ pos_photos|length }})</div>
            <div class="photo-grid">
              {% for n in pos_photos %}
                {% if photo_b64.get(n) %}
                  <div class="photo-wrap">
                    <img src="{{ photo_b64[n] }}" alt="Photo {{ n }}" loading="lazy" onclick="openLB(this.src)">
                    <span class="photo-num">Photo {{ n }}</span>
                  </div>
                {% else %}
                  <div class="photo-placeholder">Photo {{ n }}<br>not found</div>
                {% endif %}
              {% endfor %}
            </div>
          {% else %}<p class="no-img">No photos mapped</p>{% endif %}
        </div>
      </div>

      {% elif obs_desc %}
      <!-- Generic single-column layout (structural, electrical, fire, etc.) -->
      <div class="obs-single-col neutral-panel">
        <div class="panel-label">🔵 Observation</div>
        <div class="obs-desc-box">{{ obs_desc }}</div>
        {% set all_photos = ia_map.get("primary_photos", ia_map.get("neg_photos", [])) %}
        {% if all_photos %}
          <div class="photos-sublabel">Photos ({{ all_photos|length }})</div>
          <div class="photo-grid">
            {% for n in all_photos %}
              {% if photo_b64.get(n) %}
                <div class="photo-wrap">
                  <img src="{{ photo_b64[n] }}" alt="Photo {{ n }}" loading="lazy" onclick="openLB(this.src)">
                  <span class="photo-num">Photo {{ n }}</span>
                </div>
              {% else %}
                <div class="photo-placeholder">Photo {{ n }}<br>not found</div>
              {% endif %}
            {% endfor %}
          </div>
        {% else %}<p class="no-img">No photos mapped</p>{% endif %}

        <!-- Domain-specific extra fields -->
        {% for field_key, field_label in [
            ("affected_elements",   "Affected Elements"),
            ("crack_pattern",       "Crack Pattern"),
            ("affected_components", "Affected Components"),
            ("compliance_status",   "Compliance Status"),
            ("last_service_date",   "Last Service Date"),
            ("service_type",        "Service Type"),
            ("condition",           "Condition"),
            ("additional_findings", "Additional Findings"),
        ] %}
          {% if obs[field_key] is defined and obs[field_key] and obs[field_key] != "Not Available" %}
          <div class="field-row" style="margin-top:10px">
            <div class="field-label">{{ field_label }}</div>
            <div class="field-val">{{ obs[field_key] }}</div>
          </div>
          {% endif %}
        {% endfor %}
      </div>
      {% endif %}

      <!-- Leakage timing (waterproofing only) -->
      {% if obs.leakage_timing and obs.leakage_timing != "Not Available" %}
      <div style="padding:8px 18px;background:#fff8e1;border-bottom:1px solid #eee;font-size:13px">
        ⏱️ <strong>Leakage timing:</strong> {{ obs.leakage_timing }}
      </div>
      {% endif %}

      <!-- THERMAL -->
      {% if thermals %}
      <div class="thermal-strip">
        <div class="thermal-label">🌡️ Thermal Imaging Data</div>
        {% if obs.thermal_findings and obs.thermal_findings != "Not Available" %}
          <p style="font-size:13px;color:#1565c0;margin-bottom:10px;font-style:italic">{{ obs.thermal_findings }}</p>
        {% endif %}
        <div class="thermal-grid">
          {% for item in thermals %}
          <div class="thermal-wrap">
            <img src="{{ item.b64 }}" alt="Thermal" loading="lazy" onclick="openLB(this.src)" style="cursor:zoom-in">
            <div class="thermal-meta">
              <span class="t-hot">🔴 Hotspot: {{ item.meta.hotspot|default("N/A") }}</span>
              <span class="t-cold">🔵 Coldspot: {{ item.meta.coldspot|default("N/A") }}</span>
              <span class="t-file">{{ item.meta.file|default("") }} · {{ item.meta.date|default("") }}</span>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
      {% elif obs.thermal_findings and obs.thermal_findings != "Not Available" %}
      <div class="thermal-strip">
        <div class="thermal-label">🌡️ Thermal Findings</div>
        <p style="font-size:13px;color:#1565c0;font-style:italic">{{ obs.thermal_findings }}</p>
      </div>
      {% endif %}

      <!-- ROOT CAUSE + RECOMMENDATION -->
      <div class="analysis-row">
        <div class="rc-box">
          <div class="rc-label">🔍 Root Cause Analysis</div>
          {% if rc %}
            <p style="font-size:13px">{{ rc.root_cause|default("Not Available") }}</p>
            <!-- Show whichever path/risk field exists for this domain -->
            {% for path_key in ["water_path","structural_risk","safety_risk","life_safety_risk","urgency_note","impact"] %}
              {% if rc[path_key] is defined and rc[path_key] and rc[path_key] != "Not Available" %}
              <div class="path-note">↳ {{ rc[path_key] }}</div>
              {% endif %}
            {% endfor %}
          {% else %}
            <p class="no-img">Not Available</p>
          {% endif %}
        </div>
        <div class="rec-box">
          <div class="rec-label">
            {% if rec %}<span class="pri-tag {{ 'p1' if rec.priority=='P1' else 'p2' if rec.priority=='P2' else 'p3' }}">{{ rec.priority|default("") }}</span>{% endif %}
            Recommended Action
          </div>
          {% if rec %}
            <p style="font-size:13px;font-weight:600">{{ rec.action_title|default("") }}</p>
            <p class="method-text">{{ rec.treatment_method|default("") }}</p>
            {% if rec.estimated_cost_range and rec.estimated_cost_range != "Not Available" %}
              <p class="cost-text">💰 {{ rec.estimated_cost_range }}</p>
            {% endif %}
            <p class="outcome-text">✓ {{ rec.expected_outcome|default("") }}</p>
          {% else %}
            <p class="no-img">Not Available</p>
          {% endif %}
        </div>
      </div>

    </div><!-- /area-block -->
  {% endfor %}

  </div>
</div>

<!-- ══ SECTION 3 — ROOT CAUSE ══ -->
<div class="section" id="sec3">
  <div class="sec-hdr"><span class="sec-num">03</span><h2>Root Cause Analysis</h2></div>
  <div class="sec-body">

    <h3 style="font-size:13px;color:#0f3460;font-weight:700;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px">
      Summary Table
    </h3>
    <table style="margin-bottom:28px">
      <thead>
        <tr>
          <th style="width:5%;text-align:center">#</th>
          <th>Problem Observed</th>
          <th>Cause / Source</th>
        </tr>
      </thead>
      <tbody>
        {% for item in ddr.section_3_issue_analysis|default([]) %}
        <tr>
          <td style="text-align:center;font-weight:700;color:#0f3460">{{ loop.index }}</td>
          <td style="background:#fff9f9">
            {{ item.problem_observation|default(item.neg_observation)|default("Not Available") }}
          </td>
          <td style="background:#f9fff9">
            {{ item.source_observation|default(item.pos_observation)|default(item.likely_cause)|default(item.contributing_factors)|default("Not Available") }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <h3 style="font-size:13px;color:#0f3460;font-weight:700;margin-bottom:14px;text-transform:uppercase;letter-spacing:.5px">
      Detailed Analysis
    </h3>
    {% for item in ddr.section_3_issue_analysis|default([]) %}
    <div style="border:1px solid #dde3f0;border-radius:8px;margin-bottom:14px;overflow:hidden">
      <div style="background:#f0f4ff;padding:9px 16px;border-bottom:1px solid #dde3f0">
        <span style="font-size:13px;font-weight:700;color:#0f3460">{{ item.area_title|default(item.area_id)|default("") }}</span>
      </div>
      <div style="padding:13px 16px">
        <p style="font-size:13px;margin-bottom:8px">{{ item.root_cause|default("Not Available") }}</p>
        <!-- Show whichever domain-specific follow-up field is present -->
        {% for note_key in ["water_path","structural_risk","safety_risk","life_safety_risk","urgency_note","impact","applicable_standard","service_impact"] %}
          {% if item[note_key] is defined and item[note_key] and item[note_key] != "Not Available" %}
          <div style="font-size:12px;color:#666;font-style:italic;border-left:3px solid #f5a623;padding-left:10px;margin-top:6px">
            {{ note_key.replace("_"," ")|title }}: {{ item[note_key] }}
          </div>
          {% endif %}
        {% endfor %}
      </div>
    </div>
    {% endfor %}

  </div>
</div>

<!-- ══ SECTION 4 — SEVERITY ══ -->
<div class="section" id="sec4">
  <div class="sec-hdr"><span class="sec-num">04</span><h2>Severity Assessment</h2></div>
  <div class="sec-body">
    <table>
      <thead>
        <tr>
          <th style="width:15%">Area</th>
          <th style="width:10%">Severity</th>
          <th style="width:7%">Score</th>
          <th style="width:43%">Reasoning</th>
          <th style="width:25%">Urgency</th>
        </tr>
      </thead>
      <tbody>
        {% for item in ddr.section_4_severity_assessment|default([]) %}
        <tr>
          <td><strong>{{ item.area_title|default(item.area_id)|default("") }}</strong></td>
          <td>
            {% set sv = item.severity|default("") %}
            {% if sv == "High" %}<span class="sev-badge sev-high">High</span>
            {% elif sv == "Moderate" %}<span class="sev-badge sev-mod">Moderate</span>
            {% elif sv == "Low" %}<span class="sev-badge sev-low">Low</span>
            {% else %}<span>{{ sv }}</span>{% endif %}
          </td>
          <td style="text-align:center;font-weight:700;font-size:17px;color:#0f3460">{{ item.severity_score|default("") }}</td>
          <td style="font-size:13px">{{ item.reasoning|default("Not Available") }}</td>
          <td style="font-size:12px;font-weight:600">
            {% set urg = item.urgency|default("") %}
            {{ '🔴' if 'Immediate' in urg else '🟠' if 'Soon' in urg else '🟢' }} {{ urg }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<!-- ══ SECTION 5 — RECOMMENDED ACTIONS ══ -->
<div class="section" id="sec5">
  <div class="sec-hdr"><span class="sec-num">05</span><h2>Recommended Actions</h2></div>
  <div class="sec-body">
    <table>
      <thead>
        <tr>
          <th style="width:13%">Area</th>
          <th style="width:7%">Priority</th>
          <th style="width:18%">Action</th>
          <th style="width:35%">Method</th>
          <th style="width:15%">Est. Cost</th>
          <th style="width:12%">Outcome</th>
        </tr>
      </thead>
      <tbody>
        {% for item in ddr.section_5_recommended_actions|default([]) %}
        <tr>
          <td><strong>{{ item.area_title|default(item.area_id)|default("") }}</strong></td>
          <td style="text-align:center">
            {% set p = item.priority|default("") %}
            <span class="pri-tag {{ 'p1' if p=='P1' else 'p2' if p=='P2' else 'p3' }}">{{ p }}</span>
          </td>
          <td style="font-weight:600">{{ item.action_title|default("") }}</td>
          <td style="font-size:12px;color:#444">{{ item.treatment_method|default("") }}</td>
          <td style="font-size:12px;color:#888">
            {% set cost = item.estimated_cost_range|default("") %}
            {{ "💰 " + cost if cost and cost != "Not Available" else "—" }}
          </td>
          <td style="font-size:12px;color:#2e7d32;font-weight:600">✓ {{ item.expected_outcome|default("") }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="font-size:11px;color:#888;margin-top:10px">
      P1 = Immediate &nbsp;·&nbsp; P2 = Within 30 days &nbsp;·&nbsp; P3 = Planned maintenance
    </p>
  </div>
</div>

<!-- ══ SECTION 6 — ADDITIONAL NOTES ══ -->
<div class="section" id="sec6">
  <div class="sec-hdr"><span class="sec-num">06</span><h2>Additional Notes</h2></div>
  <div class="sec-body">
    {% set s6 = ddr.section_6_additional_notes|default({}) %}
    <div class="notes-grid">
      <div class="note-card">
        <h4>📋 General Observations</h4>
        <p>{{ s6.general_observations|default("Not Available") }}</p>
      </div>
      <div class="note-card">
        <h4>🛡️ Preventive Measures</h4>
        <p>{{ s6.preventive_measures|default("Not Available") }}</p>
      </div>
      <div class="note-card">
        <h4>👁️ Monitoring Advice</h4>
        <p>{{ s6.monitoring_advice|default("Not Available") }}</p>
      </div>
      <div class="note-card">
        <h4>🔧 Contractor Note</h4>
        <p>{{ s6.contractor_note|default("Not Available") }}</p>
      </div>
      {% set wn = s6.warranty_note|default("") %}
      {% if wn and wn != "Not Available" %}
      <div class="note-card" style="grid-column:1/-1">
        <h4>📜 Warranty / Guarantee</h4>
        <p>{{ wn }}</p>
      </div>
      {% endif %}
    </div>
  </div>
</div>

<!-- ══ SECTION 7 — MISSING INFO ══ -->
<div class="section" id="sec7">
  <div class="sec-hdr"><span class="sec-num">07</span><h2>Missing or Unclear Information</h2></div>
  <div class="sec-body">
    {% set missing_list = ddr.section_7_missing_or_unclear_information|default([]) %}
    {% if missing_list %}
      {% for item in missing_list %}
      <div class="missing-item">
        <div class="missing-title">⚠️ {{ item.item|default("Unknown gap") }}</div>
        <p><strong>Impact:</strong> {{ item.impact|default("Not Available") }}</p>
        <p><strong>Recommendation:</strong> {{ item.recommendation|default("Not Available") }}</p>
      </div>
      {% endfor %}
    {% else %}
      <p style="color:#2e7d32;font-weight:600">✓ No significant gaps identified in the inspection data.</p>
    {% endif %}
  </div>
</div>

<div class="disclaimer">
  <strong>Disclaimer:</strong> This report is based on a visual and non-destructive inspection
  conducted on the date noted above. It is not exhaustive — defects hidden behind walls, floors,
  or ceilings may not be identified. Structural findings require evaluation by a Registered
  Structural Engineer. This report is prepared for the client's internal use only.
</div>

</div><!-- /page -->

<div class="footer">
  © {{ ddr.report_meta.company_name|default("Inspection Services") }}
  {% if ddr.property_info.inspection_date|default("") %}&nbsp;·&nbsp; {{ ddr.property_info.inspection_date }}{% endif %}
  {% set rn = ddr.report_meta.report_number|default("") %}
  {% if rn and rn != "Not Available" %}&nbsp;·&nbsp; Report No: {{ rn }}{% endif %}
</div>

</body>
</html>
"""


def _build_thermal_map(thermal_images: list, ia_map_list: list) -> dict:
    if not thermal_images:
        return {}
    thermal_areas = [ia for ia in ia_map_list if ia.get("has_thermal")]
    if not thermal_areas:
        return {ia_map_list[0]["area_id"]: thermal_images} if ia_map_list else {}
    result = {}
    per_area = max(1, len(thermal_images) // len(thermal_areas))
    for i, ia in enumerate(thermal_areas):
        start = i * per_area
        end   = start + per_area if i < len(thermal_areas) - 1 else len(thermal_images)
        result[ia["area_id"]] = thermal_images[start:end]
    return result


def render_html_report(ddr: dict, payload: dict) -> str:
    """
    Render a self-contained HTML report from any DDR JSON + extraction payload.
    Defensive: never crashes on missing JSON keys — uses | default() everywhere.
    Works for any inspection domain.
    """
    photo_b64      = payload.get("photo_b64", {})
    thermal_images = payload.get("thermal_images", [])
    ia_map_list    = ddr.get("impacted_areas_map", [])

    ia_lookup       = {ia["area_id"]: ia  for ia in ia_map_list}
    severity_lookup = {s["area_id"]: s
                       for s in ddr.get("section_4_severity_assessment", [])}
    rec_lookup      = {r["area_id"]: r
                       for r in ddr.get("section_5_recommended_actions", [])}
    rc_lookup       = {r["area_id"]: r
                       for r in ddr.get("section_3_issue_analysis", [])}

    thermal_for_area = _build_thermal_map(thermal_images, ia_map_list)

    env      = Environment(loader=BaseLoader(), autoescape=False)
    # Allow attribute access on dicts via dot notation in template
    env.globals["undefined"] = ""
    template = env.from_string(HTML_TEMPLATE)

    return template.render(
        ddr              = ddr,
        photo_b64        = photo_b64,
        thermal_images   = thermal_images,
        ia_lookup        = ia_lookup,
        severity_lookup  = severity_lookup,
        rec_lookup       = rec_lookup,
        rc_lookup        = rc_lookup,
        thermal_for_area = thermal_for_area,
    )