# Test gauntlet

An end-to-end test suite for the TTB label review pipeline: synthetic label
images with **known ground-truth content**, paired with declared application
data that either matches that content exactly or deliberately diverges from
it in a specific, targeted way. Because we control both sides, we know the
correct verdict for every field ahead of time — any difference between that
and what the real pipeline (Qwen2.5-VL via Ollama + the matching engine)
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

Backend and Ollama (with `qwen2.5vl` pulled) need to be running first:

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

## Findings from the last full run (36/43 passed)

With the matching-engine bugs fixed, `net_contents_unparseable_declared_unit`
now passes for the right reason. Fixing the ABV bug also **unmasked** a
separate, previously-hidden issue: `ipa_clean_correct` used to pass only
because the old engine bug and a model quirk happened to produce the same
"flagged" result by coincidence — with the engine bug gone, the real model
behavior underneath it is now visible as its own failure (item 5 below).

Running the gauntlet against `qwen2.5vl` surfaced five reproducible gaps —
reproducible meaning they happen consistently on a specific label, including
on **clean, undistorted** images, so they're model/prompt behavior, not
image-quality noise or a fixture bug:

1. **The model silently "corrects" the Government Warning's capitalization.**
   `warning_title_case` renders "Government Warning" in title case (a real
   27 CFR 16.21 violation), but the model transcribes it back as
   "GOVERNMENT WARNING" in its response — passing the exact-match check that
   exists specifically to catch this. The model appears to normalize
   well-known boilerplate to its canonical form rather than transcribing
   verbatim capitalization, which defeats the one field the app treats as
   legally exact.

2. **Country of origin can be hallucinated from a US address on imports.**
   `country_of_origin_missing_on_import` removes the "Product of Sweden"
   line entirely, but the model returns `"New York, NY"` — the importer's US
   city/state from the name/address block — as if it were the country of
   origin. The system prompt tells the model to leave `country_of_origin`
   null for domestic products even if a US location is mentioned, but
   doesn't cover this case: an import with no actual origin statement.

3. **`class_type` sometimes absorbs adjacent appellation text.** Both
   `chianti_clean_correct` (no distortion) and `noise_correct` come back with
   `class_type` read as `"Chianti Classico DOCG"` instead of `"Chianti
   Classico"` — "DOCG" is part of the separate appellation line
   ("Chianti Classico DOCG") elsewhere on the back label. The model conflates
   two visually similar, nearby text blocks into one field.

4. **Some labels come back with nearly every field marked illegible despite
   being read correctly.** `lager_clean_correct` and `glare_correct` (same
   underlying label) both get `class_type`, `net_contents`, `name_address`,
   `government_warning_text`, etc. flagged as `illegible_fields` — yet the
   same response's actual extracted values for those fields are correct
   verbatim transcriptions. Confirmed with a raw diagnostic call
   (`extract_label_fields` directly, and a plain free-form transcription
   prompt) — the label is genuinely legible and a simpler prompt reads it
   perfectly; something about this label's structure under the schema-guided
   extraction prompt makes the model self-report low confidence anyway. This
   produces a false "flagged" review burden on a fully compliant label.

5. **An absent field is sometimes marked "illegible" instead of just null.**
   `ipa_clean_correct`'s label genuinely has no ABV printed anywhere (it's a
   malt beverage, where that's allowed) — the model correctly extracts
   `abv_percent: null`, but *also* adds `"abv_percent"` to `illegible_fields`.
   `illegible_fields` is documented in the extraction prompt as "present but
   unreadable," not "absent," so this over-flagging routes a fully compliant
   label to human review for no reason. Likely the same underlying tendency
   as finding 4 — the model hedging into "flag it" even when it already has
   a confident, correct answer.

None of these are fixture bugs — expected verdicts for all five are computed
by the same `compare()` function the app itself uses (now with both matching
engine bugs above fixed), and the underlying label images were manually
reviewed and are cleanly legible. They're reported here rather than fixed,
since fixing them means iterating on the extraction prompt/model, which is a
separate piece of work from the test harness itself.
