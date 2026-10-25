# Guided project intake and execution

## Entry commands

| Intent | Claude Code | Codex |
| --- | --- | --- |
| Start with my target | `/evals:start` or `/evals:evals` | `$evals-start` or `$evals` |
| Evaluate only | `/evals:run` | `$evals-run` |
| Improve failures | `/evals:improve` | `$evals-improve` |
| Trace a real workflow | `/evals:trace` | `$evals-trace` |
| Review existing results | `/evals:report` | `$evals-report` |

Claude commands and Codex skills route to this same core workflow. Codex also
offers `/skills` for selecting the skill. Do not claim custom `/evals:*` slash
commands exist in Codex or that the plugin registers a global `/evals` command.

## Discover before asking

Inspect README/configuration and the relevant application entrypoints, suites,
examples, traces and reports. Reuse the person's current request and earlier
answers. Avoid a generic questionnaire when the project already establishes a
fact. Do not read credential files or ask people to paste keys into the brief.

Create or resume `evaluations/brief.json`. Use the bundled CLI, or installed
`evals`, with these commands:

```console
evals brief init evaluations/brief.json --project-root .
evals brief check evaluations/brief.json
evals brief update evaluations/brief.json --from .evals/intake-answers.json
```

`init` never overwrites an existing brief. `update` merges supplied fields and
preserves other answers. The answers file is an ordinary JSON object containing
only fields learned from the person or project. Do not put literal placeholders
into ready fields. Paths inside assets/allowed_changes are relative to project_root;
the saved project_root is relative to the brief's directory.

## Conversation

A bare start often needs the target, goal, success examples and desired mode.
Ask two or three concise questions per round using the host's available question
tool, or a normal conversational question when that tool is unavailable. For example:

1. Which behavior should we target, and what is currently going wrong?
2. What should a correct result do? Existing examples or acceptance rules help.
3. Should I evaluate only or implement and verify fixes too?

Then resolve any missing entrypoint, environment, permitted application actions,
or allowed change files. The brief checker supplies specific missing fields and
question prompts. It does not require asking already-discovered facts again.
System categories, existing examples/data, project provider and budget details
should come from the request/project when available; ask when a missing fact
materially changes the work. Use the existing provider/model rather than introducing one.

Defaults are one trial, at most three candidate attempts and at most 100 framework
target invocations across the planned baseline/candidate batches. Explain these
defaults in the brief recap and honor the person's overrides. A target invocation
can make multiple internal model/tool calls; this is not an API-spend cap.

Record environment and action scope from actual context: `local`, `staging` or
`production`; application side effects `none`, `sandboxed` or `authorized`.
Do not infer production-write authorization from a request for evaluation.
Framework report/history writes are separate from evaluated application actions.

If the host is noninteractive (for example `codex exec` or `claude --print`) and
critical information is missing, write the draft, list the pending questions,
and stop before target calls/application edits. A later request can resume the
saved brief; do not fabricate a user's answer to make a test run finish.

## Execute the selected mode

Once `brief check` is ready, summarize the target, acceptance rules, action scope,
planned files and budgets. Continue under existing authorization; this recap is
not a mandatory second approval gate.

For evaluate/improve, connect a thin adapter to the real entrypoint and author
or reuse the actual suite. Save its path as `assets.suite`. Readiness describes
intake completeness; the execution preflight also validates the integration and
whole planned target-call budget. Never substitute `init` demo fixtures for the app.
Check the adapter contract before running: `output` must be a string. Put structured
objects in `state`/`result` (or JSON-serialize them), and point graders at that
actual shape. An otherwise correct target response must not become an adapter error.

```console
evals workflow start evaluations/brief.json --output .evals/guided
evals workflow status .evals/guided
```

- **evaluate:** runs the supplied suite, saves the report/summary/history and
  portable review page. Failed checks do not authorize application fixes.
- **improve:** starts a guarded baseline in `.evals/guided/improvement`, freezes
  the original brief and request copy as well as the normal contract, and uses
  `constraints.allowed_changes` as tracked application files. Diagnose and implement
  the authorized fix, then call `improve check` and `improve finish` on that session.
  Continue to the final evidence rather than stopping after setup.
- **trace:** instrument the actual entrypoint using the tracing SDK and create
  a live suite, then run it; or ingest existing JSON traces listed in assets.traces.
  Label capture ingestion as recorded evidence, not a new live execution. Do not
  start persistent services unless requested.
- **report:** uses one existing report, or baseline then candidate, to generate
  the offline review. It makes no target/model calls or application changes.

An existing active improvement session can be resumed directly. Do not restart
baselines or reset budgets just because another command was invoked. If the person
changes the goal/criteria, prepare a new brief/baseline rather than editing a frozen
brief. Honor explicit session paths by using the core commands with `--lock BRIEF`
when the wrapper's directory layout would conflict with the requested path.

Finish with the requested goal, measured results, fixes (if authorized), regressions,
remaining gaps and evidence paths. Build a review page from the selected candidate
and its baseline. Preserve the distinction between intake ready, baseline ready,
verified improvement and merely generated reports.

If integration errors require a fresh baseline, preserve the error evidence and
original frozen files. Repair the integration, allocate only the remaining total
target-call/attempt budget to a new brief/session, then rerun the real baseline
before any app fix. Never claim an errored baseline measured application quality.
The final response must name the active continuation's workflow/session path and
include aggregate call accounting across the recovery; do not present a stale
original workflow as the verified continuation.
