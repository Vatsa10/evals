---
name: evals
description: Set up, run, compare, and monitor evaluations for LLM applications, RAG pipelines, tool-using agents, and conversations using Evals. Use for AI quality tests, plug-and-play evaluation setup, production tracing, and investigating evaluation failures.
---

# Evals

Use the bundled independent engine. DeepEval is design reference material, not a
dependency; do not install it or substitute its CLI for this framework.

Resolve symlinks on this skill directory, then resolve the plugin root as two
parents above it. Run the engine
from the user's project with `python "<plugin-root>/scripts/evals.py" <command>`.
An installed `evals` CLI is also usable. Python 3.11+ is the only runtime requirement.
Keep the working directory in the user's project so reports land there.

Inspect the application's actual entrypoint, tools, retrieval, conversation state,
and existing tests. Reuse existing datasets and success criteria. If an essential
criterion is unavailable, ask for it while continuing unrelated setup.

For the suite and adapter contracts, read [the framework reference](references/framework.md).
For production tracing or continuous monitoring, read [monitoring](references/monitoring.md).

- Create or adapt a committed suite and an adapter calling the real application.
  `init evaluations` generates runnable demo fixtures; those fixtures only verify
  the framework and must not be presented as evidence of application quality.
- Specify outcomes first. For tool-using agents, check observable environment
  state when available and check tool arguments or dependencies where required.
  Do not require an exact trajectory when several valid approaches exist.
- For RAG, separate retrieval coverage from answer quality. The built-in document
  ID metrics measure retrieval, and substring checks do not establish faithfulness.
- For conversations, collect the actual messages across turns. A recorded history
  evaluates those observations; a live adapter must execute the interaction to
  measure current behavior. Do not invent hidden reasoning or unavailable traces.
- Use deterministic checks for verifiable facts. For subjective quality, use a
  custom judge adapter with a rubric and representative human-scored examples.
  Reuse the project's configured provider; the engine has no default judge model.

Run `validate <suite>` before `run <suite>`. Use `--trials N` when the user wants
reliability measurements; each live attempt gets a fresh process. External files,
databases, and services still need fixtures or reset logic in the target adapter.
Keep case references out of target inputs; the engine already excludes graders.

Read the saved JSON report, including failing grader evidence and target errors.
Treat `missing_evidence` and judge/adapter errors as evaluation errors. Report the
gap or improve instrumentation rather than silently awarding a score.

When asked to improve the app, save a baseline, make a targeted change, rerun the
same cases, and use `compare <baseline> <candidate>`. Preserve grading criteria;
changing them requires a new baseline. Comparisons describe observed success-rate
changes, not statistical significance. Honor the requested iteration budget and
stop when it is reached or remaining work needs information or authorization.

For plug-and-play setup, do the integration work in the user's project: create a
real adapter and suite, add tracing around relevant application components, and
verify one complete run. Offer the commands for continuous monitoring once the
first run works. Launch a persistent monitor only when the user requests it.
Keep expected answers and criteria stable when repairing application failures.

Report what was evaluated, passed/failed/error counts, representative failures,
the saved report path, and remaining evidence gaps. State when only demo fixtures
or recorded observations were evaluated. Do not claim host integration was tested
unless the plugin was actually loaded in that host.
