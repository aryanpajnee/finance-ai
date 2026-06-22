# Document Q&A Implementation Plan

> **How this plan is executed (project rule):** This is a learning project — **the user types
> every line of `.py` code themselves.** This plan explains each step and shows the exact snippet
> to type; it does **not** get handed to a subagent that writes the code. Verification is by
> `if __name__ == "__main__"` smoke runs and the live Streamlit app (this project has no pytest
> suite), mirroring `summary.py` / `llm.py`. Checkbox syntax is for progress tracking only.

**Goal:** Add a standalone, multi-turn chat below the PDF download where an analyst uploads finance
PDFs and gets high-level answers grounded strictly in those documents.

**Architecture:** A new module `docchat.py` (modelled on `summary.py`) extracts PDF text with
PyMuPDF, estimates a token budget, and builds one flattened long-context prompt per turn that it
sends through the existing `get_llm_response`. `app.py` adds the uploader + custom-styled chat UI
below the download button, holding history in `st.session_state`.

**Tech Stack:** Streamlit, PyMuPDF (`import fitz`), existing `llm.py` Gemini wrapper, `markdown`.

## Global Constraints

- **User types all `.py` code.** the assistant explains + shows snippets only. (HTML/CSS/config is delegated.)
- **`llm.py` stays untouched.** Reuse `get_llm_response(prompt)` — one string in, `str` or `None` out.
- **`get_llm_response` returns `None` on any failure.** Every caller must handle `None`.
- **Long-context, NOT RAG.** No chunking / embeddings / retrieval.
- **No OCR in v1.** Unreadable PDFs are named + excluded, never silently included.
- **Loud refusal over silent best-effort** for unreadable PDFs and over-budget uploads.
- **Strictly document-grounded** answers; attribute figures to their source doc; never merge across docs.
- **Cache expensive calls** (`@st.cache_data`) — Streamlit reruns the whole script every interaction.
- **Never put `</style>` (even in a comment) in `styles.css`** — it closes the injected style block.
- **Token cap = 600_000** (chars/4 heuristic), tunable.

---

### Task 1: Add the PyMuPDF dependency

**Files:**
- Modify: environment only (no `requirements.txt` exists yet).

- [ ] **Step 1: Install PyMuPDF**

Run: `pip install pymupdf`

- [ ] **Step 2: Verify the import name is `fitz`**

Run: `python -c "import fitz; print(fitz.__version__)"`
Expected: prints a version string (e.g. `1.24.x`), no traceback.

---

### Task 2: `docchat.py` — extract text from uploaded PDFs

**Files:**
- Create: `docchat.py`

**Interfaces:**
- Produces: `extract_pdfs(files) -> (docs, failures)` where `files` is a list/tuple of
  `(filename: str, pdf_bytes: bytes)`, `docs` is a list of `(filename, text)` with usable text, and
  `failures` is a list of filenames with no usable text layer.
- Produces: module constant `MIN_CHARS = 100`.

- [ ] **Step 1: Type the extraction function**

```python
import fitz  # PyMuPDF

MIN_CHARS = 100  # below this, treat the PDF as having no usable text layer (scanned/image-only)


def extract_pdfs(files):
    """files: list of (filename, pdf_bytes). Returns (docs, failures)."""
    docs, failures = [], []
    for name, data in files:
        try:
            with fitz.open(stream=data, filetype="pdf") as doc:
                text = "\n".join(page.get_text() for page in doc)
        except Exception as e:
            print(f"EXTRACT ERROR {name}: {e}")
            failures.append(name)
            continue
        if len(text.strip()) < MIN_CHARS:
            failures.append(name)
        else:
            docs.append((name, text))
    return docs, failures
```

- [ ] **Step 2: Add a smoke test using the repo's own sample PDF**

```python
if __name__ == "__main__":
    with open("report_TCS.pdf", "rb") as f:
        data = f.read()
    docs, failures = extract_pdfs([("report_TCS.pdf", data)])
    print("docs:", [(n, len(t)) for n, t in docs])
    print("failures:", failures)
```

- [ ] **Step 3: Run the smoke test**

Run: `python docchat.py`
Expected: `docs: [('report_TCS.pdf', <some number > 100>)]` and `failures: []`.

---

### Task 3: `docchat.py` — token-budget guard

**Files:**
- Modify: `docchat.py`

**Interfaces:**
- Consumes: `docs` (from `extract_pdfs`), `history` (list of `{"role", "content"}` dicts).
- Produces: `within_budget(docs, history) -> (ok: bool, estimate: int)`.
- Produces: constants `CHARS_PER_TOKEN = 4`, `TOKEN_CAP = 600_000`.

- [ ] **Step 1: Type the estimator and the guard**

```python
CHARS_PER_TOKEN = 4
TOKEN_CAP = 600_000
_PROMPT_OVERHEAD_CHARS = 3000  # system prompt + per-doc headers, rough


def _estimate_tokens(docs, history, question=""):
    chars = sum(len(text) for _, text in docs)
    chars += sum(len(m["content"]) for m in history)
    chars += len(question) + _PROMPT_OVERHEAD_CHARS
    return chars // CHARS_PER_TOKEN


def within_budget(docs, history):
    est = _estimate_tokens(docs, history)
    return est <= TOKEN_CAP, est
```

- [ ] **Step 2: Extend the smoke test to print the estimate**

Add to the `__main__` block, after the existing prints:

```python
    ok, est = within_budget(docs, [])
    print("within_budget:", ok, "est tokens:", est)
```

- [ ] **Step 3: Run it**

Run: `python docchat.py`
Expected: `within_budget: True est tokens: <number>` — a small number for the one sample PDF.

---

### Task 4: `docchat.py` — guardrailed prompt + `answer_question`

**Files:**
- Modify: `docchat.py`

**Interfaces:**
- Consumes: `get_llm_response` from `llm.py`; `docs`, `history`, `question`.
- Produces: `answer_question(docs, history, question) -> str | None` (None on LLM failure).

- [ ] **Step 1: Import the LLM wrapper at the top of the file**

```python
from llm import get_llm_response
```

- [ ] **Step 2: Type the system prompt (strict grounding rules)**

```python
SYSTEM_PROMPT = """You are a financial analyst assistant. You answer questions STRICTLY from the
uploaded documents below — nothing else.

Rules:
- Use ONLY facts found in the documents. Never add outside knowledge, news, or figures.
- If the answer is not in the documents, say plainly: "The documents don't cover this." Do not guess.
- Attribute every figure to its source document by filename (e.g. "per AnnualReport_FY24.pdf ...").
- Never merge or average numbers across different documents or different years into one figure.
- All companies are Indian; use rupees (₹) or no currency unit — never dollars.
- Answer at a high level useful to a working analyst: concise and decision-relevant, not embellished.
- Do not give investment advice (no buy/sell/hold)."""
```

- [ ] **Step 3: Type the prompt builder**

```python
def _build_prompt(docs, history, question):
    parts = [SYSTEM_PROMPT, "", "=== DOCUMENTS ==="]
    for name, text in docs:
        parts.append(f"\n--- DOCUMENT: {name} ---\n{text}")
    parts.append("\n=== CONVERSATION SO FAR ===")
    for m in history:
        speaker = "Analyst" if m["role"] == "user" else "Assistant"
        parts.append(f"{speaker}: {m['content']}")
    parts.append(f"\nAnalyst: {question}")
    parts.append("Assistant:")
    return "\n".join(parts)


def answer_question(docs, history, question):
    return get_llm_response(_build_prompt(docs, history, question))
```

- [ ] **Step 4: Extend the smoke test with a real question**

Add to the `__main__` block:

```python
    ans = answer_question(docs, [], "What is the company's total revenue, and from which document?")
    print("\nANSWER:\n", ans)
```

- [ ] **Step 5: Run it**

Run: `python docchat.py`
Expected: an answer that cites `report_TCS.pdf` (or says the documents don't cover it) — and crucially
does NOT invent an unattributed number. Confirms the live Gemini path works end-to-end.

---

### Task 5: `app.py` — uploader, cached extraction, warnings, history reset

**Files:**
- Modify: `app.py` (add a cached extraction wrapper near the other `@st.cache_data` wrappers; add the
  section at the very bottom, after the `st.download_button(...)` call).

**Interfaces:**
- Consumes: `extract_pdfs`, `within_budget`, `answer_question`, `TOKEN_CAP` from `docchat`.
- Produces: `st.session_state` keys `doc_sig` (file-set signature) and `doc_history` (list of turns).

- [ ] **Step 1: Add imports at the top of `app.py`**

```python
from docchat import extract_pdfs, within_budget, answer_question, TOKEN_CAP
```

- [ ] **Step 2: Add a cached extraction wrapper near the other cache wrappers**

```python
@st.cache_data
def cached_extract(files):
    return extract_pdfs(files)
```

- [ ] **Step 3: Below the download button, add the section header + uploader + history reset**

Type this so it runs only when a ticker has produced a report (same indentation level as the
`st.download_button` block, i.e. inside the `else` that handles a found ticker):

```python
        st.markdown('<div class="ts-section">Ask the documents</div>', unsafe_allow_html=True)
        uploaded = st.file_uploader("Upload finance PDFs", type="pdf", accept_multiple_files=True)
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
```

- [ ] **Step 4: Verify the uploader renders and warns**

Run: `streamlit run app.py`, analyze a ticker (e.g. `TCS.NS`), scroll past the download button.
Expected: the "Ask the documents" section + uploader appear. Uploading `report_TCS.pdf` shows no
warning; uploading any scanned/image-only PDF names it in a yellow warning.

---

### Task 6: `app.py` — chat history render, input, budget check, answer

**Files:**
- Modify: `app.py` (continue inside the `if uploaded:` block from Task 5).

**Interfaces:**
- Consumes: `st.session_state.doc_history`, `docs`, `within_budget`, `answer_question`, `TOKEN_CAP`.

- [ ] **Step 1: After the `failures` warning, handle the no-readable-docs case**

```python
            if not docs:
                st.markdown('<div class="ts-warn">No readable documents to chat with.</div>',
                            unsafe_allow_html=True)
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
```

Note: history is rendered **before** `st.chat_input`; after a successful answer we append both turns
and `st.rerun()` so the new messages paint immediately. On `None` we show the busy notice and do
**not** append a broken turn.

- [ ] **Step 2: Verify a full multi-turn exchange**

Run the app, analyze `TCS.NS`, upload `report_TCS.pdf`, ask a question answerable from it, then a
follow-up.
Expected: both Q and A appear as chat bubbles; the follow-up shows the model remembers the thread;
a question not covered yields "The documents don't cover this."

---

### Task 7: `styles.css` — chat bubble + section styling (delegated boilerplate)

**Files:**
- Modify: `styles.css`

- [ ] **Step 1: Add `.ts-chat` classes consistent with the tearsheet aesthetic**

Append (the assistant may write this — it's CSS boilerplate, not learning-rule `.py`). Reuse existing
paper/ink/accent variables and the IBM Plex Sans body font. Distinguish analyst vs AI turns
(e.g. analyst right-aligned / accent edge, AI left-aligned / paper card). **Do not** include a
literal `</style>` anywhere, even in a comment.

- [ ] **Step 2: Style the `st.chat_input` surround to match the existing text input**

Reuse the same selector approach already used for `.stTextInput input` so the chat box matches the
command bar. Note in a comment that these Streamlit-internal selectors are brittle across upgrades.

- [ ] **Step 3: Visual check**

Run the app and confirm the chat bubbles + input read as part of the tearsheet, not default Streamlit.

---

### Task 8: Live end-to-end verification (Playwright)

**Files:** none.

- [ ] **Step 1: Drive the live app**

Use Playwright MCP `browser_navigate` to the running app, analyze `TCS.NS`, upload `report_TCS.pdf`,
ask a grounded question and an unanswerable one. Verify with `browser_snapshot` (a11y tree) — NOT
`browser_take_screenshot`, which times out on the Google-Fonts fetch.

- [ ] **Step 2: Confirm the failure paths**

Verify: a scanned PDF is named + excluded; changing the uploaded file set clears the chat history.

---

## Self-Review

- **Spec coverage:** new module `docchat.py` (Tasks 2–4) ✓; multi-PDF accumulated answer (extract +
  prompt loop over docs) ✓; multi-turn history in session_state (Tasks 5–6) ✓; long-context/no-RAG
  (flattened prompt, no chunking) ✓; loud extraction failure (Task 5) ✓; loud budget refusal
  (Tasks 3, 6) ✓; strict grounding + attribution + no-merge (Task 4 prompt) ✓; below download button
  / standalone (Task 5) ✓; custom `.ts-*` styling + `st.chat_input` kept (Tasks 6–7) ✓; cache
  extraction, not chat (Tasks 5–6) ✓; history reset on file-set change (Task 5) ✓; None handling
  (Task 6) ✓; pymupdf dep (Task 1) ✓; no OCR (Task 2 excludes) ✓.
- **Placeholder scan:** no TBD/TODO; every code step shows real code. (Task 7 is intentionally
  descriptive — it's delegated CSS, the one place the assistant may author.)
- **Type consistency:** `docs` = list of `(name, text)`; `history` = list of `{"role","content"}`;
  `files` = tuple of `(name, bytes)` — used consistently across `extract_pdfs`, `within_budget`,
  `answer_question`, and `app.py`. `TOKEN_CAP` defined in Task 3, imported in Task 5.
