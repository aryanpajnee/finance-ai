import streamlit as st
import pandas as pd
from data import fetch_financials
from risk import assess_risk
import math
from summary import generate_risk_summary
from report import generate_pdf
import markdown
from docchat import extract_pdfs , estimate_tokens , within_budget ,answer_question, TOKEN_CAP

def load_css():
    with open("styles.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()
st.markdown('<div class="ts-eyebrow">AI Financial Risk Analyst</div>', unsafe_allow_html=True)
@st.cache_data
def cached_fetch(ticker):
    return fetch_financials(ticker)

@st.cache_data
def cached_summary(metadata , result):
    return generate_risk_summary(metadata , result)

@st.cache_data
def cached_pdf(metadata , results , summary):
    return generate_pdf(metadata , results , summary)

@st.cache_data
def cached_extract(files):
    return extract_pdfs(files)

def normalize_ticker(raw):
    t = raw.strip().upper()
    if t and "." not in t:
        t += ".NS"
    return t

#st.title("AI Financial Risk Analyst")
raw_ticker = st.text_input("Enter an Indian stock ticker. (e.g. TCS)\n")
ticker = normalize_ticker(raw_ticker)
def indian_format(value):
    if pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    integer, decimal = f"{abs(value):.2f}".split(".")
    if len(integer) > 3:
        last3 = integer[-3:]
        rest = integer[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])   # take 2 digits from the right
            rest = rest[:-2]
        groups.insert(0, rest)
        integer = ",".join(groups) + "," + last3
    return f"{sign}{integer}.{decimal}"

def risk_band(score):
    if score < 35: return "is-low", "Low risk"
    if score < 65: return "is-mod", "Moderate risk"
    return "is-high", "High risk"

if ticker:
    df , metadata = cached_fetch(ticker)
    
    if df is None:
        st.error("No data found. Check ticker symbol.")
        
    else:
        #st.subheader(metadata["name"])
        st.markdown('<hr class="ts-rule">', unsafe_allow_html=True)
        st.markdown(f'<div class="ts-company">{metadata["name"] or "N/A"}</div>', unsafe_allow_html=True)
        meta = " · ".join([
            (metadata["sector"] or "N/A").title(),
            f"MCAP {metadata['market_cap'] or 'N/A'}",
            metadata["currency"] or "N/A",
        ])
        st.markdown(f'<div class="ts-meta">{meta}</div>', unsafe_allow_html=True)
        
        with st.expander("Raw financials (₹ Crore)"):
            st.dataframe((df / 1e7).map(indian_format))
        #st.dataframe(display_df)
        result = assess_risk(df)
        score = result["final_adjusted"]
        snapshot = result["final"]
        missing = [n for n in result["ratios"] if result["ratios"][n] is None]
        if len(missing) >= 2:
            st.markdown('<div class="ts-warn">This risk model is built for non-financial companies. '
                        "Several core metrics aren't available here — common for banks, NBFCs, and "
                        'insurers. Treat the score as low-confidence.</div>', unsafe_allow_html=True)

        if score is None:
            st.markdown('<div class="risk-axis"><div class="risk-top">'
                        '<span class="risk-eyebrow">Risk score</span>'
                        '<span class="risk-band">No score</span></div>'
                        '<div class="risk-legend">Not enough data to compute a score.</div></div>',
                        unsafe_allow_html=True)
        else:
            band_class, band_label = risk_band(score)
            pos = max(0, min(100, score))
            ghost_html = connector_html = legend = ""
            if snapshot is not None and abs(score - snapshot) >= 0.05:
                gpos = max(0, min(100, snapshot))
                lo, hi = sorted((pos, gpos))
                connector_html = f'<div class="risk-connector" style="left:{lo}%;width:{hi-lo}%"></div>'
                ghost_html = f'<div class="risk-ghost" style="left:{gpos}%"></div>'
                legend = f'<div class="risk-legend">was <b>{snapshot:.1f}</b> &nbsp;&#9654;&nbsp; now <b>{score:.1f}</b></div>'
            st.markdown(
                f'<div class="risk-axis {band_class}">'
                f'<div class="risk-top"><span class="risk-eyebrow">Risk score</span>'
                f'<span class="risk-band">{band_label}</span></div>'
                f'<div class="risk-track"><div class="risk-zones"></div>'
                f'{connector_html}{ghost_html}'
                f'<div class="risk-marker" style="left:{pos}%"><span class="risk-value">{score:.1f}</span></div>'
                f'</div>'
                f'<div class="risk-scale"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>'
                f'{legend}</div>',
                unsafe_allow_html=True)
        
        st.markdown('<div class="ts-section">Evidence</div>', unsafe_allow_html=True)
        body = ""
        for name in result["ratios"]:
            raw = result["ratios"][name]
            sub = result["scores"][name]
            label = name.replace("_", " ").title()

            if raw is None:
                value = "N/A"
            elif name == "debt_to_equity" and math.isinf(raw):
                value = "Negative equity"
            elif name == "interest_coverage" and math.isinf(raw):
                value = "No debt"
            elif name in ("operating_margin", "revenue_growth"):
                value = f"{raw * 100:.2f}%"
            else:
                value = f"{raw:.2f}"

            delta = result["trend_deltas"][name]
            adj = result["scores_adjusted"][name]
            if sub is None:
                sub_d, trend_d, adj_d, tcls = "N/A", "—", "N/A", "flat"
            else:
                sub_d, adj_d = round(sub, 1), round(adj, 1)
                if delta == 0:  trend_d, tcls = "—", "flat"
                elif delta > 0: trend_d, tcls = f"▲ +{delta}", "up"
                else:           trend_d, tcls = f"▼ {delta}", "down"
            body += (f'<tr><td class="metric">{label}</td><td class="num">{value}</td>'
                     f'<td class="num">{sub_d}</td><td class="num {tcls}">{trend_d}</td>'
                     f'<td class="num">{adj_d}</td></tr>')
        st.markdown('<table class="ts-table"><thead><tr><th>Metric</th><th class="num">Value</th>'
                    '<th class="num">Risk</th><th class="num">Trend</th><th class="num">Adj.</th></tr></thead>'
                    f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)
        st.markdown('<p class="ts-hint">▲ trend raised risk · ▼ trend lowered risk</p>', unsafe_allow_html=True)

        years = [p.year for p in result["periods"]]
        trail = []
        for name in result["series"]:
            cells = {}
            for y, v in zip(years, result["series"][name]):
                cells[str(y)] = "—" if v is None else (
                    f"{v * 100:.1f}%" if name in ("operating_margin", "revenue_growth")
                    else ("∞" if math.isinf(v) else f"{v:.2f}"))
            trail.append({"Metric": name.replace("_", " ").title(), **cells})
        st.markdown('<div class="ts-section">Per-year ratios</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(trail), hide_index=True)

        with st.spinner("Generating summary..."):
            summary = cached_summary(metadata , result)
        
        st.markdown('<div class="ts-section">Analyst note</div>', unsafe_allow_html=True)
        if summary is None:
            st.markdown('<div class="ts-note"><p>AI summary unavailable right now (service busy). '
                        'The score and evidence above are still valid.</p></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="ts-note">{markdown.markdown(summary)}</div>', unsafe_allow_html=True)
            
        report_summary = summary if summary else 'AI summary unavailable at generation time.'
        pdf_bytes = cached_pdf(metadata , result , report_summary)
        st.download_button(
            label="↓ Download report (PDF)",
            data= pdf_bytes , 
            file_name=f"{raw_ticker}_risk_report.pdf",
            mime="application/pdf" ,
        )
        
        st.markdown('<div class="ts-section">Ask the documents</div>', unsafe_allow_html=True )
        uploaded = st.file_uploader("Upload finance PDFs" , type="pdf" , accept_multiple_files=True)
        if uploaded:
            files = tuple((f.name, f.getvalue()) for f in uploaded)
            sig = tuple((f.name, f.size) for f in uploaded)
            
            if st.session_state.get("doc_sig") != sig:
                st.session_state.doc_sig = sig
                st.session_state.doc_history = []
                
            docs, failures = cached_extract(files)
            
            if failures:
                st.markdown('<div class="ts-warn">Couldn\'t read text from: '
                            + ", ".join(failures)
                            + '. These look scanned or image-only and were skipped (no OCR).</div>',
                            unsafe_allow_html=True)
                
            if not docs:
                st.markdown('<div class="ts-warn">No readable documents to chat with.</div>' , unsafe_allow_html=True)
                
            else:
                for m in st.session_state.doc_history:
                    cls = "ts-chat-user" if m["role"] == "user" else "ts-chat-ai"
                    st.markdown(f'<div class="ts-chat {cls}">{markdown.markdown(m["content"])}</div>',
                                unsafe_allow_html=True)
                q = st.chat_input("Ask about the uploaded documents")
                if q:
                    ok, est = within_budget(docs, st.session_state.doc_history)
                    if not ok:
                        st.markdown(f'<div class="ts-warn">These documents are too large to read at '
                                    f'once (~{est:,} tokens vs ~{TOKEN_CAP:,} limit). Remove one and '
                                    f'try again.</div>', unsafe_allow_html=True)
                    else:
                        with st.spinner("Reading the documents..."):
                            ans = answer_question(docs, st.session_state.doc_history, q)
                        if ans is None:
                            st.markdown('<div class="ts-warn">AI service busy — try again in a '
                                        'moment.</div>', unsafe_allow_html=True)
                        else:
                            st.session_state.doc_history.append({"role": "user", "content": q})
                            st.session_state.doc_history.append({"role": "assistant", "content": ans})
                            st.rerun()
#st.session_state