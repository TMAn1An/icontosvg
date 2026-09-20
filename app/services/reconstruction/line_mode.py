"""Line-icon reconstruction: centerline -> stroked SVG primitives.

Emits true SVG strokes (fill="none", explicit stroke-width/cap/join) built
only from the extracted centerline — never from raw edge contours — so
blurry outer edges are never traced into a filled shape.

Circles are matched before any straightening, so curved geometry never
reaches the regularizer. Everything else is fit and axis-aligned by
services/geometry/regularize.py, then emitted as the simplest primitive
that fits: <rect> for an axis-aligned rectangular loop, <line> for a
single straight run, <polyline> otherwise.
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
    trace_branches,
)
from app.services.geometry.primitives import fit_circle, is_axis_aligned_rectangle
from app.services.geometry.regularize import RegularizationStats, regularize_branches
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
    regularization: RegularizationStats


class LineModeStrategy(ReconstructionStrategy):
    def __init__(
        self,
        ink_threshold: int = 200,
        simplify_epsilon_ratio: float = 0.35,
        circle_residual_ratio: float = 0.06,
        angle_tolerance_degrees: float = 4.0,
    ) -> None:
        self._ink_threshold = ink_threshold
        self._simplify_epsilon_ratio = simplify_epsilon_ratio
        self._circle_residual_ratio = circle_residual_ratio
        self._angle_tolerance_degrees = angle_tolerance_degrees
        self.diagnostics: LineModeDiagnostics | None = None

    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        height, width = crop_grayscale.shape
        binary = binarize_for_skeleton(crop_grayscale, self._ink_threshold)
        skeleton = extract_skeleton(binary)
        stroke_width, stroke_widths = estimate_stroke_width(binary, skeleton)

        raw_branches = trace_branches(skeleton)
        branches = prune_spurs(raw_branches, skeleton, stroke_width)

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

        # Curved geometry is claimed first and kept out of the regularizer.
        straight_branches: list[np.ndarray] = []
        straight_closed: list[bool] = []
        for branch in branches:
            if self._append_circle(document, branch):
                counts["circle"] += 1
                continue
            straight_branches.append(branch)
            straight_closed.append(is_closed(branch))

        # Simplification tolerance scales with stroke width: a 2px-wide
        # stroke carries finer real detail than a 10px-wide one.
        epsilon = max(0.75, stroke_width * self._simplify_epsilon_ratio)
        chains, regularization = regularize_branches(
            straight_branches,
            straight_closed,
            epsilon=epsilon,
            stroke_width=stroke_width,
            angle_tolerance_degrees=self._angle_tolerance_degrees,
        )

        for vertices, closed in zip(chains, straight_closed):
            kind = self._append_straight_element(document, vertices, closed)
            if kind is not None:
                counts[kind] += 1

        self.diagnostics = LineModeDiagnostics(
            stroke_width=stroke_width,
            stroke_widths=stroke_widths,
            branch_count_raw=len(raw_branches),
            branch_count_after_pruning=len(branches),
            element_counts=counts,
            regularization=regularization,
        )
        return document

    def _append_circle(self, document: SvgDocument, branch: np.ndarray) -> bool:
        if not (is_closed(branch) and len(branch) >= 8):
            return False

        fit = fit_circle(branch)
        if fit.circle.radius <= 1.0:
            return False
        if fit.mean_residual > max(0.6, fit.circle.radius * self._circle_residual_ratio):
            return False

        document.elements.append(
            SvgCircle(cx=fit.circle.cx, cy=fit.circle.cy, r=fit.circle.radius)
        )
        return True

    def _append_straight_element(
        self, document: SvgDocument, vertices: np.ndarray, closed: bool
    ) -> str | None:
        if len(vertices) < 2:
            return None

        if closed and is_axis_aligned_rectangle(np.unique(vertices, axis=0)):
            min_x, min_y = vertices.min(axis=0)
            max_x, max_y = vertices.max(axis=0)
            document.elements.append(
                SvgRect(
                    x=float(min_x),
                    y=float(min_y),
                    width=float(max_x - min_x),
                    height=float(max_y - min_y),
                )
            )
            return "rect"

        if len(vertices) == 2:
            document.elements.append(
                SvgLine(
                    x1=float(vertices[0][0]),
                    y1=float(vertices[0][1]),
                    x2=float(vertices[1][0]),
                    y2=float(vertices[1][1]),
                )
            )
            return "line"

        points = [(float(x), float(y)) for x, y in vertices]
        if closed and points[0] != points[-1]:
            points.append(points[0])
        document.elements.append(SvgPolyline(points=points))
        return "polyline"
