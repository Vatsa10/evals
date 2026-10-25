"""Copy licensed fonts and Phosphor icons into the buildless website."""

import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


ICONS = "arrow-up-right arrow-right arrow-down arrow-clockwise github-logo terminal-window check check-circle x list fingerprint crosshair path seal-check code asterisk pulse info copy tree-structure chats-circle bell cube wrench sparkle database plus pause play circle-notch minus plugs-connected".split()


def vendor(packages, root):
    assets = root / "website" / "assets"
    fonts = assets / "fonts"
    licenses = assets / "licenses"
    fonts.mkdir(parents=True, exist_ok=True)
    licenses.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ("geist", "geist-mono"):
        package = packages / "@fontsource-variable" / name
        shutil.copy2(package / "files" / f"{name}-latin-wght-normal.woff2", fonts / f"{name}-latin.woff2")
        shutil.copy2(package / "LICENSE", licenses / f"{name}-OFL.txt")
        versions[f"@fontsource-variable/{name}"] = json.loads((package / "package.json").read_text())["version"]
    core = packages / "@phosphor-icons" / "core"
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    sprite = ET.Element(f"{{{namespace}}}svg")
    for name in ICONS:
        source = ET.parse(core / "assets" / "regular" / f"{name}.svg").getroot()
        symbol = ET.SubElement(sprite, f"{{{namespace}}}symbol", {"id": name, "viewBox": source.attrib["viewBox"], "fill": "currentColor"})
        symbol.extend(list(source))
    ET.ElementTree(sprite).write(assets / "icons.svg", encoding="utf-8", xml_declaration=False)
    shutil.copy2(core / "LICENSE", licenses / "phosphor-MIT.txt")
    versions["@phosphor-icons/core"] = json.loads((core / "package.json").read_text())["version"]
    (assets / "third-party.json").write_text(json.dumps({"packages": versions,
        "notes": "Self-hosted font subsets and selected unmodified icon paths. Original licenses are in licenses/. No external runtime requests."}, indent=2) + "\n", encoding="utf-8")
    print(f"Vendored two fonts and {len(ICONS)} icons")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=Path(".evals/site-deps/node_modules"))
    args = parser.parse_args()
    vendor(args.packages, Path(__file__).resolve().parents[1])
