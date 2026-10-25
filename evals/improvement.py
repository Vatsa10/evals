"""An auditable evaluate, diagnose, change, and verify loop for coding agents."""

from contextlib import contextmanager
import difflib
import hashlib
import json
import os
from pathlib import Path
import uuid

from evals import __version__
from evals.artifacts import read_json, write_json
from evals.engine import compare_reports, digest, load_suite, run_suite
from evals.monitoring import save_run
from evals.storage import Store, utc_now


def file_hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def engine_hash():
    return digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def source_hashes(paths):
    return {path: file_hash(path) for path in paths}


@contextmanager
def session_lock(directory):
    path = directory / ".lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"Improvement session is busy: {directory}") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def grading_files(suite, root):
    paths = []
    for case in suite["cases"]:
        for grader in case["graders"]:
            if grader["type"] != "custom":
                continue
            adapter = grader["adapter"]
            if adapter["type"] == "python":
                paths.append((root / adapter["path"]).resolve())
            else:
                paths.extend((root / arg).resolve() for arg in adapter["argv"] if (root / arg).is_file())
    return paths


def target_files(suite, root):
    adapter = suite["target"]
    if adapter["type"] == "python":
        return [(root / adapter["path"]).resolve()]
    return [(root / arg).resolve() for arg in adapter["argv"] if (root / arg).is_file()]


def snapshot(paths, directory, label):
    folder = directory / "sources" / label
    folder.mkdir(parents=True, exist_ok=True)
    hashes = source_hashes(paths)
    for index, path in enumerate(paths):
        if hashes[path] is not None:
            (folder / f"{index}.source").write_bytes(Path(path).read_bytes())
    return hashes


def changed_sources(state, directory, label, hashes):
    changes = []
    for index, path in enumerate(state["tracked_files"]):
        before_hash, after_hash = state["baseline_sources"][path], hashes[path]
        if before_hash == after_hash:
            continue
        before = directory / "sources" / "baseline" / f"{index}.source"
        after = directory / "sources" / label / f"{index}.source"
        old = before.read_text(encoding="utf-8", errors="replace").splitlines(True) if before.is_file() else []
        new = after.read_text(encoding="utf-8", errors="replace").splitlines(True) if after.is_file() else []
        changes.append({"path": path, "before_sha256": before_hash, "after_sha256": after_hash,
                        "diff": "".join(difflib.unified_diff(old, new, fromfile=f"baseline/{Path(path).name}",
                                                            tofile=f"candidate/{Path(path).name}"))})
    return changes


def ensure_contract(state):
    if state["engine_sha256"] != engine_hash():
        raise ValueError("Evaluation engine changed. Start a new baseline before verifying improvements.")
    changed = [path for path, expected in state["locked_files"].items() if file_hash(path) != expected]
    if changed:
        raise ValueError("Evaluation contract changed; restore it or start a new session: " + ", ".join(changed))


def evaluate_specs(state, directory, label):
    reports = []
    store = Store(state["store"])
    for index, spec in enumerate(state["suites"]):
        report = run_suite(spec["suite"], Path(spec["root"]))
        report["improvement_session_id"] = state["id"]
        report["improvement_phase"] = label
        report = save_run(store, report)
        filename = f"{label}-{index}.json"
        write_json(directory / filename, report)
        reports.append(filename)
    return reports


def write_brief(state, directory):
    latest = next((a for a in reversed(state["attempts"]) if a["status"] == "completed"), None)
    decision = read_json(directory / "decision.json") if state["status"] != "active" else None
    if decision and decision["selected_attempt"] is not None:
        latest = next(a for a in state["attempts"] if a["number"] == decision["selected_attempt"])
    report_files = latest["reports"] if latest else state["baseline_reports"]
    lines = ["# Evaluation and improvement brief", "", f"Goal: {state['goal']}", "",
             f"Session: {directory}", f"Attempts: {len(state['attempts'])}/{state['max_attempts']}",
             f"State: {state['status']}", "", "## Measured behavior", ""]
    failures = 0
    for filename in report_files:
        report = read_json(directory / filename)
        counts = report["summary"]
        lines += [f"### {report['suite']}", "",
                  f"{counts['passed']} passed; {counts['failed']} failed; {counts['error']} errors.",
                  f"Full evidence: {filename}", ""]
        for trial in report["trials"]:
            if trial["status"] == "passed" or failures >= 12:
                continue
            failures += 1
            detail = {"case_id": trial["case_id"], "trial": trial["trial"], "status": trial["status"],
                      "error": trial.get("error"), "graders": trial["graders"],
                      "observation": trial.get("observation")}
            lines += ["```json", json.dumps(detail, indent=2, ensure_ascii=False)[:6000], "```", ""]
    if latest:
        lines += ["## Selected attempt" if decision else "## Latest attempt", "", f"Hypothesis: {latest['hypothesis']}",
                  f"Ready to verify: {latest['ready']}", f"Reason: {latest['reason']}", ""]
    lines += ["## Next action", "",
              "Read the evidence and identify a failure in the real application's prompts, retrieval, tools, or code.",
              "Make one bounded application change and explain the hypothesis. Preserve the cases, references, graders, and budgets.",
              "Never replace the application with expected answers or a demo. Fix missing evidence or infrastructure errors explicitly.",
              "Run the following from the project, using the installed plugin entrypoint when the CLI is not installed:", "",
              "```text", f'evals improve check "{directory}" --hypothesis "Explain the application change"',
              f'evals improve finish "{directory}"', "```", "",
              "A verified result applies to the frozen suites and observed trials. It is not proof of universal model quality.",
              "Human review decides whether to adopt or deploy the application changes.", ""]
    (directory / "brief.md").write_text("\n".join(lines), encoding="utf-8")


def start(suite_path, *, goal, track, max_attempts=3, regression_suites=(), lock=(), trials=None,
          output=None, store=None, allow_partial=False):
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("An improvement session requires the user's goal")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if not track:
        raise ValueError("Track at least one application or prompt file")
    suites, locks, tracked = [], [], [Path(path).resolve() for path in track]
    for index, path in enumerate([suite_path, *regression_suites]):
        suite, root = load_suite(path)
        if suite.get("mode", "live") != "live":
            raise ValueError("Improvement requires live suites, not regraded captures")
        if trials is not None:
            suite["trials"] = trials
        # Validate trial overrides before allocating a session or calling a target.
        from evals.engine import validate_suite
        validate_suite(suite, root)
        suites.append({"path": str(Path(path).resolve()), "root": str(root), "suite": suite,
                       "role": "primary" if index == 0 else "regression"})
        locks.extend([Path(path).resolve(), *grading_files(suite, root)])
        tracked.extend(target_files(suite, root))
    locks.extend(Path(path).resolve() for path in lock)
    for path in [*tracked, *locks]:
        if not path.is_file():
            raise ValueError(f"Session input file does not exist: {path}")
    tracked, locks = sorted(set(map(str, tracked))), sorted(set(map(str, locks)))
    if set(tracked) & set(locks):
        raise ValueError("Keep application files separate from frozen grading files")
    session_id = uuid.uuid4().hex[:12]
    directory = Path(output or Path(".evals/improvements") / session_id).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    state = {"schema_version": 1, "engine_version": __version__, "engine_sha256": engine_hash(),
             "id": session_id, "created_at": utc_now(), "status": "active", "goal": goal.strip(),
             "max_attempts": max_attempts, "allow_partial": allow_partial, "suites": suites,
             "locked_files": source_hashes(locks), "tracked_files": tracked,
             "attempts": [], "store": str(Store(store).path)}
    with session_lock(directory):
        state["baseline_sources"] = snapshot(tracked, directory, "baseline")
        state["baseline_reports"] = evaluate_specs(state, directory, "baseline")
        ensure_contract(state)
        if source_hashes(tracked) != state["baseline_sources"]:
            raise ValueError("Application files changed during the baseline; start a fresh session")
        write_json(directory / "session.json", state)
        write_brief(state, directory)
    return directory, state


def load_session(directory):
    directory = Path(directory).resolve()
    state = read_json(directory / "session.json")
    if state.get("schema_version") != 1:
        raise ValueError("Unsupported improvement session schema")
    return directory, state


def check(directory, *, hypothesis):
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("Describe the change and why it should improve the failure")
    directory = Path(directory).resolve()
    with session_lock(directory):
        _, state = load_session(directory)
        ensure_contract(state)
        if state["status"] != "active":
            raise ValueError("This improvement session is already closed")
        if len(state["attempts"]) >= state["max_attempts"]:
            raise ValueError("Improvement attempt budget exhausted; review the results before starting another session")
        index = len(state["attempts"]) + 1
        label = f"attempt-{index}"
        sources = snapshot(state["tracked_files"], directory, label)
        attempt = {"number": index, "hypothesis": hypothesis.strip(), "started_at": utc_now(),
                   "status": "running", "sources": sources}
        state["attempts"].append(attempt)
        write_json(directory / "session.json", state)
        try:
            attempt["reports"] = evaluate_specs(state, directory, label)
            ensure_contract(state)
            if source_hashes(state["tracked_files"]) != sources:
                raise ValueError("Application changed during evaluation; this attempt cannot verify it")
            comparisons = [compare_reports(read_json(directory / before), read_json(directory / after))
                           for before, after in zip(state["baseline_reports"], attempt["reports"])]
            errors = any(c["candidate_errors"] for c in comparisons)
            regressions = any(c["regressions"] or c["metric_regressions"] for c in comparisons)
            improved = any(c["improvements"] or c["metric_improvements"] for c in comparisons)
            primary = read_json(directory / attempt["reports"][0])
            all_pass = not primary["summary"]["failed"] and not primary["summary"]["error"]
            changed = changed_sources(state, directory, label, sources)
            ready = not errors and not regressions and improved and bool(changed) and (all_pass or state["allow_partial"])
            reason = ("Evaluation errors remain" if errors else "A case or grader regressed" if regressions else
                      "No measurable improvement" if not improved else "No tracked application change" if not changed else
                      "Primary acceptance checks still fail" if not all_pass and not state["allow_partial"] else
                      "Observed improvement with unchanged criteria and no detected regressions")
            attempt.update(status="completed", finished_at=utc_now(), comparisons=comparisons,
                           changed_files=changed, ready=ready, improved=improved, reason=reason)
            write_json(directory / f"{label}-comparison.json", comparisons)
        except BaseException as exc:
            attempt.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "error",
                           ready=False, reason=f"{type(exc).__name__}: {exc}")
            write_json(directory / "session.json", state)
            write_brief(state, directory)
            raise
        write_json(directory / "session.json", state)
        write_brief(state, directory)
        return attempt


def finish(directory):
    directory = Path(directory).resolve()
    with session_lock(directory):
        _, state = load_session(directory)
        ensure_contract(state)
        if state["status"] != "active":
            return read_json(directory / "decision.json")
        current = source_hashes(state["tracked_files"])
        selected = next((a for a in reversed(state["attempts"]) if a.get("ready") and a["sources"] == current), None)
        baseline_passes = all(not read_json(directory / p)["summary"]["failed"] and
                              not read_json(directory / p)["summary"]["error"] for p in state["baseline_reports"])
        status = "verified_improvement" if selected else (
            "baseline_satisfied" if baseline_passes and current == state["baseline_sources"] else "not_verified")
        decision = {"session_id": state["id"], "goal": state["goal"], "status": status,
                    "selected_attempt": selected["number"] if selected else None,
                    "reason": selected["reason"] if selected else (
                        "The original application already passed the acceptance checks" if status == "baseline_satisfied" else
                        "Current application files do not match a verified candidate; inspect brief.md and run another check"),
                    "reports": selected["reports"] if selected else state["baseline_reports"],
                    "changed_files": selected["changed_files"] if selected else [],
                    "verified_at": utc_now(),
                    "scope": "Frozen suites and observed trials only; human review decides adoption or deployment"}
        write_json(directory / "decision.json", decision)
        if status != "not_verified":
            state["status"] = status
            write_json(directory / "session.json", state)
        write_brief(state, directory)
        return decision
