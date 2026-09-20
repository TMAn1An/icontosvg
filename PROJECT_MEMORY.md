# Project memory

Durable context for Icon Sheet Studio: what was decided, and why. Read
this before changing the geometry pipeline.

## Hard boundary

This is a from-scratch build driven by
`ICON_SHEET_STUDIO_FROM_SCRATCH_SPEC.md` (supplied separately, not
committed). **No previous IconSheetStudio codebase was requested,
inspected, imported, or reused**, and none may be. Only the written
specification and the supplied reference assets informed the design.

## Product goal

Convert a blurry raster icon sheet into separate, named, clean, editable
SVG icons. The target is professional geometric reconstruction — true
strokes and primitives. A basic image trace with hundreds of noisy
anchors is explicitly not acceptable; see
`docs/reference/rough-conversion-reference.png` for the failure mode
being avoided (comb-like double outlines from tracing both edges of a
blurry stroke).

## Stack decision

Single-language: **PySide6 (Qt6) + Python**, one process, no IPC.

Rejected: Tauri/Electron front end with a Python CV backend. It would put
an IPC boundary between the geometry code and the visual feedback loop —
exactly the pair that needs tightest iteration — for no benefit. Qt also
supplies `QUndoStack` (the spec requires command-based history),
`QGraphicsView` (crop boxes, handles) and `QSvgRenderer` (preview and
comparison) directly.

Core deps: Pillow (decoding), OpenCV, scikit-image, NumPy/SciPy, lxml,
svgpathtools. Pillow rather than `cv2.imread` because it handles palette
and ICC-profile cases more consistently across JPG/PNG/WebP.

## Architectural invariants

These are load-bearing. Breaking one reintroduces a defect that was
already diagnosed and fixed.

1. **`ReconstructionMode` (line/filled/mixed) is first-class from day
   one.** `reconstruction/base.py` dispatches on it. Implement filled and
   mixed by filling in `filled_mode.py` / `mixed_mode.py`, *not* by
   restructuring `base.py` or `svg_model.py`.
2. **Line mode works from the skeleton only, never from raw edge
   contours.** This is what structurally prevents blurry outer edges from
   being traced into filled shapes.
3. **Florence-2 must never be required to run the app.**
   `naming/florence2.py` defers its `torch`/`transformers` imports into
   `__init__`, so importing the naming package never needs them. They live
   only in `requirements-naming.txt`. `HeuristicNamingProvider` (zero ML
   deps, deterministic) is the default.
4. **`QualityReport.manual_review_status` starts and stays `"pending"`.**
   Only a human who has viewed the rendered SVG may change it. Nothing in
   the codebase sets any other value.
5. **Curves are claimed before straightening.** Circle fitting runs first
   in `line_mode.reconstruct`, so curved geometry never reaches the
   regularizer.

## Geometry pipeline

```
binarize -> skeletonize -> trace branches -> prune spurs
  -> [circle fit claims curves] -> fit sections -> estimate icon axes
  -> snap to shared axes -> align offsets -> rebuild vertices
  -> align free endpoints -> emit primitives
```

### Segmentation: proximity merging is mandatory

Raw connected components gave **276 crops for 50 icons** — every icon
splits into its disconnected parts (outer outline, inner `$` glyph, and
each individual dash of a dashed line). `segmentation.py` therefore does
threshold -> components -> speckle rejection -> **proximity merge** ->
padding -> reading-order banding, recovering exactly 50.

`MERGE_DISTANCE = 24` must sit between the largest intra-icon gap and the
smallest inter-icon gutter. On this sheet icons are ~130px wide on a
~205px pitch, so gutters are ~75px and intra-icon gaps ~8px. Padding is
applied **once after** merging — applying it per component padded
multi-part icons repeatedly.

### Centerline tracing: topological degree, not neighbour count

`trace_branches` classifies skeleton pixels by the number of *connected
neighbour clusters*, not raw 8-neighbour count. Counting raw neighbours
misreads diagonal staircases: an ordinary path pixel can have three
mutually-adjacent neighbours and would be mistaken for a junction.

### Spur pruning: a spur has ONE free end

A spur hangs off real structure — one free end, one junction end. A short
branch free at **both** ends is a standalone detail (a dash, a tick) and
must be kept regardless of length. The original `or` condition silently
deleted 2 of 6 dashes on the credit-card icon.

### Regularization: axes decided icon-wide, before any vertex

`geometry/regularize.py`. Skeleton pixels are stair-stepped, so following
them literally produces visibly tilted and bowed strokes. Order matters:

- Sections are fit with **trimmed total-least-squares** (orthogonal, so
  near-vertical runs fit as well as horizontal ones).
- The icon's own horizontal and vertical angles are estimated **before**
  anything is classified or moved, length-weighted over doubled angles
  (correct circular statistics for undirected lines), candidates gathered
  in a window of 2x tolerance.
- Every eligible section adopts the shared angle, so related bars and
  edges are parallel **by construction** rather than each independently
  rounded.
- Vertices are then rebuilt as **intersections of the corrected lines**.
  Without this, snapping two adjacent sections independently splits their
  shared corner apart.

Axis estimates **lock to exact 0/90** unless the whole icon is
consistently rotated past the tolerance. Otherwise a single tilted stroke
declares its own tilt to be level — which is exactly what happened on the
first implementation. Only 1 of 50 icons on the real sheet keeps a
rotated axis.

Tolerance is **4.0°**. Real skeleton noise on this sheet reaches 3.4°, so
3.5° dropped genuine cases; 4.0° is the top of the specified 2–4° range.

Three guards protect intent:
- sections outside tolerance stay diagonal;
- short sections *inside* a multi-section run are protected, so rounded
  corners keep their transitions (a standalone short run like a dash is
  still eligible — it has no corner to protect);
- circles never reach the regularizer at all.

**Removed deliberately:** the earlier `snap_angle`/`snap_segment` pair,
which snapped to fixed 0/45/90/135 targets. That would drag a genuine 42°
diagonal onto 45°. Data-driven shared axes replace it; do not reintroduce
fixed-target snapping.

## Measurement caveats

**SSIM against the source JPEG is not a valid arbiter for geometry
straightening.** It measures pixel overlap with a blurry raster, so
correcting a stroke that genuinely wobbles necessarily *reduces* overlap
with that wobble while being more correct as vector art. Two of four
sampled icons scored lower after regularization while being visibly
better. Judge such changes by axis-exactness counts, displacement
distributions, and visual review. Details in `QUALITY_LOG.md`.

Known-weak metrics, not yet fixed: stroke width is overestimated ~15–25%
(the distance transform reports exactly 4.00 regardless of threshold);
edge alignment returns 1.0000 because a 5x5 dilation tolerance is too
lenient; stroke consistency is inflated by junction blobs.

## Model / effort policy

Per `CLAUDE.md`: Opus at high effort for geometry reconstruction,
centerline extraction, curve fitting and quality-metric debugging; Sonnet
at medium for UI, tests, refactoring, docs and straightforward service
work; Haiku at low for mechanical edits only. State current model/effort
before a major task and stop for the user to switch manually rather than
switching unilaterally.

## Status and scope

Phase 1 vertical slice works end to end: upload -> preprocess -> detect ->
crop -> heuristic name -> centerline reconstruction -> clean SVG ->
render -> single-SVG export, validated in two renderers.

Intentionally not built yet: filled mode, mixed mode, ZIP export, the
anchor-point editor, Florence-2 wiring, and the UI tabs beyond
placeholders. The `curve_fit.py` stub is where arc and Bézier fitting
goes — currently the largest remaining visual defect is that rounded
corners come out as chamfers.
