# Changelog

All notable changes to Icon Sheet Studio. Dates are ISO 8601.

## [Unreleased]

### 2026-09-20 — Topology-first, confidence-gated reconstruction

Replaces the per-branch curve classifier of `[0.2.0]`, which the user
rejected as a quality regression. That version is preserved at tag
`failed-experiment/curve-classification-v1` (commit `f2b3f64`) and was
never merged to `main`.

#### Added

- `services/geometry/topology.py` — skeleton graph with Rutovitz
  crossing-number node degree, spur pruning and degree-2 healing to a
  joint fixed point, junction pairing by tangent continuity, and stroke
  assembly. Strokes are reassembled whole *before* anything is fitted.
- `services/geometry/candidates.py` — competing primitives for a whole
  stroke (straight, corner-polyline, circle, ellipse, rounded rect,
  polygon, arc, cubic chain, composite) plus the RDP baseline, and the
  eight-veto safety gate `evaluate_gate`.
- Corner preservation as a gate veto, in two parts: a distance test
  (every detected corner within `0.6 x stroke width` of the candidate)
  and a tangent-retention test (a candidate must keep at least half the
  turn the pixels show at any corner of 35° or more).
- `corner_polyline_candidate` — straight runs fitted between detected
  corners and met at their intersections, preferred over any curve when
  every run is straight. A zigzag is not a curve.
- Corner-bounded pieces inside `composite_candidate`: an arc may run up
  to a corner, never through it.
- `tests/unit/test_topology_reconstruction.py` — 29 tests covering the
  ten mandated regression cases.

#### Fixed

- **Dollar sign.** The root cause was node degree computed by clustering
  8-adjacent neighbours, which reports the centre of a `+` as degree 1
  and hid every crossing (`junctions: 0`). With the crossing number it
  now emits one continuous vertical `<line>` and one continuous S as a
  3-segment cubic path (0.89px max error), plus the coin `<circle>`, with
  no spurious `Z`.
- **Two dashes vanished from crop-2.** Endpoint alignment clustered both
  ends of a dash shorter than its own tolerance and collapsed it to zero
  length. Endpoints of the same segment are now excluded from a cluster.
  All six dashes present in the crop now survive; `removed_degenerate`
  is 0 across all 50 icons.
- **Chart-arrow zigzag arrived smoothed.** Now a sharp 6-point polyline.
- **Bar-chart tops eaten by arcs.** Corner-bounded composite pieces stop
  an arc spanning a flat top and both its corners.
- **Sharp triangular arrowhead (synthetic).** A 3-corner polygon at blur
  sigma 0, 1.4 and 2.0.

#### Measured

50/50 crops reconstruct; 743 strokes through 605 junction pairings; 426
`line`, 104 `polyline`, 89 `bezier`, 38 `corner-polyline`, 27 `circle`,
23 `composite`, 18 `arc`, 17 `rounded-rect`, 1 `polygon`; 2,642 anchors;
0 degenerate elements removed, 0 strokes needing review, 0 invalid SVG.
Test suite 103 passed, 5 skipped.

#### Known defects, not fixed

crop-35's arrowhead is a blob (a regression against the pre-`0.2.0`
output); crop-21's S is continuous but mis-shaped; crop-31's tall bar
top is slightly domed; one crop-2 dash sits ~10° off horizontal. Full
detail in `PROJECT_MEMORY.md` §20b and `QUALITY_LOG.md`.

### 2026-09-20 — Documentation audit

Documentation audit (this update): rewrote `PROJECT_MEMORY.md` against a
27-point completeness checklist, added `DECISIONS.md`, expanded
`RUNBOOK.md` with complete Windows PowerShell and Linux/macOS
instructions for every operational task, added a documentation-update
rule to `CLAUDE.md`. No code changes.

## [0.2.0] — 2026-09-20

Curve-versus-corner classification. Commit `f2b3f64` on branch
`claude/happy-carson-lh8mr7`.

### Added — curve-versus-corner classification

- `services/geometry/curve_fit.py`: neighborhood-based corner proposal,
  robust line fitting, circular-arc fitting with a monotone-sweep test,
  cubic Bezier fitting with parameter refinement, and simplest-adequate
  model selection over line/arc/cubic with the candidate errors recorded
  for auditing.
- `SvgPath` with structured M/L/A/C commands, so one branch mixing
  straight, arc and cubic sections stays a single editable stroke.
- Joint resolution: sharp corners by line intersection, smooth joints by
  tangent matching, with the residual discontinuity measured and
  reported rather than assumed.
- 34 curve-classification tests: sharp triangle, rounded rectangle,
  semicircle, S-curve, line-to-arc transition and the real dollar-sign
  crop, each with a blurred + JPEG-recompressed variant.

### Fixed

- Curves no longer shredded into chords. Across the 50-icon sheet the
  output went from 0 arcs / 0 Beziers to 257 arcs / 52 cubics, with fit
  errors staying sub-pixel (line 0.26 mean, arc 0.67, cubic 0.75).
- Arcs finer than the stroke, and shallow arcs standing in for bowed
  straights, are both rejected on physical grounds.

### Planned next, in defect priority order

- Junction routing — the largest remaining source of defects; it
  fragments the dollar sign and bends skeletons near T-junctions.
- Corner radii below ~1.6px sagitta still chamfer (only 1 of 4 corners
  on the credit-card frame became an arc).
- Stroke-width estimator rework — currently overestimates ~15–25%.
- Filled reconstruction mode (stub exists, interface fixed).

## [0.1.0] — 2026-09-20

First checkpoint. Phase 1 vertical slice runs end to end on the real
finance icon sheet and its output is validated in two independent
renderers.

### Added

- Project scaffold: PySide6 UI shell with workflow tabs, `app/domain`
  (dataclass models, `QUndoStack` commands, JSON project store),
  `app/services` split one concern per module.
- `ReconstructionMode` (line/filled/mixed) as a first-class enum with
  strategy dispatch in `reconstruction/base.py`; `filled_mode.py` and
  `mixed_mode.py` present as interface stubs.
- Provider-based naming (`naming/base.py`) with a dependency-free
  `HeuristicNamingProvider` default and an optional
  `Florence2NamingProvider` whose heavy imports are deferred into
  `__init__`.
- `services/preprocessing.py` — Pillow-based JPG/PNG/WebP loading,
  grayscale conversion, 1x/2x/4x analysis upscale.
- `services/segmentation.py` — threshold, connected components, speckle
  rejection, proximity merging, reading-order banding.
- `services/geometry/centerline.py` — skeleton-graph tracing with
  neighbour-cluster degree classification, closed-loop cycle tracing,
  spur pruning, distance-transform stroke-width estimation.
- `services/geometry/primitives.py` — algebraic circle fitting,
  axis-aligned rectangle detection.
- `services/geometry/regularize.py` — trimmed total-least-squares section
  fitting, icon-wide dominant-axis estimation, shared-axis snapping,
  parallel-offset collapsing, vertex rebuilding by line intersection,
  free-endpoint alignment.
- `services/svg_model.py` — SVG document builder emitting `<line>`,
  `<polyline>`, `<circle>`, `<ellipse>`, `<rect>`; validation; 2-decimal
  coordinate formatting; `anchor_count()`.
- `services/quality.py` — multi-signal reporting (SSIM, edge alignment,
  stroke-width consistency, anchor count, fragment count) with
  `manual_review_status` pinned to `"pending"`.
- `services/export.py` — validated single-SVG export.
- 45 unit tests across geometry, regularization, SVG validity,
  segmentation, crop editing, naming and project persistence.
- Reference assets: the real JPEG fixture plus professional SVG
  construction examples and the annotated rough-tracing failure case.
- Documentation: `RUNBOOK.md`, `PROJECT_MEMORY.md`, `QUALITY_LOG.md`,
  `CLAUDE.md`, `README.md`.

### Fixed

- **Icon over-segmentation.** Raw connected components produced 276 crops
  for 50 icons, splitting every icon into its disconnected parts.
  Proximity merging recovers exactly 50, in 5 rows of 10, with no ink
  clipped outside any box.
- **Padding applied per component** rather than once after merging, which
  padded multi-part icons repeatedly.
- **Placeholder reconstruction.** The initial `skeleton_to_segments`
  collapsed every skeleton component to a single straight segment between
  extreme endpoints — meaningless for real geometry. Replaced with full
  skeleton-graph tracing and per-branch primitive selection.
- **Tilted and bowed strokes.** Straight sections followed stair-stepped
  skeleton pixels literally, and snapping only ever reached standalone
  `<line>` elements — segments inside a polyline kept raw pixel
  directions. Now regularized against icon-wide axes, applied inside
  polylines. Near-axis segments that end up exactly axis-aligned went
  from 8/13, 11/14, 9/10, 10/16 to 14/14, 16/16, 18/18, 17/18 on the four
  sampled icons.
- **Standalone details deleted by spur pruning.** The free-end test used
  `or`, so a short branch free at both ends — a dash, a tick — qualified
  as a spur. 2 of 6 dashes on the credit-card icon were being silently
  discarded; all 6 now survive.
- **Zero-length sections** from closed-loop wraparound produced NaN in
  the length-weighted offset averages, corrupting whole outlines.
- **Angle-deviation statistic** ignored the 180° wrap, reporting a
  spurious 179.97° maximum correction.

### Changed

- Removed `snap_angle`/`snap_segment`, which snapped to fixed
  0/45/90/135 targets and would drag a genuine 42° diagonal onto 45°.
  Replaced by data-driven shared-axis estimation.
- Angle tolerance set to 4.0°: real skeleton noise on the test sheet
  reaches 3.4°, so 3.5° dropped genuine cases.
- SVG coordinates rounded to 2 decimals with trailing zeros stripped.

### Known defects

Carried forward and reported honestly; see `QUALITY_LOG.md` for
measurements.

- Rounded corners emit as chamfers; `<rect>` never fires (0/50 icons,
  every rectangle on the sheet is rounded).
- Tight organic curves (the `$` glyph) reconstruct crudely.
- Stroke width overestimated ~15–25%.
- Edge-alignment metric too lenient (returns 1.0000); stroke-consistency
  metric inflated by junction blobs.
- Skeleton endpoint retraction: free ends pull in by ~half a stroke
  width, partly masked by round caps.
- One residual 2.339° deviation on a 9.4px protected corner section.
- Heuristic names are placeholders (`outline-icon`) and feed filenames.
