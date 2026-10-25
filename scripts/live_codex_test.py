"""Verify the installed Evals skill in a real, signed-in Codex CLI session."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


PROMPT = '''Use $evals, the installed Evals plugin, for this real plugin verification.
Work only in this current test project; do not edit the plugin or install dependencies.
support_app.py is a deterministic fixture representing the business layer of an AI support app.
The policy says returns are allowed through day 30 inclusive and rejected after day 30.
1. Load the Evals skill from the installed plugin, then inspect support_app.py.
2. Create evaluations/adapter.py and evaluations/suite.json that call the real handle_return function.
   Cover day 7, day 30, and day 31. Use stable IDs: day-7, day-30, day-31.
   Grade the actual returned decision. Do not change expected behavior to make tests pass.
3. Validate and run the suite with the installed plugin engine; save .evals/baseline.json.
4. Fix the application boundary bug, rerun the exact same suite, and save .evals/candidate.json.
5. Compare baseline and candidate; save the comparison output as .evals/comparison.json.
6. Explain what the skill did, the counts, and the bug found.
The fixture does not call an LLM; the Codex session is the live agent under test.
Do not use unrelated connectors, send messages, or alter Git configuration.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(".evals/codex-live"))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise ValueError(f"Choose a fresh test workspace: {workspace}")
    workspace.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1]
    shutil.copy2(source / "examples" / "support" / "support_app.py", workspace / "support_app.py")
    artifacts = workspace / ".evals"
    artifacts.mkdir()
    (artifacts / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    command = ["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "--skip-git-repo-check",
               "--json", "--cd", str(workspace), "--output-last-message", str(artifacts / "final.txt"), "-"]
    print(f"Starting live Codex verification in {workspace}", flush=True)
    with (artifacts / "session.jsonl").open("w", encoding="utf-8") as output:
        result = subprocess.run(command, input=PROMPT, text=True, encoding="utf-8",
                                stdout=output, stderr=subprocess.PIPE, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError(f"Codex exited {result.returncode}: {result.stderr[-4000:]}")
    baseline = json.loads((artifacts / "baseline.json").read_text(encoding="utf-8-sig"))
    candidate = json.loads((artifacts / "candidate.json").read_text(encoding="utf-8-sig"))
    comparison = json.loads((artifacts / "comparison.json").read_text(encoding="utf-8-sig"))
    if baseline["summary"]["failed"] != 1 or baseline["summary"]["error"] != 0:
        raise RuntimeError(f"Expected boundary failure in baseline: {baseline['summary']}")
    if candidate["summary"] != {"total": 3, "passed": 3, "failed": 0, "error": 0, "success_rate": 1.0}:
        raise RuntimeError(f"Candidate did not pass: {candidate['summary']}")
    if baseline["dataset_sha256"] != candidate["dataset_sha256"]:
        raise RuntimeError("Codex changed the dataset or grading criteria")
    if not comparison["improvements"] or comparison["regressions"]:
        raise RuntimeError("Expected an improvement without regressions")
    summary = {"status": "passed", "baseline": baseline["summary"], "candidate": candidate["summary"],
               "unchanged_dataset": True, "improvements": comparison["improvements"],
               "workspace": str(workspace)}
    (artifacts / "verification.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
