# Runbook

Operational guide for Icon Sheet Studio. For architecture and decision
history see `PROJECT_MEMORY.md` and `DECISIONS.md`. For measured results
see `QUALITY_LOG.md`.

Every section below gives both a **Linux/macOS (bash)** and a **Windows
(PowerShell)** command sequence. They are equivalent; use whichever
matches your platform.

## Repository

- Remote: `https://github.com/TMAn1An/icontosvg`
- Development branch: `claude/happy-carson-lh8mr7`
- `main` exists on the remote but is intentionally not kept in sync with
  every feature-branch commit — see "Git branch workflow" below.

## Clone the repository

**Linux/macOS**

```bash
git clone https://github.com/TMAn1An/icontosvg.git
cd icontosvg
git checkout claude/happy-carson-lh8mr7
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/TMAn1An/icontosvg.git
Set-Location icontosvg
git checkout claude/happy-carson-lh8mr7
```

## Create and activate a virtual environment

Python 3.11+ required.

**Linux/macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**Windows (PowerShell)**

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks the activation script with an execution-policy
error, run once (per user, not per project):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Install core dependencies

Installs PySide6, Pillow, numpy, opencv-python-headless, scikit-image,
scipy, lxml, svgpathtools — everything needed to run the application, no
ML dependencies.

**Linux/macOS**

```bash
pip install -r requirements.txt
```

**Windows (PowerShell)**

```powershell
pip install -r requirements.txt
```

## Install development dependencies

Adds `pytest` and `pytest-qt` on top of the core requirements. Use this
for day-to-day development instead of installing `requirements.txt`
separately.

**Linux/macOS**

```bash
pip install -r requirements-dev.txt
```

**Windows (PowerShell)**

```powershell
pip install -r requirements-dev.txt
```

## Install optional naming-model dependencies

Only needed to use `Florence2NamingProvider`
(`app/services/naming/florence2.py`, currently a stub — see
`PROJECT_MEMORY.md` §5). Adds `torch`, `transformers`, `einops`, `timm`.
**The application runs fully without this** — `HeuristicNamingProvider`
is the default naming provider and has zero ML dependencies.

**Linux/macOS**

```bash
pip install -r requirements-naming.txt
```

**Windows (PowerShell)**

```powershell
pip install -r requirements-naming.txt
```

Note: `torch` on Windows without a CUDA GPU installs the CPU-only wheel
automatically via this requirements file; no extra flags needed for a
CPU-only setup.

## Running the desktop application

**Linux/macOS**

```bash
python -m app.main
```

**Windows (PowerShell)**

```powershell
python -m app.main
```

**Current state:** this launches the PySide6 window with all five
workflow tabs (Import/Slices/Names/Reconstruct/Export), but the tabs are
**not yet wired to the pipeline services** (see `PROJECT_MEMORY.md` §5
and §24 item 4). To exercise the actual reconstruction pipeline today,
use "Processing the finance sheet from Python" below instead of the UI.

## Running tests

Requires `QT_QPA_PLATFORM=offscreen` even for non-UI tests, because
`app/domain/commands.py` builds on `QUndoCommand`, which needs a Qt
platform plugin to import.

**Linux/macOS**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest              # full suite (79 tests)
QT_QPA_PLATFORM=offscreen python -m pytest -q            # quiet
QT_QPA_PLATFORM=offscreen python -m pytest -v            # verbose, one line per test
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_curve_fit.py -v
```

**Windows (PowerShell)**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest              # full suite (79 tests)
python -m pytest -q            # quiet
python -m pytest -v            # verbose, one line per test
python -m pytest tests/unit/test_curve_fit.py -v
```

(On Windows, `QT_QPA_PLATFORM=offscreen` is usually unnecessary if you
have a real display, but setting it is harmless and keeps behavior
consistent with CI/headless runs.)

Expected result as of commit `f2b3f64`: **79 passed**.

## Generating fixtures

Regenerates `fixtures/synthetic/` (gitignored, rebuildable). No current
test depends on this — the geometry unit tests build their synthetic
arrays inline — but it is useful for manual inspection.

**Linux/macOS**

```bash
python -m tests.fixtures_gen.make_synthetic
ls fixtures/synthetic/
```

**Windows (PowerShell)**

```powershell
python -m tests.fixtures_gen.make_synthetic
Get-ChildItem fixtures\synthetic\
```

## Processing the finance sheet from Python

There is no CLI yet and the UI tabs are not wired (see above). Drive the
services directly. This exact sequence is what produced the numbers in
`QUALITY_LOG.md`.

**Linux/macOS and Windows (identical Python, run via `python` on either
platform — save as a `.py` file or paste into a REPL)**

```python
from app.services.preprocessing import load_sheet
from app.services.segmentation import detect_crops
from app.services.naming.heuristic import HeuristicNamingProvider
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.export import export_single_svg

sheet = load_sheet("fixtures/real/finance-icon-sheet.jpg")
crops = detect_crops(sheet.grayscale)            # expect exactly 50
print(f"detected {len(crops)} crops")

crop = next(c for c in crops if c.id == "crop-31")
patch = sheet.grayscale[
    int(crop.y):int(crop.y + crop.height),
    int(crop.x):int(crop.x + crop.width),
]
rgb_patch = sheet.rgb[
    int(crop.y):int(crop.y + crop.height),
    int(crop.x):int(crop.x + crop.width),
]

name = HeuristicNamingProvider().suggest_name(rgb_patch)
print(f"suggested name: {name.value}")

strategy = LineModeStrategy()
document = strategy.reconstruct(patch)
print(strategy.diagnostics.section_counts)        # {'line': N, 'arc': N, 'bezier': N}
print(strategy.diagnostics.regularization)        # snapped/aligned counts

problems = export_single_svg(document, f"outputs/{name.value}.svg")
print("valid" if not problems else problems)
```

To process **every** crop on the sheet (as used for the sheet-wide
numbers in `QUALITY_LOG.md`):

```python
from app.services.preprocessing import load_sheet
from app.services.segmentation import detect_crops
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.export import export_single_svg

sheet = load_sheet("fixtures/real/finance-icon-sheet.jpg")
crops = detect_crops(sheet.grayscale)

for crop in crops:
    patch = sheet.grayscale[
        int(crop.y):int(crop.y + crop.height),
        int(crop.x):int(crop.x + crop.width),
    ]
    strategy = LineModeStrategy()
    document = strategy.reconstruct(patch)
    export_single_svg(document, f"outputs/{crop.id}.svg")

print(f"exported {len(crops)} icons to outputs/")
```

`strategy.diagnostics` (a `LineModeDiagnostics`) carries stroke width,
branch counts, `section_counts` (line/arc/bezier), `corner_count`,
`joint_discontinuities`, `fit_errors`, and the full `RegularizationStats`
— the source of every number in `QUALITY_LOG.md`.

## Locating exported files

- **Single/batch SVG exports** produced by the snippets above land in
  `outputs/` at the repository root (relative to wherever you ran
  Python). This directory is gitignored (`outputs/*`, kept present via
  `outputs/.gitkeep`) — nothing here is meant to be committed.
- **The real test sheet** is at `fixtures/real/finance-icon-sheet.jpg`.
- **Reference SVGs** (professional construction examples, the
  rough-tracing failure image) are in `docs/reference/`.
- **Project JSON** (if you call `domain.project_store.save_project`)
  goes wherever you point it; no default location is assumed.

**Linux/macOS**

```bash
ls -la outputs/
```

**Windows (PowerShell)**

```powershell
Get-ChildItem outputs\
```

## Rendering an exported SVG for visual review

Two independent renderers; use both, since agreement between them is
what proves a file is genuinely valid rather than merely tolerated by
one parser. This is the "manual visual review gate" described below, not
optional polish.

**Qt (the application's own renderer)** — use from Python:

```python
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

svg_text = open("outputs/your-icon.svg", encoding="utf-8").read()
renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
image = QImage(400, 400, QImage.Format_RGB32)
image.fill(Qt.white)
painter = QPainter(image)
renderer.render(painter)
painter.end()
image.save("outputs/your-icon-qt-render.png")
```

Note: `QImage` pads scanlines to 4-byte alignment. If you convert to a
numpy array yourself, use `bytesPerLine()` as the row stride, not
`width * 3` — using the wrong stride silently corrupts the image on
non-multiple-of-4 widths.

**Chromium (independent check)** — headless screenshot from the shell:

**Linux/macOS**

```bash
/opt/pw-browsers/chromium-1194/chrome-linux/chrome --headless --disable-gpu \
  --no-sandbox --hide-scrollbars --window-size=900,700 \
  --screenshot=outputs/your-icon-chromium.png outputs/your-icon.svg
```

(This exact Chromium path is specific to this project's sandboxed
container. On a normal machine, replace it with your installed Chrome/
Chromium binary path, or `chromium --headless ...` / `chrome --headless
...` if it is on `PATH`.)

**Windows (PowerShell)**

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless --disable-gpu `
  --hide-scrollbars --window-size=900,700 `
  --screenshot="outputs\your-icon-chromium.png" "outputs\your-icon.svg"
```

## Manual visual review gate

No slice is complete until its exported SVG has been rendered, opened,
and compared against the source crop by a human. `QualityReport.
manual_review_status` defaults to `"pending"` and nothing in the
codebase may set it otherwise — only a person who has actually looked at
the output changes it (see `PROJECT_MEMORY.md` §4 invariant, §19 for the
review history so far).

Automated signals inform that review; they do not replace it. In
particular **SSIM against the source JPEG is not a valid arbiter for
geometry-straightening or curve-classification changes** — see
`QUALITY_LOG.md` and `DECISIONS.md` for two independent instances of this
being observed and confirmed.

## Fixing common Qt, EGL, and OpenGL errors

### `ImportError: libEGL.so.1: cannot open shared object file` (Linux)

PySide6 needs system GL/EGL libraries that slim/headless containers
omit.

```bash
apt-get update
apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1
```

If `apt-get update` reports failures for unrelated third-party PPAs,
those can be ignored as long as the main Ubuntu/Debian archive entries
succeed — check for `Setting up libegl1:amd64 ...` (or similar) in the
install output.

### Any Qt widget/application code fails with "could not connect to display" or similar (Linux, no display attached)

Run with the offscreen platform plugin:

```bash
export QT_QPA_PLATFORM=offscreen
python -m app.main     # or pytest, etc.
```

### `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` (Linux)

Usually the same root cause as the EGL error above (missing system
libraries) or a missing display. Set `QT_QPA_PLATFORM=offscreen` for
headless use, or ensure `libxkbcommon-x11-0` and X11 libraries are
installed for a real display.

### Windows: `ImportError: DLL load failed while importing QtCore`

Almost always a missing Visual C++ Redistributable. Install the latest
**Microsoft Visual C++ Redistributable (x64)** from Microsoft, then
retry. Also confirm you are running the same Python architecture (64-bit)
as the installed PySide6 wheel — `python -c "import platform;
print(platform.architecture())"` should report `64bit`.

### Windows: PowerShell venv activation blocked

```
File ...\Activate.ps1 cannot be loaded because running scripts is
disabled on this system.
```

Fix (per user, one-time):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### macOS: PySide6 fails to import with a codesigning/Gatekeeper error

Reinstall PySide6 from PyPI inside the virtualenv (`pip install
--force-reinstall PySide6`) rather than using a system-wide copy; mixing
a Homebrew Qt with the PyPI PySide6 wheel is a common source of this.

### Tests hang or crash instead of failing cleanly (any platform)

Confirm `QT_QPA_PLATFORM=offscreen` is set before running pytest — a
missing platform plugin can manifest as a hang waiting for a display
rather than a clean import error, depending on the Qt version.

## Git branch workflow

- Development happens on **`claude/happy-carson-lh8mr7`**.
- `main` is intentionally not kept fast-forwarded to every feature-branch
  commit — advancing it requires the repository owner's explicit
  approval in the current conversation. Do not merge or force-push into
  `main` without that.
- Push the feature branch normally:

  **Linux/macOS and Windows (identical)**

  ```bash
  git push origin claude/happy-carson-lh8mr7
  ```

- Never force-push. Never delete a branch. Never push directly to `main`
  without explicit approval.
- Per the rule in `CLAUDE.md`, update `PROJECT_MEMORY.md`,
  `CHANGELOG.md`, and (when a real design decision was made)
  `DECISIONS.md` in the same commit or the very next one after any
  meaningful milestone.
