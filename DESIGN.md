# Evals design system

## Surfaces

The existing landing page uses a dark monochrome palette, Geist/Geist Mono,
fine borders, restrained transparent surfaces and motion. Reports are product
surfaces: use quiet dark panels, semantic tables, and system fonts so exported
pages work offline without external dependencies.

## Report tokens

- Background: `oklch(0.145 0.005 260)`.
- Panel: `oklch(0.19 0.005 260)`.
- Primary text: `oklch(0.94 0.005 260)`.
- Muted text: `oklch(0.73 0.005 260)`.
- Borders: `oklch(0.32 0.005 260)`.
- Controls: consistent 8px corners and at least 40px height.
- Typography: system sans; monospace identifiers and hashes.

## Layout and behavior

Use a compact report header, provenance strip, category coverage table, filter
toolbar, and case table. Stack controls on narrow screens; contain horizontal
scroll inside tables. No page-load choreography. Keep focus visible and reduce
transitions when requested by the operating system.
