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
        │                     background task ──▶ open-weight vision-language model
        │                                          (Llama 4 Maverick on Amazon Bedrock, or self-hosted via Ollama)
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

**The model starts reading the label the moment it's uploaded**, not when the agent presses Review. Bedrock reads a label image in ~1.5 s (the self-hosted model on the development machine took ~9 s), and a person spends longer than that typing in application fields. So by the time they submit, the review is normally just the matching step, which takes milliseconds. The results show both numbers ("ready 0.1s after you pressed Review · the label took 8.7s to read"). Each image is read separately, which also tells the engine which side of the container each field was printed on (wine's brand name and class/type must be on the front label).

The extraction step and the compliance-decision step are deliberately separate. The vision model's job is to read what's on the label; it never decides whether something is compliant. That decision is made by plain, testable Python code, so a legally-exact requirement (like the wording of the Government Warning) is checked with a deterministic rule instead of resting on a model's judgment call. Each field gets one of these rule types:

- **Exact match** — the Government Warning statement, checked verbatim (including that "GOVERNMENT WARNING" appears in capital letters) against the text prescribed by 27 CFR 16.21.
- **Tolerance match** — alcohol content, allowing the ±0.3 percentage point tolerance permitted by 27 CFR 5.65; and proof, which must equal twice the stated ABV.
- **Enum validation** — net contents, checked against the authorized standard-of-fill sizes for the product: 27 CFR 5.203 for spirits, 27 CFR 4.72 for wine (including 4 L+ in even liters), none for malt beverages. It understands mL, cL, L, fl oz, pints, quarts and gallons, so a declared "12 FL OZ" matches a label's "355 mL".
- **Fuzzy match** — brand name, class/type, and name/address, which are compared case- and punctuation-insensitively (so "STONE'S THROW" and "Stone's Throw" correctly match) and flagged rather than hard-failed when they're close-but-not-identical.
- **Placement** — on wine, brand name and class/type found only on the back label are flagged (27 CFR 4.32(a)).

### Batch review

For the peak-season case of an importer submitting 200–300 applications at once, **Review a batch** takes a folder of label photos plus a spreadsheet with one row per application. A template can be downloaded from the batch page; only `front_image` is required. A folder of photos alone also works: each label is then checked on its own, with `NAME_front` / `NAME_back` photos paired automatically.

- **Every problem is found before anything uploads.** Missing or misspelled filenames come with a "did you mean", along with bad beverage classes, unreadable ABV values, and duplicate rows. The agent fixes them and re-drops, or starts the rest.
- **The batch runs on the server.** Photos are shrunk in the browser and uploaded one application at a time, and each starts being read as soon as it arrives. After the upload the agent can close the page. The batch survives a backend restart, and re-dropping the same folder resumes an interrupted upload.
- **Single reviews always go first.** Model calls go through a priority gate, so an agent reviewing one label at their desk waits only for the batch images already being read, not the whole queue. Measured on the dev machine: 11.5 s for an interactive label with ~80 s of batch work queued ahead of it.
- **Triage, not a spreadsheet.** Results list "Needs your review" first, then "Couldn't be read", then the rest. Each opens in the same side-by-side view as a single review, with Accept / Reject / Needs follow-up and Next/Previous. The whole batch exports as CSV, decisions included.

The design, and what's deliberately left for later, is in [docs/batch-processing-plan.md](docs/batch-processing-plan.md).

**Every declared field is optional.** Class/type, ABV and net contents aren't even on the real TTB F 5100.31 form. Asking an agent to type them in from the label, then checking the label against what they typed, would be circular. A field left blank is checked on the label alone: is a required field printed at all, is the container a standard size, is the warning exact. Only beverage class and import status are required, because they decide which rules apply.

Fields that are only required in certain cases — country of origin (imports only), appellation and sulfite declaration (wine only), alcohol content (optional for malt beverages depending on state law) — are handled per beverage class rather than with one blanket rule.

## Why an open-weight model, and why Bedrock

Label extraction deliberately does **not** depend on a vendor-only model (GPT, Claude, Gemini). TTB's network blocks outbound traffic to a lot of external domains, and a prior scanning-vendor pilot reportedly broke because the firewall blocked its ML endpoints. So the model has to be something the agency could run wherever its own policy allows: its own cloud account, its own hardware, or behind its firewall.

That's why the model is **open-weight**, and why the code has two interchangeable providers behind one setting (`INFERENCE_PROVIDER`):

- **`bedrock`** (the deployed demo): Llama 4 Maverick on Amazon Bedrock. Pay-per-call, always available, no GPU to keep running. Bedrock is available in AWS GovCloud and reachable over a private endpoint, so this is also a realistic production shape: the traffic stays inside a FedRAMP-authorized cloud account instead of going to a third-party AI vendor. (TTB is on Azure; Azure's model catalog serves the same open-weight models, so the equivalent there is a new ~100-line client, not a redesign.)
- **`ollama`**: the same pipeline against a self-hosted model (Qwen2.5-VL 7B) on your own machine, for fully offline or on-premises use. This is what the project was first built and tuned on.

Both send the identical prompt and are parsed by the same code; the provider modules are the only place that knows either API. Nothing a client sends becomes part of a prompt, a model name, or a model option.

One implementation note worth recording: Ollama supports constraining a model's output to a JSON schema (grammar-guided decoding), which on paper guarantees syntactically valid JSON. In practice, testing this against a real label found it caused the model to silently drop or misassign several fields on this project's schema, even though the JSON it returned was always valid — a mechanical guarantee of *valid* JSON turned out not to be the same as a guarantee of *complete* JSON. The extraction prompt instead describes the schema in text and the backend does its own defensive parsing (with one retry on a malformed response), which measured as far more reliable for this model. See `backend/app/inference/ollama_client.py` for the details.

## Performance

**Llama 4 Maverick on Bedrock** (the deployed configuration), label images capped at 1024 px:

- **~1.5 s to read one label image** (range 1.0–4.7 s across the test gauntlet), started the moment it's uploaded. By the time the agent has filled in the application, the result is waiting and pressing Review is just the matching step.
- **About $0.001 per image** at Bedrock's on-demand price, so a 300-application batch with front and back labels costs under $1.
- **A re-uploaded image** is recognized by content hash and not read again.

**Qwen2.5-VL 7B via Ollama on an M4 Pro** (the self-hosted option): ~6–9 s per image; worst case (both images submitted with the review, no head start) median 12.1 s, range 4–16 s. A dedicated GPU would be considerably faster.

The gauntlet (`testing/run_gauntlet.py`) is the benchmark for either.

## Tech stack

| Component | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, SQLite |
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS |
| Model serving | [Amazon Bedrock](https://aws.amazon.com/bedrock/) (Converse API), or [Ollama](https://ollama.com/) self-hosted |
| Vision-language model | Llama 4 Maverick 17B on Bedrock; Qwen2.5-VL 7B (`qwen2.5vl`) on Ollama. Both open-weight |
| Package management | [uv](https://docs.astral.sh/uv/) (backend), npm (frontend) |

## Running locally

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 18+
- One of:
  - **Amazon Bedrock:** a Bedrock API key (Bedrock console → API keys). In `backend/.env` set `INFERENCE_PROVIDER=bedrock` and `BEDROCK_KEY=<your key>`.
  - **Ollama**, self-hosted: [install it](https://ollama.com/download) and pull the model with `ollama pull qwen2.5vl`. This is the default (`INFERENCE_PROVIDER=ollama`).

### Backend (http://localhost:8000)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

`uv sync` installs dependencies into a project-local virtualenv; no separate `pip install` or manual venv setup needed. The SQLite database and uploaded images are created inside `backend/` on first run.

Configuration is read from environment variables (see `backend/.env.example` — copy to `backend/.env` to override). The ones most worth knowing: `INFERENCE_PROVIDER` (`ollama` or `bedrock`), then either `BEDROCK_KEY` / `BEDROCK_REGION` / `BEDROCK_MODEL_ID`, or `OLLAMA_BASE_URL` (default `http://localhost:11434`) for wherever Ollama is running.

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

Backend tests don't need a model; it's stubbed out. They cover:
- the matching rules, including the examples from the stakeholder interviews: "STONE'S THROW" matches "Stone's Throw", and a title-case "Government Warning" does not pass;
- net-contents parsing, front/back merging, and image normalization;
- the upload → review API flow and the batch lifecycle (create, attach, background review, retry, cancel, resume after restart, export);
- the Bedrock client against a fake server (request shape, a reply wrapped in code fences, retry on throttling, Bedrock's error surfaced);
- the priority gate, and a regression test for a connection-pool deadlock under large batches.

```bash
cd frontend
npm test
```

Frontend tests cover batch intake: CSV parsing (quoted fields, Excel's byte-order mark), filename matching with "did you mean" suggestions, and pairing front/back photos when there's no spreadsheet.

The end-to-end check against the real model is the test gauntlet in [`testing/`](testing/README.md): 43 rendered labels with known-correct verdicts, run as single reviews or, with `--batch`, as one batch.

## Deployment

```
Internet ──▶ reverse proxy (HTTPS)
               ├─ /       ──▶ Next.js frontend  (next build && next start)
               └─ /api/*  ──▶ FastAPI backend   (one uvicorn worker)
                                 │  HTTPS, API key
                                 ▼
                           Amazon Bedrock (Llama 4 Maverick)
```

- **The backend is the only way to reach the model, and it only ever asks one thing:** "transcribe this image" with a fixed server-side prompt, using the model named in server config. Nothing a client sends becomes a prompt, a model name, or a model option. The worst a caller can do is submit images, and that is bounded by the 20 MB per-file limit, the concurrency limit on model calls (`BEDROCK_MAX_CONCURRENCY`), and whatever rate limit the reverse proxy applies. Text printed on an uploaded image can at most skew that image's own extracted fields, which are schema-validated and compared by deterministic code.
- **The Bedrock key lives only in the backend's environment.** The browser never sees it. Give it an expiry, and set an AWS budget alert.
- **Serve both from one origin** by routing `/api/*` to the backend with the prefix stripped, and build the frontend with `NEXT_PUBLIC_API_BASE_URL=https://<host>/api`. Set `CORS_ORIGINS` to the same origin.
- **Proxy timeouts:** `POST /reviews` can wait on a label that's still being read (up to the model timeout), and extraction status requests hold open for up to 25 s. The proxy's upstream read timeout needs to exceed both; 120 s is safe.
- **Run a single uvicorn worker.** Background extractions and batch runners live in the backend process.
- **Self-hosted instead:** set `INFERENCE_PROVIDER=ollama` and point `OLLAMA_BASE_URL` at a GPU machine. Ollama has no authentication, so bind it to a private address and firewall its port to the backend's IP only. Match `OLLAMA_NUM_PARALLEL` there to `OLLAMA_MAX_CONCURRENCY` here.

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
| `POST /batches` | Create a batch: a name plus one row per application (declared fields + image filenames). Rows start out waiting for their images. |
| `PUT /batches/{id}/items/{item_id}/images` | Attach a row's uploaded images (extraction ids from `POST /extractions?priority=batch`); the row is queued for review. |
| `GET /batches/{id}` | Progress: status, counts (clear / needs review / couldn't be read / decided), rough time left, and per-row outcomes. |
| `GET /batches` | Recent batches. |
| `POST /batches/{id}/cancel` · `POST /batches/{id}/retry-failed` | Stop a batch (rows already reviewed keep their results) · re-queue rows that couldn't be read. |
| `GET /batches/{id}/export.csv` | One row per application: per-field verdicts, what needs attention, and the agent's decision. |
| `POST /applications/extract-pdf` | Read a filled-in TTB F 5100.31 PDF's form fields to pre-fill the form. |

Interactive API docs are available at `/docs` while the backend is running.

## Project structure

```
backend/
  app/
    data/ttb_rules.py        Regulatory facts as plain data (warning text, ABV tolerance, standard fill sizes)
    inference/                The vision model: prompt.py (shared prompt + parsing), bedrock_client.py,
                              ollama_client.py; __init__.py picks one from INFERENCE_PROVIDER
    images.py                 Upload normalization: EXIF rotation, downscale, re-encode
    extraction_service.py     Background extraction started on upload; reuse by content hash
    matching/merge.py         Combines front + back readings, recording which side each came from
    matching/engine.py        Field-by-field comparison logic (exact/tolerance/enum/fuzzy/placement)
    routers/                  extractions.py, reviews.py, batches.py, applications.py — the API endpoints
    review_service.py         Orchestrates one end-to-end review; shared by reviews and batches
    batch_service.py          Batch rows, the background runner that reviews them, progress, CSV export
    priority_gate.py          Shares the model's capacity, single reviews ahead of batch work
    models.py, schemas.py     SQLAlchemy models / Pydantic request-response shapes
  tests/                       Unit tests (rules, parsing, merging, images) + API flow tests with a stubbed model
frontend/
  app/
    page.tsx                  Upload form
    useLabelUpload.ts         Starts extraction as soon as a photo is picked; tracks its progress
    ReviewResultView.tsx      Results beside the label images, plus the agent's decision
    batches/                  Batch pages: intake (validated in the browser), upload, progress + triage
      intake.ts               Spreadsheet parsing and validation — pure, unit-tested with `npm test`
    api.ts, types.ts          Backend client and shared types
```

## Known limitations and trade-offs

- **Batches are limited by the model's speed and quota.** On Bedrock, at ~1.5 s per image with 4 calls in flight, 300 applications with front and back labels take roughly 4 minutes of reading; raising `BEDROCK_MAX_CONCURRENCY` is bounded by the account's per-minute quota. Self-hosted on the dev machine (~7 s per image, one at a time) the same batch is over an hour. Batch intake takes a folder plus a CSV. ZIP files, one-PDF-per-application intake, and bulk "accept everything that passed" aren't built. Bulk accept in particular is a TTB policy question before it's an engineering one.
- **Background work runs inside the backend process.** Label extraction and batch runners are asyncio tasks, so run uvicorn with a single worker. Anything interrupted by a restart resumes automatically.
- **The field/rule set is a simplified model of 27 CFR Parts 4, 5, 7, and 16**, not full regulatory fidelity. Commodity-specific disclosures beyond the fields with dedicated rules (color additives, FD&C Yellow No. 5, aspartame, etc.) are surfaced as flagged items for human review rather than individually coded. Spirits' "same field of vision" rule (brand, class/type, ABV) can't be judged from separate photos and isn't checked.
- **Image handling is limited to rotation and size.** EXIF rotation is corrected and images are downscaled, but there's no deskewing, perspective correction, or glare removal; the pipeline relies on the vision model's robustness for photos taken at odd angles.
- **Type size, bold type, and contrast** (minimum lettering size, the bold "GOVERNMENT WARNING:", background contrast) can't be verified from a photograph and are treated as manual-review items.
- **The vision model can misread in plausible-looking ways.** During development it transcribed a title-case "Government Warning" as all caps, invented a warning for a front label that had none, and split a bottler statement in two. Each was fixed and is covered by the 43-case test gauntlet (see `testing/README.md`). Qwen2.5-VL passes 43/43. Llama 4 Maverick passes 42/43: on an imported wine it swapped the class/type ("Chianti Classico") with the appellation printed below it ("Chianti Classico DOCG"), so a compliant label was flagged for review, which is the safe direction to be wrong in. The prompt was tuned on these same 43 labels, so it was deliberately not re-tuned to chase that case. A transcription model can't guarantee character-exact fidelity. The exact-wording checks are only as good as the reading they're given, which is why the agent always sees the label image next to every verdict.
- **No integration with the actual COLA system.** This is a standalone prototype; a real deployment would need to fit into TTB's existing authorization and workflow systems.
- **SQLite, no authentication.** Appropriate for a prototype's scale and review process; a production deployment would need a concurrent-safe database and access control. Schema changes aren't migrated: delete `backend/ttb_review.db` after pulling a change to the models.
