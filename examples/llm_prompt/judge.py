"""A deterministic acceptance check over an actual model response."""

import json


def evaluate(request):
    output = request["observation"]["output"]
    try:
        parsed = json.loads(output)
    except (ValueError, TypeError):
        return {"score": 0, "reason": "Response must be plain JSON", "evidence": output}
    expected = request["case"]["expected_quantity"]
    actual = parsed.get("quantity") if isinstance(parsed, dict) else None
    correct = type(actual) is int and actual == expected
    return {"score": int(correct), "reason": f"Expected quantity {expected}; observed {actual!r}",
            "evidence": {"actual": actual, "expected": expected, "output": output}}
