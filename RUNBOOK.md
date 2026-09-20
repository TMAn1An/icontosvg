# Runbook

Operational guide for Icon Sheet Studio. For architecture and decision
history see `PROJECT_MEMORY.md`.

## Setup

Python 3.11+ required.

```bash
python -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

Florence-2 naming is **optional** and deliberately excluded from the core
requirements. The application runs fully without it:

```bash
pip install -r requirements-naming.txt   # only if you want Florence-2
```

### Linux/headless gotcha

PySide6 needs system GL/EGL libraries that slim containers omit. If
`import PySide6.QtGui` fails with `libEGL.so.1: cannot open shared object
file`:

```bash
apt-get update && apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1
```

Run anything Qt-dependent headless with `QT_QPA_PLATFORM=offscreen`.

## Run the application

```bash
python -m app.main
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest          # full suite
QT_QPA_PLATFORM=offscreen python -m pytest -q       # quiet
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_regularize.py -v
```

The offscreen platform is required because `app/domain/commands.py` builds
on `QUndoCommand`, so even domain tests import Qt.

## Regenerate synthetic fixtures

```bash
python -m tests.fixtures_gen.make_synthetic      # writes fixtures/synthetic/
```

`fixtures/synthetic/` is gitignored and rebuildable. Geometry unit tests
construct their own arrays inline and do not depend on it.

## Reference assets

- `fixtures/real/finance-icon-sheet.jpg` — the real 2048x1107 JPEG test
  sheet (5x10 grid, 50 line icons). See `fixtures/real/README.md`.
- `docs/reference/` — professional SVG construction examples and the
  annotated rough-tracing failure case. See `docs/reference/README.md`.

Note: `docs/reference/finance-icon-sheet.svg` is a branded 6000x2600
template with a different layout and scale from the JPEG. It is a
construction-quality reference, **not** a registered pixel ground truth,
and cannot be used for automated overlay scoring.

## Inspect the pipeline on the real sheet

There is no CLI yet (Phase 1 is a vertical slice; the UI tabs are still
placeholders). Drive the services directly:

```python
from app.services.preprocessing import load_sheet
from app.services.segmentation import detect_crops
from app.services.naming.heuristic import HeuristicNamingProvider
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.export import export_single_svg

sheet = load_sheet("fixtures/real/finance-icon-sheet.jpg")
crops = detect_crops(sheet.grayscale)            # expect exactly 50
crop = next(c for c in crops if c.id == "crop-31")

patch = sheet.grayscale[
    int(crop.y):int(crop.y + crop.height),
    int(crop.x):int(crop.x + crop.width),
]
name = HeuristicNamingProvider().suggest_name(
    sheet.rgb[int(crop.y):int(crop.y + crop.height), int(crop.x):int(crop.x + crop.width)]
)

strategy = LineModeStrategy()
document = strategy.reconstruct(patch)
print(strategy.diagnostics.regularization)        # snapped/aligned counts
print(export_single_svg(document, f"outputs/{name.value}.svg") or "valid")
```

`strategy.diagnostics` carries stroke width, branch counts, element counts
and the full `RegularizationStats` — the numbers reported in
`QUALITY_LOG.md`.

## Render an exported SVG

Two independent renderers; use both, since agreement between them is what
proves the file is genuinely valid rather than merely Qt-tolerant.

**Qt (the app's own renderer)** — see `render_svg` usage in the pipeline
snippet above; note `QImage` pads scanlines to 4-byte alignment, so use
`bytesPerLine()` as the row stride when converting to numpy, not
`width * 3`.

**Chromium (independent check)**

```bash
/opt/pw-browsers/chromium-1194/chrome-linux/chrome --headless --disable-gpu \
  --no-sandbox --hide-scrollbars --window-size=900,700 \
  --screenshot=outputs/check.png outputs/your-icon.svg
```

## Manual visual review gate

No slice is complete until its exported SVG has been rendered, opened, and
compared against the source crop by a human. `QualityReport.manual_review_status`
defaults to `"pending"` and nothing in the codebase may set it otherwise —
only a person who has actually looked at the output changes it.

Automated signals inform that review; they do not replace it. In
particular **SSIM against the source JPEG is not a valid arbiter for
geometry-straightening changes** — see `QUALITY_LOG.md`.

## Git

Development branch: `claude/happy-carson-lh8mr7`. Push with
`git push -u origin HEAD`. Do not force-push; do not push to `main`
without explicit owner approval.
