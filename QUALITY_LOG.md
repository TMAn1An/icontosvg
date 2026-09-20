# Quality log

Measured results on real input, with defects recorded honestly. Per the
specification, completion is never claimed from a single score, and no
slice is complete until its exported SVG has been rendered and visually
compared by a human.

Test input: `fixtures/real/finance-icon-sheet.jpg` — 2048x1107 JPEG, RGB,
true white background (all four corner patches 255.00), 5.49% ink at
threshold 128. A 5x10 grid of 50 line icons.

---

## 2026-09-20 — Phase 1 slice, geometry regularization

**Suite:** 45 tests, all passing (Python 3.11.15, PySide6 6.11.2).

### Segmentation

| | result |
|---|---|
| crops detected | **50** (matches the 5x10 grid exactly) |
| rows recovered | 5, ten icons each |
| ink found outside any crop boundary | none |
| crops touching a sheet edge | 0 |
| crop width min/median/max | 72 / 125 / 127 px |
| crop height min/median/max | 61 / 126 / 126 px |

The small outliers are genuine: a flat wallet (126x61) and a narrow
vertical coin slot (72x126), not detection errors.

Before proximity merging this stage produced **276** crops.

### Reconstruction, sampled icons

| icon | subject | elements | anchors | circle/rect/line/polyline |
|---|---|---|---|---|
| crop-31 | monitor + bars | 7 | 29 | 1 / 0 / 2 / 4 |
| crop-2 | credit card | 10 | 38 | 0 / 0 / 7 / 3 |
| crop-35 | presentation board | 20 | 60 | 0 / 0 / 14 / 6 |
| crop-21 | speech bubble `$` | 13 | 48 | 1 / 0 / 3 / 9 |

Across all 50 icons: anchor count min 29, median 76, max 330. No icon
produced hundreds of noisy anchors per shape — the rough-tracing failure
mode is absent.

Stroke width measured at 4.00px uniformly across the sheet.

### Regularization

| icon | sections | snapped H | snapped V | offsets aligned | endpoints aligned | diagonals kept | short protected |
|---|---|---|---|---|---|---|---|
| crop-31 | 22 | 5 | 8 | 0 | 10 | 8 | 1 |
| crop-2 | 28 | 12 | 2 | 5 | 4 | 12 | 2 |
| crop-35 | 40 | 8 | 4 | 6 | 15 | 22 | 6 |
| crop-21 | 35 | 5 | 9 | 0 | 6 | 17 | 4 |
| **all 50** | **3963** | **1452 total (36.6%)** | | **593** | **1985** | **2194** | **317** |

Tilt actually corrected per snapped section: mean 0.215°, median 0.000°,
p95 1.709°, max 3.854°. Exactly 1 of 50 icons was rotated enough to keep
a non-zero shared axis; the other 49 locked to exact 0/90.

**Near-axis segments ending exactly axis-aligned:**

| icon | before | after |
|---|---|---|
| crop-31 | 8/13 | **14/14** |
| crop-2 | 11/14 | **16/16** |
| crop-35 | 9/10 | **18/18** |
| crop-21 | 10/16 | **17/18** |

**Vertex displacement, before to after:**

| icon | mean | median | p95 | max |
|---|---|---|---|---|
| crop-31 | 0.55px | 0.51 | 1.33 | 1.37 |
| crop-2 | 0.93px | 0.04 | 7.00 | 7.00 |
| crop-35 | 0.21px | 0.03 | 0.85 | 1.31 |
| crop-21 | 0.48px | 0.38 | 1.29 | 2.00 |

crop-2's 7px figure is the two *restored* dashes, which had no
counterpart before — not a shift. Nothing is moved far.

### Fidelity scores, and why two regressed

| icon | SSIM before | SSIM after | IoU before | IoU after |
|---|---|---|---|---|
| crop-31 | 0.7748 | 0.7511 | 0.6806 | 0.6491 |
| crop-2 | 0.7765 | **0.8027** | 0.6381 | 0.6324 |
| crop-35 | 0.7870 | **0.8003** | 0.6868 | **0.7042** |
| crop-21 | 0.8204 | 0.7813 | 0.7347 | 0.6852 |

Two icons scored lower after regularization **while being visibly
better**. This was investigated rather than assumed:

- vertex displacement is ≤1.33px at p95 (≤2.0px max), so no geometry is
  being flung anywhere;
- the zoomed comparison of crop-21 shows the tall bar's slanted top and
  leaning legs in "before" rendered flat and vertical in "after".

**Conclusion: SSIM against the source JPEG is an invalid arbiter for
geometry straightening.** It measures pixel overlap with a blurry raster,
so correcting a stroke that genuinely wobbles necessarily reduces overlap
with that wobble. On a 4px stroke, a 1px correction removes roughly 25%
of that stroke's overlap area. Judge such changes by axis-exactness
counts, displacement distribution, and visual review instead.

Scoring against the supplied professional SVG as ground truth was
attempted and is not possible: `docs/reference/finance-icon-sheet.svg` is
a branded 6000x2600 template with a dark preview panel and a different
icon arrangement and scale. It is a construction-quality reference only.

### Export validation

- `validate_svg` — no problems on any exported file.
- No `<image>` element; no masks or clip paths; stable viewBox.
- `fill="none"` with explicit `stroke`, `stroke-width`, `stroke-linecap`,
  `stroke-linejoin`; stroke width in viewBox units.
- Opens and renders correctly in **Qt `QSvgRenderer`** and in **headless
  Chromium**. Agreement between two independent renderers is what
  establishes validity, rather than tolerance by one.
- crop-31 exports at 511 bytes for 7 elements.

### Manual visual review

**Status: `pending` on every icon.** Nothing in the codebase sets any
other value. A human has reviewed the four sampled icons in Chromium and
the findings are the defect list below; the field stays `pending` until
the owner signs off.

---

## Open defects

Ranked by visual impact.

| # | defect | status |
|---|---|---|
| 1 | Rounded corners emit as chamfers — RDP reduces each corner arc to 1–2 straight segments. Now the most visible defect, since the straight edges around them are exact. Needs arc fitting in `curve_fit.py` (still a stub). | open |
| 2 | Tight organic curves reconstruct crudely — the `$` glyph inside crop-21 is mangled. Same root cause as #1. Pre-existing, not caused by regularization. | open |
| 3 | Stroke width overestimated ~15–25%. The distance transform reports exactly 4.00 regardless of threshold (quantized, insensitive); area÷skeleton-length gives ~3.1–3.2px at a tight threshold. Rendered strokes are visibly heavier than the original and this depresses SSIM/IoU independently of shape accuracy. | open |
| 4 | Edge-alignment metric uninformative — a 5x5 dilation tolerance returns 1.0000 even with visible corner errors. Needs 1px tolerance or a distance-percentile report. | open |
| 5 | Stroke-consistency metric inflated — distance-transform width spikes inside junction blobs, mixing topology artifacts into the measurement. | open |
| 6 | Skeleton endpoint retraction — skeletonization pulls free ends in by ~half a stroke width, so short details come out short. Round caps accidentally mask this on long strokes but not short ones. | open |
| 7 | `<rect>` never fires (0/50 icons) — every rectangle on this sheet is rounded, so the rect path is untested on real data. | open |
| 8 | One residual 2.339° deviation on a 9.4px section in crop-21 — a short section inside a polyline, protected to preserve a corner. Correct by design, but "protected" and "should have snapped" are not perfectly separable by length alone. | accepted |
| 9 | Heuristic names are placeholders (`outline-icon`, `outline-wide-icon`) and feed export filenames. Working as designed; real naming needs Florence-2 or manual entry. | by design |

## Resolved defects

| defect | resolution |
|---|---|
| 276 crops for 50 icons | proximity merging; exactly 50 recovered |
| Padding applied per component | applied once after merging |
| Every skeleton component collapsed to one straight segment | full skeleton-graph tracing |
| Tilted/bowed strokes; snapping never reached polyline interiors | icon-wide axis regularization |
| 2 of 6 dashes silently deleted | spur test now requires one free end *and* one junction end |
| NaN from zero-length closed-loop sections | degenerate sections dropped at fit time |
| Spurious 179.97° max correction in stats | wrap-aware angular distance |
| Fixed 0/45/90/135 snapping would drag genuine diagonals | replaced with data-driven axes |
