"""Line-icon reconstruction: topology first, geometry second.

Processing order, and why it is this order:

1. Build and clean the skeleton graph (`geometry/topology.py`).
2. Identify components, endpoints, junctions and closed loops.
3. Pair branches at each junction by tangent continuity, *before* any
   fitting, so a stroke that passes through a crossing is reassembled
   whole. This is what keeps the dollar sign's vertical stroke and its
   S-curve as two continuous strokes instead of four unrelated arcs.
4. Classify each whole stroke, never a fragment.
5. Generate competing primitive candidates for it.
6. Accept a replacement only if it preserves topology and clearly
   improves the fit (`geometry/candidates.evaluate_gate`).
7. Otherwise keep the baseline straight/polyline reconstruction.

Only baseline (straight) geometry is handed to the icon-wide axis
alignment; curves are never snapped. Degenerate and duplicate elements
are removed before emission.

An earlier per-branch curve classifier is preserved for reference at tag
`failed-experiment/curve-classification-v1`; it fitted fragments without
a graph and produced zero-length elements, split glyphs, and open paths
wrongly closed with `Z`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.geometry.candidates import (
    Candidate,
    arc_candidate,
    composite_candidate,
    corner_polyline_candidate,
    baseline_candidate,
    bezier_chain_candidate,
    circle_candidate,
    deduplicate,
    ellipse_candidate,
    evaluate_gate,
    polygon_candidate,
    sharp_corner_indices,
    sharp_corner_points,
    rounded_rect_candidate,
    straight_candidate,
)
from app.services.geometry.centerline import (
    binarize_for_skeleton,
    estimate_stroke_width,
    extract_skeleton,
)
from app.services.geometry.curve_fit import detect_corners, tangent_turning
from app.services.geometry.regularize import (
    FittedLine,
    RegularizationStats,
    align_offsets,
    classify_sections,
    estimate_dominant_axes,
    snap_sections,
)
from app.services.geometry.topology import (
    SkeletonGraph,
    assemble_strokes,
    build_graph,
    pair_at_junctions,
    prune_graph_spurs,
    topology_signature,
)
from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import (
    SvgDocument,
    SvgLine,
    SvgPolyline,
    StrokeStyle,
)


@dataclass
class StrokeDecision:
    stroke_index: int
    chosen: str
    baseline_error: float
    chosen_error: float
    confidence: float
    rejected: list[tuple[str, str]] = field(default_factory=list)
    needs_review: bool = False


@dataclass
class LineModeDiagnostics:
    stroke_width: float
    stroke_widths: np.ndarray
    topology: dict[str, int]
    stroke_count: int
    junction_pairings: int
    element_counts: dict[str, int]
    regularization: RegularizationStats
    decisions: list[StrokeDecision] = field(default_factory=list)
    removed_degenerate: int = 0
    needs_review_count: int = 0


class LineModeStrategy(ReconstructionStrategy):
    def __init__(
        self,
        ink_threshold: int = 200,
        angle_tolerance_degrees: float = 4.0,
        fit_tolerance: float | None = None,
    ) -> None:
        self._ink_threshold = ink_threshold
        self._angle_tolerance_degrees = angle_tolerance_degrees
        self._fit_tolerance = fit_tolerance
        self.diagnostics: LineModeDiagnostics | None = None

    # -- main -----------------------------------------------------------

    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        height, width = crop_grayscale.shape
        binary = binarize_for_skeleton(crop_grayscale, self._ink_threshold)
        skeleton = extract_skeleton(binary)
        stroke_width, stroke_widths = estimate_stroke_width(binary, skeleton)
        stroke_width = stroke_width if stroke_width > 0 else 1.0

        # 1-2. graph, cleaned of cap/corner stubs.
        graph = self._cleaned_graph(skeleton, stroke_width)
        signature = topology_signature(graph)

        # 3. pair branches at junctions before fitting anything.
        pairing = pair_at_junctions(graph)
        strokes = assemble_strokes(graph, pairing)

        tolerance = self._fit_tolerance or max(0.6, stroke_width * 0.3)
        epsilon = max(0.75, stroke_width * 0.35)
        window = max(2, int(round(max(2.0, stroke_width) * 0.75)))

        document = SvgDocument(
            view_box=(0, 0, float(width), float(height)),
            stroke_style=StrokeStyle(
                width=round(stroke_width, 2), color="#000000",
                linecap="round", linejoin="round",
            ),
        )

        decisions: list[StrokeDecision] = []
        straight_elements: list[SvgLine | SvgPolyline] = []
        curve_elements: list = []
        counts: dict[str, int] = {}

        for index, stroke in enumerate(strokes):
            samples = stroke.samples
            if len(samples) < 2:
                continue

            baseline = self._baseline_for(samples, stroke.closed, epsilon, tolerance)

            # "Do not apply curve fitting to straight components": if a
            # straight line already describes the stroke, nothing may
            # replace it, however closely a cubic could chase the pixels.
            if baseline.kind == "line" and baseline.max_error <= tolerance:
                candidates = []
            else:
                candidates = self._candidates_for(
                    samples, stroke.closed, stroke_width, tolerance, window
                )

            decision = StrokeDecision(
                stroke_index=index, chosen=baseline.kind,
                baseline_error=baseline.max_error,
                chosen_error=baseline.max_error, confidence=1.0,
            )
            chosen = baseline

            preferred = self._preferred_kind(
                samples, window, stroke.closed, tolerance
            )
            corners = sharp_corner_points(samples, window, stroke.closed)
            passing: list[tuple[Candidate, float]] = []
            for candidate in candidates:
                gate = evaluate_gate(
                    candidate, baseline, samples, stroke.closed, stroke_width,
                    preferred=(candidate.kind == preferred),
                    corners=corners,
                )
                if gate.accepted:
                    passing.append((candidate, gate.confidence))
                else:
                    decision.rejected.append((candidate.kind, "; ".join(gate.reasons)))

            if passing:
                # Simplest adequate model: among candidates that fit within
                # tolerance, the fewest parameters wins. Sorting by error
                # alone would hand a clean semicircle to an eleven-segment
                # Bezier chain simply because it can chase the pixels
                # closer than a three-parameter arc.
                # The structurally-called-for candidate counts as adequate
                # on the same reasoning the gate uses for it: blur bows a
                # straight run by a pixel, and judging a polygonal chain
                # or a sharp polygon on raw error alone hands the shape to
                # whichever curve can chase that wobble closest.
                adequate = [
                    p for p in passing
                    if p[0].max_error <= tolerance or p[0].kind == preferred
                ]
                if adequate:
                    adequate.sort(key=lambda pair: (
                        pair[0].kind != preferred,
                        pair[0].complexity,
                        round(pair[0].max_error, 3),
                    ))
                    chosen, confidence = adequate[0]
                else:
                    passing.sort(key=lambda pair: (round(pair[0].max_error, 3),
                                                   pair[0].complexity))
                    chosen, confidence = passing[0]
                decision.chosen = chosen.kind
                decision.chosen_error = chosen.max_error
                decision.confidence = confidence
            elif candidates:
                # Every curve candidate was refused: keep the safe result and
                # flag it, rather than shipping a guess.
                decision.needs_review = baseline.max_error > tolerance * 2
                decision.confidence = 0.0

            decisions.append(decision)
            counts[chosen.kind] = counts.get(chosen.kind, 0) + 1

            if chosen is baseline and chosen.kind in ("line", "polyline"):
                straight_elements.extend(chosen.elements)
            else:
                curve_elements.extend(chosen.elements)

        # 7-adjacent: axis alignment applies only to straight output.
        regularization = self._align_straight(straight_elements, stroke_width)

        all_elements = straight_elements + curve_elements
        cleaned = deduplicate(all_elements)
        removed = len(all_elements) - len(cleaned)
        document.elements.extend(cleaned)

        self.diagnostics = LineModeDiagnostics(
            stroke_width=stroke_width,
            stroke_widths=stroke_widths,
            topology=signature,
            stroke_count=len(strokes),
            junction_pairings=len(pairing) // 2,
            element_counts=counts,
            regularization=regularization,
            decisions=decisions,
            removed_degenerate=removed,
            needs_review_count=sum(1 for d in decisions if d.needs_review),
        )
        return document

    # -- stages ---------------------------------------------------------

    @staticmethod
    def _cleaned_graph(skeleton: np.ndarray, stroke_width: float) -> SkeletonGraph:
        """Graph built from the skeleton after spur pruning.

        Pruning runs on traced branches first so cap/corner stubs never
        become graph nodes and split a stroke at a phantom junction.
        """
        graph = build_graph(skeleton)
        return prune_graph_spurs(graph, max_length=max(3.0, stroke_width * 1.5))

    def _baseline_for(self, samples: np.ndarray, closed: bool,
                      epsilon: float, tolerance: float) -> Candidate:
        """Safe fallback: a straight line when the stroke is straight,
        otherwise the RDP polyline."""
        if not closed:
            straight = straight_candidate(samples)
            if straight is not None and straight.max_error <= tolerance:
                return straight
        return baseline_candidate(samples, closed, epsilon)

    @staticmethod
    def _preferred_kind(samples: np.ndarray, window: int, closed: bool,
                        tolerance: float) -> str | None:
        """Which representation the stroke's own character calls for.

        A path whose curvature changes sign cannot be described by arcs:
        an arc has one centre. Such a stroke wants cubics even when a
        chain of arcs happens to fit.

        A stroke a straight line already fits never gets a curve
        preference, whatever the turning profile says — noise on a short
        dash otherwise fakes an inflection and turns it into a cubic.
        """
        from app.services.geometry.candidates import _curvature_sign_splits

        if closed:
            # A closed outline that a three-corner polygon can describe is
            # an arrowhead or triangle and must stay sharp. Asking the
            # polygon fitter directly is more reliable than counting
            # corners on a cycle, where the seam can sit on a corner and
            # hide it.
            from app.services.geometry.candidates import polygon_candidate

            triangle = polygon_candidate(samples, 3, 0.0)
            if triangle is not None and triangle.max_error <= tolerance * 3.0:
                return "polygon"
            return None

        straight = straight_candidate(samples)
        if straight is not None and straight.max_error <= tolerance:
            return None

        # Straight runs meeting at sharp corners outrank any curve: if
        # every run between the raster's own corners is straight, the
        # stroke is a polygonal chain, not a wave that happens to fit.
        chain = corner_polyline_candidate(
            samples, sharp_corner_indices(samples, window, closed),
            closed, tolerance,
        )
        if chain is not None:
            return "corner-polyline"

        if _curvature_sign_splits(samples, window):
            return "bezier"
        return None

    def _candidates_for(self, samples: np.ndarray, closed: bool,
                        stroke_width: float, tolerance: float,
                        window: int) -> list[Candidate]:
        """Competing primitives, chosen by the stroke's own character."""
        out: list[Candidate] = []
        min_radius = max(1.0, stroke_width * 0.6)
        min_sagitta = max(0.8, stroke_width * 0.4)
        turning = tangent_turning(samples, window)
        median_turn = float(np.median(turning)) if turning.size else 0.0

        if closed:
            for maker in (
                lambda: circle_candidate(samples, min_radius),
                lambda: ellipse_candidate(samples),
                lambda: rounded_rect_candidate(samples, stroke_width),
            ):
                candidate = maker()
                if candidate is not None:
                    out.append(candidate)

            corners = detect_corners(samples, window)
            # A three-corner closed component is an arrowhead: keep it sharp.
            for expected in (len(corners) if corners else None, 3):
                candidate = polygon_candidate(samples, expected, stroke_width)
                if candidate is not None:
                    out.append(candidate)
                    break
            return out

        # Open strokes: straight, then constant-curvature, then changing.
        straight = straight_candidate(samples)
        if straight is not None:
            out.append(straight)

        # A chain of straight runs meeting at real corners. Offered
        # before the curve candidates because a zigzag is not a curve.
        corner_indices = sharp_corner_indices(samples, window, closed)
        chain = corner_polyline_candidate(
            samples, corner_indices, closed, tolerance
        )
        if chain is not None:
            out.append(chain)

        # Curve candidates are always offered; the gate and the
        # simplest-adequate rule decide, not a turning heuristic that
        # silently skipped shallow waves.
        arc = arc_candidate(samples, min_radius, min_sagitta)
        if arc is not None:
            out.append(arc)
        bezier = bezier_chain_candidate(samples, window, tolerance * 0.8)
        if bezier is not None:
            out.append(bezier)

        composite = composite_candidate(
            samples, stroke_width, tolerance, window,
            corner_indices=corner_indices,
        )
        if composite is not None:
            out.append(composite)
        return out

    @staticmethod
    def _align_free_ends(pairs: list, tolerance: float,
                         stats: RegularizationStats) -> None:
        """Pull loose ends of snapped straights onto a shared level.

        Bars standing on a common baseline end at the same coordinate in
        the source art; skeletonization leaves those ends a pixel or two
        apart.
        """
        candidates: list[tuple[FittedLine, str, int]] = []
        for _element, _kind, _seg, line in pairs:
            if not line.snapped:
                continue
            axis = 1 if line.orientation == "vertical" else 0
            candidates.append((line, "start", axis))
            candidates.append((line, "end", axis))

        for axis in (0, 1):
            group = [c for c in candidates if c[2] == axis]
            if len(group) < 2:
                continue

            def coord(item) -> float:
                line, which, _ = item
                return float((line.start if which == "start" else line.end)[axis])

            group.sort(key=coord)
            clusters: list[list] = []
            cluster = [group[0]]
            for item in group[1:]:
                if coord(item) - coord(cluster[-1]) <= tolerance:
                    cluster.append(item)
                else:
                    clusters.append(cluster)
                    cluster = [item]
            clusters.append(cluster)

            for members in clusters:
                # A segment shorter than the tolerance has both of its own
                # ends in one cluster; snapping them to a shared coordinate
                # would collapse it to zero length. The short dashes of a
                # dashed rule are exactly this case, and two of them used
                # to disappear from the credit-card icon.
                owners = [id(line) for line, _which, _axis in members]
                collapsing = {owner for owner in owners if owners.count(owner) > 1}
                if collapsing:
                    members = [
                        m for m in members if id(m[0]) not in collapsing
                    ]
                if len(members) < 2:
                    continue
                target = float(np.mean([coord(m) for m in members]))
                for line, which, _ in members:
                    point = line.start if which == "start" else line.end
                    step = line.direction[axis]
                    if abs(step) < 1e-9:
                        continue
                    moved = point + ((target - point[axis]) / step) * line.direction
                    if which == "start":
                        line.start = moved
                    else:
                        line.end = moved
                    stats.endpoints_aligned += 1

    def _align_straight(self, elements: list, stroke_width: float) -> RegularizationStats:
        """Icon-wide axis alignment over straight geometry only."""
        stats = RegularizationStats()
        pairs: list[tuple[object, str, int, FittedLine]] = []

        for element in elements:
            if isinstance(element, SvgLine):
                segments = [((element.x1, element.y1), (element.x2, element.y2))]
            elif isinstance(element, SvgPolyline):
                segments = list(zip(element.points, element.points[1:]))
            else:
                continue
            for seg_index, (a, b) in enumerate(segments):
                start = np.array(a, dtype=float)
                end = np.array(b, dtype=float)
                direction = end - start
                if float(np.linalg.norm(direction)) < 1e-9:
                    continue
                unit = direction / float(np.linalg.norm(direction))
                pairs.append((
                    element,
                    "line" if isinstance(element, SvgLine) else "polyline",
                    seg_index,
                    FittedLine(point=(start + end) / 2, direction=unit,
                               start=start, end=end, pixel_count=0),
                ))

        sections = [p[3] for p in pairs]
        stats.sections_total = len(sections)
        if not sections:
            return stats

        horizontal, vertical = estimate_dominant_axes(
            sections, self._angle_tolerance_degrees
        )
        stats.horizontal_angle = horizontal
        stats.vertical_angle = vertical
        classify_sections(sections, horizontal, vertical, self._angle_tolerance_degrees)
        snap_sections(sections, horizontal, vertical, min_length=0.0,
                      is_standalone=True, stats=stats)
        align_offsets(sections, max(1.0, stroke_width * 0.6), stats)
        self._align_free_ends(pairs, max(1.0, stroke_width * 0.6), stats)

        # Write the corrected geometry back, keeping each element's shape.
        for element, kind, seg_index, line in pairs:
            new_start = line.project(line.start)
            new_end = line.project(line.end)
            if kind == "line":
                element.x1, element.y1 = float(new_start[0]), float(new_start[1])
                element.x2, element.y2 = float(new_end[0]), float(new_end[1])
            else:
                points = list(element.points)
                points[seg_index] = (float(new_start[0]), float(new_start[1]))
                points[seg_index + 1] = (float(new_end[0]), float(new_end[1]))
                element.points = points

        return stats
