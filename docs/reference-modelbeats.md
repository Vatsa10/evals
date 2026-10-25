# ModelBeats reference review

Reviewed [punitarani/modelbeats](https://github.com/punitarani/modelbeats) on
2026-10-25 at commit `8c066400606d02f6b7bf4971bb74f4e402f4ea65`.
The local reference clone is `.upstream/modelbeats`, excluded from Git and plugin
packages. No upstream code or dataset was copied into the Evals implementation.

ModelBeats primarily catalogs and compares model benchmark results. Evals executes
application evaluations and verifies changes with coding agents. The following
ideas are candidates for future implementation, not newly shipped capabilities.

| Observed idea | Application to Evals |
| --- | --- |
| Result rows retain source type, source URL and optional evaluation date | Label measured, imported and provider-reported results; retain provider/model/configuration and evidence provenance |
| Missing benchmark values remain null; ranking eligibility requires coverage | Show tested categories, case counts and trial counts beside scores; distinguish untested behavior from failed behavior |
| Comparison separates shared and one-sided benchmark coverage | Compare compatible shared cases and expose excluded cases explicitly; preserve our current strict frozen-contract gate for improvement verification |
| Validate data, derive results, then publish content-versioned snapshots | Generate reproducible static run summaries from saved reports/traces, retaining contract hashes and source links |
| Pure shared scoring/selectors with contract tests | Keep aggregation and comparison logic independent of any future report UI |
| URL parameters preserve comparison state | Make future report filters and baseline/candidate selections shareable |

The strongest initial fit is explicit provenance and coverage in report summaries.
Evals already retains dataset hashes, source fingerprints, per-case results and
local evidence; a summary could expose those facts more clearly without claiming
unmeasured coverage. An overall model ranking would require its own comparable
dataset, missing-data policy and statistical justification.

## Source anchors

- [Result schema](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/packages/shared/src/schema/result.ts)
- [Coverage and normalization](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/packages/shared/src/scoring.ts)
- [Validation and artifact build pipeline](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/scripts/src/build-catalog.ts)
- [Content-derived snapshot version](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/scripts/src/snapshot.ts)
- [Comparison and scoring decisions](https://github.com/punitarani/modelbeats/blob/8c066400606d02f6b7bf4971bb74f4e402f4ea65/docs/DECISIONS.md)

Some architecture sections preserve superseded designs. This review follows the
current implementation and the explicit decision updates, including the build-time
artifact pipeline rather than the earlier database design.
