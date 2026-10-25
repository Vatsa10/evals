"""Frozen checks of observable contracts, trajectory, and database side effects."""


def evaluate(request):
    observation = request["observation"]
    expected = request["case"]["expected"]
    checks = {}
    result = observation.get("result", {})
    for key, value in expected.get("result", {}).items():
        checks["result." + key] = result.get(key) == value
    if "status" in expected:
        checks["status"] = observation.get("status") == expected["status"]
    if "ledger_count" in expected:
        ledger = observation.get("ledger", [])
        checks["ledger.count"] = len(ledger) == expected["ledger_count"]
        checks["ledger.total"] = sum(row["amount_cents"] for row in ledger) == expected["ledger_total"]
        checks["ledger.owner"] = all(row["customer"] == request["case"]["input"]["customer"] for row in ledger)
    spans = observation.get("trace", [])
    checks["trace.persisted"] = bool(observation.get("trace_id"))
    ids = {item["id"] for item in spans}
    checks["trace.parents"] = bool(spans) and all(not s.get("parent_id") or s["parent_id"] in ids for s in spans)
    names = {item["name"] for item in spans}
    for name in expected.get("components", []):
        checks["component." + name] = name in names
    if "retrieved" in expected:
        checks["retrieval.documents"] = [d["id"] for d in observation.get("retrieval_context", [])] == expected["retrieved"]
    if "max_tool_calls" in expected:
        checks["tools.budget"] = len(observation.get("tools", [])) <= expected["max_tool_calls"]
    if "turns" in expected:
        checks["conversation.turns"] = len(observation.get("messages", [])) == expected["turns"] * 2
    failed = [name for name, passed in checks.items() if not passed]
    # Each safety/outcome contract is required. Averaging would conceal a bad write.
    return {"score": float(not failed), "reason": "All contracts passed" if not failed else "Failed: " + ", ".join(failed),
            "evidence": {"checks": checks, "failed": failed, "trace_id": observation.get("trace_id")}}
