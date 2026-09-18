# TTB Label Review

An AI-assisted pre-screener for alcohol beverage labels. A user uploads a label image and the values declared on the TTB F 5100.31 application (COLA), and the tool extracts what's actually printed on the label and checks it field-by-field against what was declared — brand name, class/type, alcohol content, net contents, name and address, country of origin (imports), and the Government Warning statement.

This is a **pre-screen only**. Only TTB (via COLAs Online) can actually approve a label.

**Live demo:** not yet deployed — see [Running locally](#running-locally) below.

## Why this exists

TTB reviews roughly 150,000 label applications a year with a team of 47 agents. Most of that review time is spent on what's essentially data-entry verification — checking that the brand name, ABV, and net contents on the label match what was declared on the application. This tool automates that matching step so agents can spend their attention on the judgment calls, not the character-by-character comparisons.

## How it works

```
Label image(s) + declared application fields
        |
        v
FastAPI backend --------> Ollama (locally-hosted vision-language model)
        |                      extracts structured fields from the image(s)
        v
Matching engine: compares extracted vs. declared fields, one rule type per field
        |
        v
Per-field verdict (match / mismatch / flagged / missing) + overall status
```

The extraction step and the compliance-decision step are deliberately separate. The vision model's job is to read what's on the label; it never decides whether something is compliant. That decision is made by plain, testable Python code, so a legally-exact requirement (like the wording of the Government Warning) is checked with a deterministic rule instead of resting on a model's judgment call. Each field gets one of four rule types:

- **Exact match** — the Government Warning statement, checked verbatim (including that "GOVERNMENT WARNING" appears in capital letters) against the text prescribed by 27 CFR 16.21.
- **Tolerance match** — alcohol content, allowing the ±0.3 percentage point tolerance permitted by 27 CFR 5.65.
- **Enum validation** — net contents, checked against the ~25 standard authorized container sizes in 27 CFR 5.203(a).
- **Fuzzy match** — brand name, class/type, and name/address, which are compared case- and punctuation-insensitively (so "STONE'S THROW" and "Stone's Throw" correctly match) and flagged rather than hard-failed when they're close-but-not-identical.

Fields that are only required in certain cases — country of origin (imports only), appellation and sulfite declaration (wine only), alcohol content (optional for malt beverages depending on state law) — are handled per beverage class rather than with one blanket rule.

## Why local, self-hosted AI instead of a cloud API

This deliberately does **not** call a third-party AI vendor API (OpenAI, Anthropic, Google, etc.) for label extraction. TTB's own environment blocks outbound traffic to a lot of external domains, and a prior scanning-vendor pilot reportedly broke specifically because the firewall blocked its ML endpoints. Rather than build something that would hit the same wall in a real deployment, extraction runs against a locally-hosted, open-weight vision-language model (Qwen2.5-VL, served via [Ollama](https://ollama.com/)) — nothing in the label-review pipeline depends on an external AI vendor being reachable. The app itself could still be cloud-hosted; it's specifically the *inference* step that stays local.

One implementation note worth recording: Ollama supports constraining a model's output to a JSON schema (grammar-guided decoding), which on paper guarantees syntactically valid JSON. In practice, testing this against a real label found it caused the model to silently drop or misassign several fields on this project's schema, even though the JSON it returned was always valid — a mechanical guarantee of *valid* JSON turned out not to be the same as a guarantee of *complete* JSON. The extraction prompt instead describes the schema in text and the backend does its own defensive parsing (with one retry on a malformed response), which measured as far more reliable for this model. See `backend/app/inference/ollama_client.py` for the details.

## Tech stack

| Component | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, SQLite |
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS |
| Model serving | [Ollama](https://ollama.com/) |
| Vision-language model | Qwen2.5-VL (`qwen2.5vl`, 7B) |
| Package management | [uv](https://docs.astral.sh/uv/) (backend), npm (frontend) |

## Running locally

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 18+
- [Ollama](https://ollama.com/download), with the vision model pulled:

  ```bash
  ollama pull qwen2.5vl
  ```

### Backend (http://localhost:8000)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

`uv sync` installs dependencies into a project-local virtualenv; no separate `pip install` or manual venv setup needed. The SQLite database and uploaded images are created inside `backend/` on first run.

Configuration is read from environment variables (see `backend/.env.example` — copy to `backend/.env` to override). The one most worth knowing about: `OLLAMA_BASE_URL` (default `http://localhost:11434`) — point this at wherever Ollama is actually running.

### Frontend (http://localhost:3000)

```bash
cd frontend
npm install
npm run dev
```

`NEXT_PUBLIC_API_BASE_URL` (see `frontend/.env.example`, default `http://localhost:8000`) controls which backend the frontend talks to.

Open http://localhost:3000, upload a label image, fill in what would be declared on the COLA application, and submit.

### Running the tests

```bash
cd backend
uv run pytest
```

These are unit tests against the matching engine's rule logic (exact/tolerance/enum/fuzzy behavior, including the specific examples from the requirements gathering — e.g. that a case/punctuation difference in a brand name should match, and that a title-cased "Government Warning" should not). They don't require Ollama to be running. The extraction pipeline itself was validated end-to-end against the real model on a rendered test label: submitting matching field values returns `overall_status: "clear"` with every field marked as a match, and submitting deliberately wrong values (an out-of-tolerance ABV, an altered brand name) correctly returns `overall_status: "flagged"`, with the ABV mismatch explained in terms of the regulatory tolerance and the altered brand name correctly landing in the fuzzy "close but not identical" tier rather than a hard pass or fail.

## API

| Endpoint | Description |
|---|---|
| `POST /reviews` | Submit one label (front image, optional back image) + declared application fields. Runs extraction and matching, returns the full result. |
| `GET /reviews/{application_id}` | Re-fetch a stored review result. |
| `POST /batches` | Create a batch to group several reviews together. |
| `POST /batches/{batch_id}/items` | Add one label+application to a batch; same fields as `POST /reviews`. |
| `GET /batches/{batch_id}` | Batch summary — per-item status and results. |

Interactive API docs are available at `/docs` while the backend is running.

## Project structure

```
backend/
  app/
    data/ttb_rules.py        Regulatory facts as plain data (warning text, ABV tolerance, standard fill sizes)
    inference/ollama_client.py  The only module that knows Ollama's request/response shape
    matching/engine.py        Field-by-field comparison logic (exact/tolerance/enum/fuzzy)
    routers/                  reviews.py, batches.py — the API endpoints
    review_service.py         Orchestrates one end-to-end review; shared by both routers
    models.py, schemas.py     SQLAlchemy models / Pydantic request-response shapes
  tests/                       Matching engine unit tests
frontend/
  app/
    page.tsx                  Upload form + results view (the whole UI)
    api.ts, types.ts          Backend client and shared types
```

## Known limitations and trade-offs

- **Batch processing is simple, synchronous, in-request handling — not a job queue.** Practical for reviewing a handful to a few dozen labels at once, not a 200-300-application import in one shot. Scaling that further would mean a bulk intake path and server-side queue with rate-limit-aware fan-out; deliberately out of scope for this prototype.
- **The field/rule set is a simplified model of 27 CFR Parts 4, 5, 7, and 16**, not full regulatory fidelity. Commodity-specific disclosures beyond the fields with dedicated rules (color additives, FD&C Yellow No. 5, aspartame, etc.) are surfaced as flagged items for human review rather than individually coded.
- **No image preprocessing for skewed, glare-heavy, or poorly-lit photos.** The pipeline relies on the vision model's native robustness rather than custom deskewing or contrast correction; this is a real gap for photos taken at odd angles.
- **Type size and contrast requirements** (minimum lettering size, background contrast for the Government Warning) can't be verified from a photograph — they need physical measurement of the actual container. Treated as a manual-review item.
- **No integration with the actual COLA system.** This is a standalone prototype; a real deployment would need to fit into TTB's existing authorization and workflow systems.
- **SQLite, no authentication.** Appropriate for a prototype's scale and review process; a production deployment would need a concurrent-safe database and access control.
- **Extraction latency**: cold model load takes roughly 20 seconds on first use; once Ollama has the model resident in memory, extraction settles to roughly 4 seconds per label, which fits the target latency for this to be usable interactively rather than something an agent avoids. Ollama's keep-alive window needs to be long enough that real usage gaps between reviews don't repeatedly force a cold reload.
