# A person and a coding agent improving an AI application

The user defines useful behavior. Claude Code or Codex writes and runs evaluations,
reads failures, changes the application, and verifies the result. Evals supplies
the runner and a durable record of that loop; the coding agent does the reasoning
and editing with its normal tools. No separate optimizer service is required.

## Start from the real application

Reuse model clients and credentials already configured in the project. A live
adapter returns actual responses, retrieval, tools, messages, and environment
state. Define the user's acceptance checks and preserve working behavior with
regression cases. Human-reviewed examples help calibrate subjective judges.

After validating the suite:

```console
evals improve start evaluations/suite.json --goal "Correctly resolve eligible refunds" --track src/agent.py --track prompts/support.txt --max-attempts 3 --output .evals/improvement
```

Add `--regression-suite evaluations/regressions.json` to evaluate protected
behavior in every attempt. `--trials N` sets the baseline and candidate trial
count together. `--lock judges/rubric.md` freezes an extra grading dependency.
Paths passed to these flags resolve from the current working directory.

The command executes a live baseline and saves:

- `session.json`: goal, suites, criteria fingerprints, source fingerprints, budget,
  and candidate ledger.
- `baseline-*.json`: complete reports, evidence, and errors.
- `brief.md`: a failure brief for the person and the coding agent.
- `sources/baseline/`: snapshots of tracked application files.

The suite files, direct custom-grader files, explicitly locked rubric/reference
files, and engine source are frozen. Application files are tracked, not frozen:
they are what you improve. Python target adapter files are automatically tracked;
also name prompts and application dependencies you intend to change with `--track`.
Keep grading code in separate files from application code.

## Diagnose, edit, and measure

Read `brief.md` and the relevant reports. Make a bounded application change with
a concrete hypothesis, then run:

```console
evals improve check .evals/improvement --hypothesis "Use the fetched policy instead of guessing the refund window"
```

Each candidate records its hypothesis, source snapshots and diff, complete primary
and regression reports, and per-case/per-grader comparison to the original baseline.
Both pass-rate declines and mean grader-score declines count as observed regressions.
An improved overall case count cannot hide a worse individual metric.

The default attempt budget is three candidate evaluations. Interrupted attempts
count. A lock prevents overlapping checks from spending the same budget slot.
This is an attempt limit, not a provider token/spend limit.

Exit 0 means this candidate is ready to verify; exit 1 means it still needs work;
exit 2 means invalid configuration or changed criteria. Baseline failures are
expected, so `improve start` exits 0 after successfully recording them.

## Finish with a reviewable decision

```console
evals improve status .evals/improvement
evals improve brief .evals/improvement
evals improve finish .evals/improvement
```

`decision.json` describes one of these outcomes:

| Status | Meaning |
| --- | --- |
| `verified_improvement` | At least one case or grader improved, no detected case/grader regressions or candidate errors, primary acceptance checks pass, a tracked application file changed, and current tracked files match the tested candidate |
| `baseline_satisfied` | The original application already passed the checks and its tracked files remain unchanged; no improvement is claimed |
| `not_verified` | The current source has no matching verified candidate; the agent can continue within the remaining budget |

`--allow-partial` at session start explicitly permits an improvement with remaining
primary failures. It still requires a measurable gain and the other gates. Report
remaining failures clearly. A restored, previously verified candidate can be
selected without pretending the most recent unsuccessful alternative passed.

The framework does not commit, merge, deploy, or automatically revert application
code. Human review can inspect the diff and decision in the same workflow.

## Evidence limits

Read [the external verifier](verifier.md) for stronger isolation. Local decisions
use the `in_session` trust profile; signed external decisions use submitted
patches and independently pinned private contracts.

Verification applies to the selected cases, recorded trials, and supplied graders.
Repeated trials describe observed variability; comparisons do not estimate
statistical significance or guarantee production behavior. Run independent
representative cases and review judges rather than optimizing only the examples
used to diagnose a failure.

Only named files and direct adapter/grader files are fingerprinted. Track other
application files and lock imported grading dependencies explicitly. External
services, environment variables, data stores, remote model versions, and provider
configuration still need reproducible project fixtures or versioning. File
fingerprints deter accidental contract drift, not a malicious agent with write
access to its own session artifacts. Do not present them as a security boundary.
