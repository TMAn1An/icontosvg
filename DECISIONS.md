# Decisions

Dated record of significant technical decisions for Icon Sheet Studio,
each with the problem, the chosen solution, alternatives considered, the
reason for the choice, and its consequences/limitations. See
`PROJECT_MEMORY.md` for the synthesized architecture and
`QUALITY_LOG.md` for the numeric evidence behind several of these.

---

## 2026-09-20 — Single-process PySide6 stack, no IPC

**Problem.** The application needs both a desktop UI (crop editing,
undo/redo, an eventual anchor/handle editor) and a heavy CV/geometry
pipeline (OpenCV, scikit-image, custom fitting code). These could live in
one process or be split across a UI process and a backend process.

**Chosen solution.** Single Python process, PySide6 (Qt6) for the UI,
same process for all preprocessing/segmentation/geometry/SVG work. No
IPC boundary.

**Alternatives considered.** A Tauri or Electron front end (JS/TS,
richer web-canvas ecosystem) talking to a separate Python backend process
over IPC or a local HTTP API, giving each half its "native" tooling.

**Reason.** The UI's most important job — showing the user what the
geometry pipeline just produced, so it can be corrected — is exactly the
loop that benefits least from a process boundary. Every debugging or
tuning cycle for the geometry code needs a fast round-trip to a rendered
result. An IPC boundary adds serialization, versioning, and process-
lifecycle complexity for no offsetting benefit, since nothing about this
project needs the web UI ecosystem specifically. PySide6 also directly
supplies `QUndoStack` (the spec requires command-based undo history),
`QGraphicsView` (needed for crop boxes and future anchor handles), and
`QSvgRenderer` (needed for the compare view) — three requirements met by
the same dependency.

**Consequences and limitations.** Ties the project to Qt's threading
model for anything long-running (batch processing, Phase 4) — CPU-heavy
geometry work will need to move off the UI thread eventually via
`QThread` or a process pool, which was not yet needed for the Phase 1
vertical slice. Running headless (tests, CI, containers) requires
`QT_QPA_PLATFORM=offscreen` and system GL/EGL libraries that slim
containers may not have preinstalled (`RUNBOOK.md` documents the fix).

---

## 2026-09-20 — `ReconstructionMode` as a first-class enum from the start

**Problem.** The spec requires line, filled, and mixed reconstruction
modes, but only line mode was going to be implemented in the first
slice. A design was needed that would not require restructuring once
filled/mixed logic is added.

**Chosen solution.** `ReconstructionMode(str, Enum)` with `LINE | FILLED
| MIXED` defined immediately; `reconstruction/base.py` defines
`ReconstructionStrategy` (ABC) and `get_strategy(mode)` dispatch;
`filled_mode.py`/`mixed_mode.py` exist from the first commit as files
containing a class that raises `NotImplementedError`.

**Alternatives considered.** Implement only a `LineModeStrategy` function
directly, with no enum or dispatch layer, and add the abstraction later
when filled mode is actually built.

**Reason.** Retrofitting a mode enum after callers already assume "there
is only line mode" tends to leak that assumption into `Icon.
reconstruction_mode` defaults, UI mode selectors, and export logic in
ways that are easy to miss. Establishing the full three-way shape up
front, even with two branches stubbed, means every future change to
filled/mixed mode is additive (fill in the stub file) rather than a
refactor of `base.py`/`svg_model.py`.

**Consequences and limitations.** Two files (`filled_mode.py`,
`mixed_mode.py`) currently exist purely to raise `NotImplementedError`
and have no test coverage beyond "the interface exists" — they add a
small amount of dead weight to the codebase until implemented.

---

## 2026-09-20 — Florence-2 naming: deferred imports, never a hard requirement

**Problem.** The spec requires local, non-hosted naming via a
vision-language model (Florence-2 suggested), but `torch`/`transformers`
are large, sometimes GPU-dependent dependencies that should never block
someone from running the rest of the application.

**Chosen solution.** `NamingProvider` ABC in `naming/base.py`.
`HeuristicNamingProvider` (zero ML dependencies) is the default.
`Florence2NamingProvider` exists in `naming/florence2.py`, but its
`torch`/`transformers` imports happen **inside `__init__`**, not at
module scope, and its heavy dependencies are listed only in
`requirements-naming.txt`, never in `requirements.txt` or
`requirements-dev.txt`.

**Alternatives considered.** Making Florence-2 the only naming provider
and treating `torch`/`transformers` as core requirements; or feature-
flagging naming entirely off by default.

**Reason.** The spec explicitly says "do not depend on a hosted API" and
implies naming should degrade gracefully; a multi-gigabyte ML dependency
that fails to install (no CUDA, disk space, network) should never prevent
importing `app.services.naming` or running the rest of the pipeline.
Deferred imports mean `import app.services.naming.florence2` succeeds
even without `torch` installed — only *instantiating*
`Florence2NamingProvider` requires it, and that only happens if a caller
explicitly asks for it.

**Consequences and limitations.** `Florence2NamingProvider.suggest_name`
is currently a stub (`NotImplementedError`) — the deferred-import
machinery is verified, but no real captioning-to-slug pipeline exists
yet. `HeuristicNamingProvider` names are not meant to be accurate and
currently leak into export filenames (e.g. `outline-icon-crop-31.svg`).

---

## 2026-09-20 — Proximity merging is mandatory in segmentation

**Problem.** Running raw 8-connected-component detection on the real
50-icon finance sheet produced **276** crops, not 50 — every icon with a
disconnected part (an outer outline plus an inner glyph, or a dashed
line) was split into one crop per component.

**Chosen solution.** After connected-component detection and speckle
rejection, iteratively union any two boxes that overlap or sit within
`MERGE_DISTANCE = 24` px of each other, repeating to convergence, before
applying padding once and sorting into reading order.

**Alternatives considered.** (a) Grid-based slicing assuming a fixed N-
column x M-row layout, read from user-specified counts; (b) contour-
hierarchy grouping (parent/child contour relationships); (c) no merging,
relying on the user to manually merge crops in the UI.

**Reason.** Grid slicing (a) would work for this one regularly-gridded
sheet but is fragile to irregular layouts and was rejected as
insufficiently general for the spec's requirement to detect "icons made
from several disconnected parts" on arbitrary sheets. Contour hierarchy
(b) is a reasonable Phase 2 refinement but proximity merging was simpler
to get right first and directly measurable. Relying on manual merging (c)
would mean shipping a segmentation stage that is wrong 5x over by
default, contradicting the spec's "never discard a detected region
without user-visible feedback" in spirit if not letter — 226 spurious
crops is not a usable starting point for manual correction.

**Consequences and limitations.** `MERGE_DISTANCE` is currently a single
constant (24px) tuned to this sheet's specific geometry (icons ~130px
wide on a ~205px pitch, ~75px gutters, ~8px intra-icon gaps). A sheet
with a much tighter or looser layout would need this retuned or made
adaptive to the sheet's own measured icon pitch — not yet implemented.

---

## 2026-09-20 — Padding applied once, after merging, not per component

**Problem.** Early segmentation applied padding to each raw connected
component's box before merging. For a multi-part icon (several raw
components), this meant padding was added once per part, inflating the
final merged box far beyond the intended margin.

**Chosen solution.** Merge first (on unpadded boxes), then apply the
padding exactly once to each final merged box.

**Alternatives considered.** Padding per-component and taking the union
of the padded boxes (equivalent in effect to padding once, but more
code); tracking a per-crop padding budget.

**Reason.** Padding once after merging is both simpler and directly
correct — there is no scenario where a multi-part icon should have more
margin than a single-part one.

**Consequences and limitations.** None identified; this was a
straightforward ordering bug.

---

## 2026-09-20 — Spur pruning requires exactly one free end, not "any free end"

**Problem.** `prune_spurs` was deleting short branches that had **any**
free (non-junction) end, intending to remove stroke-cap/corner
artifacts. On the real credit-card icon, this deleted 2 of the 6 dashes
in its dashed line — a dash is free at *both* ends and was being treated
as a spur.

**Chosen solution.** A branch is a spur (removable) only if it has
**exactly one** free end and its other end is a junction (degree ≥ 3). A
branch free at both ends is kept regardless of length.

**Alternatives considered.** Length-only thresholding with no topology
check (what was originally implemented, and the source of the bug);
whitelisting specific glyph shapes known to contain dashes.

**Reason.** The topological distinction is exactly what separates "an
artifact hanging off real structure" (one attached end) from "a
standalone piece of intended geometry" (no attached end at all). No
glyph-specific whitelist is needed once the correct general rule is
identified.

**Consequences and limitations.** None identified after the fix;
verified by `test_short_dashes_are_not_pruned_away` and by direct
inspection of the real credit-card icon (all 6 dashes present after the
fix).

---

## 2026-09-20 — Data-driven shared-axis snapping, not fixed 0/45/90/135° targets

**Problem.** The first regularization implementation snapped any
near-axis or near-diagonal segment to the nearest of a fixed set of
target angles (0°, 45°, 90°, 135°, and their negatives/supplements).

**Chosen solution.** Estimate each icon's own horizontal and vertical
angle from its own straight sections (length-weighted circular mean),
locking to exact 0°/90° only when the icon is not consistently rotated
past tolerance; snap eligible sections to *those* icon-specific angles,
not to a fixed universal set.

**Alternatives considered.** Keeping the fixed-target snapping but adding
a special case to skip it for angles far from any of the four targets;
widening or narrowing the fixed-target tolerance.

**Reason.** Fixed 45° snapping is explicitly what the user's instructions
forbid ("do not snap intentional diagonals") and was demonstrably wrong:
a genuine 42° diagonal line would be dragged to exactly 45°, a visible
and incorrect distortion. Estimating axes from the icon's own evidence
instead means a diagonal that isn't near *this icon's* horizontal or
vertical axis is simply left alone — there is no arbitrary universal
target for it to be dragged toward.

**Consequences and limitations.** Icons with very few straight sections
(e.g., a single diagonal line and nothing else) have no basis for
axis estimation and default to exact 0°/90° candidates that may not
apply — acceptable because such an icon has nothing to snap to those
axes anyway (no sections are classified as near-horizontal/vertical in
the first place).

---

## 2026-09-20 — SSIM/IoU against the source JPEG rejected as an acceptance test

**Problem.** After implementing geometry regularization, SSIM and IoU
against the source JPEG *decreased* on 2 of 4 sampled icons, despite the
geometry being visibly straighter and more correct. The same pattern
recurred after curve classification (SSIM decreased on all 4 sampled
icons in that round). A metric that penalizes a visibly correct fix
cannot be used as a pass/fail gate.

**Chosen solution.** Do not use SSIM/IoU against the source raster as an
acceptance criterion for geometry-straightening or curve-classification
changes. Instead: measure vertex displacement (proving a correction is
small even when it changes a pixel-overlap score), axis-exactness counts
(segments landing at exactly the target angle), fit error against
tolerance (recorded per model in diagnostics), and require an actual
side-by-side visual render in two independent SVG renderers before
calling a change good.

**Alternatives considered.** Scoring against the supplied professional
`finance-icon-sheet.svg` as a pixel-registered ground truth instead —
investigated and found impossible, since that file is a different
branded 6000x2600 template at a different scale/layout, not a registered
version of the JPEG fixture. Also considered: adjusting SSIM's parameters
(window size, Gaussian weighting) to be less sensitive to sub-pixel
shifts — not pursued, since the underlying problem (SSIM measures overlap
with the *source's own blur*, and correcting real wobble in the source
necessarily reduces that overlap) is structural, not a parameter-tuning
issue.

**Reason.** SSIM/IoU against a blurry raster measure similarity to the
raster's own noise, not correctness of the reconstructed vector geometry.
A 1px correction on a 4px stroke removes roughly a quarter of that
stroke's pixel overlap with the source while making the output more
correct.

**Consequences and limitations.** There is currently no single automated
number that can gate "is this reconstruction good." This is treated as
correct rather than as a gap to close — the spec itself says "do not
claim professional quality from one score" — but it does mean quality
tracking in `QUALITY_LOG.md` requires a human to actually look at
renders, which does not scale to fully automated CI quality gates.

---

## 2026-09-20 — Curve classification runs before simplification, with physical gates on arc acceptance

**Problem.** The reconstruction pipeline's only open-geometry model was a
straight line. Ramer–Douglas–Peucker simplification shredded every
smooth bend (34% of the real sheet's centerline length, by measurement)
into short chords that were each individually within tolerance but had
collectively stopped representing a curve — visible as a faceted
"octagon" ring and a mangled dollar-sign glyph. A naive fix (fit an arc
wherever the residual allows) initially introduced a *new* defect:
straight edges with a little JPEG bow were being promoted to visibly
domed shallow arcs, and the dollar sign's fine detail was fit with arcs
finer than its own stroke width.

**Chosen solution.** `curve_fit.py` classifies each branch's ordered
samples into straight/corner/arc/cubic sections **before** any RDP-style
simplification, choosing the simplest model (line, 2 dof; arc, 3 dof;
cubic Bézier, 6 dof) whose worst residual fits a sub-pixel tolerance,
subject to two additional physical gates on arcs: sagitta ≥ 0.4x stroke
width (rejects shallow arcs standing in for bowed straights) and radius
≥ 0.6x stroke width (rejects sub-stroke-width curvature as skeleton
noise). Only sections classified straight are ever passed to
`regularize.py`'s axis-snapping.

**Alternatives considered.** (a) Fitting an arc/cubic to the whole
skeleton branch at once with no error-ratio or physical gate, accepting
whatever the residual-tolerance check alone allowed — tried first,
produced the domed-edge and sub-stroke-arc defects above, both confirmed
by direct measurement and visual render. (b) An error-ratio gate (arc
must beat the line's residual by some factor) instead of a physical
sagitta/radius floor — tried, then removed: redundant once tolerance-
based selection already prefers a line that fits, and it rejected valid
short arcs the physical gates would have accepted. (c) Hard-coding
recognition of common glyph shapes (e.g. a `$` template) — explicitly
rejected per the user's instruction not to special-case the dollar sign;
the classifier must work from geometric evidence only.

**Reason.** Physical gates (sagitta, radius, both relative to the
measured stroke width) tie acceptance to a quantity that has real
meaning at the scale of the actual drawn stroke, rather than to an
abstract residual-ratio comparison between two curve fits. This is what
let a straight edge with sub-stroke JPEG bow be correctly recognized as
"still a straight edge" while a genuinely rounded corner of comparable
residual is correctly recognized as an arc.

**Consequences and limitations.** The sagitta floor (0.4x stroke width)
is deliberately conservative and currently rejects some genuinely rounded
corners — on the real credit-card icon, only 1 of 4 corners cleared the
bar; the other 3 remain straight-line chamfers (masked visually by
`stroke-linejoin="round"` at this sheet's stroke width, but not actually
fit as arcs). Loosening the floor risks reintroducing the domed-straight-
edge defect it was added to prevent; this tension is recorded as pending
work (`PROJECT_MEMORY.md` §24 item 2) rather than resolved.

---

## 2026-09-20 — Junction routing explicitly out of scope for the curve fitter

**Problem.** The dollar-sign glyph's S-curve is crossed by the vertical
bar of the `$`, and the skeleton graph treats that crossing as a
junction, splitting the S into several short fragments. A fragment short
enough loses the "changing curvature" signal that would otherwise select
a cubic Bézier, and gets fit with an arc instead — visually acceptable
locally but not the single continuous S the source art actually draws.

**Chosen solution.** Treat this as a **junction-routing** problem, not a
curve-fitting problem, and explicitly do not attempt to fix it inside
`curve_fit.py`. Verify instead (via
`test_s_curve_uses_beziers_and_never_a_single_arc`) that the curve fitter
correctly produces cubics on an *unfragmented* S, proving the fitter
itself is not the defect.

**Alternatives considered.** Post-hoc stitching: detect that several
short fragments meeting at a junction plausibly continue one another's
curvature and re-fit them as one cubic across the junction. Considered
but not attempted in this iteration — it requires deciding *which* of
several arms at a junction continue each other, which is a routing
decision the curve fitter has no information to make (it only sees one
branch's samples at a time).

**Reason.** The user's own instructions were explicit that "a smooth
curve fitter cannot repair incorrectly connected branches" — conflating
the two would make `curve_fit.py` responsible for a class of defect it
structurally cannot diagnose (it never sees the junction's other arms at
all). Keeping the boundary clean means the fix, when it happens, belongs
in `centerline.trace_branches`'s junction-walking logic instead.

**Consequences and limitations.** This is the single largest remaining
visible defect on the real sheet (`PROJECT_MEMORY.md` §20a) and is not
yet fixed. Any future fix must change how branches are routed through
junction nodes, informed by the geometry of all arms meeting there — not
by anything in `curve_fit.py`.

## 2026-09-20 — Topology resolved before geometry, not alongside it

**Problem.** The per-branch curve classifier (`f2b3f64`) fitted each
skeleton branch in isolation. A stroke that crosses another arrives as
several short fragments, and no fitter working on one fragment at a time
can tell that four ~15px pieces are really two continuous strokes. The
visible result on the dollar sign was a shredded glyph; the user
rejected the whole change as a quality regression.

**Chosen solution.** A skeleton graph is built and cleaned first;
branches are paired at each junction by tangent continuity; strokes are
assembled through those pairings; only then is anything classified, and
only whole strokes are ever classified. `services/geometry/topology.py`
owns stages 1–4, `candidates.py` stages 5–6, `line_mode.py` stage 7.

**Alternatives considered.** (a) Post-hoc stitching — fit fragments,
then try to detect which results continue each other. Rejected: by the
time a fragment has been fitted to an arc, the evidence that would have
shown it was half of an S is gone. (b) Fitting across junctions by
extending each fragment's fit and testing overlap. Rejected as a more
expensive way to make the same routing decision, but later and with
worse information. (c) Keeping the previous entry's position that
junction routing was out of scope for the fitter — that boundary was
correct, and this change resolves the routing on the *other* side of it,
in graph construction, exactly as that entry said any fix would have to.

**Reason.** Connectivity is evidence the raster supplies directly and
cheaply; curvature is inferred. Spending the cheap, reliable evidence
first constrains every later inference. The inverse order throws the
connectivity away and then tries to recover it from the inferences.

**Consequences and limitations.** Node degree must be exactly right, and
this is where the old pipeline actually failed: degree computed by
clustering 8-adjacent neighbours reports the centre of a `+` as degree
1, because the four arm pixels are mutually diagonally adjacent. The
Rutovitz crossing number is now used instead, and any future change to
degree computation risks silently reintroducing the whole class of
defect. Pairing is greedy on the most nearly opposite tangents with a
115° minimum, so three or more strokes crossing at one point may pair
wrongly; nothing on the test sheet does this, and nothing detects it.

## 2026-09-20 — Corner preservation as a veto, tested on the tangent and not only the distance

**Problem.** "Do not round sharp corners" cannot be enforced by fit
error. A cubic can thread a zigzag's peak within one pixel — an
excellent score — and still arrive with a smooth tangent, which is
exactly how the chart arrow's sharp peaks became waves.

**Chosen solution.** Two vetoes in `evaluate_gate`. Every corner the
raster shows must lie within `0.6 x stroke width` of the candidate
outline, *and* the turn measured on the candidate over a fixed arc
length (`1.5 x stroke width`) must be at least half the turn measured
the same way on the pixels, for any corner turning 35° or more.
Measuring both curves over the same arc-length span is what makes the
two numbers comparable.

**Alternatives considered.** (a) Distance only — shown above not to
work. (b) Forbidding curve candidates wherever a corner is detected —
too blunt: a rounded rectangle has four real corners *and* a real
radius. (c) Penalising candidates in a score instead of vetoing them —
rejected because the user's requirement is a gate, and a penalty can
always be outvoted by a large enough error improvement.

**Reason.** A corner is a structural claim about the shape, not a
tolerance. A veto states that claim; a weight negotiates it away.

**Consequences and limitations.** `detect_corners`'s 38° threshold sets
what counts as a corner, so shallow corners are still invisible to this
gate. The retention ratio (0.5) and the turn floor (35°) are tuned
constants, not derived. A candidate can satisfy both tests and still
round a corner slightly — crop-31's tall bar top is a live example.

## 2026-09-20 — A chain of straight runs is a first-class candidate

**Problem.** Between the whole-stroke straight candidate and the curve
candidates there was nothing representing "several straight runs meeting
at sharp corners". A zigzag therefore competed as a single line (hopeless)
or as cubics (wins on error, loses the corners).

**Chosen solution.** `corner_polyline_candidate`: fit a line to each run
between consecutive detected corners, meet adjacent runs at their
intersection, emit a `<polyline>`. Offered only when *every* run is
straight within `1.5 x tolerance`, and then *preferred*, so it outranks
any curve.

**Alternatives considered.** (a) Relying on the RDP baseline, which also
has sharp corners — rejected: RDP places vertices on sample points, so
its corners sit wherever the skeleton rounded them, and its error is
worse than a cubic's, so it loses selection. (b) Letting the composite
fitter produce it — rejected: composite is greedy left-to-right and does
not know where the corners are until told, and its pieces meet at sample
points rather than intersections.

**Reason.** Intersecting the two adjacent fits recovers the corner the
raster lost to stroke width and blur, which is the one place where the
reconstruction can legitimately be *sharper* than the pixels.

**Consequences and limitations.** The `1.5 x tolerance` run slack is
tuned: too tight and a plainly polygonal zigzag falls to a cubic (it
did, at 1.0x); too loose and a gently curved stroke is faceted. The
preference makes this candidate outrank curves whenever it exists, so a
shape that is genuinely part-polygon, part-curve gets the polygon
reading. Closed strokes are excluded — `polygon_candidate` covers those.
