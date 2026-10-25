"""Initial application implementation, to be replaced after evaluating its traces."""

import json
import uuid

from evals import span
from backend import ToolError, refund_request
from model import parse_object


def run(data, model, documents, url):
    flow = data["flow"]
    if flow == "llm":
        raw = model.generate("extractor", "Extract quantity and currency. Explain your answer.", data)
        return {"output": raw, "status": "answered"}
    if flow == "rag":
        with span("knowledge.search", kind="retriever", input={"topic": data["topic"]}) as current:
            ranking = data.get("ranked_ids", [d["id"] for d in documents])
            selected = sorted(documents, key=lambda d: ranking.index(d["id"]) if d["id"] in ranking else len(ranking))[:1]
            current.set_output(selected)
        answer = parse_object(model.generate("answerer", 'Return JSON {"days":integer,"answer":string,"citations":[document IDs]}. Answer from these documents.',
                                             {"question": data["question"], "documents": selected}))
        return {"output": json.dumps(answer), "result": answer, "status": "answered", "retrieval_context": selected}
    if flow == "chatbot":
        messages, replies = [], []
        for turn in data["turns"]:
            messages.append({"role": "user", "content": turn["message"]})
            answer = parse_object(model.generate("chatbot", 'Return JSON {"name":string or null,"seat":string or null,"answer":string}. Use the conversation; never guess absent preferences.',
                                                 {"messages": messages[-1:]}))
            messages.append({"role": "assistant", "content": json.dumps(answer)})
            replies.append(answer)
        return {"output": json.dumps(replies[-1]), "result": replies[-1], "messages": messages, "status": "answered"}
    if flow == "multi_agent":
        with span("researcher", kind="agent") as researcher:
            handoff = data.get("handoff") or parse_object(model.generate("researcher.model", 'Return JSON {"claims":[{"text":string,"source_id":string}]}. Extract supported facts from sources.', data))
            researcher.set_output(handoff)
        with span("writer", kind="agent") as writer:
            draft = parse_object(model.generate("writer.model", 'Return JSON {"answer":string,"citations":[source IDs]}. Draft from the supplied claims.', handoff))
            writer.set_output(draft)
        return {"output": json.dumps(draft), "result": draft, "status": "published", "handoff": handoff}
    if flow == "tools":
        plan = parse_object(model.generate("refund.planner", 'Return JSON {"order_id":string,"amount_cents":integer}. Extract the requested order and refund amount in cents.', {"message": data["message"]}))
        responses = []
        for _ in range(data.get("deliveries", 1)):
            for attempt in range(2):
                try:
                    result = refund_request(url, data["customer"], {**plan, "key": uuid.uuid4().hex})
                    break
                except ToolError:
                    result = {"status": "refunded"}
            responses.append(result)
        return {"output": json.dumps(responses[-1]), "status": "refunded", "result": responses[-1]}
    raise ValueError(f"Unknown flow: {flow}")
