# Live verification

## Version 0.3.0: provenance, coverage and portable reporting

Verified on 2026-10-25 using the existing configured `claude-opus-5-5` model.
The reporting integration executed six application cases spanning LLM extraction,
RAG, multi-turn chat, multi-agent review, and ambiguous tool commits. A separate
session-isolation regression was protected. There were 23 model calls and 14
persisted request traces across baseline/candidate execution.

The primary suite improved from **1/6 to 6/6** with zero evaluation errors and
no observed regressions. The new report records measured adapter execution,
separate declared/adapter-reported model metadata, five tested categories and
an explicitly untested vision category. Full and exploratory pages were generated
from the saved reports. The exploratory comparison correctly retained one shared
case and exposed five candidate-only cases, with verification ineligible.

Offline Chromium checks passed at 1360, 768 and 390px for both views, including
URL state restoration, browser back, keyboard operation, empty states and no
external requests. The new reporting tests cover malformed evidence, changed
contracts/judges, legacy reports, snapshot changes/tampering and summary privacy.
All 73 automated tests pass. The clean plugin and installed wheel both generated
the same versioned report from the saved live evidence.

See the [reporting guide](reporting.md) and
[captured portable report](../website/reports/production).

## Version 0.2.1: five system categories

The production-style lab was run end to end on 2026-10-25 with actual configured
model inference, local HTTP tools, transactional SQLite side effects and persisted
traces. It covers standalone LLM calls, RAG, multi-turn chatbots, multi-agent
handoffs and tool workflows.

The frozen primary suite improved from **1/16 to 16/16**, using one candidate
attempt, with zero evaluation errors and no case/grader regressions. A protected
three-case regression suite passed, then two monitoring iterations each passed
3/3 with no alerts. There were 56 model calls and 44 request traces. All 57
automated tests pass. These are observed synthetic-lab results, not customer
production traffic or broad reliability estimates.

See the [scenario matrix and reproduction guide](production-lab.md) and the
[captured evidence](evidence/production-lab-2026-10-25.json).

## Version 0.2.0: the complete improvement loop

Verified on 2026-10-25 with Codex CLI 0.164.0 and Claude Code 2.1.310 on Windows.
Both agents received the person's goal and acceptance criteria and used the
updated Evals skill to create and complete an improvement session. The prompt
did not prescribe the individual engine commands.

| Verification | Baseline | Candidate | Result |
| --- | --- | --- | --- |
| Installed Codex plugin, actual application fixture | 2 passed / 1 failed | 3 passed / 0 failed | `verified_improvement`, 1 attempt |
| Claude Code plugin, actual application fixture | 2 passed / 1 failed | 3 passed / 0 failed | `verified_improvement`, 1 attempt |
| Actual LLM responses, system-prompt improvement | 1 passed / 2 failed | 3 passed / 0 failed | `verified_improvement`, 1 attempt |

All successful runs had zero evaluation errors, unchanged datasets/graders, and
captured application or prompt changes. The agent workflow fixtures call the
real support function but are deterministic. The third row calls an actual model
through the existing Claude Code login and checks the generated responses.

For the real LLM test, the baseline prompt forced quantity zero for every request.
The observed outputs were zero for one notebook, a combined order of five, and a
cancellation. The coding agent read the failure brief and changed only the prompt
to perform general quantity extraction, addition, cancellation handling, and plain
JSON formatting. The candidate produced 1, 5, and 0, respectively. The same judge
and cases were used. This is evidence on three specified cases, not a benchmark
of broad model performance.

An initial adapter probe returned integration errors because the installed Claude
CLI could return a JSON message array rather than a single result object. Those
errors were kept separate from quality failures. After repairing and testing the
adapter, a fresh baseline measured the prompt failures above.

The automated framework suite has 54 passing tests, including contract changes,
regression gates, stale source, interruption/budget handling, and actual CLI
envelope shapes. Raw sessions are kept in ignored `.evals` directories.

To repeat the agent workflow with a fresh workspace:

```console
python scripts/live_codex_test.py --host codex --workspace .evals/codex-improvement-new
python scripts/build_plugin.py dist/evals-claude-test
python scripts/live_codex_test.py --host claude --plugin-dir dist/evals-claude-test/plugins/evals --workspace .evals/claude-improvement-new
```

The Codex route requires the current plugin to be installed. Both routes use
existing CLI authentication and configured models, normal workspace/edit
permissions, and an explicit two-attempt budget. No approval-bypass flags are used.

See the [improvement workflow](improvement-workflow.md) and the
[actual LLM example](../examples/llm_prompt).

## Historical first plugin verification (0.1.0)

Verified on 2026-10-25 with Codex CLI 0.164.0 on Windows, using the user's existing
ChatGPT login. The actual installed `evals@evals` plugin was loaded in a new
`codex exec` session with the normal workspace sandbox.

## What happened

1. Built a clean marketplace with `scripts/build_plugin.py` and installed it
   through `codex plugin marketplace add` and `codex plugin add`.
2. Started Codex in a separate test project with the prompt `Use $evals`.
3. Codex read the installed skill and its framework reference from its plugin
   cache, then inspected the provided support application.
4. It created a Python adapter calling the application's actual `handle_return`
   function and a suite covering day 7, day 30, and day 31.
5. The baseline reported 2 passed, 1 failed, 0 errors. Day 30 was incorrectly
   rejected because the implementation used `>= 30`.
6. Codex changed the condition to `> 30`, reran the same suite, and obtained
   3 passed, 0 failed, 0 errors.
7. Comparison reported one improvement and no regressions. The dataset SHA-256
   was identical across runs, proving the test inputs and grading contract
   remained unchanged.

The coding-agent session was live. The support app was a deterministic fixture;
this verifies plugin authoring/execution/debugging, not an LLM provider's quality.
Raw sessions and reports stay in ignored `.evals/codex-live` files and are not
published as repository content.

To repeat after installing the plugin:

```console
python scripts/live_codex_test.py --workspace .evals/codex-another-run
```

The script requires a fresh workspace and verifies the saved baseline, candidate,
comparison, and unchanged dataset contract. It uses the configured Codex model
and existing authentication; it does not select a new model or request an API key.

## Other paths checked

- Built a Python wheel and installed it into an isolated virtual environment.
- Ran the installed wheel from a separate project: 8 demo trials passed.
- Ran two finite monitoring cycles and inspected saved SQLite history.
- Captured nested tool/model spans, linked conversation IDs, and ran online graders.
- Verified local HTTP trace ingestion, run history, missing-evidence handling,
  online failure alerts, and trace-to-regression-suite export through tests.
- Validated Claude Code plugin/marketplace manifests and the shared skill. Version
  0.2.0 also verifies a live Claude Code improvement session, as described above.

The monitoring API is local. Hosted operations, external alert delivery, provider
auto-instrumentation, a browser dashboard, and model-specific semantic graders
are separate future extensions; custom grader adapters can supply judges today.
