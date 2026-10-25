---
name: evals
description: Evaluate and improve real LLM applications and AI agents inside Claude Code or Codex. Define success with the user, run evaluations, diagnose failures, change prompts/tools/code, and verify improvements against frozen criteria. Also supports AI tracing and monitoring.
---

# Evals

Evals is a person-and-coding-agent improvement loop. The person supplies the goal
and acceptance criteria. You connect the real application, run evaluations,
investigate failures, improve the system, and verify the result in this same
coding-agent session. The engine measures evidence and preserves the baseline.

Use the bundled independent engine. DeepEval is reference material, not a runtime
dependency. Resolve this skill's real directory (including symlinks); the plugin
root is two parents above it. Run commands from the user's project with
`python "<plugin-root>/scripts/evals.py" <command>`, or use an installed `evals`.
Python 3.11+ is required.

## Start from the person's target

Read [guided intake](references/intake.md) for a new request or a bare invocation.
Inspect the project and reuse prior answers before asking questions. Establish
the target, exact goal, acceptance criteria, existing assets, desired mode and
execution scope. Save a durable project brief and check its missing fields.
Ask only what matters and is not already known, in small conversational rounds.
Never invent acceptance criteria, provider configuration or authorization.
When the request is complete, execute the selected workflow without another
generic confirmation. If essential answers are missing, keep the draft and wait;
do not run model calls or change application behavior yet.

Use the mode selected by the person or the invoked command. Evaluate-only means
no application fixes. An improvement request authorizes bounded changes in the
agreed files. A report request uses existing evidence and makes no target calls.
Preserve explicitly requested output paths and existing valid suites/sessions.

## Choose the requested workflow

- **Evaluate only:** inspect the app, create/reuse a live suite and adapter,
  validate, run, and explain evidence. Do not change application behavior unless
  the user asked for improvement.
- **Evaluate and improve:** complete the loop below. Do not stop at a score or
  suggestions when the user authorized implementing improvements.
- **Tracing/monitoring:** read [monitoring](references/monitoring.md) and connect
  the actual app. Start persistent services only when requested.

Read [the engine contract](references/framework.md) when authoring cases/adapters.
Read [the improvement workflow](references/improvement.md) before starting a loop.
For provenance, category coverage, evolving-dataset comparisons or a shareable
report page, read [reporting](references/reporting.md).
For application coverage beyond a single agent, read the relevant rows of the
[system evaluation matrix](references/system-evaluation.md): LLM outputs, RAG,
chatbots, tool workflows, and multi-agent handoffs.

## Evaluate and improve

1. Inspect the real model/agent entrypoint, prompts, retrieval, tools, tests, and
   existing datasets. Reuse the user's model/provider and environment. Do not
   switch models silently. Use the person's stated goal and acceptance criteria;
   ask only if a missing criterion materially prevents valid grading.
2. Build or reuse meaningful cases and a thin adapter calling the actual app.
   Include existing working behavior as regression cases or a separate regression
   suite. Keep labels out of the target request. Demo fixtures from `init` only
   test the framework and cannot establish application quality.
3. Select graders that measure the goal. Use deterministic checks for verifiable
   facts and a custom calibrated LLM judge for subjective quality. Substring checks
   do not prove faithfulness. Recorded captures can inform cases, but verifying a
   fix requires live execution. Do not invent traces or hidden reasoning.
4. Validate the suite. Start an improvement session with the user's goal, the app
   and prompt files you will change, and any regression suites. Freeze external
   rubric/reference files with `--lock`. Use the user's attempt budget, or the
   default maximum of three candidate evaluations.
5. Read `brief.md` and the relevant full reports. Use `diagnose REPORT.json` to
   locate failed graders and error spans, including recovered tool errors. Identify the earliest failed
   component from evidence. Form a specific hypothesis, then edit the real prompt,
   retrieval, tool behavior, or application code. Treat missing evidence and
   infrastructure errors explicitly rather than grading them as successes.
6. Run `improve check SESSION --hypothesis "..."`. Inspect case and grader
   regressions, error counts, and remaining failures. Preserve the frozen cases,
   graders, references, and trial budgets; improving the app is the work. Never
   weaken a check, hardcode expected answers, or substitute a fake app to pass.
7. Continue only while the session budget and user scope permit. Restore only
   your own changes when abandoning an unsuccessful approach. A previously tested
   candidate can be selected after its exact tracked source is restored.
8. Run `improve finish SESSION`. A verified decision requires a measured
   improvement, no detected case/grader regressions, no candidate errors, and the
   currently tracked source to match the tested candidate. By default, the primary
   acceptance suite must pass. Human review decides whether to adopt or deploy.
9. Report the goal, root cause, actual changes, baseline/candidate evidence,
   regression results, remaining gaps, session directory, and decision status.
   Distinguish `baseline_satisfied` from an improvement and `not_verified` from
   success. A stochastic run is observed evidence, not universal proof.
   Use `summarize REPORT.json` to expose provenance and untested categories. For
   a review artifact, use `report-site CANDIDATE --baseline BASELINE --output DIR`.
   Shared-case comparisons are exploratory and cannot replace the strict gate.

Keep scope clear. The framework does not automatically edit arbitrary systems or
change business goals. You perform the application work through the host's normal
tools and permissions. The person can inspect the source diff and evidence in
the improvement session without leaving their coding workflow.
