# Project memory

Durable context for Icon Sheet Studio: what this project is, what exists,
what was decided, and why. Read this before changing the geometry
pipeline. For day-to-day commands see `RUNBOOK.md`; for dated decision
records see `DECISIONS.md`; for dated numeric results see
`QUALITY_LOG.md`; for a chronological summary see `CHANGELOG.md`.

## Hard boundary

This is a from-scratch build driven by
`ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md` (supplied separately, not
committed). **No previous IconSheetStudio codebase was requested,
inspected, imported, or reused**, and none may be. Only the written
specification and the supplied reference assets informed the design.

## 1. Project purpose and target output quality

Icon Sheet Studio is a local desktop application that converts a blurry
raster icon sheet (JPG/PNG/WebP) into separate, named, clean, editable
SVG icons. The target is **professional geometric reconstruction** — true
SVG strokes and primitives, not a pixel trace.

A basic image trace with hundreds of noisy anchors is explicitly **not
acceptable**. `docs/reference/rough-conversion-reference.png` documents
the failure mode being avoided: tracing both edges of a blurry stroke
produces comb-like double outlines. `docs/reference/main1-3.svg` and
`docs/reference/finance-icon-sheet.svg` are the professional-quality bar
this project is held to (minimal anchors, true primitives, stable
strokes) — used as qualitative references, not automated golden files.

## 2. Full product requirements

From the supplied specification (`ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md`),
the application must:

1. import JPG, JPEG, PNG, or WebP icon sheets;
2. detect and separate every icon, including icons made from several
   disconnected parts;
3. suggest a short name for every icon using a local vision-language
   model, kept behind a swappable interface;
4. allow the user to correct every name, with manual edits protected from
   automatic overwrite;
5. analyze lines, curves, circles, corners, gaps, intersections, symmetry
   and stroke structure;
6. rebuild the icon with clean SVG geometry;
7. use true SVG strokes for suitable line icons;
8. provide stroke and color controls (width, color, cap, join, miter
   limit; stored in viewBox units, not screen pixels);
9. compare the rendered SVG with the original raster crop;
10. allow manual correction when automatic reconstruction is uncertain;
11. export each icon separately and export all icons as a ZIP.

Workflow tabs specified: Import, Slices, Names, Reconstruct, Editor,
Quality, Export. Development phases specified: Phase 1 (reliable MVP),
Phase 2 (professional reconstruction: stronger fitting, symmetry, Bézier
tangent continuity, anchor reduction), Phase 3 (visual editor: anchor and
handle editing, undo/redo), Phase 4 (commercial readiness: batch
processing, packaging).

Must not: depend on a hosted/paid API for naming (a local provider is
required, with an optional API left as a future extension point); embed
raster images in production SVGs; discard a detected region without
user-visible feedback; claim "professional quality" from a single
automated score.

## 3. Current development phase

**Phase 1, vertical slice.** Not the full Phase 1 feature set — a single
thread has been driven end to end and geometry quality has been
iterated on twice beyond the original slice:

```
upload -> preprocess -> detect crops -> heuristic name
  -> centerline reconstruction (line mode only)
  -> curve/corner classification -> clean SVG -> render/compare -> export
```

This has been run against the real 50-icon finance sheet, not only
synthetic fixtures, and every stage has measured evidence in
`QUALITY_LOG.md`.

## 4. Completed and working features

- **Import/preprocessing.** `services/preprocessing.py` loads JPG/PNG/WebP
  via Pillow, produces RGB + grayscale arrays, supports 1x/2x/4x analysis
  upscale. Verified on the real sheet (2048x1107 JPEG, true white
  background).
- **Segmentation.** `services/segmentation.py` detects icon regions via
  connected components + proximity merging + reading-order banding.
  Verified: 50/50 crops recovered from the real sheet, 5 rows of 10, zero
  ink clipped outside any box.
- **Heuristic naming.** `services/naming/heuristic.py` — deterministic,
  zero ML dependencies, produces a placeholder slug
  (`outline-icon`, `solid-wide-icon`, etc.) from aspect ratio and fill
  ratio. Not accurate naming; exists so the rest of the pipeline is
  exercisable without any model weights.
- **Line-mode reconstruction.** `services/reconstruction/line_mode.py` +
  `services/geometry/{centerline,primitives,regularize,curve_fit}.py` —
  skeletonize, trace branches, classify each section as a straight
  segment, sharp corner, circular arc, or cubic Bézier, snap only the
  straight sections to icon-wide shared axes, close joints (sharp by
  intersection, smooth by tangent matching), emit the narrowest SVG
  primitive that fits. Verified on all 50 real icons; see below.
- **SVG construction and validation.** `services/svg_model.py` — builds
  `<line>`, `<polyline>`, `<circle>`, `<ellipse>`, `<rect>`, and `<path>`
  (mixed L/A/C commands) elements; `validate_svg` checks XML well-
  formedness, viewBox presence, and absence of embedded `<image>`.
- **Single SVG export.** `services/export.py` — writes and validates one
  icon's SVG. Verified valid in two independent renderers (Qt
  `QSvgRenderer` and headless Chromium).
- **Multi-signal quality reporting.** `services/quality.py` — SSIM, edge
  alignment, stroke-width consistency, anchor count, fragment count, with
  `manual_review_status` pinned to `"pending"` until a human sets it.
- **Undo/redo domain commands.** `domain/commands.py` — `MoveCropCommand`,
  `ResizeCropCommand`, `RenameIconCommand` on `QUndoStack`. Tested; not yet
  wired to a working crop-editing UI.
- **Project persistence.** `domain/project_store.py` — JSON save/load,
  round-trip tested.

## 5. Features that are still stubs

- **Filled reconstruction mode** — `services/reconstruction/filled_mode.py`
  raises `NotImplementedError`. Interface exists (`ReconstructionStrategy`,
  dispatched by `ReconstructionMode.FILLED`); no logic.
- **Mixed reconstruction mode** — `services/reconstruction/mixed_mode.py`,
  same status, dispatched by `ReconstructionMode.MIXED`.
- **Florence-2 naming** — `services/naming/florence2.py` has a working
  constructor (deferred `torch`/`transformers` imports) but
  `suggest_name` raises `NotImplementedError`. Never instantiated by
  default; the app must run without it.
- **ZIP export** — not implemented; only single-SVG export exists.
- **Anchor-point / Bézier-handle editor** — `ui/tabs/reconstruct_tab.py`
  shows a static side-by-side placeholder; no anchor selection, no handle
  dragging, no shape-specific editing (Phase 3 in the spec).
- **UI tabs generally** — `ImportTab`, `SlicesTab`, `NamesTab`,
  `ReconstructTab`, `ExportTab` exist as widget shells (buttons, labels,
  an empty `QGraphicsView`/`QGraphicsScene`) but are **not wired** to the
  services above. No tab currently loads a real file or displays real
  results; all pipeline verification so far has been done by driving the
  services directly (see `RUNBOOK.md`).
- **Crop editing beyond commands** — `MoveCropCommand`/`ResizeCropCommand`
  exist and are tested in isolation, but `SlicesTab` does not yet create
  or apply them from mouse interaction. Rotate, split, merge, multi-select
  are not implemented at all.
- **Quality tab** — no UI; `QualityReport` is only produced and consumed
  programmatically.
- **Batch processing, project crash recovery, packaging** — Phase 4 scope,
  not started.

## 6. Current folder structure

```
icon-sheet-studio/
├── app/
│   ├── main.py                      # entry point (launches MainWindow)
│   ├── domain/
│   │   ├── models.py                # Project, Crop, Icon, IconName, QualityReport, ReconstructionMode
│   │   ├── commands.py              # QUndoCommand subclasses
│   │   └── project_store.py         # JSON save/load
│   ├── services/
│   │   ├── preprocessing.py
│   │   ├── segmentation.py
│   │   ├── naming/
│   │   │   ├── base.py              # NamingProvider ABC
│   │   │   ├── heuristic.py         # default, zero ML deps
│   │   │   └── florence2.py         # optional, stub suggest_name
│   │   ├── geometry/
│   │   │   ├── primitives.py        # LineSegment, Circle, circle fit, rect test
│   │   │   ├── centerline.py        # skeleton-graph tracing, spur pruning
│   │   │   ├── regularize.py        # icon-wide axis alignment (straights only)
│   │   │   └── curve_fit.py         # line/arc/Bezier classification, joints
│   │   ├── reconstruction/
│   │   │   ├── base.py              # ReconstructionStrategy, get_strategy()
│   │   │   ├── line_mode.py         # implemented
│   │   │   ├── filled_mode.py       # stub, NotImplementedError
│   │   │   └── mixed_mode.py        # stub, NotImplementedError
│   │   ├── svg_model.py             # SVG element types + document builder + validator
│   │   ├── quality.py               # multi-signal QualityReport builder
│   │   └── export.py                # single SVG export
│   └── ui/
│       ├── theme.py
│       ├── main_window.py
│       └── tabs/
│           ├── import_tab.py        # placeholder shell
│           ├── slices_tab.py        # placeholder shell
│           ├── names_tab.py         # placeholder shell
│           ├── reconstruct_tab.py   # placeholder shell
│           └── export_tab.py        # placeholder shell
├── tests/
│   ├── unit/                        # 79 tests total, see §17
│   ├── ui/                          # placeholder package, no tests yet
│   └── fixtures_gen/
│       └── make_synthetic.py        # generates fixtures/synthetic/
├── fixtures/
│   ├── real/
│   │   ├── README.md
│   │   └── finance-icon-sheet.jpg   # the real 50-icon test sheet
│   └── synthetic/                   # gitignored, regenerable
├── docs/
│   └── reference/                   # professional SVG examples + failure-mode image
├── outputs/                         # gitignored; exported SVGs, debug images, quality artifacts
├── requirements.txt                 # core, no ML deps
├── requirements-dev.txt             # +pytest, pytest-qt
├── requirements-naming.txt          # optional, +torch/transformers
├── pyproject.toml                   # version 0.1.0
├── PROJECT_MEMORY.md                # this file
├── RUNBOOK.md
├── DECISIONS.md
├── CHANGELOG.md
├── QUALITY_LOG.md
├── CLAUDE.md
└── README.md
```

## 7. Architecture and module responsibilities

Single-language stack: **PySide6 (Qt6) + Python, one process, no IPC**
(see §21/`DECISIONS.md` for why). Each service module owns exactly one
pipeline concern:

| module | responsibility |
|---|---|
| `preprocessing.py` | decode raster, produce RGB/grayscale arrays, upscale |
| `segmentation.py` | find icon regions on the sheet, return `Crop` list |
| `naming/*` | suggest a name for one icon crop, behind `NamingProvider` |
| `geometry/centerline.py` | skeletonize a crop, trace it into branches, prune spurs, estimate stroke width |
| `geometry/primitives.py` | shared line/circle/rectangle fit helpers |
| `geometry/curve_fit.py` | classify branch samples into line/corner/arc/Bezier sections, close joints |
| `geometry/regularize.py` | align only the straight sections to icon-wide shared axes |
| `reconstruction/*` | assemble classified sections into an `SvgDocument`, one strategy per `ReconstructionMode` |
| `svg_model.py` | typed SVG element/document model, XML serialization, validation |
| `quality.py` | compute and package quality signals into a `QualityReport` |
| `export.py` | write + validate one icon's SVG to disk |
| `domain/models.py` | plain dataclasses shared by every layer |
| `domain/commands.py` | undoable mutations of those dataclasses |
| `domain/project_store.py` | JSON persistence of a `Project` |
| `ui/*` | PySide6 widgets (currently unwired shells, see §5) |

## 8. Complete processing pipeline

As implemented today, driving the services directly (no UI wiring yet):

```
load_sheet(path)                                   preprocessing.py
  -> PreprocessedSheet(rgb, grayscale, w, h)

detect_crops(grayscale)                            segmentation.py
  -> list[Crop]  (threshold -> connected components
                   -> speckle rejection -> proximity merge
                   -> padding -> reading-order sort)

for each Crop, on its grayscale patch:

  HeuristicNamingProvider().suggest_name(rgb_patch)  naming/heuristic.py
    -> IconName(value, is_manual=False)

  LineModeStrategy().reconstruct(gray_patch)         reconstruction/line_mode.py
    binarize_for_skeleton                             centerline.py
    -> extract_skeleton
    -> estimate_stroke_width
    -> trace_branches                                 (skeleton-graph, degree-based)
    -> prune_spurs                                     (keep both-ends-free details)
    -> for each branch:
         fit_branch(...)                               curve_fit.py
           detect_corners (neighborhood turning)
           decompose_run -> line / arc / cubic sections
           merge_collinear
    -> _align_straight_sections(...)                   regularize.py
         estimate_dominant_axes -> classify_sections
         -> snap_sections -> align_offsets
    -> resolve_joints(...)                              curve_fit.py
         sharp: line-line intersection
         smooth: tangent matching (arc re-centers, Bezier rotates handle)
    -> _align_free_endpoints(...)                       line_mode.py
    -> emit: <circle> | <rect> | <line> | <polyline> | <path>
    -> SvgDocument

  export_single_svg(document, path)                    export.py
    -> validate_svg -> write file

  (quality.py functions available but not yet wired into
   an automatic per-icon report; used manually, see QUALITY_LOG.md)
```

## 9. Domain models and data flow

All plain dataclasses in `app/domain/models.py`:

- `ReconstructionMode(str, Enum)` — `LINE | FILLED | MIXED`.
- `Crop` — `id, x, y, width, height, rotation, touches_edge,
  uncertain_grouping`. Produced by `segmentation.detect_crops`, mutated by
  `MoveCropCommand`/`ResizeCropCommand`.
- `IconName` — `value, is_manual, confidence`. Produced by a
  `NamingProvider`, mutated by `RenameIconCommand` (which always sets
  `is_manual=True`, per the spec's "manual names are never silently
  overwritten" rule).
- `QualityReport` — `ssim, edge_alignment, stroke_width_consistency,
  anchor_count, fragment_count, manual_review_status="pending", warnings`.
  Built by `quality.build_quality_report`; `manual_review_status` is never
  set to anything but `"pending"` anywhere in the codebase (invariant #4
  in §21).
- `Icon` — `id, crop, name, reconstruction_mode, svg_document,
  quality`. The unit that flows through Names/Reconstruct/Quality/Export.
- `SourceSheet` — `file_path, file_hash, width, height`.
- `Project` — `name, source, icons: list[Icon]`. Serialized whole by
  `project_store.save_project`/`load_project` (JSON, round-trip tested).

Data flow: a `SourceSheet` + raw `Crop` list are the inputs to naming and
reconstruction; each produces an `IconName`/`SvgDocument`/`QualityReport`
that gets attached to an `Icon`; the `Icon` list plus `SourceSheet` make a
`Project`, which is the unit persisted to disk. Nothing in this chain
currently flows through the UI — it is exercised by calling the service
functions directly (`RUNBOOK.md` has the exact snippet).

## 10. Segmentation algorithm

`services/segmentation.py`. Threshold (ink < 200) → 8-connected components
→ reject components under 12px area (JPEG speckle) → **proximity merge**
(iteratively union boxes within `MERGE_DISTANCE = 24` px or overlapping,
repeated to convergence) → pad once by 4px → flag boxes far from the
median area as `uncertain_grouping` (never discard) → sort into
reading-order rows (banded by half the median crop height) → assign
sequential `crop-N` ids.

**Why proximity merging is mandatory:** raw connected components alone
gave 276 crops for the 50-icon sheet — every icon splits into its
disconnected parts (outer outline, inner `$` glyph, each dash of a dashed
line). `MERGE_DISTANCE` must sit between the largest intra-icon gap and
the smallest inter-icon gutter; on this sheet icons are ~130px wide on a
~205px pitch (gutters ~75px, intra-icon gaps ~8px), so 24px works.
Padding is applied **once after** merging — applying it per raw component
padded multi-part icons repeatedly (a defect, fixed).

Verified result on the real sheet: exactly 50 crops, 5 rows of 10, zero
ink found outside any crop boundary, zero crops touching the sheet edge.

## 11. Centerline and skeleton-graph algorithm

`services/geometry/centerline.py`. `binarize_for_skeleton` (threshold
200) → `skimage.morphology.skeletonize` → `estimate_stroke_width` via
`cv2.distanceTransform` (2x distance at skeleton pixels) →
`trace_branches` walks the skeleton as a graph:

- **Degree by connected neighbour clusters, not raw 8-neighbour count.**
  `_neighbor_group_count` groups mutually-adjacent neighbours before
  counting groups. Counting raw neighbours misreads diagonal staircases —
  an ordinary path pixel can have three mutually-adjacent 8-neighbours and
  would be mistaken for a junction.
- Nodes are pixels whose degree ≠ 2 (endpoints and junctions). Each edge
  out of a node is walked to the next node, preferring the step that
  leaves the previous pixel's neighbourhood (so diagonal staircases
  advance instead of doubling back).
- Closed loops with no endpoint/junction (a clean circle) are traced as
  cycles separately, since the node-based walk never visits them.

`prune_spurs` removes dead-end stubs from stroke caps/corners: **a spur
has exactly one free end and one junction end.** A short branch free at
**both** ends is a standalone detail (a dash, a tick) and is kept
regardless of length — the original `or` condition treated any short
branch with any free end as a spur and silently deleted 2 of 6 dashes on
the real credit-card icon (fixed; see `DECISIONS.md`).

## 12. Geometry regularization algorithm

`services/geometry/regularize.py` — **operates only on sections already
classified as straight** by `curve_fit.py` (§13); curves never reach it.

1. Each straight section is fit with **trimmed total-least-squares**
   (orthogonal regression via SVD, so near-vertical runs fit as well as
   horizontal ones; outlier pixels trimmed by a median-absolute-deviation
   threshold).
2. The icon's own horizontal and vertical angles are estimated **before**
   anything is classified or moved: length-weighted circular mean over
   *doubled* angles (correct statistics for undirected lines), candidates
   gathered within a window of 2x the tolerance.
3. Estimates **lock to exact 0°/90°** unless the whole icon is
   consistently rotated past tolerance — otherwise a single tilted stroke
   would declare its own tilt to be level (this happened on the first
   implementation and was fixed). Only 1 of 50 real icons keeps a
   non-zero rotated axis.
4. Every eligible straight section snaps to the shared axis, so related
   bars and edges become parallel **by construction**.
5. Parallel, snapped sections within 0.6x stroke width of each other
   collapse onto one shared offset (shared baselines).
6. Vertices are rebuilt as **intersections of the corrected lines**
   (falling back to the original point if the intersection is unstable or
   implausibly far) — without this, snapping two adjacent sections
   independently would split their shared corner apart.
7. Free (unjoined) endpoints of snapped straights that nearly share a
   level are pulled onto one coordinate, moving along the section's own
   direction.

Tolerance is **4.0°** — real skeleton noise on the test sheet reaches
3.4°, so 3.5° dropped genuine cases; 4.0° is the top of the spec's
suggested 2–4° range. Guards: sections outside tolerance stay diagonal;
short sections *inside* a multi-section run are protected from snapping
(preserves rounded-corner transitions — a standalone short run like a
dash has no corner to protect, so it is still eligible).

## 13. Current line, curve, corner, and primitive handling

`services/geometry/curve_fit.py` — runs **before** any simplification, on
the full ordered skeleton samples of each branch.

**Corner detection** (`detect_corners`): tangent turning is measured over
a `window` of samples (never a single pixel — one skeleton stair-step
turns sharply for one sample and means nothing). A corner must (a) exceed
a turning threshold (38°), (b) be the local peak, and (c) be both
*concentrated* (turn substantially more than its wide neighbourhood
median — this is what excludes an arc, whose turning is even) and
*local* (turn on only one side of its peak — this excludes a tight
sustained curve). Corners within a fixed margin of a branch's free end
are excluded (skeleton caps/junction stubs curl like corners but aren't).

**Model selection** (`select_model` / `decompose_run`): simplest-adequate
over three models, tried in order of complexity:

- **`LineModel`** (2 dof) — total-least-squares fit, as in regularize.py.
- **`ArcModel`** (3 dof) — algebraic (Kâsa) circle fit, accepted only if
  the samples' angle around the fitted center advances **monotonically**
  (an S-curve fails this by construction, since its center of curvature
  flips sides), the radius is neither implausibly small nor larger than
  ~12x the run's own length, and it passes two physical gates:
  - **sagitta ≥ 0.4 x stroke width** — an arc's departure from the
    straight chord joining its ends must be big enough to see at stroke
    scale, or a straight run with a little JPEG bow gets promoted to a
    shallow, visibly domed arc.
  - **radius ≥ 0.6 x stroke width** — curvature finer than the stroke
    that drew it is skeleton noise, not evidence; without this the dollar
    sign emitted radius-1.3px arcs.
- **`BezierModel`** (6 dof) — cubic fit with chord-length parameterization,
  refined by re-projecting samples onto the current curve (matters for
  tight turns). Reached only when neither a line nor an arc fits within a
  sub-pixel tolerance — this is how changing-curvature shapes (an S-curve,
  the dollar sign) are answered on the evidence, never by a special case
  for any particular glyph.

A straight run is only accepted if it is **≥ 4x stroke width long and
near-zero-turning along its whole extent**, verified by an actual line
fit (not the turning profile alone) — a short enough chunk of *any*
large-radius arc fits a line within tolerance, so without this check a
clean semicircle gets a flat nibble carved from its middle and an S-curve
splits at its inflection.

**Joint resolution** (`resolve_joints`): sharp corners close by
intersecting the two adjacent lines; smooth joints close by tangent
matching — a Bézier rotates its handle onto the shared tangent, an arc
moves its center onto the normal through the joint (only if the implied
radius stays within 0.5x–2x of the fitted one, or the radius collapses
toward the joint). Where a straight meets a curve, the straight's tangent
wins, so axis alignment survives the joint.

**Primitive emission** (`reconstruction/line_mode.py`): a branch made
entirely of `LineModel` sections emits `<line>`/`<polyline>`/`<rect>` (the
narrowest that fits); a fully closed near-circular arc emits `<circle>`;
anything mixing line/arc/cubic sections emits a single `<path>` with
`M`/`L`/`A`/`C` commands, so one branch stays one editable stroke.

**Measured on the real 50-icon sheet:** before this classification step,
output contained 3,771 straight sections, 0 arcs, 0 cubics (34% of
centerline length was genuinely curved and had nowhere to go). After:
2,747 lines, 257 arcs, 52 cubics; fit error stays sub-pixel for every
model (line mean 0.26px, arc mean 0.67px, cubic mean 0.75px). Full tables
in `QUALITY_LOG.md`.

## 14. SVG construction rules

`services/svg_model.py`:

- Elements: `SvgLine`, `SvgCircle`, `SvgEllipse`, `SvgRect`,
  `SvgPolyline`, and `SvgPath` (structured `PathMoveTo`/`PathLineTo`/
  `PathArcTo`/`PathCubicTo` commands, serialized to a `d` string).
- Document-level style only: `fill="none"`, explicit `stroke`,
  `stroke-width`, `stroke-linecap`, `stroke-linejoin` on the `<svg>` root
  — true SVG strokes, never a filled trace, per invariant #2.
- Stroke width is measured in **viewBox units**, not screen pixels, per
  the spec's explicit requirement.
- Coordinates are rounded to 2 decimals with trailing zeros stripped
  (`_num` helper) — deliberately not full float precision, to keep files
  small and diffable.
- `validate_svg` checks: XML well-formedness, `viewBox` attribute
  present, no `<image>` element anywhere (no embedded raster is ever
  allowed in the output, per the spec).
- `SvgDocument.anchor_count()` sums on-curve anchors across all element
  types (a `SvgPath`'s Bézier handles are not counted as anchors, since
  they aren't independent editable points in the same sense).
- No masks, clip-paths, or metadata are emitted by any current code path.

## 15. Naming-provider architecture

`services/naming/base.py` defines `NamingProvider` (ABC,
`suggest_name(icon_crop_rgb) -> IconName`). Two implementations:

- `HeuristicNamingProvider` (`heuristic.py`) — the default. Zero ML
  dependencies; deterministic; derives a slug from aspect ratio and fill
  ratio (e.g. `outline-wide-icon`). Not meant to be accurate — it exists
  so every other stage is exercisable without model weights.
- `Florence2NamingProvider` (`florence2.py`) — optional. Imports
  `torch`/`transformers` **only inside `__init__`**, never at module
  scope, so importing the `naming` package never requires those packages.
  Its `suggest_name` currently raises `NotImplementedError` (§5). Never
  instantiated unless explicitly requested; the app must run fully
  without it (invariant #3).

This satisfies the spec's requirement to keep the naming model "behind an
interface so another local model or optional API can be added later"
without ever making a heavy dependency mandatory.

## 16. Quality metrics and known weaknesses

`services/quality.py` computes, independently:

- `compute_ssim` — structural similarity between rendered and original.
  **Known invalid for judging geometry-straightening changes**: it
  measures pixel overlap with a blurry JPEG, so correcting a stroke that
  genuinely wobbles necessarily *reduces* overlap with that wobble while
  being more correct as vector art. Observed twice in practice — see
  `QUALITY_LOG.md`, both the regularization and curve-classification
  entries.
- `compute_edge_alignment` — recall of original ink under a dilated
  render. **Known too lenient**: a 5x5 dilation tolerance returns 1.0000
  even with visible corner errors.
- `compute_stroke_width_consistency` — 1 minus the coefficient of
  variation of stroke widths. **Known inflated**: distance-transform
  width spikes inside junction blobs, mixing topology artifacts into the
  measurement.
- `count_fragments` — extra connected components beyond expected.
- `build_quality_report` — always sets `manual_review_status="pending"`;
  nothing else in the codebase may set any other value (invariant #4).

**Stroke width itself is overestimated ~15–25%**: the distance transform
reports exactly 4.00px regardless of ink threshold on the real sheet
(quantized/insensitive); area÷skeleton-length gives ~3.1–3.2px at a tight
threshold. This is a pipeline defect (affects the emitted `stroke-width`
and every metric derived from it), not just a metric artifact — see
Known defect (c) in §20.

**Reliable measurements used instead**, established across two
iterations: axis-exactness counts (near-axis segments landing at exactly
0°/90° after alignment), vertex displacement distributions (proving a
correction is small even when it changes a score), fit error against
tolerance (per model, recorded in `ModelChoice`/`LineModeDiagnostics`),
and direct visual comparison in two independent renderers.

## 17. Testing strategy and current test count

**79 tests total** (Python 3.11.15, PySide6 6.11.2, `pytest-qt` 4.5.0),
all passing on `f2b3f64`. Requires `QT_QPA_PLATFORM=offscreen` even for
non-UI tests, since `domain/commands.py` builds on `QUndoCommand`.

| file | tests | covers |
|---|---|---|
| `test_geometry.py` | 8 | line segment math, axis-aligned rectangle test, circle fit |
| `test_svg_model.py` | 7 | SVG element serialization, validation, anchor counting |
| `test_crop_editing.py` | 2 | move/resize commands + undo/redo |
| `test_naming.py` | 3 | heuristic provider determinism, rename-marks-manual |
| `test_project_store.py` | 1 | JSON save/load round trip |
| `test_segmentation.py` | 6 | multi-part merge, speckle rejection, reading order, padding-once, edge flag |
| `test_regularize.py` | 18 | tilt snapping, parallelism, shared baselines, diagonal preservation, curve non-snapping, rounded-corner survival |
| `test_curve_fit.py` | 34 | corner/arc/cubic classification on 6 fixture families x crisp/blurred variants, plus unit tests for turning, corner detection, model selection, Bézier/line fitting |

Strategy: unit tests drive real service functions on synthetic rasters
built with OpenCV drawing primitives (never mocked geometry), with a
`blur()` helper (Gaussian blur + JPEG re-encode) applied to every
curve-fit fixture so the classifier is exercised against realistic
degradation, not only crisp edges. Real-sheet verification is done
separately, by scripts against `fixtures/real/finance-icon-sheet.jpg`,
with numeric results recorded in `QUALITY_LOG.md` — this is deliberately
**not** folded into the automated suite, since judging real-photo output
requires the human visual review the spec mandates, not an assertion.

**Not yet covered:** no UI/widget tests exist (`tests/ui/` is an empty
placeholder package) despite `pytest-qt` being installed for this
purpose; filled mode and mixed mode have no tests (they raise
`NotImplementedError` and nothing tests that they raise it); no
integration test drives the full pipeline end-to-end as pytest (it has
only been driven by ad hoc scripts, documented in `RUNBOOK.md`).

## 18. Real fixtures and reference assets

- `fixtures/real/finance-icon-sheet.jpg` — 2048x1107 JPEG, RGB, true
  white background (all four corner patches measured at exactly 255.00),
  5.49% ink at threshold 128. A 5x10 grid of 50 line-style finance icons.
  This is the primary real-world test input; see `fixtures/real/README.md`.
- `fixtures/synthetic/` — gitignored, regenerated by
  `tests/fixtures_gen/make_synthetic.py` (currently produces one
  horizontal-line PNG; not depended on by any current test, which build
  their synthetic arrays inline instead).
- `docs/reference/finance-icon-sheet.svg` — a professionally hand-built
  SVG of the **same subject matter** but a **different branded 6000x2600
  template** (dark preview panel, different layout/scale). Confirmed by
  inspection to be unusable as a registered pixel ground truth; kept as a
  qualitative "what good construction looks like" reference only.
- `docs/reference/main1.svg`, `main2.svg`, `main3.svg` — professional SVG
  icon construction examples (style/anchor-economy reference).
- `docs/reference/rough-conversion-reference.png` — annotated example of
  the double-outline tracing failure this project must avoid.

## 19. Manual visual-review results

Per invariant #4/spec requirement, `manual_review_status` has never been
programmatically set to anything but `"pending"`. Human visual review has
happened twice, both recorded in full in `QUALITY_LOG.md`:

- **2026-09-20, geometry regularization** (commit `a510ccd`): four sampled
  icons (crop-31 monitor+bars, crop-2 credit card, crop-35 presentation
  board, crop-21 coin+dollar-sign+bars) rendered in both Qt and headless
  Chromium and visually compared against the source crop. Found: SSIM
  regressed on 2 of 4 icons while the geometry was visibly straighter
  (confirmed by a zoomed side-by-side, not asserted) — see §16.
- **2026-09-20, curve classification** (commit `f2b3f64`): the same four
  icons re-reviewed after arc/Bézier classification. Found real
  improvement (properly rounded pill shapes, corners) alongside real new
  defects introduced mid-iteration and then fixed within the same session
  (shallow arcs standing in for bowed straights) and one that remains
  (see §20a).

Both entries are dated the same day because both pieces of work were
completed in one continuous session; they are tracked as separate
`QUALITY_LOG.md` entries because they are separate reviewed changes.

## 20. Known defects

In priority order. Full numeric evidence for all of these is in
`QUALITY_LOG.md`.

**(a) Damaged dollar-sign curves.** The `$` glyph inside crop-21
reconstructs as several short (~15px) fragments rather than one
continuous curve, because the vertical bar of the `$` crosses the S-curve
and the skeleton graph treats that crossing as a junction. A fragment
that short has only one sign of curvature and is fit with an arc rather
than the cubic a full S needs. **This is a junction-routing defect, not a
curve-fitting defect** — explicitly out of scope for `curve_fit.py`,
which was verified (via `test_s_curve_uses_beziers_and_never_a_single_arc`)
to correctly produce cubics on an *unfragmented* S-curve. Fixing this
requires changing how the skeleton graph is routed through junctions, a
different piece of work.

**(b) Chamfered rounded corners.** A corner is only classified as an arc
if its sagitta reaches 0.4x stroke width. On the real credit-card icon's
outer frame, only **1 of 4** corners met this bar; the other 3 remain
straight-line (`L`) chamfers in the emitted path. At the sheet's 4px
stroke width, `stroke-linejoin="round"` visually softens this enough to
be easy to overclaim as "fixed" from a casual look at the render — it is
not fixed, only improved from 0/4 in the pre-classification baseline.

**(c) Stroke-width overestimation.** The distance-transform estimator in
`centerline.estimate_stroke_width` reports exactly 4.00px regardless of
ink threshold on the real sheet; an independent area÷skeleton-length
estimate gives ~3.1–3.2px. This means every emitted `stroke-width`
attribute is ~15–25% too heavy, which also visibly thickens the rendered
strokes relative to the source and depresses SSIM/IoU independently of
shape accuracy. Not yet fixed.

**(d) Remaining alignment issue.** Shallow corners below the 38° turning
threshold are not classified as corners at all — they still render
correctly (the vertex comes from intersecting the two adjacent lines
regardless of whether a "corner" label was attached), but they are not
detected or reported as corners. Measured: 287 of 498 total joints across
the sheet are unlabelled straight-straight joints averaging 19.7°
deviation, versus the 211 joints that *are* classified (curve-involved),
which achieve 91% under 10° deviation. This is a **detection/labeling
gap**, not a visible geometry defect — the shapes are correct — but it
means corner *count* and corner *statistics* under-report.

Additional open items (full list and resolved-defect history in
`QUALITY_LOG.md`): edge-alignment metric too lenient (returns 1.0000
regardless); stroke-consistency metric inflated by junction blobs; an arc
tangent-matched at one joint may retain a small kink at its far joint
(measured 14.1° on a synthetic fixture); `<rect>` has never fired on the
real sheet (every rectangle on it is rounded, so the code path is
untested on real data); heuristic names are placeholders and currently
feed export filenames (by design, pending Florence-2 or manual entry).

## 20a. Model / effort policy

Preserved verbatim from earlier project memory; the authoritative copy
lives in `CLAUDE.md`, restated here so this file remains self-contained.

Per `CLAUDE.md`: Opus at high effort for geometry reconstruction,
centerline extraction, curve fitting and quality-metric debugging; Sonnet
at medium for UI, tests, refactoring, docs and straightforward service
work; Haiku at low for mechanical edits only. State current model/effort
before a major task and stop for the user to switch manually rather than
switching unilaterally.

## 21. Important technical decisions and reasons

Summarized here; full dated entries with alternatives considered are in
`DECISIONS.md`.

1. **Single-process PySide6, not a two-language IPC split.** Puts
   geometry code and its visual feedback loop in the same process.
2. **`ReconstructionMode` first-class from day one**, dispatch in
   `reconstruction/base.py`. Implement filled/mixed by filling in their
   stub files, never by restructuring `base.py`/`svg_model.py`.
3. **Line mode works from the skeleton only, never raw edge contours** —
   structurally prevents blurry outer edges from being traced into filled
   shapes (the double-outline failure mode).
4. **Florence-2 imports deferred to `__init__`**, never at module scope —
   the app must run fully without it installed.
5. **`manual_review_status` starts and stays `"pending"`** — only a human
   who has viewed the rendered SVG may change it.
6. **Curves are classified before any straightening/simplification** —
   `curve_fit.py` runs on raw ordered samples before regularization ever
   sees them, and only straight-classified sections are handed to
   `regularize.py`.
7. **Axis estimates lock to exact 0°/90° unless the whole icon is
   consistently rotated** past tolerance — prevents one tilted stroke
   from declaring its own tilt to be level.
8. **An arc must earn its extra degree of freedom**: sagitta ≥ 0.4x
   stroke width and radius ≥ 0.6x stroke width, both gates added after
   observing specific visual defects their absence caused (domed flat
   edges; sub-stroke-width arcs on the dollar sign).
9. **SVG coordinates rounded to 2 decimals**, not full float precision —
   readability/diffability over marginal precision.

## 22. Rejected approaches and why they failed

- **Tauri/Electron UI + separate Python CV backend.** Rejected before
  implementation: would add an IPC boundary between geometry code and its
  visual feedback loop, the exact pair needing the tightest iteration,
  for no offsetting benefit.
- **Fixed-target angle snapping (`snap_angle`/`snap_segment`, snapping to
  0/45/90/135°).** Implemented, then removed: it would drag a genuine 42°
  diagonal onto 45°, violating "do not snap intentional diagonals."
  Replaced by data-driven, icon-wide shared-axis estimation.
  (`DECISIONS.md`.)
- **Spur-pruning with an `or` free-end test.** Deleted 2 of 6 real dashes
  as false spurs. Replaced with an "exactly one free end AND the other a
  junction" test. (`DECISIONS.md`.)
- **Raw connected components for segmentation, no merging.** Produced 276
  crops for 50 real icons. Replaced with proximity merging.
  (`DECISIONS.md`.)
- **Using SSIM/IoU against the source JPEG as the acceptance test for
  geometry-straightening changes.** Tried, then explicitly rejected as
  invalid: it penalizes corrections that make the output *more* correct
  as vector art, because it measures overlap with the raster's own blur.
  Replaced by axis-exactness counts + displacement distributions + visual
  review. (§16, `QUALITY_LOG.md`.)
- **Using the supplied professional `finance-icon-sheet.svg` as a
  pixel-registered ground truth for automated scoring.** Attempted, found
  impossible: it is a different branded template at a different scale and
  layout, not a registered version of the JPEG fixture. Kept only as a
  qualitative reference.
- **A single "whole-run" line-vs-arc-vs-cubic choice with no straight-run
  carve-out.** Produced correct classification on clean shapes but let a
  short chunk of any large-radius arc pass as a line, fragmenting clean
  semicircles and S-curves at false boundaries. Replaced by verifying
  candidate straight runs with an actual bounded line fit, not turning
  angle alone.
- **Accepting any arc whose residual fits tolerance, with no sagitta/
  radius floor.** Produced domed "straight" edges (JPEG bow read as a
  shallow arc) and sub-stroke-width arcs on fine glyph detail. Both gates
  added after specific observed defects (§13, §20b/c).

## 23. Development history in milestone order

All on branch `claude/happy-carson-lh8mr7`. Commit hashes are exact; see
`CHANGELOG.md` for full per-commit detail and `QUALITY_LOG.md` for the
numeric results attached to each.

1. **`c1ec58c`** — Scaffold: PySide6 UI shell, domain dataclasses +
   commands + project store, service module skeletons, `Reconstruction
   Mode` enum with dispatch, heuristic + stub Florence-2 naming, initial
   line-mode reconstruction (placeholder centerline-to-segment logic),
   SVG builder/validator, quality-report struct, single-SVG export,
   initial reference-asset copy-in, initial docs.
2. **`e48f901`** — Real centerline tracing + segmentation fix. Diagnosed
   276-crops-for-50-icons on the real sheet; added proximity merging.
   Replaced the placeholder reconstruction (one straight segment per
   skeleton component) with true skeleton-graph branch tracing, degree
   classification, spur pruning (with the both-free-ends fix), primitive
   selection (circle/rect/line/polyline).
3. **`a510ccd`** — Geometry regularization. Added `regularize.py`:
   icon-wide dominant-axis estimation and snapping, offset alignment,
   vertex rebuild by intersection, free-endpoint alignment. Removed fixed
   0/45/90/135 snapping. First manual visual review round; discovered and
   documented the SSIM-invalidity finding.
4. **`569e804`** — Checkpoint: created `RUNBOOK.md`, `PROJECT_MEMORY.md`
   (first version), `CHANGELOG.md`, `QUALITY_LOG.md`; ran full suite;
   committed and pushed both `main` and the feature branch to
   `github.com/TMAn1An/icontosvg` after GitHub App authorization.
5. **`f2b3f64`** — Curve-versus-corner classification. Added
   `curve_fit.py` (corner detection, line/arc/cubic model selection with
   the sagitta/radius gates, joint resolution) and `SvgPath`. Measured
   the pre-fix state first (0 arcs/0 cubics despite 34% curved
   centerline length) before implementing. 34 new tests. Second manual
   visual review round.
6. **(this update)** — Documentation audit: rewrote `PROJECT_MEMORY.md`
   against the 27-point checklist below, added `DECISIONS.md`, expanded
   `RUNBOOK.md` with full Windows/Linux instructions, added a
   documentation-update rule to `CLAUDE.md`.

## 24. Pending work in priority order

1. **Junction routing** (§20a) — the largest remaining source of visible
   defects; fragments the dollar sign, bends skeletons near T-junctions.
   Requires changing how `centerline.trace_branches` routes through
   junction nodes, likely informed by the local geometry of all arms
   meeting there rather than the current arbitrary walk order.
2. **Lower/adapt the corner-arc sagitta floor** (§20b) so more genuine
   rounded corners are recognized without reintroducing the
   bowed-straight-as-arc defect that floor was added to prevent.
3. **Stroke-width estimator rework** (§20c) — replace or supplement the
   quantized distance-transform measurement.
4. **Wire the UI tabs to the services** — none of `ImportTab`/
   `SlicesTab`/`NamesTab`/`ReconstructTab`/`ExportTab` currently calls
   real pipeline code; this blocks any interactive use of the
   application and is arguably higher-priority than further geometry
   refinement for reaching a usable Phase 1.
5. **Filled reconstruction mode** — interface is ready
   (`ReconstructionMode.FILLED`, `filled_mode.py` stub); needs contour-
   hierarchy-based filled-region reconstruction per the spec.
6. **ZIP export.**
7. **Mixed reconstruction mode.**
8. **Florence-2 `suggest_name` implementation.**
9. **Anchor-point/Bézier-handle editor** (Phase 3 in the spec).
10. **Tighten edge-alignment and stroke-consistency metrics** so Quality
    tab numbers are trustworthy once that tab is built.

## 25. Installation and run instructions

See `RUNBOOK.md` for the complete, tested Windows PowerShell and
Linux/macOS command sequences (clone, venv, install, run, test, generate
fixtures, process the real sheet, locate outputs, fix Qt/EGL errors).
Summary:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest   # 79 tests should pass
python -m app.main                            # launches the UI shell (unwired, see §5)
```

## 26. Git branch workflow

- Development branch: **`claude/happy-carson-lh8mr7`**. All commits so
  far are on this branch.
- `main` exists on the remote (`github.com/TMAn1An/icontosvg`) at commit
  `569e804` (the checkpoint before curve classification) and has **not**
  been fast-forwarded to `f2b3f64`. Advancing `main` requires explicit
  owner approval — do not push to `main` without it.
- Push the feature branch with `git push origin claude/happy-carson-lh8mr7`
  (already tracks `origin`). Never force-push. Never delete a branch.
- Commit messages should describe *why*, and each meaningful geometry or
  pipeline change should be paired with a `QUALITY_LOG.md` entry and,
  where a real decision was made, a `DECISIONS.md` entry (see the rule
  added to `CLAUDE.md`).

## 27. How another AI should safely continue this project

1. **Read in this order before touching code:** this file in full, then
   `DECISIONS.md`, then the most recent `QUALITY_LOG.md` entry, then
   `CLAUDE.md`'s model/effort policy.
2. **Never claim a defect is fixed from a rendered screenshot alone.**
   Every fix in this project's history was verified by (a) a targeted
   unit test, (b) a measurement on the real 50-icon sheet, and (c) a
   before/after visual render in two independent SVG renderers. Follow
   the same pattern; `RUNBOOK.md` has the exact commands.
3. **Do not trust SSIM/IoU as a pass/fail gate** for any change to
   straight-vs-curve classification or axis alignment — see §16 and both
   `QUALITY_LOG.md` entries for why a visibly-better result can score
   lower. Use axis-exactness counts, vertex-displacement distributions,
   and fit-error-against-tolerance instead, plus an actual look at the
   render.
4. **Never set `QualityReport.manual_review_status` to anything but
   `"pending"` in code.** That field exists specifically so quality is
   never self-certified.
5. **Respect the architectural invariants in §21** — in particular,
   don't restructure `reconstruction/base.py`/`svg_model.py` to add
   filled/mixed mode; fill in their existing stub files instead. Don't
   move Florence-2 imports to module scope. Don't let curves reach
   `regularize.py`.
6. **When fixing junction routing (§24 item 1)**, remember that
   `curve_fit.py` was deliberately kept out of scope for this — verify
   any junction-routing fix with the existing
   `test_dollar_sign_crop_is_carried_by_curves_not_chords` test plus a
   fresh visual check on `fixtures/real/finance-icon-sheet.jpg` crop-21,
   and update `QUALITY_LOG.md` with fragment counts before/after.
7. **Update documentation as part of the same change, not after.** Per
   the rule in `CLAUDE.md`: any meaningful milestone (a geometry
   algorithm change, a new pipeline stage, a fixed defect, a UI tab
   wired to real services) must update `PROJECT_MEMORY.md` (the relevant
   numbered section above), `CHANGELOG.md`, and — if it involved a real
   design decision with alternatives — `DECISIONS.md`, in the same
   commit or the very next one.
8. **Follow the model/effort policy in `CLAUDE.md`**: geometry work is
   Opus/high; UI, tests, refactoring and docs are Sonnet/medium. State
   current model/effort before starting a major task, and if a change of
   model is warranted, stop and tell the human the exact browser action
   rather than switching unilaterally.
9. **Check git state before pushing.** `main` is intentionally behind
   the feature branch (§26) — do not fast-forward or merge into `main`
   without the owner's explicit instruction in the current conversation.
