# Guided commands for Claude Code and Codex

Evals can begin with a conversation about the person's target rather than a
prewritten suite. The harness inspects the project, asks only missing questions,
saves the answers, connects the real app, and executes the selected workflow.

## Commands

| What you want | Claude Code | Codex |
| --- | --- | --- |
| Help me define and start the work | `/evals:start` | `$evals-start` |
| Run evaluations without application fixes | `/evals:run` | `$evals-run` |
| Diagnose, fix and verify failures | `/evals:improve` | `$evals-improve` |
| Instrument or inspect real traces | `/evals:trace` | `$evals-trace` |
| Review existing results and build a report | `/evals:report` | `$evals-report` |

The existing `/evals:evals` and `$evals` entrypoints remain available and use the
same guided intake. In Codex, `/skills` opens the skill picker. Codex skill
mentions use `$`; the plugin does not register custom Codex `/evals:*` commands.
Claude plugin commands are namespaced, so the installed command is `/evals:start`,
not a global `/evals` command. Restart the host if newly installed commands do not
appear.

## Start with a conversation

```text
/evals:start
```

The agent reads relevant project files and existing evaluation artifacts before
asking questions. A typical first round is:

1. Which behavior should we target, and what is currently going wrong?
2. What should a correct result do? Existing examples or acceptance rules help.
3. Should I evaluate only, or implement and verify fixes too?

It also resolves missing entrypoints, existing data/traces, environment, action
scope, allowed application files and budget constraints. It reuses answers from
the request/project instead of asking the same questions again. For subjective
criteria, the person and agent establish an appropriate rubric and calibration
examples before treating a model judge as an acceptance gate.

The person can provide a complete request in one command:

```text
$evals-improve Evaluate and fix the quantity extractor in app/extract.py.
Two notebooks plus three more must produce quantity 5; a cancellation must
produce quantity 0. Use our existing provider and dataset. Run locally with
sandboxed actions. You may edit app/extract.py and prompts/extract.txt.
Use one trial and at most two candidate attempts.
```

When everything is known, the agent recaps the plan and proceeds under that
authorization. The command does not require an extra generic confirmation.
When critical answers are absent, it preserves a draft and waits before target
calls or application changes. In noninteractive CLI sessions, questions are
returned as text and a later invocation resumes the saved brief.

## Saved project brief

The default path is `evaluations/brief.json`. It records:

- Target, exact goal, success criteria, system categories and requested mode.
- Real entrypoint and existing suite, examples, traces, reports and regressions.
- Candidate/trial/target-call budgets and allowed application change files.
- Execution environment and permitted application side effects.

The CLI also supports manual setup and automation:

```console
evals brief init evaluations/brief.json --project-root .
evals brief check evaluations/brief.json
evals brief show evaluations/brief.json
evals brief update evaluations/brief.json --from .evals/answers.json
```

`init` refuses to overwrite a brief. `update` merges explicit supplied fields and
preserves the other answers. `check` lists missing fields/questions, with exit 1
while intake is incomplete. Schema/configuration errors use exit 2. A draft can
be ready for setup even when an adapter/suite still needs to be implemented.

Paths in assets and allowed_changes are relative to project_root. The saved
project_root is relative to the brief's directory, so it remains usable from a
different working directory. Keep credentials in the project's normal secret
configuration, not in intake answers.

Example answers file, merged into a generated draft:

```json
{
  "mode": "improve",
  "target": "Application quantity extractor",
  "goal": "Extract combined quantities without breaking cancellations",
  "success_criteria": ["Two plus three yields five", "Cancellation yields zero"],
  "system_types": ["llm"],
  "assets": {"entrypoint": "app/extract.py:extract", "suite": "evaluations/suite.json"},
  "constraints": {"allowed_changes": ["app/extract.py", "prompts/extract.txt"], "max_attempts": 2},
  "execution": {"environment": "local", "side_effects": "sandboxed"}
}
```

Defaults are one trial, three candidate attempts and at most 100 framework target
invocations for the whole configured plan. The preflight counts all live primary
and protected-regression cases across baseline plus the full candidate budget.
If that upper bound exceeds max_target_calls, execution stops before calling the
application. This bounds framework adapter invocations, not internal LLM/tool
calls, tokens, elapsed time or API charges. Configure those limits in the actual
application/provider too when needed.

## Execution and artifacts

After the harness has connected the real application and saved assets.suite:

```console
evals workflow start evaluations/brief.json --output .evals/guided
evals workflow status .evals/guided
```

All commands work through the plugin's bundled
`python "<plugin-root>/scripts/evals.py"` entrypoint without installing the SDK.

| Mode | What the helper executes |
| --- | --- |
| evaluate | Runs the suite, records history/alerts, writes report.json, summary.json and review/index.html |
| improve | Starts a frozen baseline in improvement/, preserving the original brief and a request copy as locked files |
| trace | Runs a real instrumented suite, or ingests existing captured JSON traces with explicit recorded-evidence labeling |
| report | Builds an offline review from one report or baseline then candidate, with no new target calls |

For improvement, the harness continues after the baseline:

```console
evals improve brief .evals/guided/improvement
evals improve check .evals/guided/improvement --hypothesis "Explain the actual application change"
evals improve finish .evals/guided/improvement
evals workflow status .evals/guided
```

The agent edits the agreed application files between brief and check, then
generates a review from the selected candidate and baseline. Existing direct
engine commands remain supported. If the person requests an explicit session
layout, the harness can use `improve start` directly with `--lock BRIEF` after
the same intake and budget preflight.

Changing the agreed brief after an improvement baseline invalidates subsequent
checks. Start a new brief/baseline for changed goals; do not weaken the frozen
contract or reset budgets to make failures disappear. The wrapper tracks allowed
application files inside the declared project root. File hashes and recorded
scope help review ordinary changes; they are not an adversarial security boundary
or an enforcement layer for arbitrary remote side effects. The host's permissions
and the application's own authorization still apply.

If adapter/transport errors require a new baseline, retain the initial error
evidence and original frozen files. Any continuation must use only the remaining
aggregate call/attempt budget and report its actual active workflow path. A fresh
baseline is required before claiming a behavioral improvement under a repaired
integration; initialization errors are not model-quality measurements.

`workflow status` exposes the current improvement state and decision. Intake ready,
baseline ready, a generated report and verified improvement are separate outcomes.

## Verification

Run the native entrypoints with missing requirements, then resume using supplied
answers in separate real harness sessions:

```console
python scripts/build_plugin.py dist/evals-guided
python scripts/live_guided_test.py --host claude --plugin-dir dist/evals-guided/plugins/evals --workspace .evals/guided-claude
python scripts/live_guided_test.py --host codex --workspace .evals/guided-codex
```

The Codex route uses the currently installed plugin. Both require existing CLI
authentication and use normal workspace/edit permissions. The target application
is a deterministic sandbox fixture with a call counter; the coding-agent sessions
are live. The test checks zero target calls during incomplete intake, preserved
answers, a frozen brief, bounded attempts/calls, unchanged grading criteria and a
verified application fix. No approval-bypass flags are used.

Native invocation formats follow [Claude Code skills/commands](https://code.claude.com/docs/en/skills)
and [official OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills).
