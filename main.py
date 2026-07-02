"""FastAPI backend for the AI Financial Risk Analyst.

This replaces Streamlit. Streamlit was secretly doing two jobs: (1) serving a web
page, and (2) running the Python pipeline. This file does both explicitly:

  - It serves the static front end (static/index.html, styles.css, app.js).
  - It exposes the existing modules (data/risk/summary/report/docchat) as JSON
    URLs the browser's JavaScript can call.

The five core modules are untouched. All number formatting lives here in Python so
the page can never silently diverge from the old Streamlit display logic.
"""

import html
import math
import re
import time
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from data import fetch_financials
from risk import assess_risk
from summary import generate_risk_summary
from report import generate_pdf
import markdown
from docchat import extract_pdfs, within_budget, answer_question, TOKEN_CAP

app = FastAPI(title="AI Financial Risk Analyst")

# Anchor static paths to this file's directory so launch CWD doesn't matter.
BASE_DIR = Path(__file__).resolve().parent

# Upload limits — reject early with a clear message instead of choking later.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file
MAX_UPLOAD_FILES = 10                # files per request
MAX_DOC_SESSIONS = 20                # bound _docs_cache (evict oldest beyond this)
MAX_ANALYSIS_ENTRIES = 32            # bound _analysis_cache (evict oldest beyond this)
# TTL long enough to avoid re-burning the Gemini free-tier quota within a session,
# short enough that a server left running doesn't serve day-old financials as fresh.
ANALYSIS_TTL_SECONDS = 3600          # 1-hour freshness window

# In-memory caches — the hand-written equivalent of Streamlit's @st.cache_data.
# Keyed by normalized ticker so /api/report can reuse what /api/analyze computed
# (and we never re-hit yfinance / Gemini for the same ticker twice).
_analysis_cache: dict[str, dict] = {}
# Uploaded-document text, keyed by an upload session id the browser sends back.
_docs_cache: dict[str, list] = {}


# --------------------------------------------------------------------------- #
# Helpers ported verbatim from the old app.py so display matches exactly.
# --------------------------------------------------------------------------- #
def normalize_ticker(raw):
    t = raw.strip().upper()
    if t and "." not in t:
        t += ".NS"
    return t


def risk_band(score):
    if score < 35:
        return "is-low", "Low risk"
    if score < 65:
        return "is-mod", "Moderate risk"
    return "is-high", "High risk"


def indian_format(value):
    if pd.isna(value) or not math.isfinite(value):
        return "—"
    sign = "-" if value < 0 else ""
    integer, decimal = f"{abs(value):.2f}".split(".")
    if len(integer) > 3:
        last3 = integer[-3:]
        rest = integer[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        groups.insert(0, rest)
        integer = ",".join(groups) + "," + last3
    return f"{sign}{integer}.{decimal}"


def _col_label(c):
    try:
        return c.strftime("%Y-%m-%d")
    except Exception:
        return str(c)


# --------------------------------------------------------------------------- #
# Turn the Python pipeline output into a JSON-safe payload for the browser.
# Every numeric quirk (None, inf, NaN) is resolved to a clean string/number HERE,
# so the JSON never contains Infinity/NaN (which aren't valid JSON anyway).
# --------------------------------------------------------------------------- #
def build_analysis_payload(df, metadata, result, summary_html):
    score = result["final_adjusted"]
    snapshot = result["final"]

    missing = [n for n in result["ratios"] if result["ratios"][n] is None]
    low_confidence = len(missing) >= 2

    # ----- Risk axis -----
    if score is None:
        risk = {"score": None}
    else:
        band_class, band_label = risk_band(score)
        show_ghost = snapshot is not None and abs(score - snapshot) >= 0.05
        risk = {
            "score": float(score),
            "score_display": f"{score:.1f}",
            "snapshot": float(snapshot) if snapshot is not None else None,
            "snapshot_display": f"{snapshot:.1f}" if snapshot is not None else None,
            "band_class": band_class,
            "band_label": band_label,
            "show_ghost": bool(show_ghost),
        }

    # ----- Evidence table -----
    evidence = []
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
            sub_d, adj_d = round(float(sub), 1), round(float(adj), 1)
            if delta == 0:
                trend_d, tcls = "—", "flat"
            elif delta > 0:
                trend_d, tcls = f"▲ +{delta}", "up"
            else:
                trend_d, tcls = f"▼ {delta}", "down"
        evidence.append({"label": label, "value": value, "sub": sub_d,
                         "trend": trend_d, "tcls": tcls, "adj": adj_d})

    # ----- Per-year ratios -----
    years = [_col_label(p) if not hasattr(p, "year") else str(p.year)
             for p in result["periods"]]
    per_year = []
    for name in result["series"]:
        cells = []
        for v in result["series"][name]:
            if v is None:
                cells.append("—")
            elif name in ("operating_margin", "revenue_growth"):
                cells.append(f"{v * 100:.1f}%")
            elif math.isinf(v):
                cells.append("∞")
            else:
                cells.append(f"{v:.2f}")
        per_year.append({"metric": name.replace("_", " ").title(), "cells": cells})

    # ----- Raw financials (₹ Crore) -----
    crore = (df / 1e7).map(indian_format)
    raw_table = {
        "columns": [str(c) for c in crore.columns],
        "index": [_col_label(i) for i in crore.index],
        "rows": crore.values.tolist(),
    }

    meta_line = " · ".join([
        (metadata["sector"] or "N/A").title(),
        f"MCAP {metadata['market_cap'] or 'N/A'}",
        metadata["currency"] or "N/A",
    ])

    return {
        "company": metadata["name"] or "N/A",
        "meta": meta_line,
        "low_confidence": low_confidence,
        "risk": risk,
        "evidence": evidence,
        "years": years,
        "per_year": per_year,
        "raw_table": raw_table,
        "summary_html": summary_html,
    }


def _run_analysis(raw, allow_recompute=True):
    """Fetch → assess → summarize → render PDF. Cached by normalized ticker.
    Returns a dict with either {"error": msg} or {"payload":..., "pdf":...}.

    allow_recompute=False (used by /api/report) means: serve whatever is in the
    cache, even if a prior Gemini call failed — never re-fetch just to hand back
    a PDF that already exists. Re-fetching here risked yfinance rate-limiting a
    ticker the user is actively looking at, and re-burned Gemini quota."""
    ticker = normalize_ticker(raw)
    if not ticker:
        return {"error": "Enter a ticker symbol."}
    if ticker in _analysis_cache:
        cached = _analysis_cache[ticker]
        fresh = time.monotonic() - cached["_cached_at"] <= ANALYSIS_TTL_SECONDS
        # Serve the cache unless it's fresh but the summary failed AND we're
        # allowed to retry it (i.e. this is a real /api/analyze call, not a
        # /api/report download of an already-computed result).
        if fresh and not (cached.get("_summary_pending") and allow_recompute):
            return cached
        del _analysis_cache[ticker]

    df, metadata = fetch_financials(ticker)
    if df is None:
        return {"error": ("No data for this ticker — check the symbol, or Yahoo "
                          "Finance may be rate-limiting; try again in a minute.")}

    result = assess_risk(df)
    summary = generate_risk_summary(metadata, result)
    # Escape the LLM text BEFORE markdown: python-markdown passes raw HTML through
    # unsanitized, and this string is injected via innerHTML client-side.
    summary_html = markdown.markdown(html.escape(summary)) if summary else None
    payload = build_analysis_payload(df, metadata, result, summary_html)

    report_summary = summary if summary else "AI summary unavailable at generation time."
    # PDF failure must not sink the whole analysis — data/risk/summary still stand.
    try:
        pdf = generate_pdf(metadata, result, report_summary)
    except Exception:
        pdf = None

    entry = {
        "payload": payload,
        "pdf": pdf,
        "_cached_at": time.monotonic(),
        # A failed summary is cached too (so a PDF download doesn't re-fetch),
        # but flagged so a later /api/analyze call is allowed to retry Gemini
        # instead of pinning "summary unavailable" to this ticker until restart.
        "_summary_pending": summary is None,
    }
    _analysis_cache[ticker] = entry
    # Bound the cache: evict oldest entries (dicts keep insertion order).
    while len(_analysis_cache) > MAX_ANALYSIS_ENTRIES:
        _analysis_cache.pop(next(iter(_analysis_cache)))
    return entry


# --------------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/analyze")
def api_analyze(ticker: str):
    entry = _run_analysis(ticker)
    if "error" in entry:
        return JSONResponse({"error": entry["error"]}, status_code=404)
    return entry["payload"]


@app.get("/api/report")
def api_report(ticker: str):
    entry = _run_analysis(ticker, allow_recompute=False)
    if "error" in entry:
        return JSONResponse({"error": entry["error"]}, status_code=404)
    if entry["pdf"] is None:
        return JSONResponse(
            {"error": "PDF generation failed for this ticker — try again later."},
            status_code=503,
        )
    safe_ticker = re.sub(r"[^A-Za-z0-9._-]", "", normalize_ticker(ticker)) or "report"
    filename = f"{safe_ticker}_risk_report.pdf"
    return Response(
        content=entry["pdf"],
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/upload")
def api_upload(files: list[UploadFile] = File(...)):
    # Plain def: FastAPI runs it in a threadpool, keeping CPU-bound PyMuPDF
    # extraction off the event loop.
    if len(files) > MAX_UPLOAD_FILES:
        return JSONResponse(
            {"error": f"Too many files — upload at most {MAX_UPLOAD_FILES} PDFs at a time."},
            status_code=400,
        )
    pairs = []
    for f in files:
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"error": f"'{f.filename}' is over the 25 MB per-file limit."},
                status_code=400,
            )
        pairs.append((f.filename, data))
    docs, failures = extract_pdfs(pairs)
    session_id = uuid.uuid4().hex
    _docs_cache[session_id] = docs
    # Bound the cache: evict oldest sessions (dicts keep insertion order).
    while len(_docs_cache) > MAX_DOC_SESSIONS:
        _docs_cache.pop(next(iter(_docs_cache)))
    return {
        "session_id": session_id,
        "doc_names": [name for name, _ in docs],
        "failures": failures,
        "has_docs": bool(docs),
    }


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: str
    question: str
    history: list[ChatTurn] = []


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    docs = _docs_cache.get(req.session_id)
    if not docs:
        return JSONResponse({"error": "No readable documents for this session."},
                            status_code=400)

    history = [{"role": t.role, "content": t.content} for t in req.history]
    ok, est = within_budget(docs, history, req.question)
    if not ok:
        return {"error": "too_large", "est": est, "cap": TOKEN_CAP}

    ans = answer_question(docs, history, req.question)
    if ans is None:
        return {"error": "busy"}
    # Escape before markdown — the result is injected via innerHTML client-side.
    return {"answer": ans, "answer_html": markdown.markdown(html.escape(ans))}


# --------------------------------------------------------------------------- #
# Static front end (mounted last so /api/* routes win).
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
