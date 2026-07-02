import math
import os
import sys

# WeasyPrint loads native libs (pango/glib/cairo) via dlopen. On macOS these live
# in Homebrew's lib dir, which isn't on the default dyld search path, so point to it
# before importing weasyprint.
if sys.platform == "darwin":
    for brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):
        if os.path.isdir(brew_lib):
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{brew_lib}:{existing}" if existing else brew_lib
            )
            break
        
from datetime import date
from html import escape

import markdown
from weasyprint import HTML

from summary import _format_raw


def _score_band(score):
    """Map a 0-100 risk score to a (label, color) pair for the report badge."""
    if score is None:
        return "No score", "#6b7280"
    if score < 35:
        return "Low risk", "#15803d"
    if score < 65:
        return "Moderate risk", "#b45309"
    return "High risk", "#b91c1c"


def build_report_html(metadata, result, summary):
    rows = ""
    for name in result["ratios"]:
        raw = result["ratios"][name]
        sub = result["scores"][name]                      # unadjusted level score
        delta = result["trend_deltas"][name]
        adj = result["scores_adjusted"][name]
        label = name.replace("_", " ").title()
        value = "N/A" if raw is None else _format_raw(name, raw)
        if sub is None:
            sub_display, trend_display, adj_display = "N/A", "—", "N/A"
        else:
            sub_display = round(sub, 1)
            trend_display = "—" if delta == 0 else (f"▲ +{delta}" if delta > 0 else f"▼ {delta}")
            adj_display = round(adj, 1)
        rows += (
            f"<tr><td>{label}</td>"
            f"<td class='num'>{value}</td>"
            f"<td class='num'>{sub_display}</td>"
            f"<td class='num'>{trend_display}</td>"
            f"<td class='num'>{adj_display}</td></tr>"
    )

    # Per-year ratios table — same source (result["series"]) and cell rules as the web UI.
    year_headers = ""
    for p in result["periods"]:
        year = p.year if hasattr(p, "year") else str(p)
        year_headers += f"<th class='num'>{year}</th>"

    year_rows = ""
    for name in result["series"]:
        label = name.replace("_", " ").title()
        cells = ""
        for v in result["series"][name]:
            if v is None:
                cell = "—"
            elif name in ("operating_margin", "revenue_growth"):
                cell = f"{v * 100:.1f}%"
            elif math.isinf(v):
                cell = "∞"
            else:
                cell = f"{v:.2f}"
            cells += f"<td class='num'>{cell}</td>"
        year_rows += f"<tr><td>{label}</td>{cells}</tr>"

    score = result["final_adjusted"]
    score_text = "N/A" if score is None else f"{score:.1f} / 100"
    band_label, band_color = _score_band(score)
    
    snapshot = result["final"]
    snapshot_html = ""
    if score is not None and snapshot is not None and abs(score - snapshot) >= 0.05:
        snapshot_html = f'<div class="snapshot">Point-in-time before trend: {snapshot:.1f} / 100</div>'

    # yfinance-sourced strings go straight into the HTML template — escape them so
    # names like "M&M" don't mangle the markup.
    name = escape(str(metadata["name"] or "N/A"))
    sector = escape(str(metadata["sector"] or "N/A"))
    market_cap = escape(str(metadata["market_cap"] or "N/A"))
    currency = escape(str(metadata["currency"] or "N/A"))
    generated = date.today().strftime("%d %B %Y")

    # The LLM writes the summary in Markdown (bold, lists) — render it to real HTML
    # rather than dumping raw asterisks into the page. Escape it FIRST: python-markdown
    # passes raw HTML through unsanitized, and WeasyPrint renders it (local-file-read vector).
    summary_html = markdown.markdown(escape(summary))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        margin: 1.6cm 1.8cm 2.2cm 1.8cm;
        @bottom-center {{
            content: "AI Financial Risk Analyst  ·  Page " counter(page) " of " counter(pages);
            font-size: 8.5px;
            color: #9ca3af;
        }}
    }}
    body {{
        font-family: Helvetica, Arial, sans-serif;
        color: #1f2937;
        font-size: 11.5px;
        line-height: 1.5;
    }}
    .brand {{
        font-size: 10px;
        font-weight: bold;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        color: #2563eb;
    }}
    h1 {{
        font-size: 24px;
        color: #111827;
        margin: 2px 0 2px 0;
    }}
    .meta {{
        color: #6b7280;
        font-size: 11px;
        margin-bottom: 4px;
    }}
    .meta span {{ margin-right: 14px; }}
    .rule {{
        border: none;
        border-top: 2px solid #2563eb;
        margin: 10px 0 18px 0;
    }}
    .score-box {{
        background: {band_color};
        color: #fff;
        padding: 14px 18px;
        border-radius: 8px;
        margin: 4px 0 22px 0;
    }}
    .score-box .label {{
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        opacity: 0.9;
    }}
    .score-box .value {{
        font-size: 26px;
        font-weight: bold;
        margin: 2px 0;
    }}
    .score-box .scale {{ font-size: 10px; opacity: 0.85; }}
    h2 {{
        font-size: 14px;
        color: #111827;
        border-bottom: 1px solid #e5e7eb;
        padding-bottom: 4px;
        margin: 24px 0 10px 0;
    }}
    .score-box .snapshot {{
        font-size: 11px;
        opacity: 0.85;
        margin-top: 5px;
    }}  
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ padding: 7px 10px; }}
    th {{
        background: #1e293b;
        color: #fff;
        text-align: left;
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    th.num, td.num {{ text-align: right; }}
    tbody tr:nth-child(even), table tr:nth-child(even) {{ background: #f3f4f6; }}
    td {{ border-bottom: 1px solid #e5e7eb; }}
    .summary p {{ margin: 0 0 9px 0; }}
    .summary li {{ margin: 0 0 5px 0; }}
    .disclaimer {{
        margin-top: 26px;
        padding-top: 10px;
        border-top: 1px solid #e5e7eb;
        color: #9ca3af;
        font-size: 9px;
        line-height: 1.45;
    }}
</style>
</head>
<body>
    <div class="brand">AI Financial Risk Analyst</div>
    <h1>{name}</h1>
    <div class="meta">
        <span>{sector}</span>
        <span>Market Cap: {market_cap}</span>
        <span>Currency: {currency}</span>
        <span>Generated: {generated}</span>
    </div>
    <hr class="rule">

    <div class="score-box">
        <div class="label">Overall Risk Score &mdash; {band_label}</div>
        <div class="value">{score_text}</div>
        {snapshot_html}
        <div class="scale">0 = least risky&nbsp;&nbsp;·&nbsp;&nbsp;100 = most risky</div>
    </div>

    <h2>Metric Breakdown</h2>
    <table>
        <tr><th>Metric</th><th class="num">Value</th><th class="num">Risk Score</th><th class="num">Trend</th><th class="num">Adj. Risk</th></tr>
        {rows}
    </table>

    <h2>Per-year ratios</h2>
    <table>
        <tr><th>Metric</th>{year_headers}</tr>
        {year_rows}
    </table>

    <h2>Plain-English Summary</h2>
    <div class="summary">{summary_html}</div>

    <div class="disclaimer">
        This report is generated automatically from publicly available financial data (via yfinance)
        and a transparent, code-computed risk model. Figures may be incomplete or delayed. The risk
        model is built for non-financial companies and is less reliable for banks, NBFCs, and insurers.
        This is not investment advice.
    </div>
</body>
</html>"""


def generate_pdf(metadata, result, summary):
    html = build_report_html(metadata, result, summary)
    return HTML(string=html).write_pdf()

if __name__ == "__main__":
    from data import fetch_financials
    from risk import assess_risk
    from summary import generate_risk_summary

    df, metadata = fetch_financials("TCS.NS")
    result = assess_risk(df)
    summary = generate_risk_summary(metadata, result)
    pdf_bytes = generate_pdf(metadata, result, summary)
    with open("report_TCS.pdf", "wb") as f:
        f.write(pdf_bytes)
    print("wrote report_TCS.pdf")