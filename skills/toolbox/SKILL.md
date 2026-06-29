---
name: toolbox
description: >
  The full set of CLI tools on this server and when to use each: spreadsheets/data, office
  documents, OCR, PDF, web/domain research, calculation, archives. Read this for any task
  involving data, documents, files, or numbers so you reach for an existing tool instead of
  inventing one. Demonstrates the deterministic-tool pattern.
---

# Toolbox — what you have and when

Check `command -v <tool>` if unsure. Prefer existing tools over writing code or guessing.

## Spreadsheets & data
- **Read/write xlsx/docx programmatically**: the data venv python (pandas, openpyxl, xlsxwriter, python-docx).
- **ssconvert** convert xlsx/ods/csv. **mlr** (miller) filter/sort/group CSV/TSV/JSON. **csvkit** in2csv/csvsql/csvlook.
- **sqlite3** storage/queries (system-of-record).

## Documents
- **libreoffice --headless --convert-to pdf|docx|xlsx** convert any office format. One at a time (RAM).
- **pandoc** markdown <-> docx/html. **weasyprint** HTML+CSS -> PDF (no browser). **qpdf** split/merge. **pdftotext** text from PDF.

## OCR
- **tesseract <img> out -l <langs>** read scanned invoices, screenshots, photos. Convert PDF pages with `pdftoppm` first.

## Web & domain research
- **whois** owner/registration/expiry. **dig MX +short** mail provider. **whatweb -q** CMS/platform.
- **curl -sI / -w '%{time_total}'** headers/status/load time. **trafilatura** clean main text. **lynx -dump** HTML to text.
- **testssl** deep TLS/cert audit (sparingly, slow). Web search via the agent's web_search tool.

## Calculation
- **qalc -t "<expr>"** math incl. units + live FX. Math syntax, not prose: `qalc -t "1500 * 21%"`.
- **bc**, **units** basics.

## Files, archives, media
- **7z / unzip / unrar** extract. **fd** find. **bat** view. **rg** in-file search. **ffmpeg** audio/video.

## Rules
- Tool present? `command -v <tool>`. Not present -> say so, use an alternative.
- A real `.xlsx`/`.docx`/`.pdf` is always produced by a real tool — never write plain text with a fake extension.
