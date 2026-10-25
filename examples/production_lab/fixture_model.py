"""Deterministic model double for orchestration tests. Never measures model quality."""

import json
import re

from evals import span


class FixtureModel:
    def __init__(self):
        self.calls, self.usage, self.model_ids = 0, [], ["deterministic-test-double"]

    def generate(self, role, instruction, payload):
        with span(role, kind="llm", input={"instruction": instruction, "payload": payload}) as current:
            self.calls += 1
            if role == "extractor":
                text = payload["text"].lower()
                value = {"quantity": 5 if "three more" in text else 1,
                         "currency": "EUR" if "eur" in text else None}
                result = "The quantity is " + str(value["quantity"]) if "Explain your answer" in instruction else json.dumps(value)
            elif role == "answerer":
                documents = payload["documents"]
                value = {"days": int(re.search(r"(\d+) days", documents[0]["text"])[1]),
                         "answer": documents[0]["text"], "citations": [documents[0]["id"]]}
                result = json.dumps(value)
            elif role == "chatbot":
                text = " ".join(m["content"] for m in payload["messages"] if m["role"] == "user")
                name = re.search(r"My name is (\w+)", text)
                preferences = re.findall(r"\b(aisle|window) seat", text)
                result = json.dumps({"name": name[1] if name else None, "seat": preferences[-1] if preferences else None, "answer": "Preference summary"})
            elif role == "researcher.model":
                result = json.dumps({"claims": [{"text": source["text"], "source_id": source["id"]} for source in payload["sources"]]})
            elif role == "writer.model":
                result = json.dumps({"answer": " ".join(c["text"] for c in payload["claims"]),
                                     "citations": sorted({c["source_id"] for c in payload["claims"]})})
            elif role == "reviewer.model":
                result = json.dumps({"supported": True, "reason": "All draft facts occur in the source."})
            elif role == "refund.planner":
                text = payload["message"]
                result = json.dumps({"order_id": re.search(r"O-\d+", text)[0],
                                     "amount_cents": int(re.search(r"\$(\d+)", text)[1]) * 100})
            else:
                raise ValueError(f"Unexpected model role {role}")
            current.set_output({"text": result, "provider": "deterministic-test-double"})
            return result
