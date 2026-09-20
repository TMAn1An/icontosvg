# Icon Sheet Studio

Local desktop application that converts a blurry raster icon sheet into
separate, named, clean, editable SVG icons. See
`ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md`-derived plan in `CLAUDE.md` for
full product scope; this is a from-scratch build with no dependency on any
earlier IconSheetStudio codebase.

## Status

Phase 1, slice 1 in progress: upload -> preprocess -> detect one icon ->
editable crop -> heuristic name -> centerline reconstruction -> SVG export
-> render/compare. Line-icon mode only; filled and mixed modes are
interface stubs (`app/services/reconstruction/filled_mode.py`,
`mixed_mode.py`).

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
pytest
```
