import streamlit as st
import pandas as pd
from data import fetch_financials
from risk import assess_risk
import math
from summary import generate_risk_summary
from report import generate_pdf


st.markdown(
    "<style>[data-testid='InputInstructions'] {display: none;}</style>",
    unsafe_allow_html=True,
)
@st.cache_data
def cached_fetch(ticker):
    return fetch_financials(ticker)

@st.cache_data
def cached_summary(metadata , result):
    return generate_risk_summary(metadata , result)

@st.cache_data
def cached_pdf(metadata , results , summary):
    return generate_pdf(metadata , results , summary)

st.title("AI Financial Risk Analyst")

ticker = st.text_input("Enter an Indian stock ticker. (e.g. TCS.NS)\n")
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

if ticker:
    df , metadata = cached_fetch(ticker)
    
    if df is None:
        st.error("No data found. Check ticker symbol.")
        
    else:
        st.subheader(metadata["name"])
        st.markdown(f"Sector: {(metadata['sector'] or 'N/A').title()}")
        st.markdown(f"Market Cap: {metadata['market_cap']}")
        st.markdown(f"Currency: {metadata['currency'] or 'N/A'}")
        display_df = (df / 1e7).map(indian_format)
        st.caption("All figures in ₹ Crore")
        st.dataframe(display_df)
        result = assess_risk(df)
        score = result["final"]
        missing = [n for n in result["ratios"] if result["ratios"][n] is None]
        if len(missing) >= 2:
            st.warning(
                "⚠️ This risk model is built for non-financial companies. "
                "Several core metrics aren't available here — common for banks, "
                "NBFCs, and insurers, which report financials differently and need "
                "a specialised framework. Treat the score below as low-confidence."
            )
        if score is None:
            st.header("Risk Score: NA")
            st.header("Not enough data to compute a score.")
        else:
            st.header(f"Risk Score: {score:.2f} / 100")
            st.markdown("0 = least risky , 100 = most risky")
        
        rows =[]
        for name in result["ratios"]:
            raw = result["ratios"][name]
            sub = result["scores"][name]
            label = name.replace("_", " ").title()
        
            if raw is None:
                value = "N/A"
            elif name == "debt_to_equity" and math.isinf(raw):
                value = "Negative equity (insolvent)"
            elif name == "interest_coverage" and math.isinf(raw):
                value = "No debt (fully covered)"
            elif name in ("operating_margin", "revenue_growth"):
                value = f"{raw * 100:.2f}%"
            else:
                value = f"{raw:.2f}"
                
            sub_display = "N/A" if sub is None else round(sub, 1)
            rows.append({"Metric": label, "Value": value, "Risk Score": sub_display})
            
        breakdown = pd.DataFrame(rows)
        st.dataframe(breakdown, hide_index=True)
        
        with st.spinner("Generating summary..."):
            summary = cached_summary(metadata , result)
        
        if summary is None:
            st.info("AI summary unavailable right now (service busy). The risk score and metrics above are still valid.") 
        else:
            st.subheader("Plain-English Summary")
            st.markdown(summary)
            
        report_summary = summary if summary else 'AI summary unavailable at generation time.'
        pdf_bytes = cached_pdf(metadata , result , report_summary)
        st.download_button(
            label='📄 Download PDF report',
            data= pdf_bytes , 
            file_name=f"{ticker}_risk_report.pdf",
            mime="application/pdf" ,
            
        )
#st.session_state