"""Competing primitive candidates for a whole stroke, and the gate that
decides whether any of them may replace the safe baseline.

Nothing here fits a fragment. Every candidate is generated for a
complete, topologically whole stroke produced by `topology.py`, and
every candidate is measured against the same samples. The baseline
polyline is always generated and is always what ships unless a curve
candidate demonstrably beats it *and* passes the safety gate.

The gate is deliberately hostile to curve output. A curve is only worth
having if it is both a better fit and structurally identical to what it
replaces; a curve that closes an open stroke, moves geometry far, drops
a detail, or emits a degenerate element is rejected regardless of how
well it fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.spatial import cKDTree

from app.services.geometry.curve_fit import (
    arc_length,
    detect_corners,
    fit_arc,
    fit_cubic_bezier,
    fit_line,
    tangent_turning,
)
from app.services.svg_model import (
    PathCubicTo,
    PathLineTo,
    PathMoveTo,
    SvgCircle,
    SvgEllipse,
    SvgLine,
    SvgPath,
    SvgPolyline,
    SvgRect,
)

MIN_ELEMENT_LENGTH = 0.5  # below this an element is degenerate, never emitted
CORNER_TURN_DEGREES = 35.0  # a turn this sharp is structure, not noise
CORNER_TURN_RETENTION = 0.5  # a replacement must keep at least this much of it


@dataclass
class Candidate:
    kind: str
    elements: list
    max_error: float
    rms_error: float
    complexity: int
    closed: bool
    outline: np.ndarray  # densely sampled geometry, for measurement
    notes: str = ""


@dataclass
class GateResult:
    accepted: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> "GateResult":
        self.accepted = False
        self.reasons.append(reason)
        return self


def _polyline_points(samples: np.ndarray, closed: bool) -> np.ndarray:
    if closed and len(samples) > 2 and not np.allclose(samples[0], samples[-1]):
        return np.vstack([samples, samples[:1]])
    return samples


def measure(samples: np.ndarray, outline: np.ndarray) -> tuple[float, float]:
    """Max and RMS distance from the original samples to a candidate."""
    if len(outline) == 0:
        return float("inf"), float("inf")
    tree = cKDTree(outline)
    distances, _ = tree.query(samples)
    return float(distances.max()), float(np.sqrt((distances**2).mean()))


def _densify(points: np.ndarray, step: float = 0.4) -> np.ndarray:
    """Resample a vertex chain into dense points for distance measurement."""
    if len(points) < 2:
        return points
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        dist = float(np.linalg.norm(b - a))
        n = max(1, int(dist / step))
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / n))
    return np.array(out)


def _arc_outline(center: np.ndarray, radius: float, start: np.ndarray,
                 end: np.ndarray, clockwise: bool) -> np.ndarray:
    a0 = float(np.arctan2(start[1] - center[1], start[0] - center[0]))
    a1 = float(np.arctan2(end[1] - center[1], end[0] - center[0]))
    if clockwise:
        while a1 > a0:
            a1 -= 2 * np.pi
    else:
        while a1 < a0:
            a1 += 2 * np.pi
    angles = np.linspace(a0, a1, 180)
    return np.column_stack([
        center[0] + radius * np.cos(angles),
        center[1] + radius * np.sin(angles),
    ])


def _bezier_outline(p0, p1, p2, p3, n: int = 120) -> np.ndarray:
    t = np.linspace(0, 1, n).reshape(-1, 1)
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t**2 * p2 + t**3 * p3)


# ---------------------------------------------------------------------------
# baseline (always available, always safe)
# ---------------------------------------------------------------------------


def baseline_candidate(samples: np.ndarray, closed: bool, epsilon: float) -> Candidate:
    """RDP polyline — the existing straight/polyline reconstruction."""
    pts = _polyline_points(samples, closed)
    contour = pts.astype(np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(contour, epsilon, closed).reshape(-1, 2).astype(float)
    if closed and len(simplified) > 2 and not np.allclose(simplified[0], simplified[-1]):
        simplified = np.vstack([simplified, simplified[:1]])
    if len(simplified) < 2:
        simplified = np.vstack([pts[0], pts[-1]])

    outline = _densify(simplified)
    max_e, rms_e = measure(samples, outline)

    if len(simplified) == 2 and not closed:
        elements = [SvgLine(
            x1=float(simplified[0][0]), y1=float(simplified[0][1]),
            x2=float(simplified[1][0]), y2=float(simplified[1][1]),
        )]
        kind = "line"
    else:
        elements = [SvgPolyline(points=[(float(x), float(y)) for x, y in simplified])]
        kind = "polyline"

    return Candidate(
        kind=kind, elements=elements, max_error=max_e, rms_error=rms_e,
        complexity=len(simplified), closed=closed, outline=outline,
    )


def straight_candidate(samples: np.ndarray) -> Candidate | None:
    """A single straight line spanning the whole stroke."""
    if len(samples) < 2:
        return None
    line = fit_line(samples)
    start = line.point + np.dot(samples[0] - line.point, line.direction) * line.direction
    end = line.point + np.dot(samples[-1] - line.point, line.direction) * line.direction
    if float(np.linalg.norm(end - start)) < MIN_ELEMENT_LENGTH:
        return None
    outline = _densify(np.vstack([start, end]))
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="line", complexity=2, closed=False, outline=outline,
        max_error=max_e, rms_error=rms_e,
        elements=[SvgLine(x1=float(start[0]), y1=float(start[1]),
                          x2=float(end[0]), y2=float(end[1]))],
    )


# ---------------------------------------------------------------------------
# closed-shape candidates
# ---------------------------------------------------------------------------


def circle_candidate(samples: np.ndarray, min_radius: float) -> Candidate | None:
    fit = fit_arc(samples, min_radius)
    if fit is None or fit.sweep_degrees < 300:
        return None
    angles = np.linspace(0, 2 * np.pi, 240)
    outline = np.column_stack([
        fit.center[0] + fit.radius * np.cos(angles),
        fit.center[1] + fit.radius * np.sin(angles),
    ])
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="circle", complexity=3, closed=True, outline=outline,
        max_error=max_e, rms_error=rms_e,
        elements=[SvgCircle(cx=float(fit.center[0]), cy=float(fit.center[1]),
                            r=float(fit.radius))],
    )


def ellipse_candidate(samples: np.ndarray) -> Candidate | None:
    if len(samples) < 5:
        return None
    try:
        (cx, cy), (w, h), angle = cv2.fitEllipse(samples.astype(np.float32))
    except cv2.error:
        return None
    if abs(angle % 180.0) > 3.0 and abs(angle % 180.0 - 180.0) > 3.0:
        return None  # rotated ellipses need a transform we do not emit
    rx, ry = w / 2, h / 2
    if rx < 1 or ry < 1:
        return None
    t = np.linspace(0, 2 * np.pi, 240)
    outline = np.column_stack([cx + rx * np.cos(t), cy + ry * np.sin(t)])
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="ellipse", complexity=4, closed=True, outline=outline,
        max_error=max_e, rms_error=rms_e,
        elements=[SvgEllipse(cx=float(cx), cy=float(cy), rx=float(rx), ry=float(ry))],
    )


def rounded_rect_candidate(samples: np.ndarray, stroke_width: float) -> Candidate | None:
    """Rounded rectangle / capsule for a closed axis-aligned stroke."""
    min_x, min_y = samples.min(axis=0)
    max_x, max_y = samples.max(axis=0)
    w, h = max_x - min_x, max_y - min_y
    if w < 2 or h < 2:
        return None

    best: Candidate | None = None
    # Try a range of corner radii, including the capsule limit (min side / 2).
    limit = min(w, h) / 2
    for radius in np.linspace(0.0, limit, 12):
        outline = _rounded_rect_outline(min_x, min_y, w, h, radius)
        max_e, rms_e = measure(samples, outline)
        if best is None or max_e < best.max_error:
            best = Candidate(
                kind="rounded-rect" if radius > 0.5 else "rect",
                complexity=5, closed=True, outline=outline,
                max_error=max_e, rms_error=rms_e,
                elements=[SvgRect(x=float(min_x), y=float(min_y),
                                  width=float(w), height=float(h),
                                  rx=float(radius) if radius > 0.5 else 0.0)],
                notes=f"radius={radius:.2f}",
            )
    return best


def _rounded_rect_outline(x: float, y: float, w: float, h: float,
                          r: float) -> np.ndarray:
    r = max(0.0, min(r, min(w, h) / 2))
    pts: list[np.ndarray] = []
    corners = [
        (x + w - r, y + r, -np.pi / 2, 0.0),
        (x + w - r, y + h - r, 0.0, np.pi / 2),
        (x + r, y + h - r, np.pi / 2, np.pi),
        (x + r, y + r, np.pi, 3 * np.pi / 2),
    ]
    straight = [
        ((x + r, y), (x + w - r, y)),
        ((x + w, y + r), (x + w, y + h - r)),
        ((x + w - r, y + h), (x + r, y + h)),
        ((x, y + h - r), (x, y + r)),
    ]
    for i in range(4):
        a, b = straight[i]
        pts.extend(_densify(np.array([a, b])))
        cx, cy, a0, a1 = corners[i]
        if r > 0:
            ang = np.linspace(a0, a1, 24)
            pts.extend(np.column_stack([cx + r * np.cos(ang), cy + r * np.sin(ang)]))
    return np.array(pts)


def polygon_candidate(samples: np.ndarray, expected_corners: int | None,
                      stroke_width: float) -> Candidate | None:
    """Sharp closed polygon, for shapes like an arrowhead."""
    pts = _polyline_points(samples, True)
    contour = pts.astype(np.float32).reshape(-1, 1, 2)
    perimeter = cv2.arcLength(contour, True)
    for frac in (0.02, 0.03, 0.045, 0.06, 0.08):
        approx = cv2.approxPolyDP(contour, frac * perimeter, True).reshape(-1, 2).astype(float)
        if expected_corners is not None and len(approx) != expected_corners:
            continue
        if len(approx) < 3:
            continue
        ring = np.vstack([approx, approx[:1]])
        outline = _densify(ring)
        max_e, rms_e = measure(samples, outline)
        return Candidate(
            kind="polygon", complexity=len(approx), closed=True, outline=outline,
            max_error=max_e, rms_error=rms_e,
            elements=[SvgPolyline(points=[(float(x), float(y)) for x, y in ring])],
            notes=f"corners={len(approx)}",
        )
    return None


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    """2-D scalar cross product; numpy's own is deprecated for 2-vectors."""
    return float(a[0] * b[1] - a[1] * b[0])


def corner_polyline_candidate(samples: np.ndarray, corner_indices: list[int],
                              closed: bool, tolerance: float) -> Candidate | None:
    """Straight runs meeting at the corners the raster actually shows.

    A chart arrow's zigzag is not a curve: it is four straight runs with
    sharp turns between them. Fitting each run separately and meeting
    the neighbours at their intersection keeps the turns sharp, whereas
    a cubic chain chases the skeleton's wobble and arrives at every peak
    slightly smoothed. Returns None unless *every* run is straight
    within tolerance, so a stroke that genuinely curves between corners
    is left to the curve candidates.
    """
    if closed or len(corner_indices) < 1 or len(samples) < 6:
        return None

    bounds = [0, *corner_indices, len(samples) - 1]
    bounds = sorted(set(bounds))
    pieces = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a >= 2]
    if len(pieces) < 2:
        return None

    # Runs are allowed a little more slack than a whole-stroke fit: a
    # skeleton wobbles by about a pixel along a long straight run, and
    # refusing the chain over that hands a plainly polygonal zigzag to a
    # cubic. The gate still caps the finished chain's displacement.
    run_tolerance = tolerance * 1.5

    fits = []
    for start, end in pieces:
        piece = samples[start : end + 1]
        fit = fit_line(piece)
        projected = fit.point + np.outer(
            (piece - fit.point) @ fit.direction, fit.direction
        )
        if float(np.max(np.linalg.norm(piece - projected, axis=1))) > run_tolerance:
            return None
        fits.append(fit)

    vertices = [
        fits[0].point
        + np.dot(samples[pieces[0][0]] - fits[0].point, fits[0].direction)
        * fits[0].direction
    ]
    for before, after, (_, joint) in zip(fits, fits[1:], pieces[:-1]):
        cross = float(_cross2(before.direction, after.direction))
        if abs(cross) < 1e-6:
            vertices.append(samples[joint].astype(float))
            continue
        delta = after.point - before.point
        step = float(_cross2(delta, after.direction)) / cross
        meeting = before.point + step * before.direction
        # An intersection far outside the joint means the two runs are
        # nearly parallel; trust the pixels there instead.
        if float(np.linalg.norm(meeting - samples[joint])) > 4.0 * max(tolerance, 1.0):
            meeting = samples[joint].astype(float)
        vertices.append(meeting)
    last_fit, (last_start, last_end) = fits[-1], pieces[-1]
    vertices.append(
        last_fit.point
        + np.dot(samples[last_end] - last_fit.point, last_fit.direction)
        * last_fit.direction
    )

    ring = np.asarray(vertices, dtype=float)
    if len(ring) < 3:
        return None
    outline = _densify(ring)
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="corner-polyline", complexity=len(ring), closed=False, outline=outline,
        max_error=max_e, rms_error=rms_e,
        elements=[SvgPolyline(points=[(float(x), float(y)) for x, y in ring])],
        notes=f"corners={len(ring) - 2}",
    )


# ---------------------------------------------------------------------------
# open-shape curve candidates
# ---------------------------------------------------------------------------


def arc_candidate(samples: np.ndarray, min_radius: float,
                  min_sagitta: float) -> Candidate | None:
    fit = fit_arc(samples, min_radius)
    if fit is None:
        return None
    chord = float(np.linalg.norm(fit.end - fit.start))
    half = min(chord / 2, fit.radius)
    sagitta = float(fit.radius - np.sqrt(max(0.0, fit.radius**2 - half**2)))
    if sagitta < min_sagitta:
        return None
    outline = _arc_outline(fit.center, fit.radius, fit.start, fit.end, fit.clockwise)
    max_e, rms_e = measure(samples, outline)
    from app.services.svg_model import PathArcTo

    return Candidate(
        kind="arc", complexity=3, closed=False, outline=outline,
        max_error=max_e, rms_error=rms_e,
        elements=[SvgPath(commands=[
            PathMoveTo(x=float(fit.start[0]), y=float(fit.start[1])),
            PathArcTo(rx=float(fit.radius), ry=float(fit.radius),
                      large_arc=fit.sweep_degrees > 180.0,
                      sweep=not fit.clockwise,
                      x=float(fit.end[0]), y=float(fit.end[1])),
        ])],
    )


def _curvature_sign_splits(samples: np.ndarray, window: int,
                           min_run: int = 8, min_turn_degrees: float = 25.0) -> list[int]:
    """Indices where curvature genuinely reverses (inflections).

    A bare sign flip is not enough: skeleton noise flips the sign for a
    sample or two all along a clean arc, which would label a semicircle
    as changing-curvature and hand it to a cubic chain. A real
    inflection separates two substantial runs that each turn
    meaningfully in their own direction.
    """
    n = len(samples)
    if n < 2 * window + 3:
        return []

    signed = np.zeros(n)
    for i in range(window, n - window):
        before = samples[i] - samples[i - window]
        after = samples[i + window] - samples[i]
        cross = before[0] * after[1] - before[1] * after[0]
        norm = float(np.linalg.norm(before) * np.linalg.norm(after))
        if norm > 0:
            signed[i] = np.degrees(np.arcsin(np.clip(cross / norm, -1.0, 1.0)))

    signs = np.sign(signed)
    runs: list[tuple[int, int, float, float]] = []
    index = window
    while index < n - window:
        sign = signs[index]
        if sign == 0:
            index += 1
            continue
        stop = index
        while stop < n - window and (signs[stop] == sign or signs[stop] == 0):
            stop += 1
        turn = float(np.abs(signed[index:stop]).sum())
        runs.append((index, stop, float(sign), turn))
        index = stop

    strong = [r for r in runs if (r[1] - r[0]) >= min_run and r[3] >= min_turn_degrees]
    splits = []
    for previous, current in zip(strong, strong[1:]):
        if previous[2] != current[2]:
            splits.append(int((previous[1] + current[0]) // 2))
    return splits


def _fit_cubics_to_tolerance(
    piece: np.ndarray, tolerance: float, depth: int = 0
) -> list[tuple]:
    """Fit one cubic, subdividing at the worst point until it fits.

    Splitting only at inflections is not enough: a short, tightly curved
    run needs more than one cubic to stay sub-pixel, and a chain that is
    merely 'curve-shaped' loses to the polyline baseline on measured
    error — correctly, since a worse fit should never win.
    """
    if len(piece) < 4 or depth >= 4:
        return [("line", piece[-1], None, None)]

    fit = fit_cubic_bezier(piece)
    outline = _bezier_outline(fit.p0, fit.p1, fit.p2, fit.p3)
    tree = cKDTree(outline)
    distances, _ = tree.query(piece)
    if float(distances.max()) <= tolerance:
        return [("cubic", fit.p3, fit.p1, fit.p2)]

    split = int(np.argmax(distances))
    if split < 2 or split > len(piece) - 3:
        return [("cubic", fit.p3, fit.p1, fit.p2)]

    return (
        _fit_cubics_to_tolerance(piece[: split + 1], tolerance, depth + 1)
        + _fit_cubics_to_tolerance(piece[split:], tolerance, depth + 1)
    )


def bezier_chain_candidate(
    samples: np.ndarray, window: int, tolerance: float = 1.0
) -> Candidate | None:
    """Cubic chain: split at inflections, then refine to tolerance.

    Inflections are hard boundaries because a single cubic cannot change
    curvature sign cleanly; within each run the chain is subdivided only
    as far as accuracy demands.
    """
    if len(samples) < 6:
        return None
    splits = _curvature_sign_splits(samples, window)
    bounds = [0] + splits + [len(samples) - 1]
    commands: list = [PathMoveTo(x=float(samples[0][0]), y=float(samples[0][1]))]
    outline_parts: list[np.ndarray] = []
    cursor = samples[0]

    for a, b in zip(bounds, bounds[1:]):
        piece = samples[a:b + 1]
        if len(piece) < 2:
            continue
        for kind, end, c1, c2 in _fit_cubics_to_tolerance(piece, tolerance):
            if kind == "line":
                commands.append(PathLineTo(x=float(end[0]), y=float(end[1])))
                outline_parts.append(_densify(np.vstack([cursor, end])))
            else:
                commands.append(PathCubicTo(
                    x1=float(c1[0]), y1=float(c1[1]),
                    x2=float(c2[0]), y2=float(c2[1]),
                    x=float(end[0]), y=float(end[1]),
                ))
                outline_parts.append(_bezier_outline(cursor, c1, c2, end))
            cursor = np.asarray(end, dtype=float)

    if len(commands) < 2:
        return None
    outline = np.vstack(outline_parts)
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="bezier", complexity=2 + 3 * (len(commands) - 1), closed=False,
        outline=outline, max_error=max_e, rms_error=rms_e,
        elements=[SvgPath(commands=commands, closed=False)],
        notes=f"segments={len(commands) - 1}",
    )


# ---------------------------------------------------------------------------
# safety gate
# ---------------------------------------------------------------------------


def sharp_corner_indices(samples: np.ndarray, window: int,
                         closed: bool = False) -> list[int]:
    """Sample indices where the traced stroke turns sharply enough to be
    a corner. See `sharp_corner_points` for what the test means."""
    if len(samples) < 2 * window + 3:
        return []

    indices = set(detect_corners(samples, window))
    if closed:
        # A closed stroke's seam sits at the ends, where `detect_corners`
        # refuses to look. Rotate it half a turn and look again, so a
        # corner that happens to fall on the seam is still seen.
        body = samples[:-1] if np.allclose(samples[0], samples[-1]) else samples
        if len(body) >= 2 * window + 3:
            shift = len(body) // 2
            rolled = np.roll(body, shift, axis=0)
            for index in detect_corners(rolled, window):
                indices.add((index + len(body) - shift) % len(body))

    return sorted(i for i in indices if 0 <= i < len(samples))


def sharp_corner_points(samples: np.ndarray, window: int,
                        closed: bool = False) -> np.ndarray:
    """Positions where the traced stroke turns sharply enough to be a corner.

    Used as a veto, not as a fitting hint: whatever primitive wins has
    to still pass through these points, so a corner the raster shows is
    never smoothed into a radius. `detect_corners` already separates a
    corner from a tight arc by requiring the turn to be concentrated,
    so an honestly rounded corner produces no point here and a rounded
    primitive stays allowed.
    """
    indices = sharp_corner_indices(samples, window, closed)
    if not indices:
        return np.empty((0, 2))
    return samples[indices]


def _turn_at(points: np.ndarray, target: np.ndarray, span: float) -> float:
    """Turning angle, in degrees, of `points` at the place nearest `target`.

    Measured over a fixed arc length on either side rather than a fixed
    number of samples, so the same span can be applied to the traced
    pixels and to a candidate's densified outline and the two numbers
    compared directly.
    """
    if len(points) < 3:
        return 0.0
    index = int(np.argmin(np.linalg.norm(points - target, axis=1)))

    def reach(direction: int) -> np.ndarray | None:
        travelled = 0.0
        cursor = index
        while 0 <= cursor + direction < len(points):
            step = float(np.linalg.norm(points[cursor + direction] - points[cursor]))
            cursor += direction
            travelled += step
            if travelled >= span:
                return points[cursor]
        return points[cursor] if cursor != index and travelled > span * 0.5 else None

    before = reach(-1)
    after = reach(+1)
    if before is None or after is None:
        return 0.0
    incoming = points[index] - before
    outgoing = after - points[index]
    n_in = float(np.linalg.norm(incoming))
    n_out = float(np.linalg.norm(outgoing))
    if n_in < 1e-9 or n_out < 1e-9:
        return 0.0
    cosine = float(np.clip(np.dot(incoming / n_in, outgoing / n_out), -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def evaluate_gate(
    candidate: Candidate,
    baseline: Candidate,
    samples: np.ndarray,
    closed: bool,
    stroke_width: float,
    improvement_ratio: float = 0.85,
    max_displacement_ratio: float = 1.0,
    preferred: bool = False,
    corners: np.ndarray | None = None,
) -> GateResult:
    """Decide whether `candidate` may replace `baseline`.

    Every check is a veto. A curve has to be structurally identical to
    what it replaces and measurably better; anything else keeps the
    baseline, which is always a safe straight/polyline reconstruction.
    """
    result = GateResult(accepted=True, confidence=1.0)

    if candidate.closed != closed:
        result.reject(
            "closure mismatch: refusing to close an open stroke"
            if candidate.closed else "closure mismatch: refusing to open a closed stroke"
        )
        return result

    for element in candidate.elements:
        if _degenerate(element):
            result.reject("degenerate (zero-length) element")
            return result

    max_displacement = max(1.0, stroke_width * max_displacement_ratio)
    if candidate.max_error > max_displacement:
        result.reject(
            f"max displacement {candidate.max_error:.2f}px exceeds "
            f"{max_displacement:.2f}px"
        )

    # A candidate the stroke's own structure calls for — a three-corner
    # outline wanting a sharp polygon, an inflected path wanting cubics —
    # is judged by the displacement cap above rather than by beating a
    # polyline that simply has more vertices to hug pixels with. Blur
    # bows a triangle's edge by a few pixels, and demanding the polygon
    # also win on raw error would hand that edge to an arc.
    if not preferred and candidate.max_error > baseline.max_error * improvement_ratio:
        result.reject(
            f"no clear improvement: {candidate.max_error:.2f}px vs baseline "
            f"{baseline.max_error:.2f}px"
        )

    # Coverage: the candidate must span the same extent as the samples.
    if len(candidate.outline):
        tree = cKDTree(candidate.outline)
        d_start, _ = tree.query(samples[0])
        d_end, _ = tree.query(samples[-1])
        if max(d_start, d_end) > max(1.5, stroke_width * 0.75):
            result.reject("endpoint coverage lost")

        # And must not wander outside the ink it came from.
        back = cKDTree(samples)
        outward, _ = back.query(candidate.outline)
        if float(outward.max()) > max(2.0, stroke_width * 1.5):
            result.reject("candidate strays outside the traced stroke")

        # Corner preservation. A bar chart's flat top meets its sides at
        # two sharp corners; an arc drawn between them has a small mean
        # error and would otherwise win, replacing the top edge with a
        # dome. Any corner the raster shows has to survive.
        if corners is not None and len(corners):
            missed, _ = tree.query(corners)
            limit = max(1.0, stroke_width * 0.6)
            if float(missed.max()) > limit:
                result.reject(
                    f"rounds off a corner the raster shows "
                    f"({float(missed.max()):.2f}px from it, limit {limit:.2f}px)"
                )

            # Passing near the corner is not enough: a cubic can thread a
            # zigzag's peak within a pixel and still arrive with a smooth
            # tangent, which is what turned the chart arrow's sharp peaks
            # into waves. Compare the turn itself, measured the same way
            # on the pixels and on the candidate.
            span = max(2.0, stroke_width * 1.5)
            for corner in corners:
                raster_turn = _turn_at(samples, corner, span)
                if raster_turn < CORNER_TURN_DEGREES:
                    continue
                kept = _turn_at(candidate.outline, corner, span)
                if kept < raster_turn * CORNER_TURN_RETENTION:
                    result.reject(
                        f"smooths a {raster_turn:.0f}deg corner down to "
                        f"{kept:.0f}deg"
                    )
                    break

    if result.accepted:
        margin = max(0.0, baseline.max_error - candidate.max_error)
        result.confidence = float(
            min(1.0, 0.5 + 0.5 * margin / max(baseline.max_error, 1e-6))
        )
    else:
        result.confidence = 0.0
    return result


def _degenerate(element) -> bool:
    if isinstance(element, SvgLine):
        return float(np.hypot(element.x2 - element.x1,
                              element.y2 - element.y1)) < MIN_ELEMENT_LENGTH
    if isinstance(element, SvgPolyline):
        pts = np.array(element.points, dtype=float)
        if len(pts) < 2:
            return True
        return float(np.sum(np.hypot(*np.diff(pts, axis=0).T))) < MIN_ELEMENT_LENGTH
    if isinstance(element, SvgCircle):
        return element.r < MIN_ELEMENT_LENGTH
    if isinstance(element, SvgEllipse):
        return element.rx < MIN_ELEMENT_LENGTH or element.ry < MIN_ELEMENT_LENGTH
    if isinstance(element, SvgRect):
        return element.width < MIN_ELEMENT_LENGTH or element.height < MIN_ELEMENT_LENGTH
    if isinstance(element, SvgPath):
        moves = [c for c in element.commands if not isinstance(c, PathMoveTo)]
        return len(moves) == 0
    return False


def deduplicate(elements: list) -> list:
    """Drop degenerate elements and exact duplicates."""
    seen: set[str] = set()
    out = []
    for element in elements:
        if _degenerate(element):
            continue
        key = repr(element)
        if key in seen:
            continue
        seen.add(key)
        out.append(element)
    return out


def _longest_prefix(samples: np.ndarray, tolerance: float, fitter, min_points: int):
    """Longest prefix of `samples` that `fitter` matches within tolerance."""
    best = None
    low, high = min_points, len(samples)
    while low <= high:
        mid = (low + high) // 2
        result = fitter(samples[:mid])
        if result is not None and result[0] <= tolerance:
            best = (mid, result)
            low = mid + 1
        else:
            high = mid - 1
    return best


def composite_candidate(
    samples: np.ndarray,
    stroke_width: float,
    tolerance: float,
    window: int,
    corner_indices: list[int] | None = None,
) -> Candidate | None:
    """Segment an open stroke into straight, arc and cubic runs.

    A stroke that flows from a straight into a turn is not any single
    primitive. Greedy longest-prefix matching keeps the straight part
    straight (so it stays eligible for axis alignment) instead of
    swallowing it into one accommodating curve.
    """
    if len(samples) < 6:
        return None

    min_radius = max(1.0, stroke_width * 0.6)
    min_sagitta = max(0.8, stroke_width * 0.4)
    min_run = max(4.0, stroke_width * 2.0)

    def line_fit(piece):
        if len(piece) < 3:
            return None
        fit = fit_line(piece)
        start = fit.point + np.dot(piece[0] - fit.point, fit.direction) * fit.direction
        end = fit.point + np.dot(piece[-1] - fit.point, fit.direction) * fit.direction
        outline = _densify(np.vstack([start, end]))
        err, _ = measure(piece, outline)
        return (err, ("line", start, end, outline))

    def arc_fit(piece):
        if len(piece) < 8:
            return None
        fit = fit_arc(piece, min_radius)
        if fit is None:
            return None
        # Same physical floor as the standalone arc candidate: a bend too
        # shallow to see at stroke scale is a straight line, not an arc.
        chord = float(np.linalg.norm(fit.end - fit.start))
        half = min(chord / 2, fit.radius)
        if float(fit.radius - np.sqrt(max(0.0, fit.radius**2 - half**2))) < min_sagitta:
            return None
        outline = _arc_outline(fit.center, fit.radius, fit.start, fit.end, fit.clockwise)
        err, _ = measure(piece, outline)
        return (err, ("arc", fit, None, outline))

    from app.services.svg_model import PathArcTo

    commands: list = [PathMoveTo(x=float(samples[0][0]), y=float(samples[0][1]))]
    outline_parts: list[np.ndarray] = []
    cursor = 0
    kinds: list[str] = []
    guard = 0

    corners = sorted(corner_indices or [])

    while cursor < len(samples) - 1 and guard < 40:
        guard += 1
        # A piece may run up to the next corner but never through it.
        # Without this an arc happily spans a bar chart's flat top and
        # both of its corners, turning the top edge into a dome.
        limit = len(samples)
        for corner in corners:
            if corner > cursor + 1:
                limit = corner + 1
                break
        remaining = samples[cursor:limit]
        if len(remaining) < 4:
            remaining = samples[cursor:]
        if len(remaining) < 4:
            break

        line_best = _longest_prefix(remaining, tolerance, line_fit, 3)
        arc_best = _longest_prefix(remaining, tolerance, arc_fit, 8)

        use_line = (
            line_best is not None
            and arc_length(remaining[: line_best[0]]) >= min_run
            and (arc_best is None or line_best[0] >= arc_best[0])
        )
        use_arc = (
            not use_line
            and arc_best is not None
            and arc_length(remaining[: arc_best[0]]) >= min_run
        )

        if use_line:
            count, (_, (_, start, end, outline)) = line_best
            commands.append(PathLineTo(x=float(end[0]), y=float(end[1])))
            outline_parts.append(outline)
            kinds.append("line")
            cursor += count - 1
        elif use_arc:
            count, (_, (_, fit, _, outline)) = arc_best
            commands.append(PathArcTo(
                rx=float(fit.radius), ry=float(fit.radius),
                large_arc=fit.sweep_degrees > 180.0, sweep=not fit.clockwise,
                x=float(fit.end[0]), y=float(fit.end[1]),
            ))
            outline_parts.append(outline)
            kinds.append("arc")
            cursor += count - 1
        else:
            piece = remaining
            start_point = samples[cursor]
            for kind, end, c1, c2 in _fit_cubics_to_tolerance(piece, tolerance):
                if kind == "line":
                    commands.append(PathLineTo(x=float(end[0]), y=float(end[1])))
                    outline_parts.append(_densify(np.vstack([start_point, end])))
                else:
                    commands.append(PathCubicTo(
                        x1=float(c1[0]), y1=float(c1[1]),
                        x2=float(c2[0]), y2=float(c2[1]),
                        x=float(end[0]), y=float(end[1]),
                    ))
                    outline_parts.append(_bezier_outline(start_point, c1, c2, end))
                start_point = np.asarray(end, dtype=float)
                kinds.append(kind)
            break

    if len(commands) < 2 or not outline_parts:
        return None
    if len(set(kinds)) < 2:
        return None  # a single-kind result is already covered by its own candidate

    outline = np.vstack(outline_parts)
    max_e, rms_e = measure(samples, outline)
    return Candidate(
        kind="composite", complexity=2 + 2 * len(kinds), closed=False,
        outline=outline, max_error=max_e, rms_error=rms_e,
        elements=[SvgPath(commands=commands, closed=False)],
        notes="+".join(kinds),
    )
