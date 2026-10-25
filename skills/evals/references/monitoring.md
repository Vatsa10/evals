# Continuous evaluations and live tracing

The plugin, setup workflow, and manual SDK all use the same engine, observation
contract, and local SQLite history.

## Repeated suite runs

```console
evals monitor evaluations/suite.json --interval 60
evals monitor evaluations/suite.json --interval 1 --iterations 2
evals history --kind runs
evals history --kind alerts
```

The first run becomes the baseline unless `--baseline <report.json>` is given.
Every run is stored. Failed/error trials and observed case or grader regressions create local
alert records. Omit `--iterations` to run in the foreground until interrupted.
No scheduler or service is installed. A finite monitor returns 1 if any run
triggered an alert. Changed grading criteria require a new baseline.

## Instrument real requests

```python
from evals import observe, span, trace
from evals.monitoring import load_policy

policy, root = load_policy("evaluations/online-policy.json")

@observe(kind="tool")
def lookup_order(order_id):
    return orders.get(order_id)

def handle_request(message, thread_id):
    with trace("support", input=message, thread_id=thread_id,
               policy=policy, root=root) as request:
        order = lookup_order("o1")
        with span("answer", kind="llm") as generation:
            answer = model.respond(message, order)
            generation.set_output(answer)
        request.update(output=answer)
        return answer
```

Use the application's existing models and tools. `@observe` supports sync/async
functions, captures arguments/results, and nests spans; the outermost decorated
call creates a trace. A trace context supplies thread IDs and online graders.
Prefer explicit spans with selected inputs/outputs when arguments include secrets
or data that should not be recorded. Only wrapped operations are captured; there
is no automatic provider SDK interception or access to private model reasoning.

`request.update()` attaches output, messages, retrieval_context, usage, and actual
state. Spans retain parent IDs, timing, status, and observable input/output. Tool
spans also populate the observation's tools list.

Persistence and optional online graders run synchronously at request completion.
Model-based judges add their own latency and cost. Persistence failures emit a
warning without replacing the application's result or exception. There is no
remote exporter or background flush queue.

The default database is `.evals/evals.db` in the application's working directory.
Use `EVALS_STORE`, `store=Store("path/to/evals.db")`, or CLI `--store` to choose it.

## Online grading and the local API

A policy is a JSON object with `name` and a nonempty `graders` list, using the
same grader syntax as a suite. For unlabeled production traffic, use format and
budget checks or a custom judge with a rubric. Reference checks need labels.

```console
evals serve --policy evaluations/online-policy.json --port 8765
evals ingest capture.json --policy evaluations/online-policy.json
evals history --kind traces --thread-id conversation-123
```

`GET /health` returns counts. `GET /api/runs`, `/api/traces`, and `/api/alerts`
return JSON lists; `/<id>` fetches one record. List queries accept `limit=1..1000`
and `thread_id`. `POST /api/traces` accepts:

```json
{
  "name": "support",
  "thread_id": "conversation-123",
  "input": "Where is my order?",
  "observation": {"output": "Your order arrives tomorrow."}
}
```

The server binds to loopback. It is a local integration API, not an authenticated
internet-facing service. Incoming traces cannot supply executable graders;
online graders come only from trusted local policy configuration.

```console
evals export TRACE_ID --policy evaluations/online-policy.json --output evaluations/captured.json
evals run evaluations/captured.json
```

A captured suite evaluates saved evidence. To verify a fix against current
behavior, turn its input and criteria into a live suite.
Alerts are local records exposed through history/API. Email, Slack, webhooks,
a browser UI, and hosted monitoring are not implemented.
