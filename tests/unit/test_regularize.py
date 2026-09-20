"""Tests for geometry regularization: straightening, parallelism, alignment.

These drive the full LineModeStrategy over synthetic rasters, because the
behaviour under test is an icon-wide property (shared axes, shared
baselines) that only emerges once every branch has been fitted together.
"""

from __future__ import annotations

import numpy as np

from app.services.geometry.regularize import (
    HORIZONTAL,
    VERTICAL,
    classify_sections,
    estimate_dominant_axes,
    fit_line_robust,
    fit_sections,
)
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.svg_model import SvgCircle, SvgLine, SvgPath, SvgPolyline, SvgRect


def blank(height: int, width: int) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def draw_line(
    image: np.ndarray, start: tuple[int, int], end: tuple[int, int], thickness: int = 4
) -> None:
    import cv2

    cv2.line(image, start, end, color=0, thickness=thickness)


def segment_angles(element) -> list[float]:
    """Angles of every segment in an emitted element, normalized to (-90, 90]."""
    if isinstance(element, SvgLine):
        points = [(element.x1, element.y1), (element.x2, element.y2)]
    elif isinstance(element, SvgPolyline):
        points = element.points
    else:
        return []

    angles = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        while angle <= -90:
            angle += 180
        while angle > 90:
            angle -= 180
        angles.append(angle)
    return angles


# --- 1. a slightly tilted raster line becomes horizontal ------------------


def test_slightly_tilted_line_becomes_exactly_horizontal():
    image = blank(60, 140)
    draw_line(image, (10, 28), (130, 32))  # ~1.9 degrees of tilt

    document = LineModeStrategy().reconstruct(image)
    lines = [e for e in document.elements if isinstance(e, SvgLine)]

    assert len(lines) == 1
    assert abs(lines[0].y1 - lines[0].y2) < 1e-6


def test_tilted_line_is_counted_as_snapped():
    image = blank(60, 140)
    draw_line(image, (10, 28), (130, 32))

    strategy = LineModeStrategy()
    strategy.reconstruct(image)

    assert strategy.diagnostics.regularization.snapped_horizontal >= 1


# --- 2. several bars become parallel --------------------------------------


def test_bars_are_made_exactly_parallel():
    """Three upright bars, each drawn a little off-vertical."""
    image = blank(140, 200)
    for index, (x_top, x_bottom) in enumerate([(40, 41), (100, 99), (160, 161)]):
        top = 100 - 25 * (index + 1)
        draw_line(image, (x_top, top), (x_bottom, 110))

    strategy = LineModeStrategy()
    document = strategy.reconstruct(image)

    vertical_angles = []
    for element in document.elements:
        for angle in segment_angles(element):
            if abs(angle) >= 80:
                vertical_angles.append(abs(angle))

    assert len(vertical_angles) >= 3
    assert max(vertical_angles) - min(vertical_angles) < 1e-6


def test_dominant_vertical_angle_is_shared_across_the_icon():
    image = blank(140, 200)
    for x_top, x_bottom in [(40, 42), (100, 98), (160, 161)]:
        draw_line(image, (x_top, 30), (x_bottom, 110))

    strategy = LineModeStrategy()
    strategy.reconstruct(image)
    stats = strategy.diagnostics.regularization

    assert stats.snapped_vertical >= 3
    assert 85.0 <= stats.vertical_angle <= 95.0


# --- 3. shared baselines are aligned -------------------------------------


def test_nearly_level_bar_feet_align_onto_one_baseline():
    """Bar feet drawn 1px apart in y should end at exactly the same y."""
    image = blank(140, 200)
    for x, foot_y in [(40, 108), (100, 109), (160, 110)]:
        draw_line(image, (x, 40), (x, foot_y))

    strategy = LineModeStrategy()
    document = strategy.reconstruct(image)

    foot_ys = []
    for element in document.elements:
        if isinstance(element, SvgLine):
            foot_ys.append(max(element.y1, element.y2))

    assert len(foot_ys) == 3
    assert max(foot_ys) - min(foot_ys) < 1e-6
    assert strategy.diagnostics.regularization.endpoints_aligned >= 2


def test_parallel_lines_at_the_same_level_share_one_offset():
    """Two horizontals a pixel apart in y collapse onto a single level."""
    image = blank(80, 240)
    draw_line(image, (10, 40), (100, 40))
    draw_line(image, (140, 41), (230, 41))

    strategy = LineModeStrategy()
    document = strategy.reconstruct(image)

    ys = [e.y1 for e in document.elements if isinstance(e, SvgLine)]
    assert len(ys) == 2
    assert abs(ys[0] - ys[1]) < 1e-6
    assert strategy.diagnostics.regularization.offsets_aligned >= 2


def test_distant_parallel_lines_are_not_forced_together():
    """Alignment must express the raster, not invent it."""
    image = blank(120, 200)
    draw_line(image, (10, 30), (190, 30))
    draw_line(image, (10, 90), (190, 90))

    document = LineModeStrategy().reconstruct(image)
    ys = sorted(e.y1 for e in document.elements if isinstance(e, SvgLine))

    assert len(ys) == 2
    assert ys[1] - ys[0] > 50


# --- 4. intentional diagonals stay diagonal ------------------------------


def test_intentional_diagonal_is_not_snapped_to_an_axis():
    image = blank(140, 140)
    draw_line(image, (20, 20), (120, 120))  # a true 45 degree diagonal

    strategy = LineModeStrategy()
    document = strategy.reconstruct(image)

    angles = [angle for e in document.elements for angle in segment_angles(e)]
    assert angles
    assert all(abs(abs(angle) - 45.0) < 6.0 for angle in angles)
    assert strategy.diagnostics.regularization.diagonals_preserved >= 1


def test_shallow_diagonal_beyond_tolerance_keeps_its_angle():
    """A deliberate 12 degree slope is not 'nearly horizontal'."""
    image = blank(100, 220)
    draw_line(image, (15, 30), (205, 70))  # ~11.9 degrees

    document = LineModeStrategy().reconstruct(image)
    angles = [angle for e in document.elements for angle in segment_angles(e)]

    assert angles
    assert all(6.0 < abs(angle) < 20.0 for angle in angles)


# --- 5. curves are not converted into straight lines ---------------------


def test_circle_stays_a_circle_and_never_reaches_the_regularizer():
    import cv2

    image = blank(120, 120)
    cv2.circle(image, (60, 60), 40, color=0, thickness=4)

    strategy = LineModeStrategy()
    document = strategy.reconstruct(image)

    circles = [e for e in document.elements if isinstance(e, SvgCircle)]
    assert len(circles) == 1
    assert abs(circles[0].r - 40) < 2.0
    assert not any(isinstance(e, (SvgLine, SvgPolyline)) for e in document.elements)


def test_wavy_curve_keeps_its_intermediate_vertices():
    image = blank(120, 240)
    xs = np.arange(15, 225)
    ys = (60 + 30 * np.sin((xs - 15) / 28.0)).astype(int)
    for (x1, y1), (x2, y2) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        draw_line(image, (int(x1), int(y1)), (int(x2), int(y2)))

    document = LineModeStrategy().reconstruct(image)

    # A curve is now carried by real curve commands, not a chain of chords.
    paths = [e for e in document.elements if isinstance(e, SvgPath)]
    assert paths, "a curve must not collapse into straight segments"
    d = paths[0].to_d()
    assert "C" in d or "A" in d, f"expected curve commands, got {d}"
    assert not any(isinstance(e, SvgPolyline) for e in document.elements)


# --- 6. rounded rectangles retain rounded corners ------------------------


def draw_rounded_rect(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    thickness: int = 4,
) -> None:
    """Four straight edges joined by four quarter-circle corner arcs."""
    import cv2

    cv2.line(image, (x1 + radius, y1), (x2 - radius, y1), 0, thickness)
    cv2.line(image, (x1 + radius, y2), (x2 - radius, y2), 0, thickness)
    cv2.line(image, (x1, y1 + radius), (x1, y2 - radius), 0, thickness)
    cv2.line(image, (x2, y1 + radius), (x2, y2 - radius), 0, thickness)

    axes = (radius, radius)
    for center, start, end in [
        ((x1 + radius, y1 + radius), 180, 270),
        ((x2 - radius, y1 + radius), 270, 360),
        ((x2 - radius, y2 - radius), 0, 90),
        ((x1 + radius, y2 - radius), 90, 180),
    ]:
        cv2.ellipse(image, center, axes, 0, start, end, 0, thickness)


def test_rounded_rectangle_keeps_corner_transitions():
    """Long edges get axis-aligned; the corners keep their extra vertices."""
    image = blank(140, 200)
    draw_rounded_rect(image, 25, 25, 175, 115, radius=18)

    document = LineModeStrategy().reconstruct(image)

    paths = [e for e in document.elements if isinstance(e, SvgPath)]
    assert paths, "a rounded rectangle needs curve commands for its corners"
    d = paths[0].to_d()
    # Corners are arcs, not chamfers; the four long edges stay straight.
    assert d.count("A") >= 4, f"expected four corner arcs, got {d}"
    assert d.count("L") >= 4, f"expected four straight edges, got {d}"


def test_rounded_ends_are_preserved_as_stroke_caps():
    image = blank(60, 140)
    draw_line(image, (10, 30), (130, 30))

    document = LineModeStrategy().reconstruct(image)

    assert document.stroke_style.linecap == "round"
    assert document.stroke_style.linejoin == "round"


# --- 12. short standalone details survive --------------------------------


def test_short_dashes_are_not_pruned_away():
    image = blank(60, 200)
    for x in range(20, 180, 24):
        draw_line(image, (x, 30), (x + 10, 30))

    document = LineModeStrategy().reconstruct(image)
    drawn = [e for e in document.elements if isinstance(e, (SvgLine, SvgPolyline))]

    assert len(drawn) == 7, "every dash must survive reconstruction"


# --- supporting units ----------------------------------------------------


def test_fit_line_robust_ignores_stair_step_noise():
    xs = np.arange(0, 60, dtype=float)
    ys = np.where(xs < 30, 10.0, 11.0)  # a single 1px stair step
    centroid, direction = fit_line_robust(np.column_stack([xs, ys]))

    angle = abs(float(np.degrees(np.arctan2(direction[1], direction[0]))))
    assert angle < 2.0
    assert 9.0 < centroid[1] < 12.0


def test_fit_line_robust_handles_vertical_runs():
    ys = np.arange(0, 60, dtype=float)
    xs = np.full_like(ys, 20.0)
    _, direction = fit_line_robust(np.column_stack([xs, ys]))

    assert abs(abs(float(np.degrees(np.arctan2(direction[1], direction[0])))) - 90) < 1e-6


def test_classify_and_estimate_axes_from_sections():
    horizontal = np.column_stack([np.arange(0, 50, dtype=float), np.full(50, 5.0)])
    vertical = np.column_stack([np.full(50, 5.0), np.arange(0, 50, dtype=float)])

    sections = fit_sections(horizontal, epsilon=1.0, closed=False) + fit_sections(
        vertical, epsilon=1.0, closed=False
    )

    horizontal_angle, vertical_angle = estimate_dominant_axes(sections, 4.0)
    assert abs(horizontal_angle) < 1e-6
    assert abs(vertical_angle - 90.0) < 1e-6

    classify_sections(sections, horizontal_angle, vertical_angle, tolerance_degrees=4.0)
    assert [s.orientation for s in sections] == [HORIZONTAL, VERTICAL]


def test_consistently_rotated_icon_keeps_its_shared_axis():
    """A rotation past the tolerance but inside the candidate window is intent.

    Beyond the window (2x tolerance) an edge is not 'nearly horizontal' at
    all, so it is left as a diagonal instead of declaring a rotated axis.
    """
    angle = np.radians(6.0)
    length = np.arange(0, 60, dtype=float)
    rotated = np.column_stack([length * np.cos(angle), length * np.sin(angle)])

    sections = fit_sections(rotated, epsilon=1.0, closed=False)
    horizontal_angle, _ = estimate_dominant_axes(sections, 4.0)

    assert abs(horizontal_angle - 6.0) < 0.5
