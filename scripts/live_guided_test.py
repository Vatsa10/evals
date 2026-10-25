"""Verify native commands/skills through missing requirements and a resumed fix."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.briefs import load, readiness


def invoke(host, workspace, phase, prompt, plugin):
    artifacts = workspace / ".evals"
    artifacts.mkdir(exist_ok=True)
    (artifacts / f"{phase}-prompt.txt").write_text(prompt, encoding="utf-8")
    if host == "codex":
        command = ["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "--skip-git-repo-check",
                   "--json", "--cd", str(workspace), "--output-last-message", str(artifacts / f"{phase}-final.txt"), "-"]
    else:
        command = ["claude", "--print", "--output-format", "json", "--no-session-persistence",
                   "--plugin-dir", str(plugin.resolve()), "--permission-mode", "acceptEdits",
                   "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash(python *),PowerShell(python *)"]
    print(f"{host}: {phase}", flush=True)
    with (artifacts / f"{phase}-session.jsonl").open("w", encoding="utf-8") as output:
        result = subprocess.run(command, input=prompt, text=True, encoding="utf-8", cwd=workspace,
                                stdout=output, stderr=subprocess.PIPE, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError(f"{host} {phase} exited {result.returncode}: {result.stderr[-2000:]}")


def run(host, workspace, plugin=None):
    workspace = workspace.resolve()
    if workspace.exists():
        raise ValueError("Use a fresh test workspace")
    if host == "claude" and plugin is None:
        raise ValueError("Claude tests require --plugin-dir")
    workspace.mkdir(parents=True)
    source = (ROOT / "examples/support/support_app.py").read_text(encoding="utf-8")
    source = source.replace("    if days_since_delivery >= 30:",
        '    from pathlib import Path\n    with Path(__file__).with_name("target_calls.txt").open("a") as log:\n        log.write("call\\n")\n    if days_since_delivery >= 30:')
    app = workspace / "support_app.py"
    app.write_text(source, encoding="utf-8")
    original = hashlib.sha256(app.read_bytes()).hexdigest()
    start_command = "$evals-start" if host == "codex" else "/evals:start"
    prompt = start_command + " " + (
        "Help me set up evals for this project. I have not decided the exact target, goal or success criteria yet. "
        "Inspect what is here, save a draft at evaluations/brief.json, and ask me what you need before executing evaluations. "
        "Work only in this project; do not change the plugin, dependencies or Git configuration. Do not use unrelated connectors.")
    invoke(host, workspace, "intake", prompt, plugin)
    brief_path = workspace / "evaluations/brief.json"
    brief, _ = load(brief_path)
    assert readiness(brief)["ready"] is False, "The agent invented missing requirements"
    assert not (workspace / "target_calls.txt").exists(), "The agent ran the target before the requirements arrived"
    assert hashlib.sha256(app.read_bytes()).hexdigest() == original, "The agent changed the application during intake"
    improve_command = "$evals-improve" if host == "codex" else "/evals:improve"
    answers = improve_command + " " + (
        "Resume evaluations/brief.json. My target is support_app.py:handle_return. "
        "I want you to evaluate AND fix the return boundary: day 7 approved, day 30 approved, day 31 rejected. "
        "Use these three cases with IDs day-7, day-30 and day-31 and a thin adapter calling the actual function. "
        "You may change support_app.py, keeping its target_calls.txt instrumentation. You may add integration/evaluation files. "
        "This is a deterministic fixture, with no target LLM provider. It runs locally; side effects are sandboxed in this workspace. "
        "Use one trial, at most two candidate attempts, and at most nine framework target calls. "
        "Save the guided workflow in .evals/guided. Complete the fix, unchanged-criteria verification and review report. "
        "Do not remove instrumentation or modify the plugin/engine. Do not install dependencies, use unrelated connectors, send messages, or write outside this project.")
    invoke(host, workspace, "execution", answers, plugin)
    return verify(host, workspace)


def verify(host, workspace):
    workspace = workspace.resolve()
    brief_path = workspace / "evaluations/brief.json"
    workflow = json.loads((workspace / ".evals/guided/workflow.json").read_text(encoding="utf-8-sig"))
    sessions = []
    for path in (workspace / ".evals/guided").rglob("session.json"):
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if "baseline_reports" in value and "attempts" in value:
            sessions.append((path.parent, value))
    verified = [(path, state) for path, state in sessions
                if (path / "decision.json").exists()
                and json.loads((path / "decision.json").read_text(encoding="utf-8-sig"))["status"] == "verified_improvement"]
    assert len(verified) == 1, "Expected one verified final session, including any documented integration recovery"
    session, state = verified[0]
    decision = json.loads((session / "decision.json").read_text(encoding="utf-8-sig"))
    assert decision["status"] == "verified_improvement", decision
    selected = next(a for a in state["attempts"] if a["number"] == decision["selected_attempt"])
    before = json.loads((session / state["baseline_reports"][0]).read_text(encoding="utf-8-sig"))
    after = json.loads((session / selected["reports"][0]).read_text(encoding="utf-8-sig"))
    assert before["summary"]["passed"] == 2 and before["summary"]["failed"] == 1 and before["summary"]["error"] == 0
    assert after["summary"]["passed"] == 3 and after["summary"]["error"] == 0
    assert before["dataset_sha256"] == after["dataset_sha256"]
    assert {c["id"] for c in before["cases"]} == {"day-7", "day-30", "day-31"}
    assert all(c["trials"] == 1 for c in after["cases"])
    assert workflow["max_target_calls"] == 9
    assert sum(len(s["attempts"]) for _, s in sessions) <= 2
    active_workflow = json.loads((session.parent / "workflow.json").read_text(encoding="utf-8-sig"))
    assert active_workflow["brief"] in state["locked_files"]
    original_state = json.loads((Path(workflow["session"]) / "session.json").read_text(encoding="utf-8-sig"))
    assert hashlib.sha256(brief_path.read_bytes()).hexdigest() == original_state["locked_files"][str(brief_path)]
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected for path, expected in state["locked_files"].items())
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected for path, expected in selected["sources"].items())
    calls = len((workspace / "target_calls.txt").read_text().splitlines())
    assert 6 <= calls <= 9, f"Unexpected target calls: {calls}"
    framework_calls = 0
    for path, value in sessions:
        report_names = [*value["baseline_reports"], *[name for attempt in value["attempts"] for name in attempt.get("reports", [])]]
        framework_calls += sum(len(json.loads((path / name).read_text(encoding="utf-8-sig"))["trials"]) for name in report_names)
    assert calls <= framework_calls <= 9, "Aggregate framework call budget exceeded across recovery sessions"
    result = {"host": host, "status": "passed", "draft_waited_for_answers": True,
              "baseline": before["summary"], "candidate": after["summary"], "target_calls": calls,
              "decision": decision["status"], "brief_locked": True, "engine_version": state["engine_version"],
              "integration_recovery": len(sessions) > 1, "active_workflow": str(session.parent)}
    result["framework_target_calls"] = framework_calls
    (workspace / ".evals/verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["codex", "claude"], required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--plugin-dir", type=Path)
    parser.add_argument("--verify-existing", action="store_true", help="Recheck saved live-run evidence without new agent/target calls")
    args = parser.parse_args()
    if args.verify_existing:
        verify(args.host, args.workspace)
    else:
        run(args.host, args.workspace, args.plugin_dir)
