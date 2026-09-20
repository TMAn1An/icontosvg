"""Unit tests for centerline extraction and primitive fitting."""

import numpy as np

from app.services.geometry.centerline import (
    binarize_for_skeleton,
    estimate_stroke_width,
    extract_skeleton,
    is_closed,
    simplify_branch,
    trace_branches,
)
from app.services.geometry.primitives import (
    LineSegment,
    fit_circle,
    is_axis_aligned_rectangle,
)


def test_line_segment_length_and_angle():
    segment = LineSegment(x1=0, y1=0, x2=10, y2=0)
    assert segment.length == 10.0
    assert segment.angle_degrees == 0.0


def test_trace_branches_on_horizontal_line_gives_one_straight_branch():
    image = np.full((20, 40), 255, dtype=np.uint8)
    image[10, 5:35] = 0

    skeleton = extract_skeleton(binarize_for_skeleton(image))
    branches = trace_branches(skeleton)

    assert len(branches) == 1
    simplified = simplify_branch(branches[0], epsilon=1.0, closed=False)
    assert len(simplified) == 2


def test_trace_branches_splits_a_cross_into_four_branches():
    """A crossing is a junction: four arms, traced separately."""
    image = np.full((41, 41), 255, dtype=np.uint8)
    image[20, 5:36] = 0
    image[5:36, 20] = 0

    skeleton = extract_skeleton(binarize_for_skeleton(image))
    branches = trace_branches(skeleton)

    assert len(branches) == 4


def test_trace_branches_handles_closed_loop_without_endpoints():
    image = np.full((60, 60), 255, dtype=np.uint8)
    image[10:50, 10:50] = 0
    image[14:46, 14:46] = 255  # hollow square outline

    skeleton = extract_skeleton(binarize_for_skeleton(image))
    branches = trace_branches(skeleton)

    assert len(branches) == 1
    assert is_closed(branches[0])


def test_estimate_stroke_width_matches_drawn_width():
    image = np.full((40, 60), 255, dtype=np.uint8)
    image[18:24, 5:55] = 0  # 6px tall horizontal bar

    binary = binarize_for_skeleton(image)
    width, widths = estimate_stroke_width(binary, extract_skeleton(binary))

    assert 5.0 <= width <= 7.0
    assert widths.size > 0


def test_fit_circle_recovers_known_circle():
    angles = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    points = np.column_stack([30 + 12 * np.cos(angles), 40 + 12 * np.sin(angles)])

    fit = fit_circle(points)

    assert abs(fit.circle.cx - 30) < 0.1
    assert abs(fit.circle.cy - 40) < 0.1
    assert abs(fit.circle.radius - 12) < 0.1
    assert fit.mean_residual < 0.1


def test_fit_circle_reports_high_residual_for_a_square():
    points = np.array(
        [(0, 0), (10, 0), (20, 0), (20, 10), (20, 20), (10, 20), (0, 20), (0, 10)],
        dtype=float,
    )

    fit = fit_circle(points)

    assert fit.mean_residual > 1.0


def test_is_axis_aligned_rectangle_accepts_square_and_rejects_diamond():
    square = np.array([(0, 0), (20, 0), (20, 20), (0, 20)], dtype=float)
    diamond = np.array([(10, 0), (20, 10), (10, 20), (0, 10)], dtype=float)

    assert is_axis_aligned_rectangle(square) is True
    assert is_axis_aligned_rectangle(diamond) is False
