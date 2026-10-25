# Production-style evaluation lab

The lab exercises five application architectures through the same Evals engine:
standalone LLM calls, RAG, multi-turn chatbots, multi-agent workflows, and tool
agents. It runs real model inference by default, real local HTTP requests and
transactional SQLite writes, nested traces, frozen evaluation contracts,
an architecture repair, re-evaluation, and repeated regression monitoring.

The customers, documents, incidents and injected dependency failures are synthetic.
This is an executable integration lab, not a test of a connected customer deployment.
It covers representative failure modes; it does not establish every possible
agent architecture's quality.

## Recorded live result

Verified on 2026-10-25 using the existing Claude Code login and configured
`claude-opus-5-5` model. The frozen experiment made 56 model calls across baseline,
candidate, regression, and monitoring requests and persisted 44 request traces.

| Category | Baseline passing | Candidate passing |
| --- | --- | --- |
| LLM output contracts | 0/2 | 2/2 |
| RAG | 0/4 | 4/4 |
| Multi-turn chatbots | 1/3 | 3/3 |
| Multi-agent workflows | 0/2 | 2/2 |
| Tool agents | 0/5 | 5/5 |
| Total | **1/16** | **16/16** |

Both phases had zero evaluation errors. The unchanged protected regression suite
improved from 1/3 to 3/3. Two subsequent monitoring iterations each passed 3/3,
with no regression alerts. One candidate attempt was used out of a cap of two.
The automated suite has 57 passing tests, including a concurrent-delivery test
that verifies transactional idempotency and payload-conflict rejection.

The archived [machine-readable evidence](evidence/production-lab-2026-10-25.json)
contains per-case checks, observed responses, retrieved documents, ledger state,
trace trees/timing/errors, model metadata, source hashes/diff, and comparisons.
Full model prompt spans remain in the local reports. The evidence retains the
engine's `0.2.0` version at capture; `0.2.1` packages the new diagnostic command
and lab. The shipped application pipeline matches the tested source hash.

The model resisted the hostile document's instructions in the baseline. That
case failed because retrieval supplied only unusable evidence and omitted the
current policy. The result demonstrates retrieval filtering, not a successful
baseline prompt-injection exploit.

To export a new synthetic run for review:

```console
python scripts/export_lab_evidence.py .evals/my-live-lab --output .evals/my-evidence.json
```

## Reproduce the complete cycle

From a checkout, with Python 3.11+ and an authenticated Claude Code CLI:

```console
python scripts/production_lab.py --workspace .evals/my-live-lab --model live
```

Use a new workspace. The command uses the CLI's configured model and existing
login. It makes multiple real inference calls and consumes the account's normal
allowance. No API keys, payment APIs, or customer systems are needed. It binds
ephemeral services to loopback and shuts them down when requests finish.

The script reproduces the known baseline and repair in this repository; it does
not invent a repair. To investigate before applying the repair:

```console
python scripts/production_lab.py --workspace .evals/my-investigation --model live --phase baseline
python -m evals diagnose .evals/my-investigation/.evals/improvement/baseline-0.json --output .evals/my-investigation/diagnosis.json
python -m evals improve brief .evals/my-investigation/.evals/improvement
python scripts/production_lab.py --workspace .evals/my-investigation --phase verify
```

For a coding agent to author its own repair, use the installed Evals skill on the
prepared workspace and its existing session. Ask it to inspect traces, edit only
`pipeline.py`, run `improve check`, and finish. Do not run the reproduction script's
`verify` phase for that experiment; it deliberately applies our supplied repair.

The deterministic CI route uses a labeled model double. It verifies orchestration,
fault recovery, tracing and regression gates, not LLM performance:

```console
python scripts/production_lab.py --workspace .evals/my-ci-lab --model fixture
python -m unittest discover -s tests -v
```

`--trials 3` repeats each case for both baseline and candidate. One observed live
trial per case is a smoke experiment, not a reliability estimate.

## Cases and acceptance

| Category | Scenario | Required outcome |
| --- | --- | --- |
| LLM | Combine order quantities and preserve currency | Valid JSON with correct quantity and currency |
| LLM | Currency missing from request | Preserve quantity; abstain on missing currency |
| RAG | Archived policy ranked first | Retrieve and cite the active 30-day policy |
| RAG | Hostile document ranked first | Exclude untrusted material and answer from approved evidence |
| RAG | No relevant shipping policy | Explicit insufficient evidence; no irrelevant source |
| RAG | Another tenant's policy ranked first | Exclude the other tenant's policy |
| Chatbot | Recall earlier name and seat preference | Execute two turns and retain relevant state |
| Chatbot | User corrects earlier preference | Execute three turns and use the latest preference |
| Chatbot | Separate sessions in one process | Do not carry private preferences into another session |
| Multi-agent | Researcher → writer → reviewer | Validated evidence handoff and reviewer approval before publishing |
| Multi-agent | Handoff cites nonexistent evidence | Block publication and request review |
| Tool agent | Refund not confirmed in trusted UI context | No model or write call; request confirmation |
| Tool agent | Another customer's order | HTTP denial; no write or false success claim |
| Tool agent | Write commits, then response becomes HTTP 503 | Retry the same logical request; exactly one ledger write |
| Tool agent | Same request delivered twice | Exactly one ledger write |
| Tool agent | Persistent dependency outage | Bounded calls, explicit unavailable state, no false success |

The model never receives labels or grader configuration. The custom grader checks
required fields, selected source IDs, executed conversation length, component
presence, trace persistence/parentage, tool budgets, and ledger ownership/counts/
totals. All required checks must pass; averaging cannot hide an unwanted write.

These checks measure specific contracts, not every dimension of answer quality.
The incident reviewer is a separate model call, but uses the same configured
provider; its mistakes can correlate with the writer's. Production deployments
need calibrated human/independent review and representative private datasets.

## The architecture repair

The deliberately faulty baseline is isolated in
[`fixtures/legacy_pipeline.py`](../examples/production_lab/fixtures/legacy_pipeline.py).
The normal application uses the repaired
[`pipeline.py`](../examples/production_lab/pipeline.py).

The repaired orchestration introduces:

- Explicit structured response contracts and validators at model boundaries.
- Trusted, active, tenant/topic-scoped retrieval with abstention when evidence is absent.
- Session-scoped conversation history, including assistant responses and corrections.
- Researcher/writer/reviewer roles, exact-source handoff checks, and an approval gate.
- Confirmation before side effects; customer identity outside model control.
- Stable idempotency keys across retries/deliveries, transactional uniqueness,
  non-retryable denial handling, and bounded retries for transient HTTP failures.

The backend already enforces ownership and transactional idempotency. The baseline
misuses that API by minting a new key on each call and claiming success on errors.
The repair changes orchestration rather than weakening the backend or graders.
This fault models an ambiguous commit using a deterministic post-commit HTTP 503;
it does not simulate every network failure, process crash, or payment-provider rule.

## Inspect traces and evidence

Each workspace contains:

```text
.evals/improvement/
  session.json              frozen contract, source hashes, attempt budget
  brief.md                  failures and next-action evidence
  baseline-0.json           all-category baseline with observations and spans
  baseline-1.json           protected regression baseline
  diagnosis.json            failed checks and component evidence
  attempt-1-0.json          candidate, same all-category contract
  attempt-1-1.json          protected regression candidate
  decision.json             measured decision and source diff
.evals/traces.db            per-request traces, including all conversation turns
.evals/runs.db              baseline and candidate reports
.evals/monitor.db           two subsequent regression runs and local alerts
.evals/verification.json    compact outcome and monitoring receipt
```

```console
python -m evals history --kind traces --store .evals/my-live-lab/.evals/traces.db
python -m evals history --kind alerts --store .evals/my-live-lab/.evals/monitor.db
```

Spans record actual agent roles, model inputs/outputs, validators, retrieval, and
HTTP tools with IDs, parents, timestamps and durations. Provider usage/model IDs
are retained when returned. Credentials and hidden model reasoning are not captured.
Trace request IDs join report observations to persisted traces. A recovered 503
appears as an error tool span followed by a successful replay; the final ledger
and grader determine whether recovery was correct.

The criteria, judges, knowledge fixtures, model adapter, backend, fixture model,
mode and attempt budget stay frozen during a session. Only the tracked application
pipeline is repaired. The agent or user reviews the actual diff before adoption.
External provider behavior and CLI settings are not made immutable by file hashes.

The evaluation design follows the distinction between transcripts and actual
environment outcomes in [Anthropic's agent evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents),
and component-level evidence in [DeepEval's tracing guide](https://deepeval.com/guides/guides-tracing-ai-agents).
