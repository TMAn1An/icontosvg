"""Geometric regularization of traced centerlines.

Skeleton pixels are stair-stepped: a stroke drawn as a perfectly straight
horizontal line in the source art arrives here as a pixel chain that
wanders by a pixel or two, and following it literally produces lines that
are visibly tilted or bowed. This module fits each straight section with
robust regression instead, then aligns those fits to axes the icon itself
declares.

Order matters. Directions are decided for the whole icon before any
vertex is computed, so that:

- every near-horizontal section shares one horizontal angle, and every
  near-vertical section shares one vertical angle (so bars and edges come
  out exactly parallel, not each independently rounded);
- lines that sit at the same level collapse onto one shared offset
  (shared baselines);
- vertices are then recomputed as intersections of the corrected lines,
  so corners stay closed rather than splitting apart.

Deliberately left alone: sections whose angle is outside the tolerance
(intentional diagonals), short sections inside a multi-section run (the
corner transitions of a rounded rectangle), and anything the caller
already matched as a circle. Standalone short runs such as dashes are
still eligible, since they have no corner to protect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

HORIZONTAL = "horizontal"
VERTICAL = "vertical"
FREE = "free"


def _cross2(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """2-D scalar cross product, supporting a broadcast array of points."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return np.array([1.0, 0.0])
    return vector / norm


@dataclass
class FittedLine:
    """One straight section of a branch, as an infinite line plus extent."""

    point: np.ndarray
    direction: np.ndarray
    start: np.ndarray
    end: np.ndarray
    pixel_count: int
    orientation: str = FREE
    snapped: bool = False
    offset_aligned: bool = False

    @property
    def angle(self) -> float:
        """Orientation angle in degrees, normalized to (-90, 90]."""
        angle = float(np.degrees(np.arctan2(self.direction[1], self.direction[0])))
        while angle <= -90.0:
            angle += 180.0
        while angle > 90.0:
            angle -= 180.0
        return angle

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    @property
    def normal(self) -> np.ndarray:
        return np.array([-self.direction[1], self.direction[0]])

    def perpendicular_offset(self) -> float:
        """Signed distance from the origin, measured along the normal."""
        return float(np.dot(self.normal, self.point))

    def project(self, query: np.ndarray) -> np.ndarray:
        query = np.asarray(query, dtype=float)
        return self.point + np.dot(query - self.point, self.direction) * self.direction


@dataclass
class RegularizationStats:
    snapped_horizontal: int = 0
    snapped_vertical: int = 0
    offsets_aligned: int = 0
    endpoints_aligned: int = 0
    sections_total: int = 0
    diagonals_preserved: int = 0
    short_sections_protected: int = 0
    horizontal_angle: float | None = None
    vertical_angle: float | None = None
    residual_angle_deviations: list[float] = field(default_factory=list)

    @property
    def snapped_total(self) -> int:
        return self.snapped_horizontal + self.snapped_vertical


def fit_line_robust(points: np.ndarray, trim_iterations: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Total-least-squares line fit with outlier trimming.

    Orthogonal regression (rather than least squares on y) so that near-
    vertical sections fit as well as near-horizontal ones. Trimming drops
    the pixels that skeletonization pushed off the true centerline,
    typically at junctions and stroke ends.
    """
    pixels = np.asarray(points, dtype=float)
    if len(pixels) < 2:
        raise ValueError("line fit needs at least 2 points")

    keep = np.ones(len(pixels), dtype=bool)
    centroid = pixels.mean(axis=0)
    direction = _unit(pixels[-1] - pixels[0])

    for _ in range(trim_iterations + 1):
        active = pixels[keep]
        if len(active) < 2:
            break
        centroid = active.mean(axis=0)
        _, _, right = np.linalg.svd(active - centroid, full_matrices=False)
        direction = _unit(right[0])

        residuals = np.abs(_cross2(direction, pixels - centroid))
        median = float(np.median(residuals))
        deviation = float(np.median(np.abs(residuals - median)))
        # Never trim below a pixel: stair-steps are signal-free noise of
        # roughly that size, and a tighter band would reject the whole run.
        threshold = max(1.0, median + 2.5 * deviation)

        candidate = residuals <= threshold
        if candidate.sum() < max(2, int(0.5 * len(pixels))):
            break
        if np.array_equal(candidate, keep):
            break
        keep = candidate

    if np.dot(direction, pixels[-1] - pixels[0]) < 0:
        direction = -direction
    return centroid, direction


def _branch_slice(branch: np.ndarray, start: int, stop: int, closed: bool) -> np.ndarray:
    if start <= stop:
        return branch[start : stop + 1]
    if closed:
        return np.vstack([branch[start:], branch[: stop + 1]])
    return branch[stop : start + 1]


def fit_sections(branch: np.ndarray, epsilon: float, closed: bool) -> list[FittedLine]:
    """Split a branch at corners, then robustly fit each straight section."""
    if len(branch) < 2:
        return []

    contour = branch.astype(np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(contour, epsilon, closed).reshape(-1, 2).astype(float)

    if len(simplified) < 2:
        centroid, direction = fit_line_robust(branch)
        return [
            FittedLine(
                point=centroid,
                direction=direction,
                start=branch[0].astype(float),
                end=branch[-1].astype(float),
                pixel_count=len(branch),
            )
        ]

    indices = sorted(
        {int(np.argmin(np.hypot(*(branch - vertex).T))) for vertex in simplified}
    )
    if len(indices) < 2:
        indices = [0, len(branch) - 1]

    pairs = list(zip(indices, indices[1:]))
    if closed:
        pairs.append((indices[-1], indices[0]))

    sections: list[FittedLine] = []
    for start_index, stop_index in pairs:
        pixels = _branch_slice(branch, start_index, stop_index, closed)
        if len(pixels) < 2:
            continue
        # A closed branch repeats its start pixel, so the wrapping pair can
        # span no distance at all. Such a section has no direction and would
        # poison the length-weighted averages downstream.
        if float(np.linalg.norm(pixels[-1] - pixels[0])) < 0.5:
            continue
        centroid, direction = fit_line_robust(pixels)
        sections.append(
            FittedLine(
                point=centroid,
                direction=direction,
                start=pixels[0].astype(float),
                end=pixels[-1].astype(float),
                pixel_count=len(pixels),
            )
        )
    return sections


def angular_distance(first: float, second: float) -> float:
    """Distance between two undirected line angles, in degrees (period 180)."""
    difference = abs(first - second) % 180.0
    return min(difference, 180.0 - difference)


def classify_sections(
    sections: list[FittedLine],
    horizontal_angle: float,
    vertical_angle: float,
    tolerance_degrees: float,
) -> None:
    """Label each section by which icon axis it is close enough to adopt."""
    for section in sections:
        to_horizontal = angular_distance(section.angle, horizontal_angle)
        to_vertical = angular_distance(section.angle, vertical_angle)

        if to_horizontal <= tolerance_degrees and to_horizontal <= to_vertical:
            section.orientation = HORIZONTAL
        elif to_vertical <= tolerance_degrees:
            section.orientation = VERTICAL
        else:
            section.orientation = FREE


def _doubled_angle_mean(angles: list[float], weights: list[float]) -> float | None:
    """Circular mean over undirected line angles (period 180 degrees)."""
    if not angles:
        return None
    doubled = np.radians(np.asarray(angles, dtype=float) * 2.0)
    weight = np.asarray(weights, dtype=float)
    x = float((weight * np.cos(doubled)).sum())
    y = float((weight * np.sin(doubled)).sum())
    if x == 0.0 and y == 0.0:
        return None
    return float(np.degrees(np.arctan2(y, x)) / 2.0)


def estimate_dominant_axes(
    sections: list[FittedLine], tolerance_degrees: float
) -> tuple[float, float]:
    """Estimate the icon's own horizontal and vertical angles.

    Candidates are gathered over a window twice the snapping tolerance and
    weighted by section length, so the long frame edges and baselines
    decide the axes rather than short incidental runs.

    The estimate is then locked to exact 0/90 degrees unless the icon is
    consistently rotated by more than the tolerance. Icon art is drawn
    axis-aligned, so a sub-tolerance mean tilt is skeleton and JPEG noise,
    not intent — and a single tilted stroke must not be allowed to declare
    its own tilt the icon's horizontal. A genuinely rotated icon (every
    edge off by more than the tolerance) keeps its shared angle instead.
    """
    window = tolerance_degrees * 2.0

    horizontal = [s for s in sections if s.length > 0 and angular_distance(s.angle, 0.0) <= window]
    vertical = [s for s in sections if s.length > 0 and angular_distance(s.angle, 90.0) <= window]

    horizontal_angle = _doubled_angle_mean(
        [s.angle for s in horizontal], [s.length for s in horizontal]
    )
    vertical_angle = _doubled_angle_mean(
        [s.angle for s in vertical], [s.length for s in vertical]
    )

    if horizontal_angle is None or angular_distance(horizontal_angle, 0.0) <= tolerance_degrees:
        horizontal_angle = 0.0
    if vertical_angle is None or angular_distance(vertical_angle, 90.0) <= tolerance_degrees:
        vertical_angle = 90.0
    # A vertical mean can land near -90; express it as +90 for clarity.
    if vertical_angle < 0:
        vertical_angle += 180.0
    return horizontal_angle, vertical_angle


def snap_sections(
    sections: list[FittedLine],
    horizontal_angle: float,
    vertical_angle: float,
    min_length: float,
    is_standalone: bool,
    stats: RegularizationStats,
) -> None:
    """Point every eligible section at its icon-wide shared angle.

    A short section inside a multi-section run is a corner transition (the
    chamfer of a rounded corner); snapping it would square the corner, so
    it is left as fitted. A standalone run has no corner to protect.
    """
    for section in sections:
        if section.orientation == FREE:
            stats.diagonals_preserved += 1
            continue
        if not is_standalone and section.length < min_length:
            stats.short_sections_protected += 1
            continue

        target = horizontal_angle if section.orientation == HORIZONTAL else vertical_angle
        stats.residual_angle_deviations.append(angular_distance(section.angle, target))

        direction = _unit(
            np.array([np.cos(np.radians(target)), np.sin(np.radians(target))])
        )
        if np.dot(direction, section.direction) < 0:
            direction = -direction
        section.direction = direction
        section.snapped = True

        if section.orientation == HORIZONTAL:
            stats.snapped_horizontal += 1
        else:
            stats.snapped_vertical += 1


def align_offsets(
    sections: list[FittedLine], tolerance: float, stats: RegularizationStats
) -> None:
    """Collapse snapped, parallel sections that sit at the same level.

    Only sections already within `tolerance` of each other are merged, so
    this expresses an alignment the raster already shows rather than
    inventing one.
    """
    for orientation in (HORIZONTAL, VERTICAL):
        group = [s for s in sections if s.snapped and s.orientation == orientation]
        if len(group) < 2:
            continue

        group.sort(key=lambda section: section.perpendicular_offset())
        cluster: list[FittedLine] = [group[0]]
        clusters: list[list[FittedLine]] = []
        for section in group[1:]:
            if section.perpendicular_offset() - cluster[-1].perpendicular_offset() <= tolerance:
                cluster.append(section)
            else:
                clusters.append(cluster)
                cluster = [section]
        clusters.append(cluster)

        for members in clusters:
            if len(members) < 2:
                continue
            weights = np.array([member.length for member in members], dtype=float)
            offsets = np.array(
                [member.perpendicular_offset() for member in members], dtype=float
            )
            total_weight = float(weights.sum())
            if total_weight <= 0:
                continue
            mean_offset = float((weights * offsets).sum() / total_weight)
            for member in members:
                shift = mean_offset - member.perpendicular_offset()
                member.point = member.point + shift * member.normal
                member.offset_aligned = True
                stats.offsets_aligned += 1


def sections_to_vertices(
    sections: list[FittedLine], closed: bool, max_vertex_shift: float
) -> np.ndarray:
    """Rebuild a vertex chain by intersecting consecutive corrected lines.

    Falls back to the originally traced corner whenever the intersection
    is unstable (near-parallel neighbours) or implausibly far away, so a
    correction can never fling a corner across the icon.
    """
    if not sections:
        return np.empty((0, 2))
    if len(sections) == 1:
        section = sections[0]
        return np.vstack([section.project(section.start), section.project(section.end)])

    def intersect(first: FittedLine, second: FittedLine, fallback: np.ndarray) -> np.ndarray:
        denominator = _cross2(first.direction, second.direction)
        if abs(denominator) < 1e-9:
            return fallback
        numerator = _cross2(second.point - first.point, second.direction)
        candidate = first.point + float(numerator / denominator) * first.direction
        if np.linalg.norm(candidate - fallback) > max_vertex_shift:
            return fallback
        return candidate

    vertices: list[np.ndarray] = []
    if closed:
        closing = intersect(sections[-1], sections[0], sections[0].start)
        vertices.append(closing)
    else:
        vertices.append(sections[0].project(sections[0].start))

    for current, following in zip(sections, sections[1:]):
        vertices.append(intersect(current, following, current.end))

    if closed:
        vertices.append(vertices[0])
    else:
        vertices.append(sections[-1].project(sections[-1].end))

    return np.vstack(vertices)


def align_free_endpoints(
    chains: list[tuple[np.ndarray, list[FittedLine], bool]],
    tolerance: float,
    stats: RegularizationStats,
) -> None:
    """Pull loose ends that nearly share a level onto a common one.

    A bar standing on a baseline, or a row of ticks, ends at the same
    coordinate in the source art; skeletonization leaves those ends a
    pixel or two apart. Vertical ends are aligned in y, horizontal ends in
    x, and only within `tolerance`.
    """
    Candidate = tuple[np.ndarray, int, FittedLine, int]
    candidates: list[Candidate] = []

    for vertices, sections, closed in chains:
        if closed or len(vertices) < 2 or not sections:
            continue
        for vertex_index, section in ((0, sections[0]), (len(vertices) - 1, sections[-1])):
            if not section.snapped:
                continue
            axis = 1 if section.orientation == VERTICAL else 0
            candidates.append((vertices, vertex_index, section, axis))

    for axis in (0, 1):
        group = [candidate for candidate in candidates if candidate[3] == axis]
        if len(group) < 2:
            continue

        group.sort(key=lambda candidate: candidate[0][candidate[1]][axis])
        cluster: list[Candidate] = [group[0]]
        clusters: list[list[Candidate]] = []
        for candidate in group[1:]:
            previous = cluster[-1][0][cluster[-1][1]][axis]
            if candidate[0][candidate[1]][axis] - previous <= tolerance:
                cluster.append(candidate)
            else:
                clusters.append(cluster)
                cluster = [candidate]
        clusters.append(cluster)

        for members in clusters:
            if len(members) < 2:
                continue
            target = float(
                np.mean([member[0][member[1]][axis] for member in members])
            )
            for vertices, vertex_index, section, _ in members:
                vertex = vertices[vertex_index]
                step = section.direction[axis]
                if abs(step) < 1e-9:
                    continue
                travel = (target - vertex[axis]) / step
                vertices[vertex_index] = vertex + travel * section.direction
                stats.endpoints_aligned += 1


def regularize_branches(
    branches: list[np.ndarray],
    closed_flags: list[bool],
    epsilon: float,
    stroke_width: float,
    angle_tolerance_degrees: float = 4.0,
    min_section_length_ratio: float = 2.5,
    offset_tolerance_ratio: float = 0.6,
) -> tuple[list[np.ndarray], RegularizationStats]:
    """Fit, snap, and align every branch of one icon. Returns vertex chains."""
    stats = RegularizationStats()
    min_section_length = max(3.0, stroke_width * min_section_length_ratio)
    offset_tolerance = max(1.0, stroke_width * offset_tolerance_ratio)
    max_vertex_shift = max(2.0, stroke_width * 2.0)

    per_branch: list[list[FittedLine]] = [
        fit_sections(branch, epsilon, closed)
        for branch, closed in zip(branches, closed_flags)
    ]

    all_sections = [section for sections in per_branch for section in sections]
    stats.sections_total = len(all_sections)

    # Axes are decided for the whole icon before anything is classified or
    # moved, so every branch is corrected against the same reference.
    horizontal_angle, vertical_angle = estimate_dominant_axes(
        all_sections, angle_tolerance_degrees
    )
    stats.horizontal_angle = horizontal_angle
    stats.vertical_angle = vertical_angle
    classify_sections(
        all_sections, horizontal_angle, vertical_angle, angle_tolerance_degrees
    )

    for sections in per_branch:
        snap_sections(
            sections,
            horizontal_angle,
            vertical_angle,
            min_section_length,
            is_standalone=len(sections) == 1,
            stats=stats,
        )

    align_offsets(all_sections, offset_tolerance, stats)

    chains = []
    for sections, closed in zip(per_branch, closed_flags):
        vertices = sections_to_vertices(sections, closed, max_vertex_shift)
        chains.append((vertices, sections, closed))

    align_free_endpoints(chains, offset_tolerance, stats)

    return [vertices for vertices, _, _ in chains], stats
