"""Line-icon reconstruction: centerline -> stroked SVG primitives.

Emits true SVG strokes (fill="none", explicit stroke-width/cap/join) built
only from the extracted centerline — never from raw edge contours — so
blurry outer edges are never traced into a filled shape.

Each traced branch becomes the simplest primitive that fits it:
<circle> for a closed circular loop, <rect> for an axis-aligned
rectangular loop, <line> for a straight run, <polyline> otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.geometry.centerline import (
    binarize_for_skeleton,
    estimate_stroke_width,
    extract_skeleton,
    is_closed,
    prune_spurs,
    simplify_branch,
    trace_branches,
)
from app.services.geometry.primitives import (
    LineSegment,
    fit_circle,
    is_axis_aligned_rectangle,
    snap_segment,
)
from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import (
    SvgCircle,
    SvgDocument,
    SvgLine,
    SvgPolyline,
    SvgRect,
    StrokeStyle,
)


@dataclass
class LineModeDiagnostics:
    """Intermediate measurements, surfaced to the Quality tab."""

    stroke_width: float
    stroke_widths: np.ndarray
    branch_count_raw: int
    branch_count_after_pruning: int
    element_counts: dict[str, int]


class LineModeStrategy(ReconstructionStrategy):
    def __init__(
        self,
        ink_threshold: int = 200,
        simplify_epsilon_ratio: float = 0.35,
        circle_residual_ratio: float = 0.06,
    ) -> None:
        self._ink_threshold = ink_threshold
        self._simplify_epsilon_ratio = simplify_epsilon_ratio
        self._circle_residual_ratio = circle_residual_ratio
        self.diagnostics: LineModeDiagnostics | None = None

    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        height, width = crop_grayscale.shape
        binary = binarize_for_skeleton(crop_grayscale, self._ink_threshold)
        skeleton = extract_skeleton(binary)
        stroke_width, stroke_widths = estimate_stroke_width(binary, skeleton)

        raw_branches = trace_branches(skeleton)
        branches = prune_spurs(raw_branches, skeleton, stroke_width)

        # Simplification tolerance scales with stroke width: a 2px-wide
        # stroke carries finer real detail than a 10px-wide one.
        epsilon = max(0.75, stroke_width * self._simplify_epsilon_ratio)

        document = SvgDocument(
            view_box=(0, 0, float(width), float(height)),
            stroke_style=StrokeStyle(
                width=round(stroke_width, 2) if stroke_width > 0 else 1.0,
                color="#000000",
                linecap="round",
                linejoin="round",
            ),
        )

        counts = {"circle": 0, "rect": 0, "line": 0, "polyline": 0}
        for branch in branches:
            element_kind = self._append_element(document, branch, epsilon)
            counts[element_kind] += 1

        self.diagnostics = LineModeDiagnostics(
            stroke_width=stroke_width,
            stroke_widths=stroke_widths,
            branch_count_raw=len(raw_branches),
            branch_count_after_pruning=len(branches),
            element_counts=counts,
        )
        return document

    def _append_element(self, document: SvgDocument, branch: np.ndarray, epsilon: float) -> str:
        closed = is_closed(branch)

        if closed and len(branch) >= 8:
            fit = fit_circle(branch)
            if (
                fit.circle.radius > 1.0
                and fit.mean_residual <= max(0.6, fit.circle.radius * self._circle_residual_ratio)
            ):
                document.elements.append(
                    SvgCircle(cx=fit.circle.cx, cy=fit.circle.cy, r=fit.circle.radius)
                )
                return "circle"

        simplified = simplify_branch(branch, epsilon, closed)

        if closed and is_axis_aligned_rectangle(simplified):
            min_x, min_y = simplified.min(axis=0)
            max_x, max_y = simplified.max(axis=0)
            document.elements.append(
                SvgRect(
                    x=float(min_x),
                    y=float(min_y),
                    width=float(max_x - min_x),
                    height=float(max_y - min_y),
                )
            )
            return "rect"

        if len(simplified) == 2:
            segment = snap_segment(
                LineSegment(
                    x1=float(simplified[0][0]),
                    y1=float(simplified[0][1]),
                    x2=float(simplified[1][0]),
                    y2=float(simplified[1][1]),
                )
            )
            document.elements.append(
                SvgLine(x1=segment.x1, y1=segment.y1, x2=segment.x2, y2=segment.y2)
            )
            return "line"

        points = [(float(x), float(y)) for x, y in simplified]
        if closed and points[0] != points[-1]:
            points.append(points[0])
        document.elements.append(SvgPolyline(points=points))
        return "polyline"
