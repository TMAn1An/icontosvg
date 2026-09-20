"""Line-icon reconstruction: centerline -> stroked SVG primitives.

Emits true SVG strokes (fill="none", explicit stroke-width/cap/join) built
only from the extracted centerline — never from raw edge contours — so
blurry outer edges are never traced into a filled shape.

Stage order, and why:

1. `curve_fit.fit_branch` classifies each branch's ordered samples into
   straight sections, sharp corners, circular arcs and cubic Beziers. This
   happens *before* any simplification, so curvature is never discarded by
   a straight-only model.
2. Only the sections classified straight are handed to
   `regularize`'s icon-wide axis alignment. Curves are never snapped.
3. `curve_fit.resolve_joints` closes each joint, keeping sharp corners
   sharp and matching tangents where the source is smooth.
4. Emission picks the narrowest representation: <line>/<polyline> for a
   purely straight branch, <circle> for a full circular loop, <rect> for
   an axis-aligned rectangular loop, and a single <path> mixing L/A/C
   commands whenever one branch needs more than one kind of section.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.geometry.centerline import (
    binarize_for_skeleton,
    estimate_stroke_width,
    extract_skeleton,
    is_closed,
    prune_spurs,
    trace_branches,
)
from app.services.geometry.curve_fit import (
    ArcModel,
    BezierModel,
    BranchFit,
    LineModel,
    fit_branch,
    resolve_joints,
)
from app.services.geometry.primitives import is_axis_aligned_rectangle
from app.services.geometry.regularize import (
    FittedLine,
    RegularizationStats,
    align_offsets,
    classify_sections,
    estimate_dominant_axes,
    snap_sections,
)
from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import (
    PathArcTo,
    PathCubicTo,
    PathLineTo,
    PathMoveTo,
    SvgCircle,
    SvgDocument,
    SvgLine,
    SvgPath,
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
    section_counts: dict[str, int] = field(default_factory=dict)
    corner_count: int = 0
    joint_discontinuities: list[float] = field(default_factory=list)
    fit_errors: dict[str, list[float]] = field(default_factory=dict)


class LineModeStrategy(ReconstructionStrategy):
    def __init__(
        self,
        ink_threshold: int = 200,
        angle_tolerance_degrees: float = 4.0,
        fit_tolerance: float | None = None,
        corner_threshold_degrees: float = 38.0,
    ) -> None:
        self._ink_threshold = ink_threshold
        self._angle_tolerance_degrees = angle_tolerance_degrees
        self._fit_tolerance = fit_tolerance
        self._corner_threshold_degrees = corner_threshold_degrees
        self.diagnostics: LineModeDiagnostics | None = None

    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        height, width = crop_grayscale.shape
        binary = binarize_for_skeleton(crop_grayscale, self._ink_threshold)
        skeleton = extract_skeleton(binary)
        stroke_width, stroke_widths = estimate_stroke_width(binary, skeleton)

        raw_branches = trace_branches(skeleton)
        branches = prune_spurs(raw_branches, skeleton, stroke_width)

        fits = [
            fit_branch(
                branch,
                closed=is_closed(branch),
                stroke_width=stroke_width,
                tolerance=self._fit_tolerance,
                corner_threshold_degrees=self._corner_threshold_degrees,
            )
            for branch in branches
        ]

        regularization = self._align_straight_sections(fits, stroke_width)

        discontinuities: list[float] = []
        for branch_fit in fits:
            discontinuities.extend(
                resolve_joints(branch_fit, max_shift=max(2.0, stroke_width * 2.0))
            )

        # Loose ends are aligned after the joints are closed, so that
        # pulling a bar's foot onto a shared baseline cannot disturb the
        # corner at its other end.
        self._align_free_endpoints(
            fits, max(1.0, stroke_width * 0.6), regularization
        )

        document = SvgDocument(
            view_box=(0, 0, float(width), float(height)),
            stroke_style=StrokeStyle(
                width=round(stroke_width, 2) if stroke_width > 0 else 1.0,
                color="#000000",
                linecap="round",
                linejoin="round",
            ),
        )

        counts = {"circle": 0, "rect": 0, "line": 0, "polyline": 0, "path": 0}
        section_counts: dict[str, int] = {}
        fit_errors: dict[str, list[float]] = {"line": [], "arc": [], "bezier": []}
        corner_count = 0

        for branch_fit in fits:
            if not branch_fit.sections:
                continue
            corner_count += branch_fit.corner_count
            for section in branch_fit.sections:
                kind = section.model.kind
                section_counts[kind] = section_counts.get(kind, 0) + 1
                fit_errors[kind].append(section.model.max_error)

            kind = self._emit(document, branch_fit)
            if kind is not None:
                counts[kind] += 1

        self.diagnostics = LineModeDiagnostics(
            stroke_width=stroke_width,
            stroke_widths=stroke_widths,
            branch_count_raw=len(raw_branches),
            branch_count_after_pruning=len(branches),
            element_counts=counts,
            regularization=regularization,
            section_counts=section_counts,
            corner_count=corner_count,
            joint_discontinuities=discontinuities,
            fit_errors=fit_errors,
        )
        return document

    # -- axis alignment, straights only ---------------------------------

    def _align_straight_sections(
        self, fits: list[BranchFit], stroke_width: float
    ) -> RegularizationStats:
        """Run the icon-wide axis passes over the straight sections only.

        Arcs and Beziers are not represented here at all, so no amount of
        axis alignment can touch a curve.
        """
        stats = RegularizationStats()
        pairs: list[tuple[LineModel, FittedLine]] = []
        for branch_fit in fits:
            for section in branch_fit.sections:
                model = section.model
                if not isinstance(model, LineModel):
                    continue
                pairs.append(
                    (
                        model,
                        FittedLine(
                            point=np.asarray(model.point, dtype=float),
                            direction=np.asarray(model.direction, dtype=float),
                            start=np.asarray(model.start, dtype=float),
                            end=np.asarray(model.end, dtype=float),
                            pixel_count=0,
                        ),
                    )
                )

        sections = [line for _, line in pairs]
        stats.sections_total = len(sections)
        if not sections:
            return stats

        horizontal_angle, vertical_angle = estimate_dominant_axes(
            sections, self._angle_tolerance_degrees
        )
        stats.horizontal_angle = horizontal_angle
        stats.vertical_angle = vertical_angle
        classify_sections(
            sections, horizontal_angle, vertical_angle, self._angle_tolerance_degrees
        )

        # Every entry here is already a straight section, so there is no
        # corner to protect and no minimum length to enforce.
        snap_sections(
            sections,
            horizontal_angle,
            vertical_angle,
            min_length=0.0,
            is_standalone=True,
            stats=stats,
        )
        align_offsets(sections, max(1.0, stroke_width * 0.6), stats)

        for model, line in pairs:
            model.point = line.point
            model.direction = line.direction
            model.snapped = line.snapped
            model.orientation = line.orientation
            # Keep the drawn extent on the corrected line.
            model.start = line.project(model.start)
            model.end = line.project(model.end)

        return stats

    @staticmethod
    def _align_free_endpoints(
        fits: list[BranchFit], tolerance: float, stats: RegularizationStats
    ) -> None:
        """Pull loose ends of axis-aligned straights onto a shared level.

        A bar standing on a baseline ends at the same coordinate in the
        source art; skeletonization leaves those ends a pixel or two
        apart. Only ends belonging to a snapped straight qualify, and only
        within `tolerance`, so this expresses an alignment the raster
        already shows rather than inventing one.
        """
        Candidate = tuple[LineModel, str, int]
        candidates: list[Candidate] = []
        for branch_fit in fits:
            if branch_fit.closed or not branch_fit.sections:
                continue
            for model, which in (
                (branch_fit.sections[0].model, "start"),
                (branch_fit.sections[-1].model, "end"),
            ):
                if not isinstance(model, LineModel) or not model.snapped:
                    continue
                axis = 1 if model.orientation == "vertical" else 0
                candidates.append((model, which, axis))

        for axis in (0, 1):
            group = [c for c in candidates if c[2] == axis]
            if len(group) < 2:
                continue

            def coordinate(candidate: Candidate) -> float:
                model, which, _ = candidate
                point = model.start if which == "start" else model.end
                return float(point[axis])

            group.sort(key=coordinate)
            clusters: list[list[Candidate]] = []
            cluster = [group[0]]
            for candidate in group[1:]:
                if coordinate(candidate) - coordinate(cluster[-1]) <= tolerance:
                    cluster.append(candidate)
                else:
                    clusters.append(cluster)
                    cluster = [candidate]
            clusters.append(cluster)

            for members in clusters:
                if len(members) < 2:
                    continue
                target = float(np.mean([coordinate(member) for member in members]))
                for model, which, _ in members:
                    point = model.start if which == "start" else model.end
                    step = model.direction[axis]
                    if abs(step) < 1e-9:
                        continue
                    moved = point + ((target - point[axis]) / step) * model.direction
                    if which == "start":
                        model.start = moved
                    else:
                        model.end = moved
                    stats.endpoints_aligned += 1

    # -- emission --------------------------------------------------------

    def _emit(self, document: SvgDocument, branch_fit: BranchFit) -> str | None:
        sections = branch_fit.sections
        models = [section.model for section in sections]

        if len(models) == 1 and isinstance(models[0], ArcModel) and branch_fit.closed:
            arc = models[0]
            if arc.sweep_degrees >= 330.0:
                document.elements.append(
                    SvgCircle(
                        cx=float(arc.center[0]),
                        cy=float(arc.center[1]),
                        r=float(arc.radius),
                    )
                )
                return "circle"

        if all(isinstance(model, LineModel) for model in models):
            vertices = [np.asarray(models[0].start, dtype=float)]
            vertices.extend(np.asarray(model.end, dtype=float) for model in models)
            if branch_fit.closed and len(vertices) > 2:
                vertices[-1] = vertices[0]

            if branch_fit.closed and is_axis_aligned_rectangle(
                np.unique(np.vstack(vertices), axis=0)
            ):
                stacked = np.vstack(vertices)
                min_x, min_y = stacked.min(axis=0)
                max_x, max_y = stacked.max(axis=0)
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

            document.elements.append(
                SvgPolyline(points=[(float(v[0]), float(v[1])) for v in vertices])
            )
            return "polyline"

        commands = [
            PathMoveTo(x=float(models[0].start[0]), y=float(models[0].start[1]))
        ]
        for model in models:
            if isinstance(model, LineModel):
                commands.append(PathLineTo(x=float(model.end[0]), y=float(model.end[1])))
            elif isinstance(model, ArcModel):
                commands.append(
                    PathArcTo(
                        rx=float(model.radius),
                        ry=float(model.radius),
                        large_arc=model.sweep_degrees > 180.0,
                        # SVG sweeps in the direction of increasing angle,
                        # which in image coordinates is the non-clockwise
                        # flag from the fit.
                        sweep=not model.clockwise,
                        x=float(model.end[0]),
                        y=float(model.end[1]),
                    )
                )
            elif isinstance(model, BezierModel):
                commands.append(
                    PathCubicTo(
                        x1=float(model.p1[0]),
                        y1=float(model.p1[1]),
                        x2=float(model.p2[0]),
                        y2=float(model.p2[1]),
                        x=float(model.p3[0]),
                        y=float(model.p3[1]),
                    )
                )

        document.elements.append(SvgPath(commands=commands, closed=branch_fit.closed))
        return "path"
