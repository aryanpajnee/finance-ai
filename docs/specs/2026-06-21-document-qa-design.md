# Document Q&A — Design Spec

- **Date:** 2026-06-21
- **Status:** Design locked, not yet implemented
- **Feature:** Upload finance documents (PDFs) and ask multi-turn questions, answered strictly from the documents.

## 1. Goal

After an analyst searches a ticker and gets the risk report, give them a section to **upload one or
more finance PDFs (annual reports, filings) and chat with an AI about them**. Answers are
**high-level and decision-relevant** for a working analyst, and **strictly grounded in the uploaded
documents** — never embellished with outside knowledge, never silently wrong.

## 2. Scope

**In:**
- Multiple PDFs uploaded together, answered as one accumulated cross-document response.
- Multi-turn chat with history persisted in `st.session_state`.
- Long-context approach: full document text injected into the prompt each turn (no RAG).
- Loud failure handling for unreadable PDFs and over-budget uploads.
- Strictly document-grounded, attributed answers.

**Out (parked):**
- OCR for scanned/image-only PDFs (v1 flags + excludes them instead).
- Tying answers to the computed risk score (standalone logic for now).
- RAG / chunking / embeddings / retrieval.
- Peer-comparison features (v1.1).

## 3. Locked decisions (from brainstorming, do not relitigate)

- **Standalone logic**, but the UI lives in `app.py` **below the download button**; it appears only
  after a ticker has been analyzed. It does **not** consume the risk score.
- **Multi-PDF**, accumulated answer across all of them.
- **Multi-turn chat**, history in `st.session_state`.
- **Long-context, NOT RAG.**
- **Loud refusal over silent best-effort** for both extraction failures and budget overruns.
- **Strictly document-grounded** answers.
- **Chat messages rendered as custom `.ts-*` tearsheet markup**; native chat-message widgets are
  not used. `st.chat_input` is kept as the input control (it can't be meaningfully replaced) and
  its surroundings are styled to match the existing text input.
- **Token budget cap ~600k tokens** (≈ 2.4M chars, chars/4 heuristic) as the refusal threshold;
  tunable.
- **No OCR in v1.**

## 4. Architecture

One new module, `docchat.py`, modelled on `summary.py`: build a labelled context block → inject into
a guardrailed prompt → call the existing `get_llm_response`. `llm.py` is **untouched**; no LangChain.
`app.py` handles only UI and session state.

```
files ──► extract_pdfs ──► (docs, failures)
                              │
                docs ──► within_budget(docs, history) ──► ok? ──► answer_question(docs, history, q) ──► str | None
                                                          │
                                                       refuse (loud message, no LLM call)
```

### Module surface (`docchat.py`)

- `extract_pdfs(files) -> (docs, failures)`
  - `files`: the list from `st.file_uploader`.
  - `docs`: list of `(filename, text)` for PDFs that yielded meaningful text.
  - `failures`: list of filenames that yielded no meaningful text (scanned/image-only/empty).
  - Uses PyMuPDF (`import fitz`). "Meaningful text" = above a small character threshold after strip.

- `within_budget(docs, history) -> (ok: bool, estimate: int)`
  - Estimates total tokens for the full prompt that *would* be sent (all doc text + transcript +
    system prompt + the next question's overhead), via a chars/4 heuristic.
  - `ok` is `False` when the estimate exceeds the cap (~600k tokens). Returns the estimate so the UI
    can show the number in its refusal message.

- `answer_question(docs, history, question) -> str | None`
  - Builds the single flattened prompt and calls `get_llm_response`.
  - Returns the answer string, or **`None` on any LLM failure** (same contract as `get_llm_response`).
  - Does **not** itself enforce the budget — the UI calls `within_budget` first and refuses before
    ever reaching this function.

## 5. Per-turn prompt structure

`get_llm_response` takes a single string, so each turn flattens everything into one prompt:

1. **System guardrails** (see §7).
2. **Every document's full text, labelled by filename**, each delimited with a clear header so the
   model can attribute figures to a specific source.
3. **The conversation transcript so far** (prior user questions + AI answers).
4. **The new question.**

No chunking, no retrieval — the whole readable corpus rides along every turn.

## 6. Failure handling (loud, never silent)

- **Extraction failures:** any PDF in `failures` is **named in a visible warning** and **excluded**
  from context. If `docs` is empty (every upload failed), the chat does not start.
- **Budget overrun:** `within_budget` is checked before each send. Over the cap → **refuse with a
  clear message** naming the estimate vs. the cap ("these reports exceed what I can read at once —
  remove one"), and **do not call the LLM**. Never truncate silently.

## 7. Guardrails (system prompt, modelled on `summary.py`)

- Answer **only** from the uploaded documents. If the answer isn't in them, say "the documents don't
  cover this" — no outside knowledge, no guessing.
- **Attribute every figure to its source document** ("per `AnnualReport_FY24.pdf` …").
- **Never merge numbers across documents or years** into a single figure.
- High-level and **decision-relevant for an analyst** — concise, not embellished.
- No investment advice (no buy/sell/hold).

## 8. UI & session state (`app.py`, below the download button)

- `st.file_uploader(accept_multiple_files=True)` accepting PDFs.
- Extraction wrapped in `@st.cache_data` keyed on file bytes (re-parsing every Streamlit rerun would
  be wasteful). The **chat call is not cached** — the transcript changes every turn.
- Chat history in `st.session_state` as a list of `{"role", "content"}`.
- **History resets when the uploaded file-set signature (filenames + sizes) changes**, so answers
  never bleed across different document sets.
- Past turns render as **custom `.ts-*` HTML** (not native chat-message widgets). `st.chat_input`
  is the input control.
- On a new question: check `within_budget`; if over, show the refusal and stop. Otherwise call
  `answer_question`. On `None` (LLM failure), show a "service busy" notice and **do not append a
  broken turn to history**. On success, append both the question and the answer.

## 9. Dependency

Adds `pymupdf` (`import fitz`). To be reflected in the eventual `requirements.txt`.

## 10. Verification

- A text-based PDF: upload, ask a question whose answer is in the doc → grounded, attributed answer.
- A question whose answer is *not* in the doc → "the documents don't cover this", no invention.
- A scanned/image-only PDF → named in a warning and excluded; if it's the only upload, no chat.
- Multiple PDFs → answer attributes figures to the right file and does not merge across them.
- Over-budget upload set → loud refusal, no LLM call.
- Changing the uploaded file set → chat history clears.
- LLM failure path → "service busy" notice, history unchanged.
- Live check via Playwright `browser_snapshot` (screenshots time out on the Google-Fonts fetch).

## 11. Notes for implementation

- Per the project's learning rule, the user types every `.py` line; the plan explains and shows
  snippets. `styles.css` / config additions are delegated boilerplate.
- Watch the known CSS gotcha: never put `</style>` (even inside a comment) in `styles.css`.
