# Evaluate the actual system boundaries

Choose the rows matching the user's application. A multi-agent or chatbot request
must exercise those actual paths; a single function fixture cannot establish
their quality. Use existing production incidents and redacted traces when available.

| System | Meaningful scenarios | Evidence and outcome |
| --- | --- | --- |
| LLM call | Structured output, missing facts, ambiguous input | Raw response, schema validation, factual labels; keep provider failures separate |
| RAG | Stale documents, wrong tenant, malicious text, missing evidence | Selected/excluded sources, supported citations, justified abstention |
| Multi-turn chatbot | Remembered constraints, corrections, cancellation, separate sessions | Execute every turn; retain user and assistant messages, session IDs and final state |
| Tool agent | Missing confirmation, denied access, ambiguous commit, duplicates, outage | Authenticated identity outside model control, HTTP outcomes, bounded retries, committed state |
| Multi-agent system | Valid/invalid handoff, unsupported claim, reviewer disagreement | Real role calls and nested spans; typed handoff validation, citations, publication/approval state |

The task should pass when the intended outcome occurs through an acceptable
trajectory. For side effects, inspect the database or sandbox service; text saying
"done" is insufficient. For subjective quality use calibrated independent review,
not a substring that happens to occur in the response.

Record agent, LLM, retriever, validator and tool spans where applicable. Include
parent IDs, timestamps, tool arguments/results, model usage and provider identity
when available. Do not collect hidden reasoning or credentials. Missing spans are
missing evidence; do not synthesize them after execution.

Use `evals diagnose REPORT.json --output .evals/diagnosis.json` for failed checks,
component call counts, error spans and invalid parents. A recovered timeout can
coexist with a successful request. Diagnose from the full trajectory and actual
state before choosing a fix; error-span presence alone is not a failure verdict.

Fix the boundary responsible for the failure. Examples include versioned retrieval
filters, session-scoped state, typed handoffs, a reviewer approval gate, and an
idempotent transactional tool API. A new prompt alone cannot enforce customer
authorization or make a committed write safe to retry.

Run the same frozen suite and protected regressions after the change. Repeat live
trials when reliability matters and report observed counts, model identity, and
remaining uncertainty. Keep deterministic test doubles labeled as integration
checks. They are useful in CI but do not demonstrate live model quality.

The repository's [production-style lab](https://github.com/Vatsa10/evals/blob/main/docs/production-lab.md)
contains executable examples across these categories. Its data and incident faults
are synthetic; connect the user's actual app before claiming production results.
