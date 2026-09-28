# Test gauntlet

An end-to-end test suite for the TTB label review pipeline: synthetic label
images with **known ground-truth content**, paired with declared application
data that either matches that content exactly or deliberately diverges from
it in a specific, targeted way. Because we control both sides, we know the
correct verdict for every field ahead of time — any difference between that
and what the real pipeline (the vision model + the matching engine)
actually returns is a genuine finding, not a guess.

This is different from `backend/tests/test_matching_engine.py`, which unit
tests the matching *rules* in isolation (given an already-extracted value, is
the verdict logic correct). This gauntlet exercises the whole pipeline,
including the part the unit tests can't reach: can the vision model actually
read a label correctly, especially a degraded one.

## How it works

```
label_content.py    Ground-truth "what's printed on this label" templates (6 of them,
                     spanning all 3 beverage classes, domestic + imported)
cases.py             ~40 cases: each clones a template, optionally changes what's
                      printed (label_overrides) and/or what's declared
                      (declared_overrides), and picks an image distortion
render.py             Renders a label's content into front/back images (Pillow)
distortions.py        blur, rotate, low_contrast, noise, jpeg, glare, blur_rotate
generate_fixtures.py  Renders every case's images + computes its expected verdicts
                       by running the REAL matching engine (app.matching.engine.compare)
                       against the label content, treated as a perfect extraction
run_gauntlet.py        Submits every case to a live backend, compares actual vs.
                        expected, prints a report
```

Expected verdicts are never hand-typed — `generate_fixtures.py` imports
`app.matching.engine.compare` directly from the backend and runs it against
each case's ground-truth label content. If the matching rules change, expected
results update automatically instead of drifting out of sync.

## Running it

The backend needs to be running, with its model reachable: Ollama with `qwen2.5vl` pulled, or `INFERENCE_PROVIDER=bedrock` and a `BEDROCK_KEY` in `backend/.env` (see the main README):

```bash
cd backend && uv run uvicorn app.main:app --reload   # separate terminal
ollama serve                                          # if not already running
```

Then, from `backend/`'s virtualenv (fixture generation imports the backend's
own `app` package, and Pillow is a backend dev dependency):

```bash
cd backend && uv sync   # picks up Pillow

# Generate all fixture images + the expected-results manifest
uv run python ../testing/generate_fixtures.py

# Run the gauntlet against the live backend
uv run python ../testing/run_gauntlet.py
```

Useful flags:

```bash
# Regenerate/run just one or a few cases
python generate_fixtures.py --only warning_title_case
python run_gauntlet.py --only warning_title_case

# Run only cases with a given tag (see cases.py for the tag vocabulary:
# fuzzy, tolerance, enum, exact, presence, distortion, combo, known_limitation, ...)
python run_gauntlet.py --tag distortion

# Submit every case as ONE batch through the batch API (create, upload +
# attach each row's images, wait for the background runner) and check the
# same expected verdicts — batch mode gets the same correctness check as
# single reviews. Also prints throughput.
python run_gauntlet.py --batch

# Point at a non-default backend, adjust per-request timeout (cold model
# load can take 20+ seconds; the runner retries up to twice on a transient 502)
python run_gauntlet.py --base-url http://localhost:8000 --timeout 90
```

Each run writes a full JSON report to `results/report_<timestamp>.json` (and
`results/latest.json`), and prints a pass/fail summary with the specific
field(s) and expected-vs-actual statuses for every failing case.

`fixtures/` and `results/` are gitignored — both are fully reproducible from
the scripts, so there's nothing to keep in version control.

## Matching-engine bugs found and fixed

The first full run surfaced two bugs in `app/matching/engine.py` itself —
found because expected verdicts come from that same `compare()` function run
against *known-correct* ground truth, so a wrong verdict there can't be
blamed on the vision model:

- **ABV was always "missing" when neither side declared it**, even for malt
  beverages, where ABV is federally optional and a label that omits it isn't
  a compliance problem. `_abv_verdict` checked `declared is None` first and
  returned `MISSING` unconditionally, without checking whether `extracted`
  was *also* `None` (a consistent absence) or whether ABV was even required
  for this beverage class. Fixed: `_abv_verdict` now takes a `required` flag
  (computed from `required_fields_for()`, same as the existing
  country-of-origin/sulfite checks) and only reports `MISSING` for a
  both-absent ABV when it's actually required; otherwise it's a `MATCH`.
- **An unparseable declared net-contents unit silently passed as a match.**
  `parse_net_contents_ml` only recognizes mL/L; a value like `"12 FL OZ"`
  parsed to `None`, which short-circuited the mismatch check entirely and
  fell through to `MATCH` — even against a label showing a completely
  different size. Fixed: `_net_contents_verdict` now returns `FLAGGED` (not
  found comparable, needs a human look) instead of silently passing when the
  declared value can't be parsed.

Both fixes are covered by new regression tests in
`backend/tests/test_matching_engine.py` (`test_abv_not_declared_and_not_on_label_matches_when_not_required`,
`test_abv_not_declared_and_not_on_label_is_missing_when_required`,
`test_net_contents_declared_in_unparseable_unit_is_flagged_not_matched`), and
`backend/tests/` passes in full (11/11) after the change.

## Findings

### First full run (36/43 passed)

With the matching-engine bugs fixed, the first full run against `qwen2.5vl` (one extraction call over both images, JSON Schema in the prompt) surfaced five reproducible model/prompt gaps. They happened on **clean, undistorted** images, so they weren't image-quality noise:

1. **The model "corrected" the Government Warning's capitalization.** `warning_title_case` renders "Government Warning" in title case, a real 27 CFR 16.21 violation, but the model transcribed it as "GOVERNMENT WARNING".
2. **Country of origin was taken from a US address on imports.** With the "Product of Sweden" line removed, the model returned the importer's "New York, NY".
3. **`class_type` absorbed adjacent appellation text** ("Chianti Classico DOCG" instead of "Chianti Classico").
4. **Correctly read fields were also marked illegible**, flagging a fully compliant label.
5. **An absent field was marked illegible** instead of just null (ABV on a malt beverage that legitimately omits it).

### After switching to upload-time, per-image extraction (29/43, then 43/43)

Extraction now runs once per image, starting when the image is uploaded (see the main README). The first run in that mode regressed to **29/43**. A label image read on its own lacks the context of the other side:

- **Name and address split in two (6 cases).** The back label's bottler statement wraps across lines; read alone, its first line ("Northwind Distillers") was taken as a brand name and dropped from the address.
- **An invented Government Warning (2 cases).** A front label with no warning came back with a made-up statement ("CONSUMPTION OF THIS PRODUCT IS DANGEROUSLY ABUSIVE…"). With no real warning on the back to override it, a missing warning looked like a wording mismatch.
- **Brand repeated as name and address.** The bourbon front label's reading put "OLD TOM DISTILLERY" in `name_address`, which beat the back label's real statement.

Fixes, all measured on this gauntlet:

- **Prompt field descriptions.** `name_address` asks for the complete statement including the company name it starts with. `brand_name` must not come from that statement. `government_warning_text` should be null unless a warning paragraph is actually printed ("most front labels have none"). The old description said the warning "starts with 'GOVERNMENT WARNING:'". Removing that also fixed finding 1: the model had been matching the example's capitalization rather than transcribing.
- **The schema is described as a compact field list** instead of a JSON Schema dump (about 1,400 → 700 prompt tokens).
- **Merging prefers the back label** for the warning and the name/address statement, the two statements that normally live there. Among other things, an invented but perfectly worded "warning" read off a front label can then never hide a real violation printed on the back.
- **The illegible list no longer raises flags on its own** (findings 4 and 5). It only adds a "may be printed but unreadable — check by eye" note to a field that's already reported missing.

Result: **43/43**. Findings 2 and 3 didn't reproduce in this mode. Each image's prompt no longer mentions the product's import status, and appellation and class/type usually sit on different sides of the label. That's a property of these fixtures, not a guarantee.

### Latency

On an M4 Pro, with images capped at 1024 px on the long edge and Ollama running one request at a time, the uncached gauntlet cases took a **median 12.1 s** (range 4–16 s) to read both images. The gauntlet submits the images *with* the review, so this is the worst case, with no head start. In the UI, each image starts being read the moment it's picked, typically ~6–9 s per image, so the wait after pressing Review is whatever reading time is left once the agent has filled in the form. Downscaling from 1300 to 1024 px cut per-image input processing from ~8.0 s to ~4.7 s.

Cases that reuse an already-read label image with different declared values finish in ~30 ms: extraction results are reused by content hash, so only the matching step runs.

## Llama 4 Maverick on Amazon Bedrock

Run unchanged against `us.meta.llama4-maverick-17b-instruct-v1:0` (same prompt, same parsing): **42/43**, about 1.5 s per image (1.0–4.7 s). The one failure, `chianti_clean_correct`, is a field swap: the label prints the class/type "Chianti Classico" and, below it, the appellation "Chianti Classico DOCG", and the model put each in the other's field. The review comes out flagged rather than clear, so the agent is asked to look at a label that was fine. It was left unfixed on purpose: the prompt was tuned on these 43 labels, and tuning it again to pass this one would make the score less meaningful, not the model better.
