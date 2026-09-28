# TTB Label Review

An AI-assisted pre-screener for alcohol beverage labels. An agent uploads a photo of the label and, optionally, the values declared on the TTB F 5100.31 application (COLA). The tool reads what is actually printed on the label and checks each field against the application where something was declared, and against the labeling requirements either way: brand name, class/type, alcohol content and proof, net contents, name and address, country of origin for imports, and the Government Warning statement.

It is a **pre-screen only**. The agent makes every decision, and only TTB can approve a label.

**Live demo:** https://cola-demo.wjford.dev. Any photo of a bottle label works; synthetic test labels can be generated with [`testing/generate_fixtures.py`](testing/README.md).

## Summary

- **Approach:** an open-weight vision-language model transcribes each label image into structured fields as soon as it is uploaded. Deterministic, unit-tested code then checks every field against the application and TTB's labeling rules, and flags anything that needs a human look; the agent makes the final call. Because reading starts at upload (about 1.5 s per image), the result is normally ready the moment the agent presses Review. Batches of hundreds of applications run in the background, behind single reviews. See [Approach](#approach).
- **Tools:** a Python/FastAPI backend and a Next.js frontend, with Llama 4 Maverick on Amazon Bedrock as the model (or Qwen2.5-VL on self-hosted Ollama), deployed with Docker Compose. See [Tools used](#tools-used).
- **Assumptions:** the tool pre-screens and the agent decides; only beverage class and import status are required inputs; the Government Warning must match word for word; the agency firewall rules out vendor-only models; a prototype needs no COLA integration or login. See [Assumptions](#assumptions).

## Why this exists

TTB's 47 agents review about 150,000 label applications a year, and much of that time goes to data-entry verification: confirming that the brand name, alcohol content and net contents on the label match the application. This tool automates the matching so agents can spend their attention on the judgment calls.

## Approach

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

**The label is read as soon as it is uploaded,** not when the agent presses Review. Reading takes about 1.5 s on Bedrock, less time than it takes to type in the application fields, so pressing Review normally only runs the matching step, which takes milliseconds. Each result shows both figures, for example "Ready 0.1s after you pressed Review · the label took 1.5s to read". Front and back images are read separately, which also records which side each field was printed on; wine's brand name and class/type must appear on the front label.

**The model reads; plain code decides.** The vision model only transcribes the label and never judges compliance. Every verdict comes from deterministic, unit-tested Python, so a legally exact requirement such as the Government Warning wording never rests on a model's judgment. Each field has one rule type:

- **Exact match:** the Government Warning, compared word for word and punctuation included against 27 CFR 16.21, with "GOVERNMENT WARNING" required in capital letters. Line breaks, spacing, and quote and dash styles are ignored.
- **Tolerance:** alcohol content within ±0.3 percentage points (27 CFR 5.65), and proof equal to twice the stated alcohol content.
- **Standard of fill:** net contents must be an authorized container size (27 CFR 5.203 for spirits; 27 CFR 4.72 for wine, including even liters from 4 L up; none for malt beverages). mL, cL, L, fl oz, pints, quarts and gallons are all understood, so a declared "12 FL OZ" matches a label's "355 mL".
- **Fuzzy match:** brand name, class/type, and name and address are compared ignoring case and punctuation, so "STONE'S THROW" matches "Stone's Throw". Close but not identical values are flagged for a look rather than failed.
- **Placement:** on wine, a brand name or class/type found only on the back label is flagged (27 CFR 4.32(a)).

Every declared field is optional; a blank field is checked on the label alone. Rules that apply only in some cases are applied per beverage class: country of origin for imports, appellation and sulfite declaration for wine, and alcohol content, which is optional on malt beverages depending on state law.

### Batch review

For peak season, when an importer submits 200–300 applications at once, **Review a batch** accepts a folder of label photos plus a spreadsheet with one row per application. A template is available on the batch page, and only `front_image` is required. A folder of photos alone also works: each label is checked on its own, and `NAME_front` / `NAME_back` photos are paired automatically.

- **Problems are caught before anything uploads:** missing or misspelled filenames (with a "did you mean" suggestion), unknown beverage classes, unreadable alcohol values and duplicate rows.
- **The batch runs on the server.** Photos are shrunk in the browser, uploaded, and read as they arrive; the agent can close the page once the upload finishes. A batch survives a server restart, and dropping the same folder again resumes an interrupted upload.
- **Single reviews always go first.** A priority gate on model calls means an agent reviewing one label waits only for the batch images already being read, not the whole queue.
- **Triage, not a spreadsheet.** Results are listed "Needs your review" first, then "Couldn't be read", then the rest. Each one opens in the same side-by-side view as a single review, with Previous and Next. The whole batch, decisions included, exports as CSV.

## Why an open-weight model on Bedrock

TTB's network blocks outbound traffic to many domains, and a previous vendor pilot failed partly because the firewall blocked its ML endpoints. The model is therefore **open-weight**: one the agency could run in its own cloud account, on its own hardware, or behind its firewall, rather than a vendor-only model such as GPT, Claude or Gemini.

The code supports two interchangeable providers, selected with `INFERENCE_PROVIDER`:

- **`bedrock`** (the live demo): Llama 4 Maverick on Amazon Bedrock. It is pay-per-call with no GPU to keep running. Bedrock is available in AWS GovCloud and over private endpoints, so this is also a realistic production arrangement, with traffic staying inside a FedRAMP-authorized account. Azure, where TTB already runs, serves the same open-weight models; supporting it would take one more small client module, not a redesign.
- **`ollama`**: the same pipeline against a self-hosted Qwen2.5-VL 7B, for fully offline or on-premises use. The project was first built and tuned on this.

Both providers use the identical prompt and response parsing. Nothing a client sends becomes part of a prompt, a model name or a model option.

Ollama can constrain a model's output to a JSON schema, which guarantees *valid* JSON. In testing, though, it caused the model to silently drop or misassign fields, so valid turned out not to mean complete. The prompt describes the schema in text instead, and the backend parses defensively, with one retry on a malformed response. Details are in `backend/app/inference/ollama_client.py`.

## Performance

**Llama 4 Maverick on Bedrock** (the live demo), with images capped at 1024 px:

- **About 1.5 s to read one label image** (1.0–4.7 s across the test gauntlet), starting at upload.
- **About $0.001 per image,** so a 300-application batch with front and back labels costs under $1.
- **A re-uploaded image** is recognized by its content hash and not read again.

**Qwen2.5-VL 7B via Ollama on an Apple M4 Pro** (the self-hosted option): 6–9 s per image, with a median of 12.1 s (range 4–16 s) when both images are submitted together with no head start. A dedicated GPU would be considerably faster.

## Tools used

| Area | Tools |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy, SQLite, httpx |
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS |
| Vision-language model | Llama 4 Maverick 17B on [Amazon Bedrock](https://aws.amazon.com/bedrock/) (Converse API); Qwen2.5-VL 7B on self-hosted [Ollama](https://ollama.com/). Both open-weight |
| Image and document handling | Pillow (photo normalization), pypdf (TTB F 5100.31 pre-fill) |
| Testing | pytest (backend), Node's built-in test runner (frontend), and a custom end-to-end gauntlet of 43 labels rendered with Pillow |
| Code quality | Ruff (Python lint and format), ESLint, TypeScript type checking |
| Packaging and deployment | [uv](https://docs.astral.sh/uv/) and npm; Docker Compose on a Linux VPS behind an HTTPS reverse proxy |

## Running locally

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 18+
- A model provider, one of:
  - **Amazon Bedrock:** a Bedrock API key, with `INFERENCE_PROVIDER=bedrock` and `BEDROCK_KEY` set in `backend/.env`.
  - **Ollama:** [installed](https://ollama.com/download), with the model pulled (`ollama pull qwen2.5vl`). This is the default.

### Backend (http://localhost:8000)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Settings are read from environment variables or `backend/.env`; `backend/.env.example` documents the main ones. The SQLite database and uploaded images are created inside `backend/` on first start.

### Frontend (http://localhost:3000)

```bash
cd frontend
npm install
npm run dev
```

`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) sets which backend the frontend calls.

### Tests

```bash
(cd backend && uv run pytest)
(cd frontend && npm test)
```

The backend tests stub out the model, so they need no provider. They cover:
- the matching rules, including the stakeholder examples: "STONE'S THROW" matches "Stone's Throw", and a title-case "Government Warning" fails;
- net-contents parsing, front/back merging, and image handling;
- the upload-to-review flow and the full batch lifecycle (create, review, retry, cancel, resume after restart, export);
- the Bedrock client against a fake server, and the priority gate.

The frontend tests cover batch intake: CSV parsing, filename matching with "did you mean" suggestions, and front/back pairing.

End-to-end accuracy against the real model is measured by the test gauntlet in [`testing/`](testing/README.md): 43 rendered labels with known correct verdicts, run as single reviews or as one batch.

## Deployment

```
Internet ──▶ reverse proxy (HTTPS)
               └─ frontend container (Next.js) ──▶ /api/* ──▶ backend container (FastAPI, one worker)
                                                                    │  HTTPS
                                                                    ▼
                                                              Amazon Bedrock
```

The live demo runs on a Linux VPS with Docker Compose, behind an HTTPS reverse proxy:

```bash
cp backend/.env.example backend/.env   # set INFERENCE_PROVIDER=bedrock and BEDROCK_KEY
docker compose up -d --build           # serves the app on 127.0.0.1:3000
```

- **One public entry point.** The frontend container forwards `/api/*` to the backend, which has no published port. The database and uploads live on Docker volumes.
- **The model is only reachable through the backend,** which only ever asks it to transcribe an image with a fixed server-side prompt. Uploads are capped at 20 MB and 60 megapixels, and concurrent model calls are limited.
- **The Bedrock key stays on the server;** the browser never sees it. Demo spending is capped by an AWS budget that disables the key automatically if it is exceeded.
- **Timeouts:** the frontend's `/api` forwarding allows 120 s per request and uploads up to 25 MB, since a review can wait on a label still being read.
- **Single worker:** background reads and batch runners live in the backend process.
- **Self-hosted alternative:** `INFERENCE_PROVIDER=ollama`, with Ollama on a private address that only the backend can reach, since Ollama has no authentication of its own.

## API

| Endpoint | Description |
|---|---|
| `POST /extractions` | Upload one label image. Returns an id immediately; the model reads it in the background. An identical image reuses the earlier reading. |
| `GET /extractions/{id}?wait=N` | Reading status; with `wait`, holds the request up to N seconds for it to finish. |
| `DELETE /extractions/{id}` | Cancel a reading in progress (the agent chose a different photo). |
| `GET /extractions/{id}/image` | The image as the model saw it (upright, resized). |
| `POST /reviews` | Review a label: extraction ids (or the image files) plus the declared application fields. Returns the full result. |
| `GET /reviews/{application_id}` | Fetch a stored review. |
| `PUT /reviews/{application_id}/decision` | Record the agent's decision: `accept`, `reject` or `follow_up`, with an optional note. |
| `POST /batches` | Create a batch: a name plus one row per application (declared fields and image filenames). |
| `PUT /batches/{id}/items/{item_id}/images` | Attach a row's uploaded images; the row is queued for review. |
| `GET /batches/{id}` | Progress, counts, estimated time left, and each row's outcome. |
| `GET /batches` | Recent batches. |
| `POST /batches/{id}/cancel` · `POST /batches/{id}/retry-failed` | Stop a batch (finished rows keep their results) · retry rows that couldn't be read. |
| `GET /batches/{id}/export.csv` | One row per application: per-field verdicts, what needs attention, and the decision. |
| `POST /applications/extract-pdf` | Read a filled-in TTB F 5100.31 PDF to pre-fill the form. |

Interactive API documentation is served at `/docs` on the backend.

## Project structure

```
backend/
  app/
    data/ttb_rules.py        Regulatory facts as plain data (warning text, tolerances, standard fill sizes)
    inference/                The vision model: shared prompt and parsing, Bedrock and Ollama clients
    images.py                 Upload normalization: rotation, size limits, downscaling
    extraction_service.py     Background reading started on upload; reuse by content hash
    matching/merge.py         Combines front and back readings, recording which side each field came from
    matching/engine.py        Field-by-field verdicts (exact, tolerance, standard of fill, fuzzy, placement)
    review_service.py         One end-to-end review; shared by single and batch reviews
    batch_service.py          Batch rows, the background runner, progress, CSV export
    priority_gate.py          Shares model capacity, single reviews ahead of batch work
    routers/                  The API endpoints
    models.py, schemas.py     Database models and request/response shapes
  tests/                      Unit and API tests, with the model stubbed out
frontend/
  app/
    page.tsx                  Single review form
    useLabelUpload.ts         Uploads a photo the moment it's chosen and tracks its reading
    ReviewResultView.tsx      Verdicts beside the label images, plus the agent's decision
    batches/                  Batch intake (validated in the browser), upload, progress and triage
    api.ts, types.ts          Backend client and shared types
testing/                      The end-to-end gauntlet: label renderer, 43 cases, runner
```

## Assumptions

Where the brief left a gap, these assumptions filled it. Each is easy to revisit.

**The job**
- **The tool pre-screens; the agent decides.** Every result ends with the agent choosing Accept, Reject or Needs follow-up, with the label image beside every verdict. That keeps human judgment where the stakeholders said it belongs, and it is the only safe place for a model's reading to land.
- **Checking means label against application *and* label against the rules.** A blank application field is still checked on the label alone: is a required element printed, is the container a standard size, is the warning exact.
- **Only beverage class and import status are required inputs,** because they decide which rules apply. Class/type, alcohol content and net contents are not fields on TTB F 5100.31; requiring an agent to copy them from the label and then comparing the label with the copy would be circular.
- **An application is a front label plus an optional back label,** as photos or image files. A fillable TTB F 5100.31 PDF, when available, pre-fills the form but is not required.

**The rules**
- **The Government Warning must match word for word,** punctuation included, with "GOVERNMENT WARNING" in capitals (27 CFR 16.21). Bold type and minimum type size cannot be judged reliably from a photo, so they are left to the agent.
- **Names are compared ignoring case and punctuation,** and near misses are flagged rather than failed, because a near miss is exactly where an agent's judgment is needed.
- **Alcohol content allows ±0.3 percentage points between label and application** for every class, the spirits and malt beverage figure (27 CFR 5.65, 7.65). Wine's regulatory tolerance is wider, but it concerns the label against the bottle's actual contents, which a label review cannot measure. Between two documents that should agree, the stricter figure is the safer default.
- **Mandatory information is printed in English,** as TTB requires, so the model transcribes and never translates.

**The users and the environment**
- **The 5-second target is measured from when the agent presses Review.** Reading starts when a photo is chosen, so the model's time overlaps with filling in the form.
- **A batch arrives as a folder of photos plus a spreadsheet,** one row per application. The agent still reviews every flagged result; bulk-accepting everything that passed is a policy decision for TTB, not a default for the tool.
- **Agents work in a desktop browser,** one person per review. There is no login, because the brief stated that nothing sensitive is stored in this exercise. For the same reason, uploaded images are kept indefinitely; a production system would follow TTB's retention policy.
- **The firewall constraint is a real design requirement,** which is why the model is open-weight.
- **No COLA integration:** the brief describes a standalone proof of concept.
- **Synthetic labels are a fair first test.** The 43 gauntlet labels are rendered in code, with known correct answers. Real bottle photos are the next test, and they would have to be kept separate from any prompt tuning.

## Known limitations and trade-offs

- **The vision model can misread in plausible ways.** During development it capitalized a title-case "Government Warning", invented a warning on a front label that had none, and split a bottler statement in two. Each was fixed, and each is covered by the gauntlet. Qwen2.5-VL passes 43 of 43. Llama 4 Maverick passes 42 of 43: on one imported wine it swapped the class/type ("Chianti Classico") with the appellation below it ("Chianti Classico DOCG"), so a compliant label was flagged for review, which is the safe direction to be wrong in. Because the prompt was tuned on these same labels, it was not re-tuned to chase that case. Exact-wording checks are only as good as the transcription, which is why the label image is always shown beside the verdicts.
- **The rules are a simplified model of 27 CFR Parts 4, 5, 7 and 16.** Commodity-specific disclosures without a dedicated rule (color additives, FD&C Yellow No. 5, aspartame and so on) are flagged for human review. The spirits "same field of vision" rule cannot be judged from separate photos and is not checked.
- **Image handling covers rotation and size only.** There is no deskewing, perspective correction or glare removal; photos at odd angles rely on the vision model's robustness.
- **Type size, bold type and contrast** cannot be verified from a photograph and are left to the agent.
- **Batch speed is bounded by the model.** On Bedrock, 300 applications with front and back labels take roughly 4 minutes of reading, limited by the account's request quota. Intake accepts a folder plus a CSV; ZIP files, one PDF per application, and bulk accept are not built.
- **Prototype infrastructure.** SQLite with no schema migrations, no authentication, and background work inside a single backend process. A production deployment would need a concurrent-safe database, access control, and integration with TTB's existing systems.
