# Live verification

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
- Validated Claude Code plugin/marketplace manifests and the shared skill. A live
  Claude Code model session has not been run.

The monitoring API is local. Hosted operations, external alert delivery, provider
auto-instrumentation, a browser dashboard, and model-specific semantic graders
are separate future extensions; custom grader adapters can supply judges today.
