"""Classify ordered centerline samples into straights, corners, arcs and curves.

The skeleton carries full curve information, but a pipeline whose only
open-geometry model is a straight line has nowhere to put it: every
smooth bend gets shredded into short chords that are individually within
tolerance yet have collectively lost any notion of being a curve. That is
what produced faceted rings and a mangled dollar sign.

This module fits the samples *before* aggressive simplification, and
decides per section which model the evidence supports:

1. straight sections          -> LineModel
2. sharp corners              -> a hard break between sections
3. circular arcs              -> ArcModel
4. rounded transitions        -> a short ArcModel between two LineModels
5. changing-curvature curves  -> BezierModel (cubic)

Selection is by fitting error against model complexity: the simplest
model whose worst residual fits the tolerance wins, tried in order line
(2 dof) -> arc (3 dof) -> cubic Bezier (6 dof). A model is never chosen
because it is fashionable for the shape; an arc has to pass a circularity
test that an S-curve fails by construction, so the dollar sign cannot be
answered with arcs.

Corners are proposed from the change in tangent direction across a
neighborhood, never from one pixel: a single skeleton stair-step turns
sharply for one sample, while a real corner turns sharply and
*concentrates* that turn, which is what separates it from the sustained,
even turning of an arc.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Model complexity, in degrees of freedom, used to break ties toward the
# simpler explanation of the same samples.
LINE_DOF = 2
ARC_DOF = 3
BEZIER_DOF = 6


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return np.array([1.0, 0.0])
    return np.asarray(vector, dtype=float) / norm


def _cross2(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def arc_length(samples: np.ndarray) -> float:
    if len(samples) < 2:
        return 0.0
    return float(np.sum(np.hypot(*np.diff(samples, axis=0).T)))


# --------------------------------------------------------------------------
# tangent turning and corner proposal
# --------------------------------------------------------------------------


def tangent_turning(samples: np.ndarray, window: int) -> np.ndarray:
    """Turning angle in degrees at each sample, measured over +/- window.

    Using a neighborhood rather than adjacent pixels is what makes this
    robust: one stair-step of a skeleton turns 45 degrees between
    neighbouring pixels and means nothing.
    """
    count = len(samples)
    turning = np.zeros(count)
    if count < 2 * window + 1:
        return turning

    for index in range(window, count - window):
        before = samples[index] - samples[index - window]
        after = samples[index + window] - samples[index]
        if np.linalg.norm(before) == 0 or np.linalg.norm(after) == 0:
            continue
        before = _unit(before)
        after = _unit(after)
        turning[index] = abs(
            float(np.degrees(np.arctan2(_cross2(before, after), float(np.dot(before, after)))))
        )
    return turning


def detect_corners(
    samples: np.ndarray,
    window: int,
    threshold_degrees: float = 38.0,
    concentration_ratio: float = 1.8,
) -> list[int]:
    """Propose sample indices where the centerline turns sharply.

    A corner must turn by more than `threshold_degrees`, be the local peak
    of the turning profile, and turn substantially more than its
    surroundings. That last test is what distinguishes a corner from an
    arc: an arc's turning is even, so its peak barely exceeds its
    neighbourhood median and no corner is proposed.
    """
    turning = tangent_turning(samples, window)
    if not turning.any():
        return []

    wide = max(window * 3, 6)
    margin = window
    corners: list[int] = []
    for index in range(window, len(samples) - window):
        if index < margin or index > len(samples) - 1 - margin:
            # Too close to an end to be joining two runs; skeletonization
            # curls stroke caps and junction stubs like this.
            continue
        peak = turning[index]
        if peak < threshold_degrees:
            continue
        local = turning[max(0, index - window) : index + window + 1]
        if peak < local.max() - 1e-9:
            continue
        neighbourhood = turning[max(0, index - wide) : index + wide + 1]
        median = float(np.median(neighbourhood))
        if peak < concentration_ratio * max(median, 1.0):
            continue
        # The turn must also be local: a corner joins two calmer runs,
        # whereas a tight curve keeps turning on both sides of its peak.
        reach = min(window * 2, index, len(turning) - 1 - index)
        if reach > 0:
            flanks = min(turning[index - reach], turning[index + reach])
            if flanks > peak * 0.45:
                continue
        if corners and index - corners[-1] <= window:
            # Keep the sharper of two adjacent proposals.
            if peak > turning[corners[-1]]:
                corners[-1] = index
            continue
        corners.append(index)
    return corners


# --------------------------------------------------------------------------
# candidate models
# --------------------------------------------------------------------------


@dataclass
class LineModel:
    point: np.ndarray
    direction: np.ndarray
    start: np.ndarray
    end: np.ndarray
    max_error: float
    rms_error: float
    dof: int = LINE_DOF
    kind: str = "line"
    # Set by the axis-alignment pass, which only ever touches straights.
    snapped: bool = False
    orientation: str = "free"

    def start_tangent(self) -> np.ndarray:
        return self.direction

    def end_tangent(self) -> np.ndarray:
        return self.direction


@dataclass
class ArcModel:
    center: np.ndarray
    radius: float
    start: np.ndarray
    end: np.ndarray
    sweep_degrees: float
    clockwise: bool
    max_error: float
    rms_error: float
    dof: int = ARC_DOF
    kind: str = "arc"

    def _tangent_at(self, point: np.ndarray) -> np.ndarray:
        radial = _unit(np.asarray(point, dtype=float) - self.center)
        tangent = np.array([-radial[1], radial[0]])
        return -tangent if self.clockwise else tangent

    def start_tangent(self) -> np.ndarray:
        return self._tangent_at(self.start)

    def end_tangent(self) -> np.ndarray:
        return self._tangent_at(self.end)


@dataclass
class BezierModel:
    p0: np.ndarray
    p1: np.ndarray
    p2: np.ndarray
    p3: np.ndarray
    max_error: float
    rms_error: float
    dof: int = BEZIER_DOF
    kind: str = "bezier"

    @property
    def start(self) -> np.ndarray:
        return self.p0

    @property
    def end(self) -> np.ndarray:
        return self.p3

    def start_tangent(self) -> np.ndarray:
        handle = self.p1 - self.p0
        if np.linalg.norm(handle) < 1e-9:
            handle = self.p3 - self.p0
        return _unit(handle)

    def end_tangent(self) -> np.ndarray:
        handle = self.p3 - self.p2
        if np.linalg.norm(handle) < 1e-9:
            handle = self.p3 - self.p0
        return _unit(handle)


Model = LineModel | ArcModel | BezierModel


@dataclass
class ModelChoice:
    """The chosen model plus the errors of every candidate, for auditing."""

    model: Model
    line_error: float
    arc_error: float | None
    bezier_error: float
    reason: str


def fit_line(samples: np.ndarray, trim_iterations: int = 2) -> LineModel:
    """Total-least-squares line fit with outlier trimming."""
    pixels = np.asarray(samples, dtype=float)
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
        threshold = max(1.0, median + 2.5 * deviation)
        candidate = residuals <= threshold
        if candidate.sum() < max(2, int(0.5 * len(pixels))) or np.array_equal(candidate, keep):
            break
        keep = candidate

    if np.dot(direction, pixels[-1] - pixels[0]) < 0:
        direction = -direction

    residuals = np.abs(_cross2(direction, pixels - centroid))
    start = centroid + np.dot(pixels[0] - centroid, direction) * direction
    end = centroid + np.dot(pixels[-1] - centroid, direction) * direction
    return LineModel(
        point=centroid,
        direction=direction,
        start=start,
        end=end,
        max_error=float(residuals.max()),
        rms_error=float(np.sqrt((residuals**2).mean())),
    )


def arc_sagitta(model: ArcModel) -> float:
    """How far the arc departs from the straight chord joining its ends."""
    chord = float(np.linalg.norm(np.asarray(model.end) - np.asarray(model.start)))
    half = min(chord / 2, model.radius)
    return float(model.radius - np.sqrt(max(0.0, model.radius**2 - half**2)))


def fit_arc(samples: np.ndarray, min_radius: float = 0.5) -> ArcModel | None:
    """Algebraic circle fit, accepted only if the samples really are circular.

    Rejects anything whose swept angle does not advance monotonically
    around the fitted centre. An S-curve fails this test by construction,
    because its centre of curvature flips sides halfway along, so arcs can
    never be used to answer a changing-curvature shape.
    """
    pixels = np.asarray(samples, dtype=float)
    if len(pixels) < 5:
        return None

    x = pixels[:, 0]
    y = pixels[:, 1]
    design = np.column_stack([x, y, np.ones(len(x))])
    target = x**2 + y**2
    try:
        solution, *_ = np.linalg.lstsq(design, target, rcond=None)
    except np.linalg.LinAlgError:
        return None

    center = np.array([solution[0] / 2, solution[1] / 2])
    squared = solution[2] + center[0] ** 2 + center[1] ** 2
    if squared <= 0:
        return None
    radius = float(np.sqrt(squared))

    span = arc_length(pixels)
    # A radius far larger than the run itself is a straight line wearing a
    # circle's clothing; let the line model have it.
    # An arc finer than the stroke that drew it is not evidence of a curve,
    # it is noise in the skeleton; and a radius far larger than the run is
    # a straight line wearing a circle's clothing.
    if radius > span * 12 or radius < min_radius:
        return None

    angles = np.unwrap(np.arctan2(y - center[1], x - center[0]))
    steps = np.diff(angles)
    if len(steps) == 0:
        return None
    forward = int((steps > 0).sum())
    backward = int((steps < 0).sum())
    # Monotone sweep: essentially all steps must share a direction.
    if min(forward, backward) > max(1, int(0.08 * len(steps))):
        return None

    residuals = np.abs(np.hypot(x - center[0], y - center[1]) - radius)
    sweep = float(np.degrees(abs(angles[-1] - angles[0])))
    if sweep < 8.0:
        return None

    return ArcModel(
        center=center,
        radius=radius,
        start=pixels[0].copy(),
        end=pixels[-1].copy(),
        sweep_degrees=sweep,
        clockwise=backward > forward,
        max_error=float(residuals.max()),
        rms_error=float(np.sqrt((residuals**2).mean())),
    )


def _bezier_points(control: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = t.reshape(-1, 1)
    return (
        (1 - t) ** 3 * control[0]
        + 3 * (1 - t) ** 2 * t * control[1]
        + 3 * (1 - t) * t**2 * control[2]
        + t**3 * control[3]
    )


def _chord_parameters(samples: np.ndarray) -> np.ndarray:
    steps = np.hypot(*np.diff(samples, axis=0).T)
    cumulative = np.concatenate([[0.0], np.cumsum(steps)])
    total = cumulative[-1]
    if total <= 0:
        return np.linspace(0.0, 1.0, len(samples))
    return cumulative / total


def fit_cubic_bezier(samples: np.ndarray, refine_iterations: int = 2) -> BezierModel:
    """Least-squares cubic with fixed endpoints and chord-length parameters.

    Parameters are refined by re-projecting the samples onto the current
    curve, which matters for tight turns where chord length alone
    misplaces the middle of the curve.
    """
    pixels = np.asarray(samples, dtype=float)
    p0 = pixels[0].copy()
    p3 = pixels[-1].copy()
    t = _chord_parameters(pixels)

    control = np.array([p0, p0, p3, p3], dtype=float)
    for _ in range(refine_iterations + 1):
        basis1 = 3 * (1 - t) ** 2 * t
        basis2 = 3 * (1 - t) * t**2
        fixed = (1 - t).reshape(-1, 1) ** 3 * p0 + (t.reshape(-1, 1) ** 3) * p3
        residual = pixels - fixed
        design = np.column_stack([basis1, basis2])
        try:
            solution, *_ = np.linalg.lstsq(design, residual, rcond=None)
        except np.linalg.LinAlgError:
            solution = np.vstack([p0, p3])
        control = np.array([p0, solution[0], solution[1], p3], dtype=float)

        dense_t = np.linspace(0.0, 1.0, max(64, len(pixels) * 4))
        dense = _bezier_points(control, dense_t)
        distances = np.linalg.norm(pixels[:, None, :] - dense[None, :, :], axis=2)
        nearest = distances.argmin(axis=1)
        t = dense_t[nearest]
        t[0] = 0.0
        t[-1] = 1.0
        t = np.maximum.accumulate(t)

    dense_t = np.linspace(0.0, 1.0, max(128, len(pixels) * 6))
    dense = _bezier_points(control, dense_t)
    errors = np.linalg.norm(pixels[:, None, :] - dense[None, :, :], axis=2).min(axis=1)
    return BezierModel(
        p0=control[0],
        p1=control[1],
        p2=control[2],
        p3=control[3],
        max_error=float(errors.max()),
        rms_error=float(np.sqrt((errors**2).mean())),
    )


def _arc_earns_it(arc: ArcModel, line: LineModel, min_sagitta: float) -> bool:
    """An arc costs a degree of freedom, so it has to be clearly better.

    Its departure from the straight chord must be big enough to see at
    stroke scale; otherwise a straight run carrying a little JPEG bow gets
    promoted to a shallow arc and an edge that should read as flat comes
    out domed. No error-ratio test is needed on top: a line that explains
    the samples within tolerance has already been returned by the time
    this is consulted.
    """
    del line
    return arc_sagitta(arc) >= min_sagitta


def select_model(
    samples: np.ndarray,
    tolerance: float,
    min_arc_radius: float = 0.5,
    min_sagitta: float = 0.0,
) -> ModelChoice:
    """Pick the simplest model whose worst residual fits the tolerance."""
    line = fit_line(samples)
    if line.max_error <= tolerance:
        return ModelChoice(line, line.max_error, None, float("inf"), "line within tolerance")

    arc = fit_arc(samples, min_arc_radius)
    if arc is not None and arc.max_error <= tolerance and _arc_earns_it(arc, line, min_sagitta):
        return ModelChoice(
            arc, line.max_error, arc.max_error, float("inf"), "arc within tolerance"
        )

    bezier = fit_cubic_bezier(samples)
    if bezier.max_error <= tolerance:
        return ModelChoice(
            bezier,
            line.max_error,
            arc.max_error if arc else None,
            bezier.max_error,
            "bezier within tolerance",
        )

    # Nothing fits. Prefer the model with the lowest error per degree of
    # freedom so a complex model must clearly earn its extra parameters.
    candidates: list[tuple[float, Model, str]] = [
        (line.max_error * (1.0 + 0.1 * LINE_DOF), line, "line (best penalized error)"),
        (
            bezier.max_error * (1.0 + 0.1 * BEZIER_DOF),
            bezier,
            "bezier (best penalized error)",
        ),
    ]
    if arc is not None:
        candidates.append(
            (arc.max_error * (1.0 + 0.1 * ARC_DOF), arc, "arc (best penalized error)")
        )
    candidates.sort(key=lambda row: row[0])
    best = candidates[0]
    return ModelChoice(
        best[1],
        line.max_error,
        arc.max_error if arc else None,
        bezier.max_error,
        best[2],
    )


# --------------------------------------------------------------------------
# decomposition
# --------------------------------------------------------------------------


@dataclass
class Section:
    model: Model
    sharp_start: bool
    choice: ModelChoice | None = None


@dataclass
class BranchFit:
    sections: list[Section]
    closed: bool
    corner_count: int = 0
    stats: dict[str, int] = field(default_factory=dict)


def _verified_straight_runs(
    samples: np.ndarray,
    window: int,
    straight_turning: float,
    min_length: float,
    tolerance: float,
) -> list[tuple[int, int]]:
    """Straight runs proposed by low turning and confirmed by a line fit.

    Turning alone is not enough: a large-radius arc turns very little per
    sample and would pass as straight. Each proposal is therefore trimmed
    to the longest sub-run an actual line fits within tolerance, which a
    genuine arc cannot satisfy over any useful length.
    """
    verified: list[tuple[int, int]] = []
    limit = len(samples) - 1
    for low, high in _quiet_runs(samples, window, straight_turning):
        if verified and low <= verified[-1][1]:
            continue
        cursor = low
        while high - cursor >= 2:
            best = None
            # Extend past the seed: the line fit decides how far the
            # straight really runs, not the turning profile.
            lo, hi = cursor + 2, limit
            while lo <= hi:
                mid = (lo + hi) // 2
                if fit_line(samples[cursor : mid + 1]).max_error <= tolerance:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is None:
                cursor += 1
                continue

            # The line fit will happily reach into a curve, because a short
            # enough chunk of any arc is straight within tolerance. Pull the
            # tail back off the turn, then require the run to be genuinely
            # straight along its whole length rather than only at its seed.
            turning = tangent_turning(samples, window)
            while best > cursor + 2 and turning[best] > straight_turning:
                best -= 1

            span = turning[cursor : best + 1]
            straight_enough = span.size > 0 and float(np.median(span)) <= straight_turning
            if straight_enough and arc_length(samples[cursor : best + 1]) >= min_length:
                verified.append((cursor, best))
            cursor = best + 1
    return verified


def _quiet_runs(
    samples: np.ndarray, window: int, straight_turning: float
) -> list[tuple[int, int]]:
    """Index ranges whose turning stays low enough to propose a straight run."""
    turning = tangent_turning(samples, window)
    quiet = turning <= straight_turning
    # The unmeasurable ends of the profile inherit their neighbour.
    if len(quiet) > 2 * window:
        quiet[:window] = quiet[window]
        quiet[-window:] = quiet[-window - 1]

    runs: list[tuple[int, int]] = []
    start = None
    for index, is_quiet in enumerate(quiet):
        if is_quiet and start is None:
            start = index
        elif not is_quiet and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(samples) - 1))

    return [(a, b) for a, b in runs if b - a >= 2]


def decompose_run(
    samples: np.ndarray,
    tolerance: float,
    window: int,
    straight_turning: float,
    min_straight_length: float,
    depth: int = 0,
    min_arc_radius: float = 0.5,
    min_sagitta: float = 0.0,
) -> list[Model]:
    """Split one corner-free run into straight and curved models."""
    if len(samples) < 2:
        return []
    if len(samples) == 2 or arc_length(samples) < 1e-9:
        return [fit_line(samples)]

    # A straight covering the whole run wins outright: it is the simplest
    # model there is, and without this check stair-step spikes in the
    # turning profile fragment a dead-straight stroke into collinear bits.
    whole_line = fit_line(samples)
    if whole_line.max_error <= tolerance:
        return [whole_line]

    # A clean arc is claimed whole, before straight extraction gets a
    # chance to carve a flat-looking nibble out of it: a short enough
    # chunk of any large-radius arc does fit a line within tolerance.
    whole_arc = fit_arc(samples, min_arc_radius)
    if (
        whole_arc is not None
        and whole_arc.max_error <= tolerance
        and _arc_earns_it(whole_arc, whole_line, min_sagitta)
    ):
        return [whole_arc]

    # Straight runs are looked for before any cubic is accepted, so a
    # straight flowing into a turn keeps its straight section (and thus
    # stays eligible for axis alignment) instead of being swallowed by one
    # accommodating cubic.
    straights = _verified_straight_runs(
        samples, window, straight_turning, min_straight_length, tolerance
    )

    if not straights:
        choice = select_model(samples, tolerance, min_arc_radius, min_sagitta)
        if choice.model.max_error <= tolerance or depth >= 3:
            return [choice.model]
        # Split at the worst-fitting sample and try again.
        split = _worst_index(samples, choice.model)
        if split <= 1 or split >= len(samples) - 2:
            return [choice.model]
        return decompose_run(
            samples[: split + 1],
            tolerance,
            window,
            straight_turning,
            min_straight_length,
            depth + 1,
            min_arc_radius,
            min_sagitta,
        ) + decompose_run(
            samples[split:],
            tolerance,
            window,
            straight_turning,
            min_straight_length,
            depth + 1,
            min_arc_radius,
        )

    # Straight runs anchor the decomposition; the gaps between them are
    # curved and get their own model each.
    models: list[Model] = []
    cursor = 0
    for start, stop in straights:
        if start > cursor:
            gap = samples[cursor : start + 1]
            if len(gap) >= 2:
                models.extend(
                    decompose_run(
                        gap, tolerance, window, straight_turning, 1e9, depth + 1,
                        min_arc_radius, min_sagitta,
                    )
                )
        line = fit_line(samples[start : stop + 1])
        models.append(line)
        cursor = stop
    if cursor < len(samples) - 1:
        gap = samples[cursor:]
        if len(gap) >= 2:
            models.extend(
                decompose_run(
                    gap, tolerance, window, straight_turning, 1e9, depth + 1,
                    min_arc_radius, min_sagitta,
                )
            )
    return models


def _corner_extent(samples: np.ndarray, index: int, window: int) -> int:
    """How many samples either side of a corner belong to the turn itself.

    A crisp corner turns within a couple of samples; blur spreads the same
    corner over many more. Trimming a fixed count leaves curve in the
    neighbouring edge fits, so the extent is measured from the turning
    profile and the corner is recovered by intersecting the two edges.
    """
    turning = tangent_turning(samples, window)
    if index >= len(turning):
        return window
    peak = turning[index]
    if peak <= 0:
        return window
    floor = peak * 0.5
    extent = window
    while (
        index + extent < len(turning)
        and index - extent >= 0
        and turning[index + extent] >= floor
        and extent < window * 4
    ):
        extent += 1
    return extent


def _worst_index(samples: np.ndarray, model: Model) -> int:
    if isinstance(model, LineModel):
        errors = np.abs(_cross2(model.direction, samples - model.point))
    elif isinstance(model, ArcModel):
        errors = np.abs(
            np.hypot(samples[:, 0] - model.center[0], samples[:, 1] - model.center[1])
            - model.radius
        )
    else:
        dense_t = np.linspace(0.0, 1.0, max(128, len(samples) * 4))
        dense = _bezier_points(
            np.array([model.p0, model.p1, model.p2, model.p3]), dense_t
        )
        errors = np.linalg.norm(samples[:, None, :] - dense[None, :, :], axis=2).min(axis=1)
    return int(np.argmax(errors))


def fit_branch(
    samples: np.ndarray,
    closed: bool,
    stroke_width: float,
    tolerance: float | None = None,
    corner_threshold_degrees: float = 38.0,
    straight_turning_degrees: float = 3.0,
) -> BranchFit:
    """Decompose one ordered centerline branch into classified sections."""
    pixels = np.asarray(samples, dtype=float)
    if len(pixels) < 2:
        return BranchFit(sections=[], closed=closed)

    window = max(2, int(round(max(2.0, stroke_width) * 0.75)))
    if tolerance is None:
        # Sub-pixel: tight enough that a real curve cannot pass as a line,
        # loose enough to ignore skeleton stair-steps.
        tolerance = max(0.6, stroke_width * 0.3)
    # A straight section has to be a substantial run. Anything shorter is
    # usually the locally-flat neighbourhood of an inflection, and carving
    # it out fragments one smooth S into curve-line-curve.
    min_straight_length = max(4.0, stroke_width * 4.0)
    min_arc_radius = max(1.0, stroke_width * 0.6)
    min_sagitta = max(0.8, stroke_width * 0.4)

    working = pixels
    corners = detect_corners(working, window, corner_threshold_degrees)

    if closed and len(working) > 3:
        if corners:
            # Start the loop at a corner so no section straddles the seam.
            shift = corners[0]
            working = np.vstack([working[shift:], working[1 : shift + 1]])
            corners = detect_corners(working, window, corner_threshold_degrees)
        else:
            # A corner-free closed loop is a single continuous curve.
            circle = fit_arc(working, min_arc_radius)
            if circle is not None and circle.max_error <= tolerance:
                return BranchFit(
                    sections=[Section(circle, sharp_start=False)],
                    closed=True,
                    corner_count=0,
                    stats={"arc": 1},
                )

    boundaries = [0] + [c for c in corners if 0 < c < len(working) - 1] + [len(working) - 1]
    boundaries = sorted(set(boundaries))

    sections: list[Section] = []
    for position, (start, stop) in enumerate(zip(boundaries, boundaries[1:])):
        # Trim the turn itself away from the run either side of a corner.
        # The corner's own samples belong to neither edge, and including
        # them bends the fit; the corner is recovered exactly when the two
        # neighbouring sections are intersected in resolve_joints.
        low = start + _corner_extent(working, start, window) if start in corners else start
        high = stop - _corner_extent(working, stop, window) if stop in corners else stop
        if high - low < 1:
            low, high = start, stop
        run = working[low : high + 1]
        if len(run) < 2:
            continue
        models = decompose_run(
            run,
            tolerance,
            window,
            straight_turning_degrees,
            min_straight_length,
            min_arc_radius=min_arc_radius,
            min_sagitta=min_sagitta,
        )
        for model_index, model in enumerate(models):
            sections.append(
                Section(model, sharp_start=(model_index == 0 and position > 0))
            )

    sections = merge_collinear(sections)

    counts: dict[str, int] = {}
    for section in sections:
        counts[section.model.kind] = counts.get(section.model.kind, 0) + 1

    return BranchFit(
        sections=sections, closed=closed, corner_count=len(corners), stats=counts
    )


# --------------------------------------------------------------------------
# joint resolution
# --------------------------------------------------------------------------


def _set_endpoint(model: Model, point: np.ndarray, at_start: bool) -> None:
    if isinstance(model, BezierModel):
        if at_start:
            model.p0 = point
        else:
            model.p3 = point
    elif at_start:
        model.start = point
    else:
        model.end = point


def _shared_point(first: Model, second: Model, sharp: bool, max_shift: float) -> np.ndarray:
    """Where two consecutive sections should meet.

    A straight that the axis pass has aligned must keep its exact angle,
    so the meeting point is placed *on* its line rather than averaged off
    it. Two straights meet at their intersection; anything else falls back
    to the midpoint of the two fitted endpoints.
    """
    a_end = np.asarray(first.end, dtype=float)
    b_start = np.asarray(second.start, dtype=float)
    midpoint = (a_end + b_start) / 2

    first_is_line = isinstance(first, LineModel)
    second_is_line = isinstance(second, LineModel)

    if first_is_line and second_is_line:
        denominator = _cross2(first.direction, second.direction)
        if abs(denominator) > 1e-9:
            numerator = _cross2(second.point - first.point, second.direction)
            candidate = first.point + float(numerator / denominator) * first.direction
            if np.linalg.norm(candidate - midpoint) <= max_shift:
                return candidate
        # Near-parallel: keep them apart rather than inventing a far corner.
        return midpoint

    if first_is_line and not second_is_line:
        return first.point + np.dot(b_start - first.point, first.direction) * first.direction
    if second_is_line and not first_is_line:
        return second.point + np.dot(a_end - second.point, second.direction) * second.direction
    return midpoint


def _retangent(model: Model, tangent: np.ndarray, at_start: bool) -> None:
    """Steer a section's end onto a target tangent.

    A Bezier turns its handle. An arc moves its centre onto the normal
    through the joint, which is the only placement that makes a circle
    tangent to a given direction at a given point; without this a
    straight flowing into a turn leaves a visible kink.
    """
    if isinstance(model, ArcModel):
        joint = np.asarray(model.start if at_start else model.end, dtype=float)
        normal = np.array([-tangent[1], tangent[0]])
        offset = float(np.dot(model.center - joint, normal))
        radius = abs(offset)
        # Only adopt the tangent if the circle it implies is still the
        # circle the samples showed. Forcing it regardless collapses the
        # radius toward the joint and produces arcs finer than the stroke.
        if not (0.5 * model.radius <= radius <= 2.0 * model.radius):
            return
        model.center = joint + offset * normal
        model.radius = float(radius)
        return
    if not isinstance(model, BezierModel):
        return
    if at_start:
        length = float(np.linalg.norm(model.p1 - model.p0))
        model.p1 = model.p0 + tangent * length
    else:
        length = float(np.linalg.norm(model.p3 - model.p2))
        model.p2 = model.p3 - tangent * length


def resolve_joints(branch: BranchFit, max_shift: float) -> list[float]:
    """Close the gaps between consecutive sections and match smooth tangents.

    Returns the tangent discontinuity in degrees at each smooth joint, so
    continuity can be reported rather than assumed.
    """
    sections = branch.sections
    if len(sections) < 2:
        return []

    pairs = list(zip(range(len(sections) - 1), range(1, len(sections))))
    if branch.closed:
        pairs.append((len(sections) - 1, 0))

    discontinuities: list[float] = []
    for first_index, second_index in pairs:
        first = sections[first_index].model
        second = sections[second_index].model
        sharp = sections[second_index].sharp_start

        shared = _shared_point(first, second, sharp, max_shift)
        _set_endpoint(first, shared, at_start=False)
        _set_endpoint(second, shared, at_start=True)

        if sharp:
            continue

        outgoing = _unit(first.end_tangent())
        incoming = _unit(second.start_tangent())

        # A straight that the axis pass aligned defines the tangent; the
        # curve yields to it. Otherwise both sides meet in the middle.
        first_fixed = isinstance(first, LineModel)
        second_fixed = isinstance(second, LineModel)
        if first_fixed and not second_fixed:
            target = outgoing
        elif second_fixed and not first_fixed:
            target = incoming
        elif first_fixed and second_fixed:
            target = None
        else:
            target = _unit(outgoing + incoming)

        before = abs(
            float(np.degrees(np.arctan2(_cross2(outgoing, incoming), float(np.dot(outgoing, incoming)))))
        )
        if target is not None:
            _retangent(first, target, at_start=False)
            _retangent(second, target, at_start=True)
            outgoing = _unit(first.end_tangent())
            incoming = _unit(second.start_tangent())
        after = abs(
            float(np.degrees(np.arctan2(_cross2(outgoing, incoming), float(np.dot(outgoing, incoming)))))
        )
        discontinuities.append(after if target is not None else before)

    return discontinuities


def merge_collinear(sections: list[Section], tolerance_degrees: float = 1.0) -> list[Section]:
    """Fuse consecutive straight sections that lie on the same line.

    Decomposition can hand back neighbouring straights that are really one
    stroke, and leaving them split inflates the anchor count while adding
    nothing an editor could use.
    """
    if len(sections) < 2:
        return sections

    merged = [sections[0]]
    for section in sections[1:]:
        previous = merged[-1]
        if (
            isinstance(previous.model, LineModel)
            and isinstance(section.model, LineModel)
            and not section.sharp_start
        ):
            first = previous.model
            second = section.model
            cross = abs(float(_cross2(first.direction, second.direction)))
            offset = abs(float(_cross2(first.direction, second.point - first.point)))
            if cross <= np.sin(np.radians(tolerance_degrees)) and offset <= 1.0:
                combined = np.vstack([first.start, first.end, second.start, second.end])
                projections = [float(np.dot(p - first.point, first.direction)) for p in combined]
                low = first.point + min(projections) * first.direction
                high = first.point + max(projections) * first.direction
                first.start = low
                first.end = high
                first.max_error = max(first.max_error, second.max_error)
                continue
        merged.append(section)
    return merged
