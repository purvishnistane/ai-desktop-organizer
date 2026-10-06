# AI Desktop Organizer

Developer: **Purvish Nistane** ·

**Your files are messy. AI understands them.** A local-first file intelligence workspace for scanning, explaining, searching, deduplicating, and safely organizing a folder.

## What is implemented
- Recursive local scanner with progress-ready scan records, error isolation, exclusions, and incremental SQLite indexing.
- Text extraction for TXT/Markdown/CSV/JSON/XML/source code; DOCX extraction; optional PDF and OCR pipelines.
- Explainable local classification with confidence, topics, summaries, and an inspectable file detail panel.
- Semantic-style natural-language search over extracted content, filename, topics, and category.
- SHA-256 exact duplicate detection and probable version view.
- Reviewable organization preview, individual approval/rejection, safe move operations, collision handling, and undo log.
- Premium responsive React UI: overview, files, search, duplicates, versions, organize, activity, settings, dark mode, command affordances, toasts, empty states.
- Fully local operation using `demo_files/` as an optional test folder; no API key is required.

## Architecture
`frontend/` is React + TypeScript + Vite. `backend/` is FastAPI with a SQLite local index. Scanner, extraction/classification, search, organization, and operation history are isolated behind API endpoints. The AI provider boundary is intentionally configured through `AI_PROVIDER`; local intelligence is deterministic by default, while external provider integration can be added without changing filesystem or UI layers.

## Install and run
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
In another terminal:
```bash
cd frontend
npm install
npm run dev
```
Open the Vite URL. To scan the included test dataset, enter the absolute path to `demo_files` when prompted (or `./demo_files` from the repository root when running with the appropriate working directory). API docs: `http://localhost:8000/docs`.

## Configuration
Copy `.env.example` to `.env` for local configuration. No secret is included. `AI_PROVIDER=local` is the safe default. `DATABASE_URL` can point at another local SQLite file. The current live implementation deliberately keeps external AI optional: all core indexing, hashing, extraction, search, planning, moves, and undo work without external services.

## Testing
```bash
cd backend && pytest -q
cd ../frontend && npm test
```

## Privacy and safety
Metadata, hashes, and extracted text remain in local SQLite. No folder is uploaded. No file is deleted; organization only moves approved files and records reversible operations. Inputs are resolved to absolute paths and scanned as untrusted data. Do not use the move endpoint against system directories. API keys are never logged or committed.

## Known limitations
- Native folder picker and background worker packaging are platform-wrapper concerns; the API accepts a user-selected path today.
- PDF/OCR extraction is optional based on installed system/package support.
- Local semantic search uses token/concept overlap rather than a large embedding model, avoiding model downloads and preserving local privacy. A replaceable embedding/provider boundary is the next production extension.
- External AI provider calls are not enabled by default.
