"""Run from the repo root: python examples/online/instrumented.py."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals import observe, span, trace
from evals.monitoring import load_policy


@observe(kind="tool")
def get_order(order_id):
    return {"order_id": order_id, "days_since_delivery": 7}


policy, root = load_policy(Path(__file__).with_name("policy.json"))
with trace("support-request", input="Can I return o1?", thread_id="support-conversation-1",
           policy=policy, root=root) as request:
    order = get_order("o1")
    with span("format_response", kind="llm") as generation:
        # Deterministic fixture. Replace with your actual model call.
        output = '{"decision":"approved"}'
        generation.set_output(output)
    request.update(output=output, usage={"total_tokens": 120})
print(request.receipt)
