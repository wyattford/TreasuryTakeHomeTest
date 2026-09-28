# Batch review: design

This document records the design of batch review and how the built version differs from it. Phases 1 and 2 below are built; [What was built](#what-was-built) lists the differences and what remains.

## The problem

> "During peak season, we get these big importers who dump 200, 300 label applications on us at once. Right now we literally have to process them one at a time." — Sarah Chen

A 300-application batch with front and back labels is 600 images. With the self-hosted model on development hardware (Qwen2.5-VL 7B on an Apple M4 Pro), one image took about 9 s, or roughly 90 minutes for the batch. On Amazon Bedrock (Llama 4 Maverick, four calls in parallel) the same batch takes about 4 minutes. Either way, four requirements follow:

- **Batches run on the server without anyone watching.** An agent submits, returns to other work, and comes back; the browser tab does not need to stay open.
- **Batches must not block interactive reviews.** An agent reviewing a single label must not wait behind 600 queued batch images.
- **Uploads are incremental.** 600 full-size phone photos can exceed 3 GB. A single request that large would exceed proxy and per-file limits, and one network interruption would lose the whole upload.
- **Bad input is caught before the model runs.** Discovering at item 173 that a spreadsheet filename is misspelled is the failure the design exists to prevent.

## Design overview

The single-label flow already provides the building blocks: reading starts at upload (`POST /extractions`), readings are reused by content hash, and readings survive restarts. Batch review is that flow at scale, plus a server-side runner.

```
Browser                                   Backend                               Model
───────                                   ───────                               ─────
1. Agent drops a folder of
   images + a CSV manifest
2. Parse CSV, match filenames,
   validate every row (locally,
   before uploading anything)
3. POST /batches  {rows: [...]}   ──────▶ create batch + items (status: awaiting_images)
4. For each image (4 at a time):
   downscale to 1024px in-browser,
   POST /extractions?priority=batch ────▶ store image, queue reading ────────▶ (low priority)
   PUT /batches/{id}/items/{n}/images ──▶ attach reading ids; item → queued
5. Poll GET /batches/{id}          ◀────── batch runner: as each item's readings
   (progress, counts, ETA)                 finish, run matching → item reviewed
6. Triage view: flagged first, same
   result view + decisions as single
   review; export CSV
```

### Intake format

**A folder of images plus a CSV manifest,** one row per application:

| column | required | notes |
|---|---|---|
| `front_image` | yes | filename inside the folder |
| `back_image` | no | |
| `beverage_class` | no | `distilled_spirits` / `wine` / `malt_beverage`; defaults to the class chosen on the page |
| `imported` | no | `yes` / `no`; defaults to the page setting |
| `brand_name`, `fanciful_name`, `class_type`, `abv`, `net_contents`, `name_address`, `country_of_origin`, `appellation`, `sulfite_declaration` | no | the declared TTB F 5100.31 values; blank means label-only checks |
| `reference` | no | free text, such as the importer's own ID, carried through to the export |

The batch page offers a template CSV with the header row.

Because every declared field is optional, a batch can also be **images only**, with no CSV. That runs the label-only checks (required fields present, exact warning, standard container size), which are still the bulk of the routine work. Files named `<ref>_front.jpg` and `<ref>_back.jpg` are paired automatically.

A possible later format is one filled-in TTB F 5100.31 PDF per application, matched by filename and read with the existing `application_pdf.py`. It matches how applications actually arrive, but the form does not carry class/type, alcohol content or net contents, so it could only partly replace the CSV.

### Validation (step 2): complete before anything uploads

Validation runs in the browser, so it is instant, and nothing is sent until the batch is known to be good:

- The CSV parses, the required column is present, `beverage_class` values are valid, and `abv` is numeric.
- Every referenced filename exists in the dropped folder, with a "did you mean" suggestion for near misses. Images no row uses are reported, since they usually indicate a typo.
- No front image is referenced twice.
- Files are images, and none exceeds the size limit.

The agent sees one summary, for example "298 applications ready · 2 problems: line 14, back_image 'NW-114_bak.jpg' isn't in the folder — did you mean 'NW-114_back.jpg'?", and can fix and re-drop, or start the rows that are ready.

### Upload (steps 3–4)

- **The batch is created first, with all its rows,** before any image is sent. If the tab closes partway through, the batch page shows which rows still need images, and dropping the same folder again uploads only those. Content-hash reuse makes any re-sent image harmless.
- **Images are downscaled in the browser** to the same 1024 px long edge the server uses. This cuts upload volume 20–50× for phone photos and keeps every request small; the server normalizes again regardless.
- **Uploads run four at a time.** Each image goes through the ordinary `POST /extractions`, so reading starts while the rest are still uploading.

### Server side

**Data model:**

- `ReviewBatch`: name, creation, start and cancellation times. Status and counts are derived from the items.
- `BatchItem`: `row_number`, `reference`, `declared` (the CSV row as JSON), `front_extraction_id`, `back_extraction_id`, `application_id` (set once reviewed), `status` (`awaiting_images` / `queued` / `reviewed` / `error` / `skipped`), and `error_message`.

**Priority scheduling.** Model calls pass through a two-level priority gate: interactive readings always take the next free slot ahead of batch readings (`POST /extractions?priority=batch`). A single review therefore waits for at most the batch images already being read, not the whole queue.

**Batch runner.** One background task per running batch picks up items as their images are attached, waits for their readings, and calls the same `run_review` used by single reviews, so there is no second copy of the review logic. The runner never starts readings itself; uploading does. That keeps the reading queue and the review bookkeeping separate.

**Surviving restarts.** On startup, the backend restarts runners for batches with queued items. Readings that were interrupted are re-run automatically when awaited. Everything a batch needs is in the database and the upload store, so a restart costs only time.

**Failures.** An item whose reading fails, after one automatic retry, is marked `error` with the reason, and the batch continues. Failed items can be retried from the batch page.

This design is single-process, matching the in-process task registry the rest of the application uses (one uvicorn worker). Several backend processes would need a shared queue instead: a database-backed job table polled by workers, or a message broker such as Azure Service Bus.

### API

| Endpoint | Purpose |
|---|---|
| `POST /batches` | Body `{name, rows: [...]}`. Creates the batch and its items (`awaiting_images`) and returns their ids. Rows are validated again on the server. |
| `PUT /batches/{id}/items/{item_id}/images` | Body `{front_extraction_id, back_extraction_id}`. Attaches the uploaded images; the item becomes `queued`. |
| `GET /batches/{id}` | Status, counts by outcome, an estimated time remaining, and every item's outcome. |
| `POST /batches/{id}/cancel`, `POST /batches/{id}/retry-failed` | Control. |
| `GET /batches/{id}/export.csv` | One row per application: reference, each field's verdict, overall result, and the agent's decision and note. |
| `GET /batches` | Recent batches, so an agent can find theirs again. |

Opening an item and recording a decision reuse the single-review endpoints: `GET /reviews/{application_id}` and `PUT /reviews/{application_id}/decision`.

### UI

A second page, reached from a **Review one label | Review a batch** switch at the top of every page.

1. **Start a batch:** a large drop zone, a link to the CSV template, and a short explanation; then the validation summary and a single start button.
2. **Progress:** a large progress bar with a plain sentence beneath it ("112 of 300 done · about 5 minutes left · this page can be closed"), and three live counts: **Everything checks out**, **Needs your review**, **Couldn't be read**. The page URL can be bookmarked, and "Recent batches" on the start page links back to it.
3. **Triage:** items listed **Needs your review** first, each showing its reference, brand name, how many fields need attention, and the decision so far. Opening an item shows the same result view as a single review, with Previous and Next buttons.
4. **Bulk accept** of everything that passed would save the most time in a 300-label batch, and it is also the riskiest action the tool could offer. It would need an explicit confirmation stating the count, and a per-item record like any other decision. Whether TTB policy allows bulk acceptance of a pre-screen at all is a policy question for TTB, so it is not built.
5. **Export CSV** from the batch page.

### Measuring throughput

- `testing/run_gauntlet.py --batch` submits all 43 gauntlet cases as one batch through the batch API and checks every result against the expected verdicts, so batch mode gets the same correctness check as single reviews.
- Concurrency (`BEDROCK_MAX_CONCURRENCY`, or `OLLAMA_NUM_PARALLEL` and `OLLAMA_MAX_CONCURRENCY` for a self-hosted model) is the main throughput setting; on a discrete GPU, parallel requests usually raise total throughput.
- With a batch running, single reviews should stay close to one image's reading time, which is the purpose of the priority gate. Measured on the self-hosted setup: 11.5 s for a single label with about 80 s of batch work queued ahead of it.

### Testing

- **Unit:** CSV parsing and validation (missing columns, bad class values, unknown filenames, duplicates); the priority gate (interactive work ahead of batch work queued earlier).
- **API,** with the model stubbed out: the full lifecycle (create, attach images, background review, export), a failed item that does not stop the batch, retry, cancel, and resume after a simulated restart.
- **End to end:** the gauntlet's `--batch` mode.

## Phasing

1. **Core:** CSV and folder intake with browser-side validation, the create-then-attach upload flow, the server-side runner, the progress page, the triage list reusing the single-review result view, and CSV export.
2. **Robustness:** priority scheduling, resume after restart, retry and cancel, resumable uploads.
3. **Extensions:** ZIP intake, one-PDF-per-application intake, bulk accept (pending the policy question), keyboard shortcuts.

## Open questions

- What format do importers' submissions actually arrive in? If COLAs Online has a common export, intake should read it directly rather than asking agents to build a CSV.
- Is bulk acceptance of pre-screened "clear" labels acceptable to TTB, or must every label receive an individual decision?
- Should batches be private to the agent who submitted them, or visible to the whole team (for example, the Seattle office picking up an overflow batch)? The answer decides whether the prototype needs user identity at all.

## What was built

Phases 1 and 2: CSV and folder intake validated in the browser (`frontend/app/batches/intake.ts`, unit-tested), create-then-attach uploads with in-browser downscaling, the server-side runner (`backend/app/batch_service.py`), priority scheduling (`backend/app/priority_gate.py`), resume after restart, retry and cancel, the progress and triage pages, CSV export, and the gauntlet's `--batch` mode.

Differences from the design:

- **One way to add items.** An earlier multipart endpoint for adding batch items one at a time was removed rather than kept: it would have been a second path with its own review semantics. Scripts use the same create, upload and attach flow as the UI (`run_as_batch` in `testing/run_gauntlet.py`).
- **No pagination on `GET /batches/{id}`.** 300 compact rows are about 100 KB, and one response keeps the triage view simple. Pagination would matter near the 1,000-row limit.
- **Priority is fixed when an image is uploaded.** If an agent uploads an image already queued as part of a batch, the reading is shared but keeps its batch priority.

One defect was found and fixed during the build. Every review waiting on a reading held a pooled database connection for the whole wait, so a batch with more waiting rows than the pool had connections (15) deadlocked the backend: the next connection checkout blocked the event loop that the waiting reviews needed. `wait_for_extraction` now releases its connection before waiting, and a regression test covers it.

Not built (phase 3): ZIP intake, one-PDF-per-application intake, bulk accept, and keyboard shortcuts.
