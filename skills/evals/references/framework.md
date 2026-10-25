# Framework contract

`init [directory]`, `validate <suite.json>`, `run <suite.json> [--trials N]
[--output report.json]`, `report <report.json>`, `compare <baseline> <candidate>`,
`diagnose <report.json> [--output diagnosis.json]`,
`summarize <report.json>`, `report-site <candidate> --baseline <baseline> --output DIR`,
`verify-snapshot <snapshot.json>`,
and `doctor` are supported by the bundled `scripts/evals.py` entrypoint.
For the complete person-and-coding-agent feedback loop, use
`improve start/check/brief/status/finish`; see [the improvement workflow](improvement.md).

Exit status: 0 for passing runs/comparisons, 1 for failed/error trials or observed
regressions, 2 for invalid configuration, and 130 for an interrupted CLI run.

## Suites

```json
{
  "schema_version": 1,
  "name": "support-refunds",
  "mode": "live",
  "trials": 1,
  "target": {
    "type": "python",
    "path": "adapter.py",
    "function": "evaluate",
    "timeout_seconds": 60
  },
  "cases": [
    {
      "id": "eligible-order",
      "input": {"order_id": "o1"},
      "graders": [
        {"id": "refund-created", "type": "equals", "path": "/state/refund/status", "expected": "processed"}
      ]
    }
  ]
}
```

Adapter paths and command working directories resolve relative to the suite file.
Python adapters receive one dictionary with `case_id`, `trial`, `input`, and
`context`. They can be synchronous or async. References and grader configuration
are excluded from the request. Return a JSON object containing available evidence:

```json
{
  "output": "Refund processed.",
  "tools": [{"name": "refund", "arguments": {"order_id": "o1"}}],
  "state": {"refund": {"status": "processed"}},
  "messages": [{"role": "assistant", "content": "Refund processed."}],
  "retrieval_context": [{"id": "refund-policy", "text": "Eligible orders can be refunded."}],
  "trace": [{"id": "step-1", "kind": "tool", "name": "refund"}],
  "usage": {"total_tokens": 250}
}
```

Fields are optional; checks requesting absent fields return `missing_evidence`.
`state` should come from inspecting the actual environment, not the agent's claim.
Capture only observable plans, messages, calls, and artifacts; private reasoning
is not required. The tracing SDK captures nested spans around wrapped sync/async
functions; adapters can also supply traces directly. Provider SDK interception
is not implemented. See [monitoring](monitoring.md).

A command target uses:

```json
{"type": "command", "argv": ["{python}", "adapter.py"], "timeout_seconds": 60}
```

It receives the same request as JSON on stdin and must emit one JSON value on
stdout. Put diagnostics on stderr. Arguments are executed directly without a
shell. Python function adapter prints are routed to stderr automatically.

For existing captures, use `"mode": "recorded"`, omit `target`, and put an
`observation` object in each case. Recorded suites require exactly one trial;
regrading a capture does not measure independent execution reliability.

## Graders

Each grader has a `type`, optional unique `id`, optional JSON Pointer `path`, and
`threshold` in (0, 1], defaulting to 1. All graders must pass for a trial to pass.
Missing evidence or grader errors make the trial an error, while other graders
still run. Paths use JSON Pointer escaping (`~1` for `/`, `~0` for `~`).

| Type | Configuration | Default evidence |
| --- | --- | --- |
| `equals` | `expected`: exact JSON value, including number representation | `/output` |
| `contains` | `expected`: literal, case-sensitive substring | `/output` |
| `regex` | `expected`: Python regular expression | `/output` |
| `json_valid` | Checks whether a string contains one valid JSON value | `/output` |
| `max_value` | `expected`: numeric upper bound | `/output`; usually set `/usage/total_tokens` |
| `tool_calls` | `expected`: nonempty tool-call list; optional `ordered`, `allow_extra` | `/tools` |
| `retrieval_precision` | `expected`: relevant document IDs | `/retrieval_context` |
| `retrieval_recall` | `expected`: relevant document IDs | `/retrieval_context` |
| `custom` | `adapter`: Python/command adapter; optional `rubric` | Whole case and observation |

Tool checks match supplied top-level properties exactly. With `ordered: true`
the expected calls must form a subsequence. Set `allow_extra: false` to require
the same number of calls. Repeated expected calls need distinct actual calls.
For semantic argument checks or alternative valid plans, use a custom grader.

Retrieval scores use unique document IDs. Precision is relevant retrieved IDs /
retrieved IDs; recall is relevant retrieved IDs / expected relevant IDs. Empty
retrieval scores zero. These checks require relevance labels and do not establish
answer correctness or faithfulness.

Custom graders receive `{"case": ..., "observation": ..., "rubric": ...}` and
return `{"score": 0.8, "reason": "Explanation", "evidence": ...}`. Scores must be
finite numbers in [0, 1]. Use this protocol for application-specific checks,
reference-based LLM judges, conversation rubrics, or trajectory judgments. Judge
credentials and provider calls belong in that adapter; no model API is built in.
Calibrate subjective judges against human judgments before using them as gates.

## Reports and comparisons

Reports contain all observations, verdicts, evidence, execution errors, per-trial
elapsed time, per-case success rates, and suite/target source fingerprints.
`target_duration_ms` measures adapter execution; `duration_ms` includes grading.
Rate denominators include errors; error counts are also reported separately.
`any_trial_passed` and `all_trials_passed` describe the observed trial batch. They
are not estimates of pass@k or pass^k. Confidence intervals are not implemented.

Comparisons require the same cases, inputs, grading contract, mode, and direct
Python custom-grader source. They report observed case success-rate and mean
grader-score changes, and fail on case/grader regressions or candidate errors.
These are point comparisons, not significance estimates. Dependency trees, remote model versions,
and PATH-resolved command executables are not automatically fingerprinted; pin these in the
project when reproducibility requires it.

Local command-adapter file arguments are fingerprinted. For provenance, category
coverage and exploratory compatible-case comparisons, see [reporting](reporting.md).
