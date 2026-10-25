# Provenance, coverage, comparisons and report pages

Version 0.3.0 applies the useful ModelBeats reference ideas to application
evaluations: explicit provenance, coverage-aware summaries, compatible-case
exploration, pure shared aggregation, content-versioned snapshots, and URL-backed
report filters. The evaluation engine and UI are implemented independently here.

## End-to-end use

After running the real application through an existing live suite:

```console
evals run evaluations/suite.json --output .evals/baseline.json
```

Make the authorized application change and rerun the same suite:

```console
evals run evaluations/suite.json --output .evals/candidate.json
evals compare .evals/baseline.json .evals/candidate.json --output .evals/comparison.json
evals summarize .evals/candidate.json --output .evals/summary.json
evals report-site .evals/candidate.json --baseline .evals/baseline.json --output .evals/review
```

Open `.evals/review/index.html` directly in a browser. It works offline with no
server, framework, external fonts, analytics or CDN dependencies. Use the same
commands through the plugin's `python "<plugin-root>/scripts/evals.py"` entrypoint.
For verified improvement decisions, continue using `improve start/check/finish`;
the report page is a review artifact, not a substitute for those gates.

An improvement session's reports work directly:

```console
evals report-site .evals/improvement/attempt-1-0.json --baseline .evals/improvement/baseline-0.json --output .evals/improvement/review
```

For a credential-free demonstration, run `evals init evaluations` first. Its
provenance explicitly identifies deterministic fixtures; it does not call a model.

## Declare coverage and provenance

Add optional metadata to a suite:

```json
{
  "coverage_categories": ["llm", "rag", "chatbot", "multi_agent", "tools"],
  "provenance": {"label": "Extraction acceptance suite"},
  "environment": {
    "provider": "my-provider",
    "model": "my-pinned-model",
    "configuration": {"temperature": 0}
  }
}
```

Add `"category": "rag"` (or another category) to each case. Category names are
project-defined; the engine does not infer them from case IDs or prompt text.
The production lab and starter now supply explicit categories.

Coverage reports include cases, trials, validly graded trials, passes, failures,
errors and pass rate per category. A declared category with no cases is
**untested**, with a null rate. A failed category has a zero rate. A category with
only execution/grading errors is labeled `error`, not counted as tested. Rates
use all attempted trials, including errors, consistently with the existing engine.
The declared category list is an inventory, not a new acceptance gate; add real
cases before claiming that category is covered. Existing improvement gates still
apply to the actual frozen suite.

Live adapter execution has `measured` provenance and `adapter_run` execution.
It establishes that the adapter ran, not that it called a real model. Test doubles
should identify themselves with `observation.metadata.model_mode = "fixture"` or
a clear suite label. A model port can additionally report `metadata.provider` and
`metadata.model_ids`. Reports keep those adapter-reported identities separate
from the suite author's declared provider/model/configuration. Neither is an
independent attestation of the remote provider's behavior.

Recorded suites have `replay` execution. They can declare `recorded`, `imported`
or `provider_reported` provenance. The latter two require a source URL:

```json
{
  "mode": "recorded",
  "provenance": {
    "kind": "provider_reported",
    "source_url": "https://example.org/results",
    "evaluated_at": "2026-10-25",
    "label": "Illustrative source metadata; replace with the actual source"
  }
}
```

This metadata accompanies ordinary recorded cases and graders; it does not fetch
or certify a third-party benchmark. Recorded evidence cannot claim `measured`
provenance. Older saved reports remain readable, with unknown provenance and
uncategorized cases when those facts were not recorded.

## Compare evolving datasets without hiding exclusions

The default `compare` and all improvement-session checks still require the same
dataset and direct grader sources. For exploratory analysis only:

```console
evals compare .evals/baseline.json .evals/expanded.json --shared-only --output .evals/overlap.json
```

The result lists compatible shared cases, baseline-only cases, candidate-only
cases, and incompatible cases. A matching ID alone is insufficient: the per-case
input/grading contract and direct custom-grader sources must match. Older reports
without per-case contracts can overlap only when the full dataset hashes match.
Unfingerprinted external command judges are excluded from shared comparisons.
No compatible cases yields CLI exit 2; observed regressions/errors yield exit 1.

Every shared-only comparison has `verification_eligible: false`. It cannot turn
partial or changed coverage into a verified improvement. The report page also
labels changed-dataset comparisons as exploratory, shows excluded cases, and
computes its comparison totals on compatible cases only.

Command adapters now fingerprint local file arguments as well as Python adapters.
This does not pin executables resolved through PATH, imported dependencies, remote
services, or environment variables; freeze/version those explicitly when needed.

## Versioned, portable artifacts

`report-site` validates trial/case counts before deriving a summary. The output is:

```text
review/
  index.html
  report-<sha256>.json
```

The full SHA-256 identifies the canonical snapshot payload. Re-exporting the same
saved report produces the same version; changed data produces a new snapshot.
Existing differently populated files under the same version are rejected.
`index.html` embeds the snapshot, so it also works through `file://`. Rebuilding
an output directory updates its index while retaining older versioned snapshots.

```console
evals verify-snapshot .evals/review/report-<sha256>.json
```

The hash detects content changes; it is not a signature or proof of origin. An
editor can recompute a hash. Raw inputs, responses, traces, grader evidence and
configuration values are excluded from the portable summary. Configuration has
a fingerprint instead. Suite/case names, provenance links and model identities
are metadata and can still be private; review the export before sharing it.

Filters persist in the URL, for example:

```text
index.html?run=baseline&category=rag&status=failed&view=shared&q=retrieval
```

The page supports candidate/baseline selection, compatible/shared/one-sided
coverage, search, empty states, category shortcuts, keyboard navigation and browser
back/forward. Copy its URL to preserve the current view. Once hosted, that link
is shareable with other people. The same files can be uploaded to GitHub Pages;
the command does not deploy or start a persistent service.

## Reproduce the live integration

```console
python scripts/live_reporting_test.py --workspace .evals/reporting-live --model live
python scripts/check_report_site.py .evals/reporting-live/.evals/report
python scripts/check_report_site.py .evals/reporting-live/.evals/exploratory-report
```

Live mode uses the existing Claude CLI login/model and account allowance. It runs
six cases spanning LLM extraction, RAG, multi-turn chat, multi-agent review, and
ambiguous tool commits, with a protected session-isolation regression. It records
actual model and tool traces, applies the repository's known application repair,
re-evaluates unchanged criteria, and exports strict and exploratory report pages.
A declared vision category remains explicitly untested. `--model fixture` runs
the same integration with a labeled deterministic model double.
