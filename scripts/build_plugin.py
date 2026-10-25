"""Build a clean Claude Code/Codex marketplace from an explicit file allowlist."""

import argparse
import json
from pathlib import Path
import shutil


def build(destination):
    source = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(f"Build destination already exists: {destination}")
    plugin = destination / "plugins" / "evals"
    plugin.mkdir(parents=True)
    for name in ("evals", "skills", "commands", ".claude-plugin", ".codex-plugin"):
        shutil.copytree(source / name, plugin / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "marketplace.json"))
    for name in ("plugin.json", "pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(source / name, plugin / name)
    (plugin / "scripts").mkdir()
    shutil.copy2(source / "scripts" / "evals.py", plugin / "scripts" / "evals.py")
    manifest = json.loads((source / ".claude-plugin" / "marketplace.json").read_text())
    manifest["plugins"][0]["source"] = "./plugins/evals"
    (destination / ".claude-plugin").mkdir()
    (destination / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", default="dist/evals-marketplace")
    args = parser.parse_args()
    print(build(args.destination))
