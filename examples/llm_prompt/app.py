"""An actual LLM application using an existing signed-in Claude Code CLI.

This optional example runs model inference. It needs Claude Code authentication,
uses the configured default model, and can consume the account's normal allowance.
The Evals engine itself remains provider independent.
"""

import json
from pathlib import Path
import subprocess
import tempfile


def evaluate(request):
    instruction = Path(__file__).with_name("prompt.txt").read_text(encoding="utf-8")
    prompt = f"{instruction}\n\nCustomer request:\n{request['input']}"
    with tempfile.TemporaryDirectory(prefix="evals-model-") as workspace:
        response = subprocess.run(
            ["claude", "--print", "--output-format", "json", "--no-session-persistence",
             "--tools", "", "--disable-slash-commands"],
            input=prompt, text=True, encoding="utf-8", capture_output=True, cwd=workspace,
            timeout=150, check=False,
        )
    if response.returncode:
        raise RuntimeError(f"Claude model call exited {response.returncode}: {response.stderr[-1500:]}")
    envelope = json.loads(response.stdout)
    # Some Claude Code configurations include the message history in JSON mode.
    if isinstance(envelope, list):
        results = [item for item in envelope if isinstance(item, dict) and item.get("type") == "result"]
        if not results:
            raise RuntimeError("Claude JSON output did not contain a final result")
        envelope = results[-1]
    if not isinstance(envelope, dict):
        raise RuntimeError("Claude JSON output must contain a result object")
    if envelope.get("is_error"):
        raise RuntimeError(f"Claude model call failed: {envelope.get('result', 'unknown error')}")
    return {"output": envelope["result"], "usage": envelope.get("usage", {}),
            "metadata": {"provider": "claude-code-cli", "cost_usd": envelope.get("total_cost_usd")}}
