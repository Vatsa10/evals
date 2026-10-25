"""A deterministic support-app fixture for verifying the coding-agent workflow.

Policy: delivered orders can be returned through day 30 inclusive. Orders older
than 30 days must be rejected. This fixture deliberately has a boundary bug.
It does not call an LLM; the live Codex test exercises the plugin workflow.
"""


def handle_return(days_since_delivery):
    if days_since_delivery >= 30:
        return {"decision": "rejected", "message": "The return window has closed."}
    return {"decision": "approved", "message": "Your return is approved."}
