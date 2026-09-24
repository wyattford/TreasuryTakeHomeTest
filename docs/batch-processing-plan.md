# Batch processing plan

Status: **phases 1 and 2 are built** — see [What was built](#what-was-built) at the end for where the implementation differs from this plan and what's left.

## The problem

> "During peak season, we get these big importers who dump 200, 300 label applications on us at once. Right now we literally have to process them one at a time." — Sarah Chen

Some numbers set the shape of the solution. On the dev machine (M4 Pro, qwen2.5vl 7B, 1024 px images), one label image takes about 9 s of model time. A 300-application batch with front and back labels is 600 images, or about 90 minutes of GPU time. A dedicated GPU should be several times faster, but that needs measuring (see [Measuring throughput](#measuring-throughput)). Either way:

- **Batches have to run on the server without anyone watching.** An agent submits, goes back to other work, and comes back. The browser tab must not need to stay open.
- **Batches must not block interactive reviews.** An agent reviewing a single label at the desk must not wait behind 600 queued batch images.
- **Uploads have to be incremental.** 600 full-size phone photos can be 3+ GB. A single request that large would hit the reverse proxy's body-size limit and the backend's per-file limit, and one network hiccup would lose the whole upload.
- **Bad input has to be caught before the model runs.** Finding out at item 173 that a filename in the spreadsheet was misspelled is the failure mode to design out.

## Design overview

The single-label flow already has the building blocks: upload-time extraction (`POST /extractions`), result reuse by content hash, and extractions that survive restarts. Batch processing is mostly that flow at scale, plus a server-side runner.

```
Browser                                   Backend                               Ollama
───────                                   ───────                               ──────
1. Agent drops a folder / ZIP of
   images + manifest.csv
2. Parse CSV, match filenames,
   validate every row (locally,
   before uploading anything)
3. POST /batches  {rows: [...]}   ──────▶ create batch + items (status: awaiting_images)
4. For each image (4 at a time):
   downscale to 1024px in-browser,
   POST /extractions?priority=batch ────▶ store image, queue extraction ─────▶ (low priority)
   PUT /batches/{id}/items/{n}/images ──▶ attach extraction ids; item → queued
5. Poll GET /batches/{id}          ◀────── batch runner: as each item's extractions
   (progress, counts, ETA)                 finish, run matching → item reviewed
6. Triage view: flagged first, same
   result view + decisions as single
   review; export CSV
```

### Intake format

**Recommended: a folder or ZIP of images plus a CSV manifest.** Each CSV row is one application:

| column | required | notes |
|---|---|---|
| `front_image` | yes | filename inside the folder/ZIP |
| `back_image` | no | |
| `beverage_class` | yes | `distilled_spirits` / `wine` / `malt_beverage` |
| `imported` | no | `yes`/`no`, default no |
| `brand_name`, `fanciful_name`, `class_type`, `abv`, `net_contents`, `name_address`, `country_of_origin`, `appellation`, `sulfite_declaration` | no | the declared TTB F 5100.31 values; blank means label-only checks |
| `reference` | no | free text (e.g. the importer's own ID) carried through to the export |

The UI offers a downloadable template CSV that already has the header row.

Because every declared field is optional, a batch can be **images only**: no CSV, one image per application. That runs the label-only checks (required fields present, exact warning, standard container size), which is still the bulk of the routine work. A filename convention (`<ref>_front.jpg` / `<ref>_back.jpg`) pairs front and back images when there's no CSV.

A later option: one filled-in TTB F 5100.31 PDF per application (matched by filename), reusing the existing `application_pdf.py` extraction. That fits how applications actually arrive, but PDFs don't carry class/type, ABV or net contents, so they only partly replace the CSV.

### Validation (step 2): all of it before anything is uploaded

This runs in the browser, so it's instant and nothing is sent until the batch is known to be good:

- CSV parses; required columns present; `beverage_class` values valid; `abv` numeric.
- Every referenced filename exists in the dropped folder/ZIP; flag images no row uses (usually a typo).
- Duplicate rows (same front image referenced twice).
- File types are images; nothing over the size limit even before downscaling.

The agent sees one summary: "298 applications ready · 2 problems: row 14, `back_image` 'NW-114_bak.jpg' not found (did you mean 'NW-114_back.jpg'?) …". They choose **Fix and re-drop**, or **Start anyway (skip 2 rows)**.

### Upload (steps 3–4)

- **Create the batch first, with all rows**, before any images are sent. If the tab closes halfway through, the batch page shows which rows still need images, and re-dropping the same folder resumes the upload. Images already uploaded are skipped: the browser asks the server which rows are still waiting and uploads only those. Content-hash reuse also makes re-sending harmless.
- **Downscale in the browser** to the same 1024 px long edge the server uses. This cuts upload volume about 20–50× for phone photos, keeps each request small enough for any proxy, and the server re-normalizes anyway.
- **Upload with bounded parallelism** (4 at a time). Each image goes through the existing `POST /extractions`, so model work starts while the rest are still uploading.

### Server side

**Data model** (extends the existing `review_batches` / `batch_items` tables):

- `ReviewBatch`: `name`, `status` (`awaiting_images` / `running` / `done` / `cancelled`), `created_at`, `total`, plus counts computed from the items.
- `BatchItem`: `row_number`, `reference`, `declared` (JSON of the CSV row), `front_extraction_id`, `back_extraction_id`, `application_id` (set once reviewed), `status` (`awaiting_images` / `queued` / `reviewed` / `error` / `skipped`), `error_message`.

**Priority scheduling.** `extraction_service` currently gates Ollama calls with an `asyncio.Semaphore`. Replace it with a small two-level priority gate: interactive extractions (the default) always take the next free slot before batch ones (`POST /extractions?priority=batch`). An agent's single review then waits for at most the one batch image already in progress (about 9 s worst case on the M4), not the whole queue.

**Batch runner.** One background coroutine per running batch. It picks up items whose images are attached, waits for their extractions (`wait_for_extraction`, already written), and calls the same `run_review` the single-review endpoint uses. No second copy of the review logic. The runner doesn't start extractions itself; uploading does that. That keeps "extraction queue" and "review bookkeeping" as separate concerns.

**Surviving restarts.** On startup, the backend finds `running` batches and restarts their runners. Their `pending` extractions are already re-run automatically when awaited. Everything a batch needs is in the database and in `uploads/`, so a restart costs nothing but time.

**Failures.** An item whose extraction fails (after the one automatic retry) is marked `error` with the reason, and the batch carries on. **Retry failed items** re-queues them.

This stays single-process, which matches the in-process task registry the rest of the app already assumes: run uvicorn with one worker. If this ever needed several backend processes, the queue would move to something shared: a database-backed job table polled by workers, or Redis/Azure Service Bus.

### API

| Endpoint | Purpose |
|---|---|
| `POST /batches` | Body: `{name, rows: [...]}`. Creates the batch and items (`awaiting_images`) and returns their ids. Validates the rows again on the server; never trusts the browser alone. |
| `PUT /batches/{id}/items/{item_id}/images` | `{front_extraction_id, back_extraction_id}`. Attaches uploaded images; the item becomes `queued`. |
| `GET /batches/{id}` | Summary: status, counts by outcome (clear / needs review / error / waiting), throughput-based ETA. |
| `GET /batches/{id}/items?status=flagged&offset=&limit=` | Paged item list for the triage view: thumbnail id, reference, brand, overall status, decision. |
| `POST /batches/{id}/cancel`, `POST /batches/{id}/retry-failed` | Control. |
| `GET /batches/{id}/export.csv` | One row per application: reference, declared values, verdict per field, overall status, the agent's decision and note. |
| `GET /batches` | Recent batches, so an agent can find theirs again. |

Per-item detail and decisions reuse the existing endpoints: `GET /reviews/{application_id}` and `PUT /reviews/{application_id}/decision`.

The current `POST /batches/{id}/items` (one multipart item per request) stays as-is for scripts and the test runner.

### UI

A second page, reachable from a plain **Review one label | Review a batch** switch at the top of the page.

1. **Start a batch.** A large drop zone ("Drop a folder or ZIP of label photos"), a link to the CSV template, and a one-paragraph explanation. After the drop comes the validation summary described above, then a single **Start review** button.
2. **Progress.** A large progress bar with a plain sentence under it: "112 of 300 done · about 25 minutes left · you can close this page and come back." Three counts that update live: **Everything checks out**, **Needs your review**, **Couldn't be read**. The page URL is bookmarkable, and "Recent batches" on the start page links back to it.
3. **Triage.** A list sorted **Needs your review** first. Each row shows a thumbnail, reference, brand name, how many fields need attention, and the decision so far. Opening a row shows the same `ReviewResultView` as a single review (images beside verdicts, Accept / Reject / Needs follow-up), with **Previous / Next** buttons. Keyboard shortcuts are a later addition for fast users like Jenny; big buttons stay the default for everyone else.
4. **Accept all "Everything checks out"** is the biggest time-saver in a 300-label batch, and the riskiest action in the tool. It needs an explicit confirmation that states the count ("Accept 241 applications that passed every check?"), and it is recorded per item like any other decision. Whether TTB policy even allows bulk acceptance of a pre-screen is a question for Sarah, not an engineering call. **Ship behind that question.**
5. **Export CSV** on both the progress and triage views.

### Measuring throughput

Before promising 200–300-application turnaround, measure it on the target GPU box:

- Add a `--batch` mode to `testing/run_gauntlet.py` that submits all 43 cases as one batch through the new API. It reports wall-clock time, images per minute, and accuracy against the expected verdicts, so batch mode gets the same correctness check as single reviews.
- Try `OLLAMA_NUM_PARALLEL` / `OLLAMA_MAX_CONCURRENCY` of 1, 2 and 4. On a discrete GPU, parallel requests usually raise total throughput. On the Mac they mostly just split the same compute.
- While a batch runs, submit single reviews and confirm their latency stays close to one image's worth (the point of priority scheduling).

### Testing

- **Unit:** CSV parsing and validation (missing columns, bad class values, unknown filenames, duplicates); the priority gate (interactive before batch even when batch was queued first); runner resume after a simulated restart.
- **API**, with the extractor stubbed as in `tests/test_review_flow.py`: full lifecycle (create → attach images → runner reviews → export), a failed item that doesn't stop the batch, retry-failed, cancel.
- **End-to-end:** the gauntlet `--batch` mode above.

## Phasing

1. **MVP:** CSV + folder intake with browser-side validation, the create-then-attach upload flow, server-side runner, progress page, triage list reusing `ReviewResultView`, CSV export. This covers Sarah's scenario end to end.
2. **Robustness:** priority scheduling, resume on restart, retry and cancel, resumable uploads.
3. **Extras:** ZIP intake, PDF-per-application intake, bulk accept (pending the policy question), keyboard shortcuts.

## Open questions

- What format do importers' submissions actually arrive in? If there's a common export from COLAs Online, intake should read that directly rather than asking agents to build a CSV.
- Is bulk-accepting pre-screened "clear" labels acceptable to TTB, or must every label get an individual human decision?
- Should batches be private to the agent who submitted them, or visible to the whole team (e.g. Janet's Seattle office picking up an overflow batch)? This decides whether the prototype needs user identity at all.

## What was built

Phases 1 and 2, as described above: CSV + folder intake, validated in the browser (`frontend/app/batches/intake.ts`, unit-tested); create-then-attach uploads with in-browser downscaling; the server-side runner (`backend/app/batch_service.py`); priority scheduling (`backend/app/priority_gate.py`); resume on restart; retry and cancel; the progress + triage pages; CSV export; and the gauntlet's `--batch` mode.

Differences from the plan:

- **The old `POST /batches/{id}/items` endpoint was removed**, not kept. It would have been a second path for creating batch items, with its own review semantics, and nothing used it. Scripts use the same create → upload → attach flow as the UI (see `run_as_batch` in `testing/run_gauntlet.py`).
- **No pagination on `GET /batches/{id}`.** 300 compact rows is ~100 KB, and one response keeps the triage view simple. It becomes necessary around the 1,000-row cap.
- **Priority is set when an image is uploaded.** If an agent uploads an image that's already queued as part of a batch, the reading is reused but keeps its batch priority.

Found and fixed while building it: every review waiting on its extraction held a pooled database connection for the whole wait. A batch with more rows waiting than the pool has connections (15) deadlocked the backend, because the next connection checkout blocked the event loop the waiting reviews needed. `wait_for_extraction` now releases its connection before waiting, and `test_more_waiting_reviews_than_database_connections_does_not_deadlock` covers it.

Not built (phase 3): ZIP intake, PDF-per-application intake, bulk accept (pending the policy question), keyboard shortcuts.
