"""Test the Evals improvement loop in a real Claude Code or Codex session."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


PROMPT = """Use the Evals skill to evaluate and improve this application's real behavior.
Work only in this test project; do not edit the plugin or install dependencies.
My goal: approve returns through day 30 inclusive, and reject returns after day 30.
Acceptance cases: day 7 approved, day 30 approved, day 31 rejected.
Use stable case IDs day-7, day-30, day-31 and call the actual handle_return function
from support_app.py through a thin adapter.
Complete the improvement loop in this coding-agent session. Use at most two
candidate evaluations, track support_app.py, and keep the improvement session
in .evals/improvement. Preserve acceptance criteria when fixing the application.
Finish with the framework's verification decision and explain the evidence.
This fixture is deterministic and does not call an LLM; your coding-agent session
is live. Do not use unrelated connectors, send messages, change Git configuration,
or make changes outside this project.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["codex", "claude"], default="codex")
    parser.add_argument("--plugin-dir", type=Path, help="Local plugin root for a Claude Code test")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.host == "claude" and args.plugin_dir is None:
        parser.error("--plugin-dir is required when testing Claude Code")
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise ValueError(f"Choose a fresh test workspace: {workspace}")
    workspace.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1]
    shutil.copy2(source / "examples" / "support" / "support_app.py", workspace / "support_app.py")
    artifacts = workspace / ".evals"
    artifacts.mkdir()
    (artifacts / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    if args.host == "codex":
        command = ["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "--skip-git-repo-check",
                   "--json", "--cd", str(workspace), "--output-last-message", str(artifacts / "final.txt"), "-"]
    else:
        command = ["claude", "--print", "--output-format", "json", "--no-session-persistence",
                   "--plugin-dir", str(args.plugin_dir.resolve()), "--permission-mode", "acceptEdits",
                   "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash(python *),PowerShell(python *)"]
    print(f"Starting live {args.host} improvement verification in {workspace}", flush=True)
    with (artifacts / "session.jsonl").open("w", encoding="utf-8") as output:
        result = subprocess.run(command, input=PROMPT, text=True, encoding="utf-8",
                                cwd=workspace, stdout=output, stderr=subprocess.PIPE, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError(f"{args.host} exited {result.returncode}: {result.stderr[-4000:]}")
    session = artifacts / "improvement"
    state = json.loads((session / "session.json").read_text(encoding="utf-8-sig"))
    decision = json.loads((session / "decision.json").read_text(encoding="utf-8-sig"))
    if decision["status"] != "verified_improvement":
        raise RuntimeError(f"Agent did not verify an improvement: {decision}")
    selected = next(a for a in state["attempts"] if a["number"] == decision["selected_attempt"])
    baseline = json.loads((session / state["baseline_reports"][0]).read_text(encoding="utf-8-sig"))
    candidate = json.loads((session / selected["reports"][0]).read_text(encoding="utf-8-sig"))
    if baseline["summary"]["failed"] != 1 or baseline["summary"]["error"] != 0:
        raise RuntimeError(f"Expected the boundary failure in baseline: {baseline['summary']}")
    if candidate["summary"] != {"total": 3, "passed": 3, "failed": 0, "error": 0, "success_rate": 1.0}:
        raise RuntimeError(f"Candidate did not pass: {candidate['summary']}")
    if baseline["dataset_sha256"] != candidate["dataset_sha256"]:
        raise RuntimeError("Agent changed the dataset or grading criteria")
    if state["max_attempts"] != 2 or len(state["attempts"]) > 2:
        raise RuntimeError("Agent ignored the requested attempt budget")
    if not decision["changed_files"]:
        raise RuntimeError("No application change was captured")
    summary = {"status": "passed", "host": args.host, "engine_version": state["engine_version"],
               "baseline": baseline["summary"], "candidate": candidate["summary"],
               "unchanged_dataset": True, "decision": decision["status"],
               "attempts": len(state["attempts"]), "workspace": str(workspace)}
    (artifacts / "verification.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
