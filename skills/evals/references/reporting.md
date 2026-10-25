# Evidence summaries and portable reports

Use project-defined case `category` values and the suite's optional
`coverage_categories` inventory. Untested categories have null rates, failures
have zero rates, and error-only categories are not counted as tested. The category
inventory describes scope; it does not create new acceptance tests.

Live execution is labeled `measured` / `adapter_run`. This proves adapter execution,
not model inference. Preserve fixture/test-double labels. Suite `environment`
declares provider, model and configuration; observation `metadata.provider`,
`metadata.model_ids`, and `metadata.model_mode` provide separate adapter-reported
facts. Do not silently treat either as independent provider verification.

Recorded suites can label source evidence `recorded`, `imported` or
`provider_reported`; imported/provider-reported sources require an HTTP(S)
`source_url`. Optional `evaluated_at` and `label` retain context. Recorded evidence
cannot claim live measured provenance. Older reports lacking these fields remain
unknown/uncategorized.

```console
evals summarize .evals/candidate.json --output .evals/summary.json
evals report-site .evals/candidate.json --baseline .evals/baseline.json --output .evals/review
```

The HTML works directly from disk and includes category/result/search filters,
baseline/candidate selection, and URL state. The generated JSON snapshot filename
contains its full content hash. Use `verify-snapshot PATH` to detect content
changes; hashes are not signatures. The page contains summary metadata rather
than raw inputs, outputs, traces or configuration values. Names, source links and
model metadata may still be private, so review before externally publishing.
Building a page does not authorize deploying it.

Default `compare` and improvement sessions retain their strict dataset/grader
contract. For a person explicitly exploring changed datasets, use:

```console
evals compare BEFORE.json AFTER.json --shared-only --output .evals/overlap.json
```

This compares only cases with compatible input/grader fingerprints and lists
baseline-only, candidate-only and incompatible cases. No shared compatible cases
yields exit 2; observed regressions/errors yield exit 1. Every such comparison is
marked `verification_eligible: false`. Never use it to verify an application fix.
The report UI labels changed-dataset overlap as exploratory and uses comparable
cases only for its comparison totals.

Only named/direct adapter files are fingerprinted. Command-adapter local file
arguments are now included; dependencies, PATH-resolved programs, provider changes
and remote data still need explicit project pinning.
