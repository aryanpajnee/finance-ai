import fitz #pymupdf
from llm import get_llm_response

MIN_CHARS = 100

def extract_pdfs(files):
    """files: list of (filename, pdf_bytes). Returns (docs, failures)."""
    docs,failures = [] , []
    for name, data in files:
        try:
            with fitz.open(stream = data , filetype="pdf") as doc:
                text = "\n".join(page.get_text() for page in doc)
        except Exception as e:
            print(f"EXTRACT ERROR {name} : {e}")
            failures.append(name)
            continue
        if len(text.strip()) < MIN_CHARS:
            failures.append(name)
        else:
            docs.append((name,text))
        
    return docs , failures

CHARS_PER_TOKEN= 4
TOKEN_CAP = 200_000
_PROMPT_OVERHEAD_CHARS=3000

def estimate_tokens(docs , history , question=""):
    chars = sum(len(text) for _ , text in docs)
    chars += sum(len(m["content"])for m in history)
    chars += len(question) + _PROMPT_OVERHEAD_CHARS
    
    return chars // CHARS_PER_TOKEN

def within_budget(docs , history):
    est = estimate_tokens(docs , history)
    return est <= TOKEN_CAP , est


SYSTEM_PROMPT = """You are a financial analyst assistant. You answer questions about the uploaded
documents below.

Grounding rules (strict):
- Every figure must come ONLY from the documents. Never state a number that isn't in them.
- Attribute every figure to its source document by filename (e.g. "per report_TCS.pdf ...").
- Never merge or average numbers across different documents or different years into one figure.
- If a requested FACT or figure isn't in the documents, say plainly: "The documents don't cover this."
- You have NO web or external data access. Never invent or cite competitor, sector, or market figures,
  and never claim to compare against other companies — say that's not available instead.
- All companies are Indian; use rupees (₹) or no currency unit — never dollars.
- Do not give investment advice (no buy/sell/hold).

Adding insight (this is what makes you useful, not just a lookup):
- After reporting a figure from the documents, briefly explain what the metric measures and whether the
  value is strong, average, or weak by standard financial rules of thumb — framed clearly as general
  guidance, not a document fact.
- Be concise and decision-relevant. Interpret the documents' own numbers and how they relate to each
  other; do not pad with outside facts."""


def _build_prompt(docs, history , question):
    parts = [SYSTEM_PROMPT , "" , "=== DOCUMENTS ==="]
    for name,text in docs:
        parts.append(f"\n---DOCUMENT: {name} ---\n{text}")
    parts.append("\n=== CONVERSATION SO FAR ===")
    for m in history:
        speaker = "Analyst" if m["role"] == "user" else "Assistant"
        parts.append(f"{speaker}: {m['content']}")
    parts.append(f"\nAnalyst: {question}")
    parts.append("Assistant:")
    return "\n".join(parts)

def answer_question(docs , history , question):
    return get_llm_response(_build_prompt(docs, history , question))


    
    
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python docchat.py <pdf_path> [question]")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    name = path.split("/")[-1]
    docs, failures = extract_pdfs([(name, data)])
    print("docs:", [(n, len(t)) for n, t in docs])
    print("failures:", failures)
    ok, est = within_budget(docs, [])
    print("within_budget:", ok, "est tokens:", est)
    question = sys.argv[2] if len(sys.argv) > 2 else "What does this document say about revenue and margins?"
    print("\nANSWER:\n", answer_question(docs, [], question))