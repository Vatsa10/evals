# Evals

Evaluate and improve real AI applications from the coding workflow you already use.
You define success; Claude Code or Codex runs evaluations, diagnoses failures,
changes your prompts/tools/code, and verifies the result against a frozen baseline.

Our engine, graders, tracing, and storage are implemented here. DeepEval,
Langfuse, LangSmith, and Anthropic's evaluation guidance inform the design.
Python 3.11+ is the only runtime requirement.

The static landing page lives in `website/`. See the
[preview and GitHub Pages deployment guide](docs/website.md).

## Choose how to use it

| Offering | What you do | What Evals provides |
| --- | --- | --- |
| Coding-agent plugin | Install in Claude Code or Codex and invoke the skill | An agent that creates suites, runs checks, investigates failures, and verifies fixes |
| Plug-and-play setup and monitoring | Ask the agent to connect Evals to your application | Project-specific adapters, quality checks, request tracing, repeated runs, history, and local alerts |
| Manual SDK and CLI | Write your own suites, adapters, traces, and judges | The same independent engine and monitoring primitives without a coding-agent dependency |

The plugin guides the coding agent. The Python engine executes evaluations and
records evidence. Your application can use any model provider or agent stack.
DeepEval is design reference material, not a runtime dependency.

## The core workflow: evaluate, improve, verify

Ask your coding agent to improve a specific behavior, not just produce a score:

```text
Use $evals to evaluate and improve this AI application.
Use its real model calls, preserve working behavior, and verify the fix
against unchanged criteria. Use at most three candidate evaluations.
```

The agent uses `evals improve start/check/finish` to create a baseline, read an
evidence-backed failure brief, edit the actual system, and check the candidate.
Sessions retain the goal, attempt budget, source diffs, reports, and final decision.
Changed criteria, grader regressions, evaluation errors, or untested source edits
prevent a verified result. The primary acceptance suite must pass by default.

Read the [end-to-end workflow](docs/improvement-workflow.md). An
[actual LLM example](examples/llm_prompt) demonstrates improving a system prompt;
the optional CLI-based example uses your configured model and account allowance.

## 1. Use with Claude Code or Codex

Codex CLI:

```console
codex plugin marketplace add Vatsa10/evals
codex plugin add evals@evals
```

Start a new Codex session in your application, then ask:

```text
Use $evals to inspect and evaluate this application, improve its failures,
and verify the changes against the same acceptance criteria.
```

Claude Code:

```text
/plugin marketplace add Vatsa10/evals
/plugin install evals@evals
```

Start a new session and invoke `/evals:evals` with the same request.
The plugin runs its bundled engine without a package installation. SDK tracing
inside your application requires that application to be able to import Evals.

For local development, build a clean marketplace:

```console
python scripts/build_plugin.py dist/evals-marketplace
codex plugin marketplace add /absolute/path/to/evals/dist/evals-marketplace
codex plugin add evals@evals
```

The build excludes Git history, virtual environments, reports, tests, and the
reference clone. Use a fresh build directory when rebuilding. See official
[Codex plugin documentation](https://developers.openai.com/plugins/build/plugins)
and [Claude Code manifests](https://code.claude.com/docs/en/plugins-reference).

## 2. Plug-and-play setup and monitoring

Ask your coding agent:

```text
Use Evals to connect evaluations to this project's real application.
Add traces for model calls and tools, retain conversation IDs,
set up online grading and continuous regression checks,
then verify one complete request and evaluation run.
```

The agent inspects the actual entrypoints and writes the integration. Supply
expected behavior or an existing dataset so quality criteria reflect your app.
Once the integration exists:

```console
evals run evaluations/suite.json --output .evals/baseline.json
evals monitor evaluations/suite.json --interval 60 --baseline .evals/baseline.json
evals history --kind runs
evals history --kind traces --thread-id conversation-123
evals history --kind alerts
evals serve --policy evaluations/online-policy.json --port 8765
```

The monitor repeatedly runs suites and records regressions. The loopback JSON
API ingests traces and exposes run/trace/alert history. Online policies score
completed requests using the same graders. Messages, retrieval context, tools,
state, and nested spans are available as grading evidence.

Alerts are local records. This release has no hosted dashboard, external alert
delivery, or automatic provider SDK interception. The monitor runs in the
foreground until stopped and does not install a scheduler or service.

## 3. Write integrations manually

```console
git clone https://github.com/Vatsa10/evals.git
cd evals
python -m evals doctor
python -m evals init evaluations
python -m evals run evaluations/suite.json --trials 3 --output .evals/baseline.json
```

The starter contains runnable fixtures for responses, retrieval, tools, state,
and conversations. Replace the adapter and cases to evaluate your application;
fixture scores measure the framework demo.

To import the SDK from another project:

```console
python -m pip install "git+https://github.com/Vatsa10/evals.git"
```

Use `python -m pip install -e /path/to/evals` for development. Package builds may
download setuptools; the engine has no third-party runtime dependencies.
Without installation, use `python /path/to/evals/scripts/evals.py <command>`.

Adapters receive `input`, `context`, `case_id`, and `trial`, then return evidence.
Expected answers and graders are excluded from target requests. Targets can be
sync/async Python functions or JSON-in/JSON-out commands.

```python
from evals import observe, trace

@observe(kind="tool")
def fetch_order(order_id):
    return database.get_order(order_id)

with trace("support", input=user_message, thread_id=session_id) as request:
    order = fetch_order(order_id)
    answer = agent.reply(user_message, order)
    request.update(output=answer)
```

Spans capture wrapped arguments/results. Use explicit spans with selected fields
when you need control over recorded data. Supply an online policy to grade each
request. Synchronous judges add latency; private model reasoning is not required.

Read the [suite and grader reference](skills/evals/references/framework.md) and
[monitoring guide](skills/evals/references/monitoring.md).
Programmatic evaluations use `evals.engine.load_suite` and `run_suite`.

## A complete local monitoring example

```console
python examples/online/instrumented.py
python -m evals ingest examples/online/trace.json --policy examples/online/policy.json
python -m evals history --kind traces
python -m evals history --kind runs
python -m evals serve --policy examples/online/policy.json
```

In another terminal, read `http://127.0.0.1:8765/health` or `/api/traces`.
`POST /api/traces` records a request and applies the configured policy.
`evals export TRACE_ID --policy POLICY --output captured.json` creates a recorded
regression suite. Create a live suite from its input to verify a fix.

## Evaluation behavior

- Graders check exact values, substrings, patterns, JSON, numeric limits, tool
  order/arguments, and labeled retrieval precision/recall.
- Custom graders support domain checks and LLM judges with explicit providers,
  rubrics, scores, reasons, and evidence. No default judge model is selected.
- Missing evidence and execution errors remain distinct from failed assertions.
- Live trials start fresh processes. External systems need fixtures/reset logic.
- Reports include evidence, timing, source fingerprints, and case success rates.
  Comparisons require the same grading contract and track individual grader scores.
- Improvement sessions freeze criteria, cap attempts, preserve source diffs,
  and verify the current application against the evaluated candidate.
- Recorded observations have one trial. Replaying captures does not estimate
  reliability. Confidence intervals and pass@k estimators are future work.

## Development and verification

```console
python -m unittest discover -s tests -v
python scripts/build_plugin.py dist/evals-marketplace
claude plugin validate .claude-plugin/plugin.json
```

CI checks Windows/Linux with Python 3.11/3.13, builds the plugin, and runs a suite.
Live Codex verification requires a signed-in Codex CLI and is separate from
credential-free CI. See [live verification](docs/live-verification.md).

## References

The ignored `.upstream/deepeval` clone was inspected at
`5410e3822dda5f889d5f35de3325a3738004aeb1`. No upstream engine or skill is vendored.
The offline/online split follows distinctions documented by
[DeepEval](https://deepeval.com/docs/evaluation-llm-tracing),
[Langfuse](https://langfuse.com/docs/evaluation/overview), and
[LangSmith](https://docs.langchain.com/langsmith/evaluation).
Outcome verification and repeated trials are informed by
[Anthropic's evaluation guide](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
