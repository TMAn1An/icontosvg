# Icon Sheet Studio

Local desktop application that converts a blurry raster icon sheet into
separate, named, clean, editable SVG icons. See
`ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md`-derived plan in `CLAUDE.md` for
full product scope; this is a from-scratch build with no dependency on any
earlier IconSheetStudio codebase.

## Status

Phase 1 vertical slice, verified end to end on the real 50-icon finance
sheet: upload -> preprocess -> detect crops -> heuristic name ->
centerline reconstruction with line/corner/arc/Bézier classification ->
clean SVG export -> render/compare in two independent renderers.
Line-icon mode only; filled and mixed modes are interface stubs
(`app/services/reconstruction/filled_mode.py`, `mixed_mode.py`). The UI
tabs exist as widget shells but are not yet wired to the pipeline — see
`PROJECT_MEMORY.md` for the full completed/stub breakdown and
`QUALITY_LOG.md` for measured results.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

Florence-2-based naming is optional and not required to run the app:

```bash
pip install -r requirements-naming.txt
```

## Run

```bash
python -m app.main
```

## Test

```bash
QT_QPA_PLATFORM=offscreen pytest
```

(`QT_QPA_PLATFORM=offscreen` is required even for non-UI tests, since
`app/domain/commands.py` builds on Qt's `QUndoCommand`. See `RUNBOOK.md`
for full Windows/Linux instructions and troubleshooting.)

## Further reading

- `PROJECT_MEMORY.md` — architecture, algorithms, requirements, defects,
  and how to safely continue the project.
- `RUNBOOK.md` — complete setup, run, and troubleshooting instructions.
- `DECISIONS.md` — dated record of significant technical decisions.
- `QUALITY_LOG.md` — measured results and visual-review findings.
- `CHANGELOG.md` — dated summary of completed milestones.
