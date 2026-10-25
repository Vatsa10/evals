"""Dependency-free, offline report snapshots and a portable browser view."""

from copy import deepcopy
import json
from pathlib import Path

from evals.artifacts import read_json, write_json
from evals.engine import compare_reports
from evals.reporting import compare_shared_reports, content_hash, summarize_report


def public_summary(report):
    result = deepcopy(summarize_report(report))
    # Configuration can contain project-private values. Publish its fingerprint,
    # never its values. Raw prompts, observations, verdict evidence and paths are
    # deliberately absent from the summary schema.
    original = result["provenance"]
    provenance = {key: original[key] for key in ("kind", "execution", "executed_at") if key in original}
    provenance["source"] = {key: original.get("source", {})[key] for key in
                            ("kind", "source_url", "evaluated_at", "label") if key in original.get("source", {})}
    provenance["adapter_reported"] = {key: original.get("adapter_reported", {})[key] for key in
                                      ("providers", "model_ids", "model_modes") if key in original.get("adapter_reported", {})}
    result["provenance"] = provenance
    environment = original.get("declared_environment", {})
    provenance["declared_environment"] = {key: environment[key] for key in ("provider", "model") if key in environment}
    if "configuration" in environment:
        provenance["configuration_sha256"] = content_hash(environment["configuration"])
    return result


def build_snapshot(report, baseline=None):
    runs = {"candidate": public_summary(report)}
    comparison = None
    if baseline is not None:
        runs["baseline"] = public_summary(baseline)
        # First validate both reports through the shared summary path. A strict
        # mismatch is displayed as exploratory coverage, never silently verified.
        try:
            comparison = dict(compare_reports(baseline, report), scope="full_dataset",
                              verification_eligible=report["mode"] == "live", shared_cases=[c["id"] for c in report["cases"]],
                              baseline_only=[], candidate_only=[], incompatible_cases=[])
        except ValueError:
            comparison = compare_shared_reports(baseline, report)
    payload = {"schema_version": 1, "runs": runs, "comparison": comparison,
               "privacy": "Summary metadata only. Raw inputs, outputs, traces and configuration values remain in the source reports."}
    return dict(payload, version=content_hash(payload))


def verify_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("version"), str):
        raise ValueError("Invalid report snapshot")
    payload = {k: v for k, v in snapshot.items() if k != "version"}
    if content_hash(payload) != snapshot["version"]:
        raise ValueError("Snapshot content hash mismatch")
    if not isinstance(snapshot.get("runs"), dict) or "candidate" not in snapshot["runs"]:
        raise ValueError("Snapshot is missing its candidate summary")
    return snapshot["version"]


def build_report_site(report, output, baseline=None):
    snapshot = build_snapshot(report, baseline)
    verify_snapshot(snapshot)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    filename = f"report-{snapshot['version']}.json"
    path = output / filename
    if path.exists():
        if read_json(path) != snapshot:
            raise ValueError("Refusing to replace a different immutable snapshot")
    else:
        write_json(path, snapshot)
    template = (Path(__file__).parent / "assets" / "report.html").read_text(encoding="utf-8")
    embedded = json.dumps(snapshot, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    page = template.replace("__EVALS_SNAPSHOT_FILE__", filename).replace("__EVALS_SNAPSHOT__", embedded)
    (output / "index.html").write_text(page, encoding="utf-8")
    return {"index": str(output / "index.html"), "snapshot": str(path), "version": snapshot["version"]}
