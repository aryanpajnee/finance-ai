/* ============================================================================
   AI Financial Risk Analyst — front-end behavior.

   This file is the "behavior" layer. The HTML is the skeleton (what's on the
   page) and the CSS is the skin (how it looks); this JS is what *happens* when
   you act. It runs inside the browser. It cannot call Python directly, so it
   talks to the FastAPI backend over HTTP and paints the answers into the page.

   Mental model of one analysis:
     1. You type a ticker and submit the form.
     2. JS sends a request to  /api/analyze?ticker=...
     3. The backend runs the Python pipeline and replies with JSON.
     4. JS reads that JSON and fills in the page.
   ============================================================================ */

"use strict";

// --------------------------------------------------------------------------- //
// 1. Grab the page elements once, by their id, so we can read/write them later.
//    document.getElementById("x") finds <... id="x">.
// --------------------------------------------------------------------------- //
const $ = (id) => document.getElementById(id);

const tickerForm = $("ticker-form");
const tickerInput = $("ticker-input");
const statusEl = $("status");
const results = $("results");

let currentTicker = "";        // remembered so the chat / PDF know what we analyzed

// --------------------------------------------------------------------------- //
// 2. Tiny helpers for building DOM nodes safely.
//    Using textContent (not innerHTML) for untrusted text means a company name
//    or value can never inject markup into the page.
// --------------------------------------------------------------------------- //
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(message, isError) {
  if (!message) { statusEl.classList.add("hidden"); statusEl.innerHTML = ""; return; }
  statusEl.classList.remove("hidden");
  statusEl.classList.toggle("error", !!isError);
  // a spinner span + the message; spinner only while loading (not on errors)
  statusEl.innerHTML = isError ? "" : '<span class="spinner"></span>';
  statusEl.append(document.createTextNode(message));
}

// --------------------------------------------------------------------------- //
// 3. The form submit handler — the entry point of the whole app.
//    preventDefault() stops the browser's default "reload the page on submit".
//    fetch() makes the HTTP request; await waits for the reply without freezing
//    the page. The reply is parsed from JSON text into a JS object.
// --------------------------------------------------------------------------- //
tickerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const raw = tickerInput.value.trim();
  if (!raw) return;

  currentTicker = raw;
  results.classList.add("hidden");
  setStatus("Analyzing… (fetching financials and generating the summary)", false);

  try {
    const response = await fetch(`/api/analyze?ticker=${encodeURIComponent(raw)}`);
    const data = await response.json();

    if (!response.ok) {                 // backend returned 4xx/5xx with {error: ...}
      setStatus(data.error || "Something went wrong.", true);
      return;
    }

    setStatus("", false);               // clear the spinner
    render(data);                       // paint the results
    results.classList.remove("hidden");
  } catch (err) {
    setStatus("Could not reach the server. Is it running?", true);
  }
});

// --------------------------------------------------------------------------- //
// 4. render(data): take the JSON object and fill every section of the page.
//    Each sub-function below handles one block, mirroring the old app.py order.
// --------------------------------------------------------------------------- //
function render(data) {
  $("company").textContent = data.company;
  $("meta").textContent = data.meta;

  collapseRaw();   // every new analysis starts with the raw table collapsed
  $("low-conf").classList.toggle("hidden", !data.low_confidence);

  renderRiskAxis(data.risk);
  renderEvidence(data.evidence);
  renderPerYear(data.years, data.per_year);
  renderRawTable(data.raw_table);
  renderSummary(data.summary_html);

  // The PDF download is just a link to another backend route; the browser
  // downloads whatever bytes that URL returns.
  $("download-btn").href = `/api/report?ticker=${encodeURIComponent(currentTicker)}`;

  resetChat();   // a fresh analysis clears any previous document chat
}

// ----- Raw financials expander (animated open/close) ----------------------- //
const rawToggle = $("raw-toggle");
const rawPanel = $("raw-panel");

function collapseRaw() {
  rawPanel.classList.remove("open");
  rawToggle.setAttribute("aria-expanded", "false");
}

rawToggle.addEventListener("click", () => {
  const open = rawPanel.classList.toggle("open");
  rawToggle.setAttribute("aria-expanded", open ? "true" : "false");
});

// ----- Risk Axis ----------------------------------------------------------- //
function renderRiskAxis(risk) {
  const axis = $("risk-axis");
  const band = $("risk-band");
  const marker = $("risk-marker");
  const value = $("risk-value");
  const ghost = $("risk-ghost");
  const connector = $("risk-connector");
  const legend = $("risk-legend");

  // reset band classes each time
  axis.classList.remove("is-low", "is-mod", "is-high");

  if (risk.score === null || risk.score === undefined) {
    band.textContent = "No score";
    marker.classList.add("hidden");
    ghost.classList.add("hidden");
    connector.classList.add("hidden");
    legend.classList.remove("hidden");
    legend.textContent = "Not enough data to compute a score.";
    return;
  }

  axis.classList.add(risk.band_class);
  band.textContent = risk.band_label;

  // The 0–100 score IS the percentage along the track. clamp keeps it on-track.
  const pos = Math.max(0, Math.min(100, risk.score));
  marker.classList.remove("hidden");
  marker.style.left = `${pos}%`;
  value.textContent = risk.score_display;

  if (risk.show_ghost) {
    const gpos = Math.max(0, Math.min(100, risk.snapshot));
    const lo = Math.min(pos, gpos);
    const hi = Math.max(pos, gpos);
    connector.classList.remove("hidden");
    connector.style.left = `${lo}%`;
    connector.style.width = `${hi - lo}%`;
    ghost.classList.remove("hidden");
    ghost.style.left = `${gpos}%`;
    legend.classList.remove("hidden");
    legend.innerHTML =
      `was <b>${risk.snapshot_display}</b> &nbsp;&#9654;&nbsp; now <b>${risk.score_display}</b>`;
  } else {
    connector.classList.add("hidden");
    ghost.classList.add("hidden");
    legend.classList.add("hidden");
  }
}

// ----- Evidence table ------------------------------------------------------ //
function renderEvidence(rows) {
  const body = $("evidence-body");
  body.innerHTML = "";
  for (const r of rows) {
    const tr = el("tr");
    tr.append(el("td", "metric", r.label));
    tr.append(el("td", "num", r.value));
    tr.append(el("td", "num", r.sub));
    tr.append(el("td", `num ${r.tcls}`, r.trend));   // tcls = up / down / flat → color
    tr.append(el("td", "num", r.adj));
    body.append(tr);
  }
}

// ----- Per-year ratios table ----------------------------------------------- //
function renderPerYear(years, perYear) {
  const table = $("per-year-table");
  table.innerHTML = "";

  const thead = el("thead");
  const headRow = el("tr");
  headRow.append(el("th", null, "Metric"));
  for (const y of years) headRow.append(el("th", "num", y));
  thead.append(headRow);
  table.append(thead);

  const tbody = el("tbody");
  for (const row of perYear) {
    const tr = el("tr");
    tr.append(el("td", "metric", row.metric));
    for (const cell of row.cells) tr.append(el("td", "num", cell));
    tbody.append(tr);
  }
  table.append(tbody);
}

// ----- Raw financials (₹ Crore) -------------------------------------------- //
function renderRawTable(raw) {
  const table = $("raw-table");
  table.innerHTML = "";

  const thead = el("thead");
  const headRow = el("tr");
  headRow.append(el("th", null, ""));                 // top-left corner is blank
  for (const col of raw.columns) headRow.append(el("th", "num", col));
  thead.append(headRow);
  table.append(thead);

  const tbody = el("tbody");
  raw.rows.forEach((cells, i) => {
    const tr = el("tr");
    tr.append(el("td", "metric", raw.index[i]));      // row label = the date
    for (const cell of cells) tr.append(el("td", "num", cell));
    tbody.append(tr);
  });
  table.append(tbody);
}

// ----- Analyst note -------------------------------------------------------- //
function renderSummary(summaryHtml) {
  const note = $("analyst-note");
  if (summaryHtml) {
    // Trusted HTML: the backend rendered the LLM's Markdown to HTML for us.
    note.innerHTML = summaryHtml;
  } else {
    note.innerHTML =
      "<p>AI summary unavailable right now (service busy). " +
      "The score and evidence above are still valid.</p>";
  }
}

// --------------------------------------------------------------------------- //
// 5. Document Q&A.
//    Uploading sends the PDF bytes to the backend, which extracts the text and
//    hands back a session_id. The browser holds the chat history; each question
//    sends {session_id, question, history} and gets an answer back.
// --------------------------------------------------------------------------- //
const docFiles = $("doc-files");
const docFileList = $("doc-filelist");
const docWarn = $("doc-warn");
const chatLog = $("chat-log");
const chatForm = $("chat-form");
const chatInput = $("chat-input");

let docSession = null;          // id the backend gave us for the uploaded docs
let chatHistory = [];           // [{role:"user"|"assistant", content:"..."}]

function resetChat() {
  docSession = null;
  chatHistory = [];
  chatLog.innerHTML = "";
  docFileList.innerHTML = "";
  docWarn.classList.add("hidden");
  chatForm.classList.add("hidden");
  docFiles.value = "";
}

// Show the picked filenames under the drop box. Built with DOM nodes (el uses
// textContent) so a filename can never inject markup.
function showFileNames(fileList) {
  docFileList.innerHTML = "";
  const files = Array.from(fileList);
  if (!files.length) return;
  docFileList.append(document.createTextNode("Selected: "));
  files.forEach((f, i) => {
    if (i) docFileList.append(document.createTextNode(", "));
    docFileList.append(el("span", "name", f.name));
  });
}

// Shared upload routine — used by both the file picker and drag-and-drop.
async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  showFileNames(fileList);
  docWarn.classList.add("hidden");
  chatForm.classList.add("hidden");
  chatLog.innerHTML = "";
  chatHistory = [];

  // FormData is the standard way to send files; the browser sets the right
  // multipart Content-Type for us. The field name "files" matches FastAPI.
  const form = new FormData();
  for (const file of fileList) form.append("files", file);

  try {
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const data = await response.json();

    if (data.failures && data.failures.length) {
      docWarn.classList.remove("hidden");
      docWarn.textContent =
        "Couldn't read text from: " + data.failures.join(", ") +
        ". These look scanned or image-only and were skipped (no OCR).";
    }
    if (!data.has_docs) {
      docWarn.classList.remove("hidden");
      docWarn.textContent = "No readable documents to chat with.";
      return;
    }
    docSession = data.session_id;
    chatForm.classList.remove("hidden");
  } catch (err) {
    docWarn.classList.remove("hidden");
    docWarn.textContent = "Upload failed. Try again.";
  }
}

// Clicking the button opens the native dialog via the <label for>; this fires
// when the user picks files through that dialog.
docFiles.addEventListener("change", () => uploadFiles(docFiles.files));

// Append one chat bubble. role drives the styling + the label.
function addBubble(role, html) {
  const cls = role === "user" ? "ts-chat ts-chat-user" : "ts-chat ts-chat-ai";
  const bubble = el("div", cls);
  bubble.innerHTML = html;
  chatLog.append(bubble);
  bubble.scrollIntoView({ block: "nearest" });
  return bubble;
}

// Escape user text so it's shown literally, not parsed as HTML.
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return `<p>${div.innerHTML}</p>`;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = chatInput.value.trim();
  if (!question || !docSession) return;

  addBubble("user", escapeHtml(question));
  chatInput.value = "";

  // Show an animated "typing" bubble while we wait for the answer.
  const loading = addBubble("assistant",
    '<span class="chat-typing"><span></span><span></span><span></span></span>');

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: docSession,
        question: question,
        history: chatHistory,
      }),
    });
    const data = await response.json();
    loading.remove();   // drop the typing bubble before showing the result

    if (data.error === "too_large") {
      addBubble("assistant",
        `<p>These documents are too large to read at once (~${data.est.toLocaleString()} ` +
        `tokens vs ~${data.cap.toLocaleString()} limit). Remove one and try again.</p>`);
      return;
    }
    if (data.error === "busy" || !data.answer) {
      addBubble("assistant", "<p>AI service busy — try again in a moment.</p>");
      return;
    }

    addBubble("assistant", data.answer_html);
    // record BOTH turns as raw text so the next question carries the transcript
    chatHistory.push({ role: "user", content: question });
    chatHistory.push({ role: "assistant", content: data.answer });
  } catch (err) {
    loading.remove();
    addBubble("assistant", "<p>Could not reach the server. Try again.</p>");
  }
});
