---
name: make-document
description: >
  Turn a quote, letter, or report from markdown into a clean PDF/DOCX. Use for "make it a PDF",
  "quote as a document", "convert this to Word". Produces client-ready deliverables without a
  browser/Chromium. (Example application of the system + the toolbox pattern.)
---

# Document -> PDF or DOCX

Deliver in a clean format. No headless browser needed.

## Steps
1. Ack + short plan.
2. Write/obtain the content as markdown in `~/.hermes/notes/out/<slug>.md`.
3. Convert:
   - **To PDF**: markdown -> HTML via `pandoc <in>.md -o <tmp>.html`, then `weasyprint <tmp>.html <out>.pdf` (pure Python, no Chromium).
   - **To DOCX**: `pandoc <in>.md -o <out>.docx`.
4. Report the output path. **Never use wkhtmltopdf** (dead project, SSRF CVE).

## Content rules (a quote/proposal)
- Clear, no jargon. Customer benefit over feature.
- Price block: never "free"; a founding deal / friend's rate / fixed price + scope.
- State: what, scope, price (note your VAT situation), timing, validity of the quote.

## Before sending
Producing the document = ok. **Emailing/sending it to the client = ask for OK first.**
