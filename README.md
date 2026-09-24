# TTB Label Review

An AI-assisted pre-screener for alcohol beverage labels. A user uploads a label image and (optionally) the values declared on the TTB F 5100.31 application (COLA), and the tool extracts what's actually printed on the label and checks it field-by-field — against what was declared where something was, and against the label requirements themselves either way: brand name, class/type, alcohol content (and proof), net contents, name and address, country of origin (imports), and the Government Warning statement.

This is a **pre-screen only**. Only TTB (via COLAs Online) can actually approve a label.

**Live demo:** not yet deployed — see [Running locally](#running-locally) below.

## Why this exists

TTB reviews roughly 150,000 label applications a year with a team of 47 agents. Most of that review time is spent on what's essentially data-entry verification — checking that the brand name, ABV, and net contents on the label match what was declared on the application. This tool automates that matching step so agents can spend their attention on the judgment calls, not the character-by-character comparisons.

## How it works

```
Agent picks label photo(s) ──▶ POST /extractions (one per image, returns immediately)
        │                            │  normalize: fix phone rotation, downscale to 1024px
        │                            ▼
        │                     background task ──▶ Ollama (locally-hosted vision-language model)
        │                                          reads the label into structured fields
        ▼
Agent fills in the application fields meanwhile (all optional)
        │
        ▼
POST /reviews ──▶ wait for the extraction(s) (usually already finished)
                  merge front + back readings, remembering which side each field came from
                  matching engine: one rule type per field
                  ──▶ per-field verdict + overall status ──▶ agent records Accept / Reject / Needs follow-up
```

**The model starts reading the label the moment it's uploaded**, not when the agent presses Review. On the development machine the model takes ~9 s per image, and a person spends longer than that typing in application fields. So by the time they submit, the review is normally just the matching step, which takes milliseconds. The results show both numbers ("ready 0.1s after you pressed Review · the label took 8.7s to read"). Each image is read separately, which also tells the engine which side of the container each field was printed on (wine's brand name and class/type must be on the front label).

The extraction step and the compliance-decision step are deliberately separate. The vision model's job is to read what's on the label; it never decides whether something is compliant. That decision is made by plain, testable Python code, so a legally-exact requirement (like the wording of the Government Warning) is checked with a deterministic rule instead of resting on a model's judgment call. Each field gets one of these rule types:

- **Exact match** — the Government Warning statement, checked verbatim (including that "GOVERNMENT WARNING" appears in capital letters) against the text prescribed by 27 CFR 16.21.
- **Tolerance match** — alcohol content, allowing the ±0.3 percentage point tolerance permitted by 27 CFR 5.65; and proof, which must equal twice the stated ABV.
- **Enum validation** — net contents, checked against the authorized standard-of-fill sizes for the product: 27 CFR 5.203 for spirits, 27 CFR 4.72 for wine (including 4 L+ in even liters), none for malt beverages. It understands mL, cL, L, fl oz, pints, quarts and gallons, so a declared "12 FL OZ" matches a label's "355 mL".
- **Fuzzy match** — brand name, class/type, and name/address, which are compared case- and punctuation-insensitively (so "STONE'S THROW" and "Stone's Throw" correctly match) and flagged rather than hard-failed when they're close-but-not-identical.
- **Placement** — on wine, brand name and class/type found only on the back label are flagged (27 CFR 4.32(a)).

**Every declared field is optional.** Class/type, ABV and net contents aren't even on the real TTB F 5100.31 form. Asking an agent to type them in from the label, then checking the label against what they typed, would be circular. A field left blank is checked on the label alone: is a required field printed at all, is the container a standard size, is the warning exact. Only beverage class and import status are required, because they decide which rules apply.

Fields that are only required in certain cases — country of origin (imports only), appellation and sulfite declaration (wine only), alcohol content (optional for malt beverages depending on state law) — are handled per beverage class rather than with one blanket rule.

## Why local, self-hosted AI instead of a cloud API

This deliberately does **not** call a third-party AI vendor API (OpenAI, Anthropic, Google, etc.) for label extraction. TTB's own environment blocks outbound traffic to a lot of external domains, and a prior scanning-vendor pilot reportedly broke specifically because the firewall blocked its ML endpoints. Rather than build something that would hit the same wall in a real deployment, extraction runs against a locally-hosted, open-weight vision-language model (Qwen2.5-VL, served via [Ollama](https://ollama.com/)) — nothing in the label-review pipeline depends on an external AI vendor being reachable. The app itself could still be cloud-hosted; it's specifically the *inference* step that stays local.

One implementation note worth recording: Ollama supports constraining a model's output to a JSON schema (grammar-guided decoding), which on paper guarantees syntactically valid JSON. In practice, testing this against a real label found it caused the model to silently drop or misassign several fields on this project's schema, even though the JSON it returned was always valid — a mechanical guarantee of *valid* JSON turned out not to be the same as a guarantee of *complete* JSON. The extraction prompt instead describes the schema in text and the backend does its own defensive parsing (with one retry on a malformed response), which measured as far more reliable for this model. See `backend/app/inference/ollama_client.py` for the details.

## Performance

Measured on an M4 Pro (qwen2.5vl 7B via Ollama, label images capped at 1024 px):

- **~6–9 s to read one label image**, started the moment it's uploaded. If the agent spends that long filling in the application fields, the result is ready the instant they press Review.
- **Worst case** (both images submitted together with the review, no head start): median 12.1 s, range 4–16 s across the test gauntlet.
- **A re-uploaded image** is recognized by content hash and not read again.

The dedicated GPU box this is meant to run against should be considerably faster. The gauntlet (`testing/run_gauntlet.py`) is the benchmark to re-run there.

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

These cover the matching engine's rule logic, net-contents parsing, front/back merging, image normalization, and the upload → review API flow (with the vision model stubbed out). The rule tests are (exact/tolerance/enum/fuzzy behavior, including the specific examples from the requirements gathering — e.g. that a case/punctuation difference in a brand name should match, and that a title-cased "Government Warning" should not). They don't require Ollama to be running. The extraction pipeline itself was validated end-to-end against the real model on a rendered test label: submitting matching field values returns `overall_status: "clear"` with every field marked as a match, and submitting deliberately wrong values (an out-of-tolerance ABV, an altered brand name) correctly returns `overall_status: "flagged"`, with the ABV mismatch explained in terms of the regulatory tolerance and the altered brand name correctly landing in the fuzzy "close but not identical" tier rather than a hard pass or fail.

## Deployment

The intended deployment keeps the vision model entirely off the internet:

```
Internet ──▶ reverse proxy (subdomain, HTTPS)
               ├─ /       ──▶ Next.js frontend  (next build && next start)
               └─ /api/*  ──▶ FastAPI backend   (one uvicorn worker)
                                 │  LAN only
                                 ▼
                           Ollama on a separate GPU machine
```

- **Ollama is never exposed.** It binds to the GPU machine's LAN address (`OLLAMA_HOST=<lan-ip>:11434`), its host firewall only allows the backend machine's IP on 11434, and no router port-forward points at it. Ollama has no authentication of its own, so the firewall rule is what stops anything else on the network from using it.
- **The backend is the only way to reach the model, and it only ever asks one thing:** "transcribe this image" with a fixed server-side prompt, using the model named in server config. Nothing a client sends becomes a prompt, a model name, or an Ollama option. The worst a caller can do is submit images, and that is bounded by the 20 MB per-file limit, the `OLLAMA_MAX_CONCURRENCY` gate on concurrent model calls, and whatever rate limit the reverse proxy applies. Text printed on an uploaded image can at most skew that image's own extracted fields, which are schema-validated and compared by deterministic code.
- **Serve both from one origin** by routing `/api/*` to the backend with the prefix stripped, and build the frontend with `NEXT_PUBLIC_API_BASE_URL=https://<subdomain>/api`. Set `CORS_ORIGINS` to the same origin.
- **Proxy timeouts:** `POST /reviews` can wait on a label that's still being read (up to `OLLAMA_TIMEOUT_SECONDS`, 120 s by default), and extraction status requests hold open for up to 25 s. The proxy's upstream read timeout needs to exceed both.
- **Run a single uvicorn worker.** Background extractions live in the backend process.
- Match `OLLAMA_NUM_PARALLEL` on the GPU machine to `OLLAMA_MAX_CONCURRENCY` on the backend.

## API

| Endpoint | Description |
|---|---|
| `POST /extractions` | Upload one label image. Returns an extraction id immediately; the model reads it in the background. Re-uploading an identical image reuses the earlier result. |
| `GET /extractions/{id}?wait=N` | Extraction status; with `wait`, long-polls up to N seconds for it to finish. |
| `DELETE /extractions/{id}` | Cancel an in-flight extraction (the user swapped the photo). |
| `GET /extractions/{id}/image` | The image as the model saw it (upright, resized). |
| `POST /reviews` | Review a label: `front_extraction_id` (+ optional `back_extraction_id`) from the calls above, or the image files directly, plus the declared application fields. Waits for extraction if still running, then returns the full result. |
| `GET /reviews/{application_id}` | Re-fetch a stored review result. |
| `PUT /reviews/{application_id}/decision` | Record the agent's call: `accept` / `reject` / `follow_up`, with an optional note. |
| `POST /batches` | Create a batch to group several reviews together. |
| `POST /batches/{batch_id}/items` | Add one label+application to a batch; same fields as `POST /reviews`. |
| `GET /batches/{batch_id}` | Batch summary — per-item status and results. |
| `POST /applications/extract-pdf` | Read a filled-in TTB F 5100.31 PDF's form fields to pre-fill the form. |

Interactive API docs are available at `/docs` while the backend is running.

## Project structure

```
backend/
  app/
    data/ttb_rules.py        Regulatory facts as plain data (warning text, ABV tolerance, standard fill sizes)
    inference/ollama_client.py  The only module that knows Ollama's request/response shape
    images.py                 Upload normalization: EXIF rotation, downscale, re-encode
    extraction_service.py     Background extraction started on upload; reuse by content hash
    matching/merge.py         Combines front + back readings, recording which side each came from
    matching/engine.py        Field-by-field comparison logic (exact/tolerance/enum/fuzzy/placement)
    routers/                  extractions.py, reviews.py, batches.py, applications.py — the API endpoints
    review_service.py         Orchestrates one end-to-end review; shared by reviews and batches
    models.py, schemas.py     SQLAlchemy models / Pydantic request-response shapes
  tests/                       Unit tests (rules, parsing, merging, images) + API flow tests with a stubbed model
frontend/
  app/
    page.tsx                  Upload form
    useLabelUpload.ts         Starts extraction as soon as a photo is picked; tracks its progress
    ReviewResultView.tsx      Results beside the label images, plus the agent's decision
    api.ts, types.ts          Backend client and shared types
```

## Known limitations and trade-offs

- **Batch processing is simple, synchronous, in-request handling, and the UI doesn't expose it yet.** The endpoints handle a handful to a few dozen labels, not a 200–300-application import. [docs/batch-processing-plan.md](docs/batch-processing-plan.md) specifies the full design: CSV + folder intake, server-side runner, priority over interactive reviews, triage UI.
- **Background extraction runs inside the backend process.** Run uvicorn with a single worker. An extraction interrupted by a restart re-runs automatically when something waits on it.
- **The field/rule set is a simplified model of 27 CFR Parts 4, 5, 7, and 16**, not full regulatory fidelity. Commodity-specific disclosures beyond the fields with dedicated rules (color additives, FD&C Yellow No. 5, aspartame, etc.) are surfaced as flagged items for human review rather than individually coded. Spirits' "same field of vision" rule (brand, class/type, ABV) can't be judged from separate photos and isn't checked.
- **Image handling is limited to rotation and size.** EXIF rotation is corrected and images are downscaled, but there's no deskewing, perspective correction, or glare removal; the pipeline relies on the vision model's robustness for photos taken at odd angles.
- **Type size, bold type, and contrast** (minimum lettering size, the bold "GOVERNMENT WARNING:", background contrast) can't be verified from a photograph and are treated as manual-review items.
- **The vision model can misread in plausible-looking ways.** During development it transcribed a title-case "Government Warning" as all caps, invented a warning for a front label that had none, and split a bottler statement in two. Each was fixed and is covered by the 43-case test gauntlet (currently 43/43; see `testing/README.md`), but a transcription model can't guarantee character-exact fidelity. The exact-wording checks are only as good as the reading they're given, which is why the agent always sees the label image next to every verdict.
- **No integration with the actual COLA system.** This is a standalone prototype; a real deployment would need to fit into TTB's existing authorization and workflow systems.
- **SQLite, no authentication.** Appropriate for a prototype's scale and review process; a production deployment would need a concurrent-safe database and access control. Schema changes aren't migrated: delete `backend/ttb_review.db` after pulling a change to the models.
