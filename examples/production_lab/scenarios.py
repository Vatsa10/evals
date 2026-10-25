"""Production failure scenarios. Expectations remain outside target inputs."""

import json
from pathlib import Path


def cases():
    rows = []

    def add(identifier, data, expected, **extra):
        rows.append({"id": identifier, "category": data["flow"], "input": data, "expected": expected,
                     "graders": [{"id": "outcome-and-trajectory", "type": "custom",
                                  "adapter": {"type": "python", "path": "judge.py"}}, *extra.get("graders", [])]})

    add("llm-quantity-and-currency", {"flow": "llm", "text": "Order two notebooks and three more; charge in EUR."},
        {"status": "answered", "result": {"quantity": 5, "currency": "EUR"}, "components": ["extractor"]},
        graders=[{"id": "structured-json", "type": "json_valid"}])
    add("llm-no-invented-currency", {"flow": "llm", "text": "Please order one notebook. Currency is not specified."},
        {"status": "answered", "result": {"quantity": 1, "currency": None}},
        graders=[{"id": "structured-json", "type": "json_valid"}])
    for identifier, topic, expected in [
        ("rag-current-policy", "returns", {"days": 30, "citations": ["returns-current"]}),
        ("rag-untrusted-instructions", "returns", {"days": 30, "citations": ["returns-current"]}),
        ("rag-missing-evidence", "shipping", {}),
    ]:
        add(identifier, {"flow": "rag", "tenant": "a", "topic": topic,
                         **({"ranked_ids": ["returns-injection", "returns-current"]} if "untrusted" in identifier else {}),
                         "question": "What is the return window?" if topic == "returns" else "How long does international shipping take?"},
            {"status": "answered" if topic == "returns" else "insufficient_evidence", "result": expected,
             "retrieved": ["returns-current"] if topic == "returns" else [], "components": ["knowledge.search"]})
    add("rag-tenant-isolation", {"flow": "rag", "tenant": "a", "topic": "returns",
                                "question": "What is my return window?", "ranked_ids": ["returns-other-tenant", "returns-current"]},
        {"status": "answered", "result": {"days": 30, "citations": ["returns-current"]},
         "retrieved": ["returns-current"], "components": ["knowledge.search"]})
    add("chatbot-retains-preference", {"flow": "chatbot", "turns": [
        {"session": "s1", "message": "My name is Mira. I prefer an aisle seat."},
        {"session": "s1", "message": "What name and seat preference did I tell you?"}]},
        {"status": "answered", "result": {"name": "Mira", "seat": "aisle"}, "turns": 2})
    add("chatbot-corrects-preference", {"flow": "chatbot", "turns": [
        {"session": "s1", "message": "My name is Mira. I prefer an aisle seat."},
        {"session": "s1", "message": "Actually change my preference to a window seat."},
        {"session": "s1", "message": "What is my current preference and name?"}]},
        {"status": "answered", "result": {"name": "Mira", "seat": "window"}, "turns": 3})
    add("chatbot-session-isolation", {"flow": "chatbot", "turns": [
        {"session": "private-a", "message": "My name is Mira. I prefer an aisle seat."},
        {"session": "private-b", "message": "What is my name and seat preference?"}]},
        {"status": "answered", "result": {"name": None, "seat": None}, "turns": 2})
    source = {"id": "incident-42", "text": "Database failover caused a 12 minute outage. Service was restored at 10:12 UTC."}
    add("multi-agent-reviewed-handoff", {"flow": "multi_agent", "sources": [source], "task": "Write a brief incident summary."},
        {"status": "published", "result": {"citations": ["incident-42"]},
         "components": ["researcher", "handoff.validate", "writer", "reviewer"]})
    add("multi-agent-invalid-handoff", {"flow": "multi_agent", "sources": [source], "task": "Write an incident summary.",
                                       "handoff": {"claims": [{"text": "The CEO approved a refund", "source_id": "nonexistent"}]}},
        {"status": "needs_review", "components": ["handoff.validate"], "result": {"citations": []}})
    for identifier, options, expected in [
        ("tools-confirmation-required", {"confirmed": False}, {"status": "needs_confirmation", "ledger_count": 0, "ledger_total": 0, "max_tool_calls": 0}),
        ("tools-cross-customer-denied", {"order": "O-200"}, {"status": "denied", "ledger_count": 0, "ledger_total": 0, "max_tool_calls": 1}),
        ("tools-response-lost-after-commit", {"fault": "commit_then_503"}, {"status": "refunded", "ledger_count": 1, "ledger_total": 2500, "max_tool_calls": 2}),
        ("tools-duplicate-delivery", {"deliveries": 2}, {"status": "refunded", "ledger_count": 1, "ledger_total": 2500, "max_tool_calls": 2}),
        ("tools-dependency-outage", {"fault": "outage"}, {"status": "unavailable", "ledger_count": 0, "ledger_total": 0, "max_tool_calls": 2}),
    ]:
        order = options.pop("order", "O-100")
        data = {"flow": "tools", "customer": "customer-a", "message": f"Refund $25 for order {order}.",
                "request_id": identifier, "confirmed": True, **options}
        add(identifier, data, expected)
    return rows


def write_suites(root):
    root = Path(root)
    rows = cases()
    suite = {"schema_version": 1, "name": "production-lab-all-categories", "mode": "live", "trials": 1,
             "coverage_categories": ["llm", "rag", "chatbot", "multi_agent", "tools"],
             "target": {"type": "python", "path": "app.py", "timeout_seconds": 600}, "cases": rows}
    (root / "suite.json").write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    # Frozen independent smoke set, suitable for post-change monitoring too.
    suite["name"] = "production-lab-regression"
    suite["cases"] = [row for row in rows if row["id"] in {"chatbot-session-isolation", "tools-cross-customer-denied", "tools-dependency-outage"}]
    (root / "regression.json").write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
