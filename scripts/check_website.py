"""Browser checks for the static landing page (requires Playwright for development)."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright


def reveal_page(page):
    height = page.evaluate("document.documentElement.scrollHeight")
    for position in range(0, height, 600):
        page.evaluate("y => window.scrollTo({top:y,behavior:'instant'})", position)
        page.wait_for_timeout(80)
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    page.wait_for_timeout(900)


def check(base_url, output, inspect_only=False):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (1440, 1024, 900, 768, 720, 390, 375, 360, 320):
            context = browser.new_context(viewport={"width": width, "height": 1000 if width > 720 else 844},
                                          permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            errors, failed_assets = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: failed_assets.append(response.url) if response.status >= 400 else None)
            page.goto(base_url, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(1000)
            overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
            if inspect_only:
                print(json.dumps({"width": width, "document_width": page.evaluate("document.documentElement.scrollWidth"),
                    "overflowing": page.evaluate("""Array.from(document.querySelectorAll('body *'))
                        .map(e => ({tag:e.tagName, cls:e.className?.baseVal ?? e.className,
                            x:Math.round(e.getBoundingClientRect().x), right:Math.round(e.getBoundingClientRect().right)}))
                        .filter(e => e.right > innerWidth + 1).slice(0,15)""")}, indent=2))
                page.screenshot(path=str(output / f"hero-{width}.png"))
                reveal_page(page)
                page.screenshot(path=str(output / f"full-{width}.png"), full_page=True)
                context.close()
                continue
            assert not overflow, f"Horizontal page overflow at {width}px"
            assert page.locator('.guide-tabs').get_attribute('aria-orientation') == ('horizontal' if width <= 1000 else 'vertical')
            for selector, minimum in [('body', 17), ('.hero-description', 18), ('.flow-step>p', 16),
                                      ('.way-tab small', 16), ('.guide-step>p', 16),
                                      ('.code-block pre', 15), ('.monitor-copy>p', 16),
                                      ('.faq-list summary', 18), ('.faq-list details>p', 16)]:
                sizes = page.locator(selector).evaluate_all("elements => elements.map(e => parseFloat(getComputedStyle(e).fontSize))")
                assert sizes and min(sizes) >= minimum, f"Unreadable {selector} at {width}px: {sizes}"
            page.locator('[data-demo-version="before"]').click()
            assert page.locator('#demo-score').inner_text().startswith('2'), "Before-fix example is wrong"
            page.locator('[data-demo-version="after"]').click()
            page.locator('#replay-demo').click()
            page.wait_for_function("document.querySelector('#run-state').textContent.includes('Run complete')")
            assert page.locator('#demo-score').inner_text().startswith('3'), "Replay did not finish"
            for guide, expected in [('claude', '/plugin marketplace add'), ('python', 'pip install'),
                                    ('monitoring', 'online policy'), ('codex', 'codex plugin marketplace add')]:
                page.locator(f'[data-guide="{guide}"]').click()
                assert expected in page.locator('#guide-steps').inner_text(), f"Wrong {guide} guide"
                assert page.locator(f'[data-guide="{guide}"]').get_attribute('aria-selected') == 'true'
            page.locator('.copy-button').first.click()
            page.wait_for_function("document.querySelector('#toast').classList.contains('is-visible')")
            clipboard = page.evaluate('navigator.clipboard.readText()')
            assert clipboard.replace('\r\n', '\n') == 'codex plugin marketplace add Vatsa10/evals\ncodex plugin add evals@evals', repr(clipboard)
            page.locator('[data-guide="codex"]').focus()
            page.keyboard.press('ArrowDown')
            assert page.locator('[data-guide="claude"]').get_attribute('aria-selected') == 'true'
            page.keyboard.press('End')
            assert page.locator('[data-guide="monitoring"]').get_attribute('aria-selected') == 'true'
            for way, expected in [('setup', 'Connect the real application'), ('sdk', 'from evals import'),
                                  ('agent', 'Let’s make the behavior measurable')]:
                page.locator(f'[data-way="{way}"]').click()
                assert expected in page.locator('#way-content').inner_text(), f"Wrong {way} preview"
            page.locator('.faq-list summary').first.click()
            assert page.locator('.faq-list details').first.get_attribute('open') is not None
            page.locator('#motion-toggle').click()
            assert page.locator('html').get_attribute('data-motion') == 'off'
            page.locator('#motion-toggle').click()
            assert page.locator('html').get_attribute('data-motion') == 'on'
            if width <= 720:
                page.locator('.menu-toggle').click()
                assert page.locator('#mobile-nav').is_visible()
                page.keyboard.press('Escape')
                assert page.locator('#mobile-nav').is_hidden()
                page.locator('.menu-toggle').click()
                page.locator('#mobile-nav a[href="#setup"]').click()
                assert page.locator('#mobile-nav').is_hidden()
            page.locator('[data-guide="codex"]').click()
            page.locator('.setup-shell').screenshot(path=str(output / f"setup-{width}.png"))
            reveal_page(page)
            page.screenshot(path=str(output / f"full-{width}.png"), full_page=True)
            page.screenshot(path=str(output / f"hero-{width}.png"))
            assert not errors, f"Browser errors at {width}px: {errors}"
            assert not failed_assets, f"Missing assets at {width}px: {failed_assets}"
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), f"Overflow after interactions at {width}px"
            for selector in ('.evaluation-window', '.way-preview', '.setup-shell', '.monitor-visual'):
                clipped = page.locator(selector).evaluate("e => e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1")
                assert not clipped, f"Panel clips content at {width}px: {selector}"
            caption_gap = page.evaluate("document.querySelector('.visual-caption').getBoundingClientRect().top - document.querySelector('.evaluation-window').getBoundingClientRect().bottom")
            assert caption_gap >= 8, f"Example caption overlaps its panel at {width}px"
            results.append({"viewport": width, "checks": "passed", "readable_typography": "passed"})
            context.close()
        if not inspect_only:
            context = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = context.new_page()
            page.goto(base_url, wait_until='networkidle')
            assert page.locator('html').get_attribute('data-motion') == 'off'
            assert page.locator('#motion-toggle').is_disabled()
            assert page.locator('.glass-sculpture').evaluate("e => getComputedStyle(e).animationName") == 'none'
            results.append({"reduced_motion": "passed"})
            context.close()
        browser.close()
    if not inspect_only:
        (output / 'checks.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4173/')
    parser.add_argument('--output', type=Path, default=Path('.evals/website-checks'))
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--serve', action='store_true', help='Serve the local website on a temporary loopback port')
    args = parser.parse_args()
    if args.serve:
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
        handler = partial(QuietHandler, directory=str(Path(__file__).resolve().parents[1] / 'website'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            check(f'http://127.0.0.1:{server.server_port}/', args.output, args.inspect)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    else:
        check(args.url, args.output, args.inspect)
