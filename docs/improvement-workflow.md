# Evaluate and improve from the coding workflow

For an agent-resistant verification boundary, use the
[external patch verifier](isolated-verifier.md). This page describes the local
improvement loop; its hashes are in-session drift checks, not isolation.

Evals is built for a person and their coding agent to improve an AI application
together. The person defines useful behavior and reviews the result. Claude Code
or Codex connects the real application, writes evaluations, reads failures, edits
prompts/tools/retrieval/code, and verifies changes. Evals supplies repeatable
execution, frozen criteria, source snapshots, and evidence.

## In Claude Code or Codex

After installing the plugin, give the agent the objective and expected behavior:

```text
Use Evals to evaluate and improve this application's extraction accuracy.
Connect the real model calls. Preserve the cases that already work.
Use at most three candidate evaluations and show me the final evidence.
```

In Codex you can invoke `$evals` explicitly. In Claude Code use `/evals:evals`.
The agent inspects the project and uses the first-class improvement workflow.
It should implement authorized fixes rather than stopping after suggestions.
There is no separate optimizer service and no mandatory dashboard to switch to.

The agent reuses the project's configured model provider. Built-in deterministic
graders handle verifiable requirements; custom adapters can call the project's
LLM judges for subjective criteria. Judge quality still requires representative
examples and human calibration.

## What happens underneath

1. Define cases and success criteria from the person's goal or existing dataset.
2. Connect a live adapter to the actual application, then validate the suite.
3. Start an improvement session and run a baseline before changing the app.
4. Read the failure brief and underlying trace/output evidence.
5. Record a hypothesis and change the application or prompt, keeping the criteria.
6. Evaluate the candidate on the same primary and regression suites.
7. Check case results, grader scores, errors, and the tracked source diff.
8. Finish with a decision describing the tested improvement or the remaining gap.

```console
evals improve start evaluations/suite.json --goal "Improve extraction accuracy" --track app.py --track prompts/system.txt --max-attempts 3 --output .evals/improvement
evals improve brief .evals/improvement
evals improve check .evals/improvement --hypothesis "Ground extraction in the retrieved document"
evals improve finish .evals/improvement
```

The coding agent performs the edit between `brief` and `check` using its normal
tools and permissions. These commands work for manually written integrations too.
If Evals is not installed into the app environment, the plugin invokes its bundled
`scripts/evals.py` entrypoint with the same arguments.

## What prevents a misleading success

- Suite and direct custom-grader files are frozen when the baseline is created.
  Extra rubric/reference dependencies can be pinned with `--lock`.
- Baselines and candidate reports are retained separately; each attempt has a
  hypothesis, source snapshots, and a diff.
- A decline in an individual grader blocks verification even if aggregate case
  results improved. Regression suites protect other working behavior.
- Missing evidence and target/judge errors are separate from quality failures.
- Only the recorded attempt budget is allowed; interruptions consume attempts.
- Final verification checks the current tracked files against a tested candidate.
  Additional edits require another evaluation.
- Retrying unchanged code until it happens to pass does not count as a verified
  application improvement.

By default the primary acceptance suite must pass. An explicit `--allow-partial`
at the start permits measured progress with remaining failures, which are still
reported. The session cannot quietly relax this condition during an attempt.

These are reproducibility and workflow checks, not a security sandbox. A coding
agent with write access can edit its own artifacts; human review remains relevant.
External model versions, services, and untracked dependencies need project-level
fixtures/versioning. Statistical significance and universal quality guarantees
are not claimed from a small set of trials.

## Try an actual LLM prompt improvement

`examples/llm_prompt` calls the configured default model through an existing
signed-in Claude Code CLI. It contains a deliberately weak constant-output prompt.
The grading code checks actual generated JSON; it does not substitute recorded
or fabricated model outputs. The example consumes normal model account allowance.

Copy that directory into a scratch project so the original learning example is
preserved. Then, from that project with Evals installed:

```console
evals improve start suite.json --goal "Return correct order quantities as plain JSON" --track prompt.txt --max-attempts 2 --output .evals/improvement
evals improve brief .evals/improvement
```

Have your coding agent diagnose the failed responses and improve `prompt.txt`,
then use `check` and `finish`. Keep `suite.json` and `judge.py` unchanged.
The fixture covers an individual quantity, a sum across groups, and cancellation.
These cases demonstrate the loop rather than representing broad model quality.

For another provider or model stack, replace the thin model adapter with the
application's existing client. The workflow and grader contract stay the same.

See [the command and evidence contract](../skills/evals/references/improvement.md)
and [live verification](live-verification.md).
