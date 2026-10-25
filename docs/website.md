# Landing page and GitHub Pages

The landing page lives in `website/`. It is plain HTML, CSS, and JavaScript with
self-hosted Geist fonts and Phosphor icons. No application server, npm install,
or build step is required to publish it. All asset URLs are relative so it works
under the repository's `/evals/` path.

## Preview

From the repository root:

```console
python -m http.server 4173 --bind 127.0.0.1 --directory website
```

Open `http://127.0.0.1:4173/`. Stop the server with Ctrl+C.

## Deploy when ready

1. Open the repository's **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open **Actions → Deploy landing page → Run workflow**, and choose `main`.
4. The workflow uploads only `website/` and publishes it to GitHub Pages.

The expected project URL is `https://vatsa10.github.io/evals/`. The workflow is
manual so committing framework changes does not publish a site unexpectedly.
It does not enable Pages or configure a custom domain on your behalf.

For automatic site releases later, add a `push` trigger for `main` and restrict
its paths to `website/**` and `.github/workflows/pages.yml`.

## Content and interactions

- Before/after replay uses the support-policy fixture from the live Codex test.
  It is explicitly labeled as an illustrative replay, not a live backend.
- Three workflow options explain the plugin, agent-assisted setup, and manual SDK.
- Setup tabs cover Codex, Claude Code, Python, and monitoring with copy controls.
- The page supports keyboard-operated tabs and navigation, reduced motion,
  reduced transparency, and an optional pause-motion control.
- Links to the framework and monitoring guides point to the source repository.

The visual direction uses a dark monochrome palette, frosted surfaces, a custom
optical-glass hero asset, a staged evaluation replay, and scroll reveals.
Design settings: variance 7, motion 7, density 4. Animation communicates hierarchy,
the evaluation sequence, or interaction feedback. System reduced motion overrides
decorative movement; the footer control can also pause motion.

The hero illustration was generated with the built-in image generation tool and
is saved as `website/assets/hero-glass.webp`. Its [source prompt](assets/hero-glass.prompt.txt)
is retained with the design notes. The WebP is a resized, alpha-preserving web
derivative; it is separate from the interactive HTML evaluation demo.

## Browser verification

With the local preview running and Playwright available in your development
environment, run:

```console
python scripts/check_website.py
```

The checks cover five viewport widths, the before/after replay, all setup and
workflow tabs, command copying, keyboard navigation, mobile navigation, reduced
motion, missing assets, browser errors, and horizontal overflow. Screenshots and
check results are saved in ignored `.evals/website-checks/`.

Local verification on 2026-10-25 passed at 1440, 1024, 768, 390, and 360 px.
Lighthouse 13.5 scored desktop 100/100/100/100 and simulated mobile
97/100/100/100 for performance/accessibility/best practices/SEO. Both profiles
reported zero layout shift and zero blocking time. These are local audit results,
not measurements of the eventual GitHub Pages deployment.

## Updating vendored assets

Assets are committed, so this is needed only when intentionally updating them:

```console
npm install --prefix .evals/site-deps --no-audit --no-fund @fontsource-variable/geist @fontsource-variable/geist-mono @phosphor-icons/core
python scripts/vendor_site_assets.py
```

Versions are recorded in `website/assets/third-party.json`. Retain the original
SIL Open Font License and MIT license files in `website/assets/licenses/`.
