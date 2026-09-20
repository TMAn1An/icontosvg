# Claude Code notes for Icon Sheet Studio

From-scratch build per `ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md` (supplied
separately, not committed here). Do not request, inspect, import, or reuse
any previous IconSheetStudio codebase.

## Architecture

- Single-language stack: PySide6 (UI + QUndoStack for undo/redo) and the
  same Python process for all CV/geometry/SVG work. No IPC boundary.
- `app/domain/` — plain dataclasses (`models.py`), undoable commands
  (`commands.py`), JSON project persistence (`project_store.py`).
- `app/services/` — one concern per module: preprocessing, segmentation,
  naming, geometry (centerline/primitives/curve_fit), reconstruction
  (line/filled/mixed strategies behind `ReconstructionStrategy`),
  svg_model (builder + validator), quality, export.
- `ReconstructionMode` (line/filled/mixed) is a first-class enum from the
  start. `filled_mode.py` and `mixed_mode.py` are interface stubs
  (`NotImplementedError`) — implement them by filling in those files, not
  by restructuring `base.py` or `svg_model.py`.
- Naming is provider-based (`naming/base.py`). `HeuristicNamingProvider` is
  the default and has zero ML dependencies. `Florence2NamingProvider`
  defers its `torch`/`transformers` imports into `__init__`, so importing
  the naming package never requires those packages. Never make Florence-2
  a hard requirement for the app to run.
- Line-mode reconstruction works from the skeletonized centerline only,
  never from raw edge contours — this is intentional so blurry outer edges
  are never traced into a filled shape. See
  `docs/reference/rough-conversion-reference.png` for the failure mode
  this avoids.

## Model / effort recommendation

- Sonnet, medium effort: UI, tests, refactoring, docs, straightforward
  service implementation.
- Opus, high effort: geometry reconstruction, centerline extraction, curve
  fitting, and quality-metric debugging.
- Haiku, low effort: simple mechanical edits only.

Before a major task, state current model/effort. If a change is needed,
stop and tell the user the exact browser action (model selector, then
effort toggle, in the Claude Code web session) rather than switching
without confirmation.

## Testing discipline

- Unit tests in `tests/unit/` cover geometry, SVG validity, crop editing,
  naming, and project save/load.
- `QualityReport.manual_review_status` defaults to `"pending"` and must
  never be set to anything else automatically — only a human, after
  actually viewing the rendered SVG, changes it.
- No slice is complete until its exported SVG has been rendered, opened in
  a browser, and visually compared against the source crop. Report defects
  honestly rather than treating a passing test suite as sufficient.

## Documentation discipline

Update project documentation as part of the same change, not as a
separate follow-up. After every meaningful milestone — a geometry
algorithm change, a new pipeline stage, a fixed defect, a UI tab wired to
real services, a dependency or architecture decision — update, in the
same commit or the very next one:

- **`PROJECT_MEMORY.md`** — the relevant numbered section(s); this file
  must stay a complete, current description of purpose, requirements,
  phase, features (working and stubbed), folder structure, architecture,
  pipeline, algorithms, defects, and how to safely continue the project.
- **`CHANGELOG.md`** — a dated entry (or an addition to the current
  `[Unreleased]`/latest entry) describing what changed, in date order.
- **`QUALITY_LOG.md`** — when the change touches geometry, reconstruction,
  or measured quality: which icons were tested, before/after numbers,
  visual-review findings, metric limitations encountered, remaining
  defects, and the commit hash.
- **`DECISIONS.md`** — when the change involved a real decision between
  alternatives: the problem, the chosen solution, alternatives
  considered, the reason, and the consequences/limitations, dated.

Never invent completed features in documentation, and never shorten or
delete existing useful content when updating these files — extend them.
Clearly label anything unfinished as a stub. Do not paste entire source
files into documentation; summarize and cite the module/file instead.
