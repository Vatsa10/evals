"""A runnable, explicitly illustrative suite with no model credentials."""

import json
from pathlib import Path


APP = '''"""Demo fixtures. Replace evaluate() with your real application adapter."""

def evaluate(request):
    task = request["input"]["task"]
    if task == "answer":
        return {"output": "Paris"}
    if task == "retrieve":
        return {"output": "Returns are accepted within 30 days.",
                "retrieval_context": [{"id": "returns-policy", "text": "Returns are accepted within 30 days."}]}
    if task == "refund":
        return {"output": "Refund processed.",
                "tools": [{"name": "verify_identity", "arguments": {"customer_id": "c1"}},
                          {"name": "refund", "arguments": {"order_id": "o1"}}],
                "state": {"refund": {"status": "processed"}}}
    if task == "conversation":
        return {"messages": [{"role": "user", "content": "I only eat vegetarian food."},
                             {"role": "assistant", "content": "Understood."},
                             {"role": "user", "content": "Suggest dinner."},
                             {"role": "assistant", "content": "Try a vegetarian curry."}],
                "output": "Try a vegetarian curry."}
    raise ValueError(f"Unknown demo task: {task}")
'''

SUITE = {
    "schema_version": 1, "name": "demo-fixtures", "mode": "live", "trials": 1,
    "coverage_categories": ["llm", "rag", "tools", "chatbot", "multi_agent"],
    "provenance": {"label": "Deterministic demo fixtures; no model inference"},
    "target": {"type": "python", "path": "app.py", "function": "evaluate", "timeout_seconds": 10},
    "cases": [
        {"id": "llm-answer", "category": "llm", "input": {"task": "answer", "question": "What is the capital of France?"},
         "graders": [{"id": "correct-answer", "type": "equals", "expected": "Paris"}]},
        {"id": "rag-retrieval", "category": "rag", "input": {"task": "retrieve", "question": "What is the returns window?"},
         "graders": [{"id": "relevant-documents", "type": "retrieval_recall", "expected": ["returns-policy"]},
                     {"id": "window-mentioned", "type": "contains", "expected": "30 days"}]},
        {"id": "agent-refund", "category": "tools", "input": {"task": "refund", "customer_id": "c1", "order_id": "o1"},
         "graders": [{"id": "verified-before-refund", "type": "tool_calls", "ordered": True,
                      "expected": [{"name": "verify_identity", "arguments": {"customer_id": "c1"}},
                                   {"name": "refund", "arguments": {"order_id": "o1"}}]},
                     {"id": "refund-exists", "type": "equals", "path": "/state/refund/status", "expected": "processed"}]},
        {"id": "conversation-constraint", "category": "chatbot", "input": {"task": "conversation"},
         "graders": [{"id": "preference-retained", "type": "contains", "path": "/messages/3/content", "expected": "vegetarian"}]},
    ],
}


def initialize(directory):
    directory = Path(directory)
    files = {"suite.json": json.dumps(SUITE, indent=2) + "\n", "app.py": APP}
    for name in files:
        if (directory / name).exists():
            raise ValueError(f"Refusing to overwrite {directory / name}")
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        with (directory / name).open("x", encoding="utf-8") as handle:
            handle.write(content)
    return directory / "suite.json"
