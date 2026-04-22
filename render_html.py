"""
render_html.py  (DYNAMIC VERSION)
-----------------------------------
Renders the final DDR HTML from any LLM-generated DDR JSON.
- Works with any number of impacted areas
- Handles dynamic photo assignments from LLM
- Thermal images grouped by area if available
- All images embedded as base64 data URIs
"""

from jinja2 import Environment, BaseLoader

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ ddr.report_title }} – {{ ddr.report_meta.company_name }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:14px;line-height:1.6}

/* COVER */
.cover{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 55%,#0f3460 100%);color:#fff;padding:52px 60px 40px}
.cover-brand{font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#f5a623;margin-bottom:14px}
.cover h1{font-size:34px;font-weight:700;letter-spacing:.5px;margin-bottom:6px}
.cover-sub{font-size:15px;color:#ccc;margin-bottom:28px}
.cover-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:16px;margin-top:16px}
.cover-item{font-size:13px}
.cover-item span{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#f5a623;display:block}
.cover-addr{font-size:13px;color:#aaa;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,.15)}

/* TOC */
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px;padding-top:4px}
.toc a{background:#e8f0fe;color:#0f3460;padding:5px 13px;border-radius:16px;font-size:12px;font-weight:600;text-decoration:none;border:1px solid #c5d4f5}
.toc a:hover{background:#0f3460;color:#fff}

/* PAGE */
.page{max-width:1100px;margin:0 auto;padding:28px 20px}

/* SECTION */
.section{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);margin-bottom:24px;overflow:hidden}
.sec-hdr{background:#0f3460;color:#fff;padding:13px 22px;display:flex;align-items:center;gap:10px}
.sec-num{background:#f5a623;color:#1a1a2e;font-weight:700;font-size:11px;padding:3px 9px;border-radius:10px}
.sec-hdr h2{font-size:15px;font-weight:600}
.sec-body{padding:22px}

/* SUMMARY STATS */
.stat-row{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.stat-card{background:#f8f9ff;border:1px solid #e0e4f0;border-radius:8px;padding:14px 18px;flex:1;min-width:100px;text-align:center}
.stat-val{font-size:26px;font-weight:700;color:#0f3460}
.stat-val.red{color:#c62828}
.stat-val.orange{color:#e65100}
.stat-val.green{color:#2e7d32}
.stat-lbl{font-size:11px;color:#666;margin-top:4px}
.overview-box{background:#f8f9ff;border-left:4px solid #0f3460;padding:14px 18px;border-radius:0 6px 6px 0;font-size:13.5px;line-height:1.8;margin-bottom:16px}
.primary-prob{background:#fff8e1;border:1px solid #f5a623;border-radius:6px;padding:12px 16px;font-size:14px;font-weight:500}

/* AREA BLOCK */
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

/* NEG / POS PANELS */
.obs-two-col{display:grid;grid-template-columns:1fr 1fr;gap:0;border-bottom:1px solid #eee}
@media(max-width:680px){.obs-two-col{grid-template-columns:1fr}}
.obs-panel{padding:16px 18px}
.neg-panel{background:#fff9f9;border-right:1px solid #eee}
.pos-panel{background:#f9fff9}
.panel-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#555;margin-bottom:7px}
.obs-desc-box{font-size:13px;font-weight:600;padding:8px 10px;border-radius:5px;margin-bottom:10px}
.neg-panel .obs-desc-box{background:#ffebee;border-left:3px solid #e53935;color:#1a1a2e}
.pos-panel .obs-desc-box{background:#e8f5e9;border-left:3px solid #2e7d32;color:#1a1a2e}
.photos-sublabel{font-size:10px;color:#888;font-weight:600;letter-spacing:.5px;text-transform:uppercase;margin-bottom:8px}

/* PHOTO GRID */
.photo-grid{display:flex;flex-wrap:wrap;gap:8px}
.photo-wrap{position:relative;display:inline-block;line-height:0}
.photo-wrap img{width:155px;height:116px;object-fit:cover;border-radius:5px;border:1px solid #ddd;display:block;cursor:zoom-in;transition:transform .15s,box-shadow .15s}
.photo-wrap img:hover{transform:scale(1.06);box-shadow:0 4px 14px rgba(0,0,0,.22)}
.photo-num{position:absolute;bottom:4px;right:5px;background:rgba(0,0,0,.62);color:#fff;font-size:10px;padding:1px 5px;border-radius:3px;line-height:1.4}
.no-img{font-size:12px;color:#aaa;font-style:italic;padding:6px 0}

/* THERMAL STRIP */
.thermal-strip{padding:14px 18px;background:#e3f2fd;border-bottom:1px solid #bbdefb}
.thermal-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#1565c0;margin-bottom:10px}
.thermal-grid{display:flex;flex-wrap:wrap;gap:10px}
.thermal-wrap{background:#fff;border:1px solid #90caf9;border-radius:7px;overflow:hidden;max-width:300px}
.thermal-wrap img{width:100%;display:block;max-height:210px;object-fit:contain;background:#111}
.thermal-meta{padding:6px 10px;display:flex;flex-direction:column;gap:2px}
.t-hot{font-size:11px;color:#c62828;font-weight:600}
.t-cold{font-size:11px;color:#1565c0;font-weight:600}
.t-file{font-size:10px;color:#888}

/* ROOT CAUSE + REC ROW */
.rc-rec-row{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media(max-width:680px){.rc-rec-row{grid-template-columns:1fr}}
.rc-box{padding:15px 18px;background:#fffde7;border-top:1px solid #eee;border-right:1px solid #eee}
.rec-box{padding:15px 18px;background:#f3f8ff;border-top:1px solid #eee}
.rc-label,.rec-label{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;margin-bottom:7px;color:#555;display:flex;align-items:center;gap:6px}
.moisture-path{font-size:12px;color:#777;font-style:italic;margin-top:6px;padding-left:8px;border-left:2px solid #f5a623}
.method-text{font-size:12px;color:#444;margin-top:6px;line-height:1.6}
.outcome-text{font-size:12px;color:#2e7d32;font-weight:600;margin-top:6px}
.cost-text{font-size:11px;color:#888;margin-top:4px}
.pri-tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:8px}
.p1{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.p2{background:#fff8e1;color:#e65100;border:1px solid #ffcc02}
.p3{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}

/* TABLES */
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#0f3460;color:#fff;padding:10px 12px;text-align:left;font-weight:600;font-size:12px}
td{padding:9px 12px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:nth-child(even) td{background:#fafafa}
tr:hover td{background:#f0f4ff}

/* ADDITIONAL NOTES */
.notes-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:640px){.notes-grid{grid-template-columns:1fr}}
.note-card{background:#fafafa;border:1px solid #eee;border-radius:6px;padding:14px}
.note-card h4{font-size:12px;color:#0f3460;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}

/* MISSING INFO */
.missing-item{background:#fff3e0;border:1px solid #ffcc80;border-radius:6px;padding:12px 16px;margin-bottom:10px}
.missing-title{font-size:13px;font-weight:600;color:#e65100;margin-bottom:5px}
.missing-item p{font-size:13px;color:#555;margin-top:3px}

/* LIGHTBOX */
.lb-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:9999;align-items:center;justify-content:center}
.lb-overlay.open{display:flex}
.lb-overlay img{max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,.6)}
.lb-close{position:fixed;top:18px;right:24px;color:#fff;font-size:32px;cursor:pointer;z-index:10000;line-height:1}

/* FOOTER */
.footer{text-align:center;padding:22px;color:#888;font-size:12px;background:#fff;border-top:1px solid #e0e0e0;margin-top:8px}
.disclaimer{background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:14px 18px;font-size:12px;color:#666;margin-top:14px;line-height:1.7}

@media print{
  .toc,.lb-overlay{display:none}
  .area-block,.section{break-inside:avoid}
}
</style>
</head>
<body>

<!-- LIGHTBOX -->
<div class="lb-overlay" id="lb" onclick="this.classList.remove('open')">
  <span class="lb-close" onclick="document.getElementById('lb').classList.remove('open')">✕</span>
  <img id="lb-img" src="" alt="">
</div>
<script>
function openLB(src){
  document.getElementById('lb-img').src=src;
  document.getElementById('lb').classList.add('open');
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('lb').classList.remove('open')});
</script>

<!-- COVER -->
<div class="cover">
  <div class="cover-brand">{{ ddr.report_meta.company_name or "Inspection Report" }} · Detailed Diagnostic Report</div>
  <h1>{{ ddr.report_title }}</h1>
  <div class="cover-sub">Waterproofing &amp; Structural Health Assessment</div>
  {% if ddr.report_meta.report_number and ddr.report_meta.report_number != "Not Available" %}
  <div class="cover-sub" style="color:#f5a623;font-size:13px">Report No: {{ ddr.report_meta.report_number }}</div>
  {% endif %}
  <div class="cover-grid">
    <div class="cover-item"><span>Property Type</span>{{ ddr.property_info.property_type }}</div>
    <div class="cover-item"><span>Floors</span>{{ ddr.property_info.floors }}</div>
    <div class="cover-item"><span>Inspection Date</span>{{ ddr.property_info.inspection_date }}</div>
    <div class="cover-item"><span>Inspected By</span>{{ ddr.property_info.inspected_by }}</div>
    <div class="cover-item"><span>Score</span>{{ ddr.property_info.inspection_score }}</div>
    <div class="cover-item"><span>Impacted Areas</span>{{ ddr.property_info.total_impacted_areas }}</div>
    <div class="cover-item"><span>Flagged Items</span>{{ ddr.property_info.flagged_items }}</div>
  </div>
  {% if ddr.report_meta.property_address and ddr.report_meta.property_address != "Not Available" %}
  <div class="cover-addr">📍 {{ ddr.report_meta.property_address }}</div>
  {% endif %}
</div>

<div class="page">

<!-- TOC -->
<div class="toc">
  <a href="#sec1">1. Property Issue Summary</a>
  <a href="#sec2">2. Area-wise Observations</a>
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
    <div class="overview-box">{{ ddr.section_1_property_issue_summary.overview }}</div>
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-val">{{ ddr.section_1_property_issue_summary.total_affected_areas }}</div>
        <div class="stat-lbl">Affected Areas</div>
      </div>
      <div class="stat-card">
        <div class="stat-val red">{{ ddr.section_1_property_issue_summary.high_severity_count }}</div>
        <div class="stat-lbl">High Severity</div>
      </div>
      <div class="stat-card">
        <div class="stat-val orange">{{ ddr.section_1_property_issue_summary.moderate_severity_count }}</div>
        <div class="stat-lbl">Moderate Severity</div>
      </div>
      {% if ddr.section_1_property_issue_summary.low_severity_count is defined %}
      <div class="stat-card">
        <div class="stat-val green">{{ ddr.section_1_property_issue_summary.low_severity_count }}</div>
        <div class="stat-lbl">Low Severity</div>
      </div>
      {% endif %}
    </div>
    <div class="primary-prob">🔍 <strong>Primary Problem:</strong> {{ ddr.section_1_property_issue_summary.primary_problem }}</div>
  </div>
</div>

<!-- ══ SECTION 2 — AREA-WISE OBSERVATIONS ══ -->
<div class="section" id="sec2">
  <div class="sec-hdr"><span class="sec-num">02</span><h2>Area-wise Observations</h2></div>
  <div class="sec-body">

  {% for obs in ddr.section_2_area_wise_observations %}
    {% set ia_id  = obs.area_id %}
    {% set ia_map = ia_lookup.get(ia_id) %}
    {% set sev    = severity_lookup.get(ia_id) %}
    {% set rec    = rec_lookup.get(ia_id) %}
    {% set rc     = rc_cause_lookup.get(ia_id) %}
    {% set thermals = thermal_for_area.get(ia_id, []) %}

    <div class="area-block" id="{{ ia_id }}">

      <div class="area-hdr">
        <div class="area-title-row">
          <span class="area-id-badge">{{ obs.area_title }}</span>
          {% if sev %}
            {% if sev.severity == "High" %}<span class="sev-badge sev-high">High</span>
            {% elif sev.severity == "Moderate" %}<span class="sev-badge sev-mod">Moderate</span>
            {% else %}<span class="sev-badge sev-low">Low</span>{% endif %}
            <span class="score-badge">{{ sev.severity_score }}/10</span>
          {% endif %}
        </div>
        {% if sev %}<div class="area-urgency">{{ sev.urgency }}</div>{% endif %}
      </div>

      <!-- NEG / POS PANELS -->
      <div class="obs-two-col">
        <div class="obs-panel neg-panel">
          <div class="panel-label">🔴 Negative Side — Impacted Area</div>
          <div class="obs-desc-box">{{ obs.negative_side_description }}</div>
          {% if ia_map and ia_map.neg_photos %}
            <div class="photos-sublabel">
              Photographs — Photos {{ ia_map.neg_photos[0] }}–{{ ia_map.neg_photos[-1] }}
              ({{ ia_map.neg_photos | length }} photos)
            </div>
            <div class="photo-grid">
              {% for n in ia_map.neg_photos %}
                {% if photo_b64.get(n) %}
                  <div class="photo-wrap">
                    <img src="{{ photo_b64[n] }}" alt="Photo {{ n }}"
                         loading="lazy" onclick="openLB(this.src)">
                    <span class="photo-num">Photo {{ n }}</span>
                  </div>
                {% endif %}
              {% endfor %}
            </div>
          {% else %}
            <p class="no-img">No photos mapped for this side</p>
          {% endif %}
        </div>

        <div class="obs-panel pos-panel">
          <div class="panel-label">🟢 Positive Side — Source / Exposed Area</div>
          <div class="obs-desc-box">{{ obs.positive_side_description }}</div>
          {% if ia_map and ia_map.pos_photos %}
            <div class="photos-sublabel">
              Photographs — Photos {{ ia_map.pos_photos[0] }}–{{ ia_map.pos_photos[-1] }}
              ({{ ia_map.pos_photos | length }} photos)
            </div>
            <div class="photo-grid">
              {% for n in ia_map.pos_photos %}
                {% if photo_b64.get(n) %}
                  <div class="photo-wrap">
                    <img src="{{ photo_b64[n] }}" alt="Photo {{ n }}"
                         loading="lazy" onclick="openLB(this.src)">
                    <span class="photo-num">Photo {{ n }}</span>
                  </div>
                {% endif %}
              {% endfor %}
            </div>
          {% else %}
            <p class="no-img">No photos mapped for this side</p>
          {% endif %}
        </div>
      </div>

      <!-- THERMAL (if mapped) -->
      {% if thermals %}
      <div class="thermal-strip">
        <div class="thermal-label">🌡️ Thermal Imaging Data</div>
        {% if obs.thermal_findings and obs.thermal_findings != "Not Available" %}
          <p style="font-size:13px;color:#1565c0;margin-bottom:10px;font-style:italic">
            {{ obs.thermal_findings }}
          </p>
        {% endif %}
        <div class="thermal-grid">
          {% for item in thermals %}
          <div class="thermal-wrap">
            <img src="{{ item.b64 }}" alt="Thermal Image" loading="lazy"
                 onclick="openLB(this.src)" style="cursor:zoom-in">
            <div class="thermal-meta">
              <span class="t-hot">🔴 Hotspot: {{ item.meta.hotspot }}</span>
              <span class="t-cold">🔵 Coldspot: {{ item.meta.coldspot }}</span>
              <span class="t-file">{{ item.meta.file }} · {{ item.meta.date }}</span>
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
      <div class="rc-rec-row">
        <div class="rc-box">
          <div class="rc-label">🔍 Probable Root Cause</div>
          {% if rc %}
            <p style="font-size:13px">{{ rc.root_cause }}</p>
            {% if rc.moisture_path and rc.moisture_path != "Not Available" %}
            <div class="moisture-path">↳ {{ rc.moisture_path }}</div>
            {% endif %}
          {% else %}
            <p class="no-img">Not Available</p>
          {% endif %}
        </div>
        <div class="rec-box">
          <div class="rec-label">
            {% if rec %}<span class="pri-tag {{ 'p1' if rec.priority=='P1' else 'p2' if rec.priority=='P2' else 'p3' }}">
              {{ rec.priority }}</span>{% endif %}
            Recommended Action
          </div>
          {% if rec %}
            <p style="font-size:13px;font-weight:600">{{ rec.action_title }}</p>
            <p class="method-text">{{ rec.treatment_method }}</p>
            {% if rec.estimated_cost_range and rec.estimated_cost_range != "Not Available" %}
              <p class="cost-text">💰 {{ rec.estimated_cost_range }}</p>
            {% endif %}
            <p class="outcome-text">✓ {{ rec.expected_outcome }}</p>
          {% else %}
            <p class="no-img">Not Available</p>
          {% endif %}
        </div>
      </div>

    </div><!-- /area-block -->
  {% endfor %}

  </div>
</div>

<!-- ══ SECTION 3 — PROBABLE ROOT CAUSE ══ -->
<div class="section" id="sec3">
  <div class="sec-hdr"><span class="sec-num">03</span><h2>Probable Root Cause</h2></div>
  <div class="sec-body">

    <!-- Summary table matching PDF structure -->
    <h3 style="font-size:13px;color:#0f3460;font-weight:700;margin-bottom:12px;
               text-transform:uppercase;letter-spacing:.5px">
      Summary Table — Impacted vs Exposed Areas
    </h3>
    <table style="margin-bottom:28px">
      <thead>
        <tr>
          <th style="width:5%;text-align:center">Pt.</th>
          <th style="width:45%">Impacted Area (Negative Side)</th>
          <th style="width:5%;text-align:center">Pt.</th>
          <th style="width:45%">Exposed / Source Area (Positive Side)</th>
        </tr>
      </thead>
      <tbody>
        {% for item in ddr.section_3_probable_root_cause %}
        <tr>
          <td style="text-align:center;font-weight:700;color:#c62828;font-size:15px">
            {{ loop.index }}
          </td>
          <td style="background:#fff9f9">{{ item.neg_observation }}</td>
          <td style="text-align:center;font-weight:700;color:#2e7d32;font-size:14px">
            {{ loop.index }}.1
          </td>
          <td style="background:#f9fff9">{{ item.pos_observation }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <!-- Detailed root cause per area -->
    <h3 style="font-size:13px;color:#0f3460;font-weight:700;margin-bottom:14px;
               text-transform:uppercase;letter-spacing:.5px">
      Detailed Root Cause Analysis
    </h3>
    {% for item in ddr.section_3_probable_root_cause %}
    <div style="border:1px solid #dde3f0;border-radius:8px;margin-bottom:14px;overflow:hidden">
      <div style="background:#f0f4ff;padding:9px 16px;border-bottom:1px solid #dde3f0;
                  display:flex;align-items:center;gap:10px">
        <span style="font-size:13px;font-weight:700;color:#0f3460">{{ item.area_title }}</span>
      </div>
      <div style="padding:13px 16px">
        <p style="font-size:13px;margin-bottom:8px">{{ item.root_cause }}</p>
        {% if item.moisture_path and item.moisture_path != "Not Available" %}
        <div style="font-size:12px;color:#666;font-style:italic;
                    border-left:3px solid #f5a623;padding-left:10px;margin-top:6px">
          🔄 <strong>Water path:</strong> {{ item.moisture_path }}
        </div>
        {% endif %}
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
        {% for item in ddr.section_4_severity_assessment %}
        <tr>
          <td><strong>{{ item.area_title }}</strong></td>
          <td>
            {% if item.severity == "High" %}<span class="sev-badge sev-high">High</span>
            {% elif item.severity == "Moderate" %}<span class="sev-badge sev-mod">Moderate</span>
            {% else %}<span class="sev-badge sev-low">Low</span>{% endif %}
          </td>
          <td style="text-align:center;font-weight:700;font-size:17px;color:#0f3460">{{ item.severity_score }}</td>
          <td style="font-size:13px">{{ item.reasoning }}</td>
          <td style="font-size:12px;font-weight:600;color:{{ '#c62828' if 'Immediate' in item.urgency else '#e65100' if 'Soon' in item.urgency else '#2e7d32' }}">
            {{ '🔴' if 'Immediate' in item.urgency else '🟠' if 'Soon' in item.urgency else '🟢' }} {{ item.urgency }}
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
          <th style="width:35%">Treatment Method</th>
          <th style="width:15%">Est. Cost</th>
          <th style="width:12%">Outcome</th>
        </tr>
      </thead>
      <tbody>
        {% for item in ddr.section_5_recommended_actions %}
        <tr>
          <td><strong>{{ item.area_title }}</strong></td>
          <td style="text-align:center">
            <span class="pri-tag {{ 'p1' if item.priority=='P1' else 'p2' if item.priority=='P2' else 'p3' }}">
              {{ item.priority }}
            </span>
          </td>
          <td style="font-weight:600">{{ item.action_title }}</td>
          <td style="font-size:12px;color:#444">{{ item.treatment_method }}</td>
          <td style="font-size:12px;color:#888">
            {% if item.estimated_cost_range and item.estimated_cost_range != "Not Available" %}
              💰 {{ item.estimated_cost_range }}
            {% else %}—{% endif %}
          </td>
          <td style="font-size:12px;color:#2e7d32;font-weight:600">✓ {{ item.expected_outcome }}</td>
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
    <div class="notes-grid">
      <div class="note-card">
        <h4>📋 General Observations</h4>
        <p>{{ ddr.section_6_additional_notes.general_observations }}</p>
      </div>
      <div class="note-card">
        <h4>🛡️ Preventive Measures</h4>
        <p>{{ ddr.section_6_additional_notes.preventive_measures }}</p>
      </div>
      <div class="note-card">
        <h4>👁️ Monitoring Advice</h4>
        <p>{{ ddr.section_6_additional_notes.monitoring_advice }}</p>
      </div>
      <div class="note-card">
        <h4>🔧 Contractor Note</h4>
        <p>{{ ddr.section_6_additional_notes.contractor_note }}</p>
      </div>
      {% if ddr.section_6_additional_notes.warranty_note and ddr.section_6_additional_notes.warranty_note != "Not Available" %}
      <div class="note-card" style="grid-column:1/-1">
        <h4>📜 Warranty / Guarantee</h4>
        <p>{{ ddr.section_6_additional_notes.warranty_note }}</p>
      </div>
      {% endif %}
    </div>
  </div>
</div>

<!-- ══ SECTION 7 — MISSING INFO ══ -->
<div class="section" id="sec7">
  <div class="sec-hdr"><span class="sec-num">07</span><h2>Missing or Unclear Information</h2></div>
  <div class="sec-body">
    {% if ddr.section_7_missing_or_unclear_information %}
      {% for item in ddr.section_7_missing_or_unclear_information %}
      <div class="missing-item">
        <div class="missing-title">⚠️ {{ item.item }}</div>
        <p><strong>Impact:</strong> {{ item.impact }}</p>
        <p><strong>Recommendation:</strong> {{ item.recommendation }}</p>
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
  or ceilings may not be identified. Structural cracks require evaluation by a Registered
  Structural Engineer. This report is prepared for the client's internal use only.
  The inspection company accepts no responsibility for misinterpretation by third parties.
</div>

</div><!-- /page -->

<div class="footer">
  © {{ ddr.report_meta.company_name or "Inspection Services" }}
  {% if ddr.property_info.inspection_date %}&nbsp;·&nbsp; Inspection: {{ ddr.property_info.inspection_date }}{% endif %}
  {% if ddr.report_meta.report_number and ddr.report_meta.report_number != "Not Available" %}
  &nbsp;·&nbsp; Report No: {{ ddr.report_meta.report_number }}
  {% endif %}
</div>

</body>
</html>
"""


def _build_thermal_map(thermal_images: list, ia_map_list: list) -> dict:
    """
    Map thermal images to impacted areas.
    Uses has_thermal flag + proportional distribution ONLY among flagged areas.
    Each area gets a non-overlapping slice.
    """
    if not thermal_images or not ia_map_list:
        return {}

    thermal_areas = [ia for ia in ia_map_list if ia.get("has_thermal")]

    # Fallback: if LLM didn't flag any, give all to first area
    if not thermal_areas:
        return {ia_map_list[0]["area_id"]: thermal_images}

    result = {}
    total = len(thermal_images)
    n = len(thermal_areas)
    
    # Distribute evenly but don't overlap — each area gets its own slice
    base = total // n
    remainder = total % n
    
    start = 0
    for i, ia in enumerate(thermal_areas):
        # Give one extra image to first `remainder` areas
        count = base + (1 if i < remainder else 0)
        end = start + count
        if start < total:
            result[ia["area_id"]] = thermal_images[start:end]
        start = end

    return result

def render_html_report(ddr: dict, payload: dict) -> str:
    """
    Render a self-contained HTML report from any DDR JSON + extraction payload.
    Works regardless of report structure or number of impacted areas.
    """
    photo_b64      = payload["photo_b64"]
    thermal_images = payload["thermal_images"]
    ia_map_list    = ddr.get("impacted_areas_map", [])

    # Build O(1) lookup dicts
    ia_lookup       = {ia["area_id"]: ia  for ia in ia_map_list}
    severity_lookup = {s["area_id"]: s
                       for s in ddr.get("section_4_severity_assessment", [])}
    rec_lookup      = {r["area_id"]: r
                       for r in ddr.get("section_5_recommended_actions", [])}
    rc_cause_lookup = {r["area_id"]: r
                       for r in ddr.get("section_3_probable_root_cause", [])}

    thermal_for_area = _build_thermal_map(thermal_images, ia_map_list)

    env      = Environment(loader=BaseLoader(), autoescape=False)
    template = env.from_string(HTML_TEMPLATE)

    return template.render(
        ddr              = ddr,
        photo_b64        = photo_b64,
        thermal_images   = thermal_images,
        ia_lookup        = ia_lookup,
        severity_lookup  = severity_lookup,
        rec_lookup       = rec_lookup,
        rc_cause_lookup  = rc_cause_lookup,
        thermal_for_area = thermal_for_area,
    )