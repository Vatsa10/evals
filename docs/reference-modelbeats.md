# ModelBeats reference review

Reviewed [punitarani/modelbeats](https://github.com/punitarani/modelbeats) on
2026-10-25 at commit `8c066400606d02f6b7bf4971bb74f4e402f4ea65`.
The local reference clone is `.upstream/modelbeats`, excluded from Git and plugin
packages. No upstream code or dataset was copied into the Evals implementation.

ModelBeats primarily catalogs and compares model benchmark results. Evals executes
application evaluations and verifies changes with coding agents. The following
ideas are implemented for application evaluations in version 0.3.0. See the
[end-to-end reporting guide](reporting.md) for commands, schemas and limits.

| Observed idea | Implemented in Evals |
| --- | --- |
| Result provenance | Reports label measured, recorded, imported and provider-reported evidence; retain source URL/date and distinguish declared from adapter-reported model metadata |
| Honest missing coverage | Explicit case categories and declared category inventory; `summarize` exposes case/trial counts, errors and null rates for untested categories |
| Shared and one-sided comparisons | `compare --shared-only` validates per-case contracts, lists exclusions, and remains ineligible for improvement verification |
| Content-versioned artifacts | `report-site` builds an offline HTML page and SHA-256-versioned JSON summary; `verify-snapshot` detects content changes |
| Pure shared functions | `evals.reporting` handles summary validation, coverage and exploratory comparison for both CLI and UI |
| URL-backed state | Report filters retain run, category, result, coverage and search in the URL, with browser back/forward |

These features expose existing execution evidence and its scope. Raw prompts,
responses, traces and configuration values stay out of the portable summary;
full evidence remains in the local reports. Default comparisons and improvement
verification keep their strict frozen-contract requirements. An overall model
ranking still requires its own comparable dataset, missing-data policy and
statistical justification; no universal model ranking is introduced.

## Source anchors

- [Result schema](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/packages/shared/src/schema/result.ts)
- [Coverage and normalization](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/packages/shared/src/scoring.ts)
- [Validation and artifact build pipeline](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/scripts/src/build-catalog.ts)
- [Content-derived snapshot version](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/scripts/src/snapshot.ts)
- [Comparison and scoring decisions](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/docs/DECISIONS.md)

Some architecture sections preserve superseded designs. This review follows the
current implementation and the explicit decision updates, including the build-time
artifact pipeline rather than the earlier database design.
