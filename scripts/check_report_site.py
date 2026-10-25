"""Exercise generated reports offline in Chromium. Development-only Playwright."""

import argparse
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright


def check(directory, output):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    html = (directory / "index.html").read_text(encoding="utf-8")
    filename = re.search(r'href="(report-[a-f0-9]{64}\.json)"', html)[1]
    snapshot = json.loads((directory / filename).read_text(encoding="utf-8"))
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (1360, 768, 390):
            context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
            page = context.new_page()
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http:", "https:")) else None)
            page.goto((directory / "index.html").as_uri())
            assert page.locator("#suite").inner_text() == snapshot["runs"]["candidate"]["suite"]
            assert page.locator("#cases tr").count() == len(snapshot["runs"]["candidate"]["cases"])
            assert not page.evaluate("Boolean(window.injected)")
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), f"Page overflow at {width}"
            if any(c["status"] == "untested" for c in snapshot["runs"]["candidate"]["coverage"]):
                assert "Untested" in page.locator("#coverage").inner_text()
            if "baseline" in snapshot["runs"]:
                page.select_option("#run", "baseline")
                assert page.locator("#cases tr").count() == len(snapshot["runs"]["baseline"]["cases"])
                page.select_option("#run", "candidate")
            page.select_option("#status", "failed")
            assert page.locator("#cases tr").count() == sum(c["status"] == "failed" for c in snapshot["runs"]["candidate"]["cases"])
            page.go_back()
            assert page.locator("#status").input_value() == "all", "Browser back did not restore filter state"
            page.fill("#query", "no-case-with-this-identifier")
            assert page.locator("#empty").is_visible()
            first = snapshot["runs"]["candidate"]["cases"][0]
            page.fill("#query", first["id"])
            page.select_option("#category", first["category"])
            assert page.locator("#cases tr").count() >= 1
            saved_url = page.url
            restored = context.new_page()
            restored.goto(saved_url)
            assert restored.locator("#query").input_value() == first["id"]
            assert restored.locator("#category").input_value() == first["category"]
            assert restored.locator("#cases tr").count() == page.locator("#cases tr").count()
            restored.close()
            page.fill("#query", "")
            page.select_option("#category", "all")
            page.locator(".category-button").first.click()
            assert page.locator("#category").input_value() != "all"
            page.go_back()
            assert page.locator("#category").input_value() == "all"
            if snapshot["comparison"]:
                page.select_option("#view", "shared")
                assert page.locator("#cases tr").count() == len(snapshot["comparison"]["shared_cases"])
                page.select_option("#view", "all")
                if snapshot["comparison"]["scope"] == "shared_cases":
                    assert "Exploratory overlap only" in page.locator("#comparison").inner_text()
            page.locator("#cases summary").first.focus()
            page.keyboard.press("Enter")
            assert page.locator("#cases details").first.get_attribute("open") is not None
            page.screenshot(path=str(output / f"report-{width}.png"), full_page=True)
            assert not errors, errors
            assert not external, external
            results.append({"width": width, "errors": errors, "external_requests": external, "url_state": True, "keyboard": True})
            context.close()
        browser.close()
    (output / "checks.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".evals/report-browser-checks"))
    args = parser.parse_args()
    check(args.directory, args.output)
