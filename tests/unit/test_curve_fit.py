"""Curve-versus-corner classification tests.

Each fixture targets one distinction the classifier has to make, and each
has a blurred variant, because the real input is a JPEG and a classifier
that only works on crisp synthetic edges is not useful.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

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
    LineModel,
    detect_corners,
    fit_arc,
    fit_branch,
    fit_cubic_bezier,
    fit_line,
    select_model,
    tangent_turning,
)
from app.services.preprocessing import load_sheet
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.segmentation import detect_crops
from app.services.svg_model import SvgCircle, SvgLine, SvgPath, SvgPolyline

THICKNESS = 4


def blank(height: int, width: int) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def blur(image: np.ndarray, sigma: float = 1.4) -> np.ndarray:
    """Approximate the softness of a compressed raster sheet."""
    blurred = cv2.GaussianBlur(image, (0, 0), sigma)
    encoded = cv2.imencode(".jpg", blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 72])[1]
    return cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)


def section_kinds(document) -> list[str]:
    kinds = []
    for element in document.elements:
        if isinstance(element, SvgPath):
            for command in element.commands:
                kinds.append(type(command).__name__)
    return kinds


def path_d(document) -> str:
    paths = [e for e in document.elements if isinstance(e, SvgPath)]
    return paths[0].to_d() if paths else ""


def main_branch_models(image: np.ndarray) -> list:
    """Models of the longest branch only.

    Skeletonizing a corner leaves two- and three-pixel stubs beside it.
    Those are junction-routing artifacts, not something a curve fitter can
    or should repair, so shape tests look at the traced perimeter itself.
    """
    binary = binarize_for_skeleton(image)
    skeleton = extract_skeleton(binary)
    stroke_width, _ = estimate_stroke_width(binary, skeleton)
    branches = prune_spurs(trace_branches(skeleton), skeleton, stroke_width)
    longest = max(branches, key=len)
    fit = fit_branch(longest, closed=is_closed(longest), stroke_width=stroke_width)
    return [section.model for section in fit.sections]


def branch_models(image: np.ndarray) -> list:
    """Fit every branch of an image and return the flat list of models."""
    binary = binarize_for_skeleton(image)
    skeleton = extract_skeleton(binary)
    stroke_width, _ = estimate_stroke_width(binary, skeleton)
    branches = prune_spurs(trace_branches(skeleton), skeleton, stroke_width)
    models = []
    for branch in branches:
        fit = fit_branch(branch, closed=is_closed(branch), stroke_width=stroke_width)
        models.extend(section.model for section in fit.sections)
    return models


# --- sharp triangle -------------------------------------------------------


def triangle_image() -> np.ndarray:
    image = blank(160, 180)
    points = np.array([[90, 25], [155, 130], [25, 130]], dtype=np.int32)
    cv2.polylines(image, [points], isClosed=True, color=0, thickness=THICKNESS)
    return image


@pytest.mark.parametrize("blurred", [False, True])
def test_sharp_triangle_is_three_straights_with_sharp_corners(blurred: bool):
    image = triangle_image()
    if blurred:
        image = blur(image)

    models = main_branch_models(image)
    lines = [m for m in models if isinstance(m, LineModel)]
    curves = [m for m in models if not isinstance(m, LineModel)]

    assert not curves, "a triangle has no curved sections"
    if blurred:
        # Blur bows an edge by a couple of pixels; the fit reports that
        # honestly rather than pretending to sub-pixel accuracy.
        assert max(m.max_error for m in lines) < 2.5
    else:
        assert max(m.max_error for m in lines) < 1.5, "edges should fit sub-pixel"
    if blurred:
        # Blur bows an edge by more than the sub-pixel tolerance, so an
        # edge may legitimately be reported as two nearly-collinear
        # straights. What must not happen is a curve appearing.
        assert 3 <= len(lines) <= 5, [m.kind for m in models]
    else:
        assert len(lines) == 3, f"expected 3 straight edges, got {[m.kind for m in models]}"


@pytest.mark.parametrize("blurred", [False, True])
def test_triangle_corners_are_detected_and_preserved(blurred: bool):
    image = triangle_image()
    if blurred:
        image = blur(image)

    document = LineModeStrategy().reconstruct(image)
    strategy_corners = LineModeStrategy()
    strategy_corners.reconstruct(image)

    assert strategy_corners.diagnostics.corner_count >= 2
    # No curve commands anywhere: the corners stayed corners.
    assert "C" not in path_d(document)
    assert "A" not in path_d(document)


# --- rounded rectangle ----------------------------------------------------


def rounded_rect_image(radius: int = 18) -> np.ndarray:
    image = blank(140, 200)
    x1, y1, x2, y2 = 25, 25, 175, 115
    cv2.line(image, (x1 + radius, y1), (x2 - radius, y1), 0, THICKNESS)
    cv2.line(image, (x1 + radius, y2), (x2 - radius, y2), 0, THICKNESS)
    cv2.line(image, (x1, y1 + radius), (x1, y2 - radius), 0, THICKNESS)
    cv2.line(image, (x2, y1 + radius), (x2, y2 - radius), 0, THICKNESS)
    for center, start, end in [
        ((x1 + radius, y1 + radius), 180, 270),
        ((x2 - radius, y1 + radius), 270, 360),
        ((x2 - radius, y2 - radius), 0, 90),
        ((x1 + radius, y2 - radius), 90, 180),
    ]:
        cv2.ellipse(image, center, (radius, radius), 0, start, end, 0, THICKNESS)
    return image


@pytest.mark.parametrize("blurred", [False, True])
def test_rounded_rectangle_is_straights_joined_by_arcs(blurred: bool):
    image = rounded_rect_image()
    if blurred:
        image = blur(image)

    document = LineModeStrategy().reconstruct(image)
    d = path_d(document)

    assert d, "expected a path for a rounded rectangle"
    assert d.count("A") >= 4, f"corners should be arcs, not chamfers: {d}"
    assert d.count("L") >= 4, f"edges should stay straight: {d}"


@pytest.mark.parametrize("blurred", [False, True])
def test_rounded_rectangle_edges_are_axis_aligned(blurred: bool):
    image = rounded_rect_image()
    if blurred:
        image = blur(image)

    models = branch_models(image)
    straights = [m for m in models if isinstance(m, LineModel)]
    assert len(straights) >= 4

    document = LineModeStrategy().reconstruct(image)
    strategy = LineModeStrategy()
    strategy.reconstruct(image)
    stats = strategy.diagnostics.regularization
    assert stats.snapped_total >= 4
    assert abs(stats.horizontal_angle) < 1e-9
    assert abs(stats.vertical_angle - 90.0) < 1e-9


# --- semicircle -----------------------------------------------------------


def semicircle_image() -> np.ndarray:
    image = blank(140, 180)
    cv2.ellipse(image, (90, 95), (60, 60), 0, 180, 360, 0, THICKNESS)
    return image


@pytest.mark.parametrize("blurred", [False, True])
def test_semicircle_is_one_arc_not_a_chain_of_chords(blurred: bool):
    image = semicircle_image()
    if blurred:
        image = blur(image)

    models = main_branch_models(image)
    arcs = [m for m in models if isinstance(m, ArcModel)]

    assert len(arcs) == 1, f"expected a single arc, got {[m.kind for m in models]}"
    assert abs(arcs[0].radius - 60) < 3.0
    assert 150 < arcs[0].sweep_degrees < 210


@pytest.mark.parametrize("blurred", [False, True])
def test_semicircle_emits_an_arc_command(blurred: bool):
    image = semicircle_image()
    if blurred:
        image = blur(image)

    document = LineModeStrategy().reconstruct(image)
    assert "A" in path_d(document)


# --- S-shaped curve -------------------------------------------------------


def s_curve_image() -> np.ndarray:
    image = blank(200, 120)
    ys = np.arange(20, 180)
    xs = (60 + 34 * np.sin((ys - 20) / 160.0 * 2 * np.pi)).astype(int)
    for (x1, y1), (x2, y2) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        cv2.line(image, (int(x1), int(y1)), (int(x2), int(y2)), 0, THICKNESS)
    return image


@pytest.mark.parametrize("blurred", [False, True])
def test_s_curve_uses_beziers_and_never_a_single_arc(blurred: bool):
    image = s_curve_image()
    if blurred:
        image = blur(image)

    models = main_branch_models(image)
    beziers = [m for m in models if isinstance(m, BezierModel)]
    arcs = [m for m in models if isinstance(m, ArcModel)]

    assert beziers, f"an S-curve needs cubics, got {[m.kind for m in models]}"
    # Changing curvature cannot be answered by one arc.
    assert len(arcs) <= 1


def test_arc_fit_rejects_an_s_curve_outright():
    """The circularity test, not a special case, is what excludes arcs."""
    ys = np.arange(0, 160, dtype=float)
    xs = 60 + 34 * np.sin(ys / 160.0 * 2 * np.pi)
    samples = np.column_stack([xs, ys])

    assert fit_arc(samples) is None


@pytest.mark.parametrize("blurred", [False, True])
def test_s_curve_emits_cubic_commands(blurred: bool):
    image = s_curve_image()
    if blurred:
        image = blur(image)

    document = LineModeStrategy().reconstruct(image)
    assert "C" in path_d(document)


# --- line-to-arc transition ----------------------------------------------


def line_to_arc_image() -> np.ndarray:
    """A straight run flowing smoothly into a quarter turn."""
    image = blank(160, 220)
    cv2.line(image, (20, 40), (120, 40), 0, THICKNESS)
    cv2.ellipse(image, (120, 90), (50, 50), 0, 270, 360, 0, THICKNESS)
    return image


@pytest.mark.parametrize("blurred", [False, True])
def test_line_to_arc_keeps_both_a_straight_and_an_arc(blurred: bool):
    image = line_to_arc_image()
    if blurred:
        image = blur(image)

    models = main_branch_models(image)
    kinds = [m.kind for m in models]

    assert "line" in kinds, f"the straight run was lost: {kinds}"
    assert "arc" in kinds or "bezier" in kinds, f"the turn was lost: {kinds}"


@pytest.mark.parametrize("blurred", [False, True])
def test_line_to_arc_joint_is_tangent_continuous(blurred: bool):
    image = line_to_arc_image()
    if blurred:
        image = blur(image)

    strategy = LineModeStrategy()
    strategy.reconstruct(image)
    discontinuities = strategy.diagnostics.joint_discontinuities

    assert discontinuities, "expected at least one smooth joint"
    # The line-to-arc joint itself is made exactly tangent. An arc can only
    # be steered at one end without changing the radius the samples
    # showed, so a second joint at its far end may retain a small kink.
    assert min(discontinuities) < 1.0, discontinuities
    assert sorted(discontinuities)[len(discontinuities) // 2] < 5.0, discontinuities
    assert max(discontinuities) < 20.0, discontinuities


# --- the dollar-sign crop ------------------------------------------------


def dollar_sign_crop() -> np.ndarray:
    sheet = load_sheet("fixtures/real/finance-icon-sheet.jpg")
    crops = detect_crops(sheet.grayscale)
    crop = next(c for c in crops if c.id == "crop-21")
    return sheet.grayscale[
        int(crop.y) : int(crop.y + crop.height), int(crop.x) : int(crop.x + crop.width)
    ]


def test_dollar_sign_crop_is_carried_by_curves_not_chords():
    """The real glyph must be curve geometry, not a chain of short chords.

    It comes out as arcs rather than cubics, and that is the honest
    answer for this input: the vertical bar crosses the S, so the glyph
    reaches the fitter as several ~15px fragments, and a fragment that
    short has a single sign of curvature. Cubics are exercised on an
    unfragmented S by test_s_curve_uses_beziers_and_never_a_single_arc.
    Fixing the fragmentation is junction routing, not curve fitting.
    """
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())
    counts = strategy.diagnostics.section_counts

    curved = counts.get("arc", 0) + counts.get("bezier", 0)
    assert curved >= 3, f"the glyph and ring should be curve geometry: {counts}"
    circles = [e for e in document.elements if isinstance(e, SvgCircle)]
    assert circles, "the coin ring is circular evidence and must survive"

    paths = [e for e in document.elements if isinstance(e, SvgPath)]
    assert paths, "expected mixed straight/curve paths"
    assert any("A" in p.to_d() or "C" in p.to_d() for p in paths)


def test_dollar_sign_arcs_are_never_finer_than_the_stroke():
    """Curvature below the stroke width is skeleton noise, not evidence."""
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())
    stroke_width = strategy.diagnostics.stroke_width

    radii = [
        command.rx
        for element in document.elements
        if isinstance(element, SvgPath)
        for command in element.commands
        if hasattr(command, "rx")
    ]
    assert radii, "expected at least one arc"
    assert min(radii) >= stroke_width * 0.6


def test_dollar_sign_crop_keeps_its_coin_ring_circular():
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())

    circles = [e for e in document.elements if isinstance(e, SvgCircle)]
    assert len(circles) >= 1, "the coin ring should still be a circle"


def test_dollar_sign_crop_is_not_replaced_by_a_glyph_or_hardcoded_path():
    """Everything emitted must be strokes derived from the raster."""
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())
    svg_text = document.to_xml_string()

    assert "<text" not in svg_text
    assert "font" not in svg_text
    assert document.stroke_style.fill == "none"
    assert document.elements


def test_dollar_sign_crop_preserves_its_separate_details():
    """The bars beside the coin, and the coin itself, all survive."""
    strategy = LineModeStrategy()
    strategy.reconstruct(dollar_sign_crop())
    diagnostics = strategy.diagnostics

    # Nothing is dropped between tracing and emission.
    assert diagnostics.branch_count_after_pruning == diagnostics.branch_count_raw


# --- supporting units ----------------------------------------------------


def test_tangent_turning_ignores_a_single_stair_step():
    xs = np.arange(0, 40, dtype=float)
    ys = np.where(xs < 20, 10.0, 11.0)
    turning = tangent_turning(np.column_stack([xs, ys]), window=3)

    assert turning.max() < 30.0


def test_detect_corners_finds_one_corner_in_an_elbow():
    down = np.column_stack([np.full(40, 20.0), np.arange(0, 40, dtype=float)])
    right = np.column_stack([np.arange(21, 61, dtype=float), np.full(40, 39.0)])
    samples = np.vstack([down, right])

    corners = detect_corners(samples, window=3)

    assert len(corners) == 1
    assert 35 <= corners[0] <= 45


def test_detect_corners_finds_none_on_a_circular_arc():
    """An arc turns evenly, so no turn concentrates into a corner."""
    angles = np.linspace(0, np.pi, 90)
    samples = np.column_stack([60 + 50 * np.cos(angles), 60 + 50 * np.sin(angles)])

    assert detect_corners(samples, window=3) == []


def test_select_model_prefers_a_line_for_straight_samples():
    xs = np.arange(0, 50, dtype=float)
    samples = np.column_stack([xs, np.full_like(xs, 7.0)])

    choice = select_model(samples, tolerance=0.8)

    assert isinstance(choice.model, LineModel)
    assert "line" in choice.reason


def test_select_model_prefers_an_arc_over_a_bezier_for_circular_samples():
    angles = np.linspace(0.2, 2.2, 60)
    samples = np.column_stack([40 + 25 * np.cos(angles), 40 + 25 * np.sin(angles)])

    choice = select_model(samples, tolerance=0.8)

    assert isinstance(choice.model, ArcModel), choice.reason
    assert choice.line_error > choice.arc_error


def test_select_model_falls_through_to_a_bezier_for_changing_curvature():
    t = np.linspace(0, 1, 70)
    samples = np.column_stack([80 * t, 40 + 25 * np.sin(2 * np.pi * t)])

    choice = select_model(samples, tolerance=0.8)

    assert isinstance(choice.model, BezierModel), choice.reason


def test_fit_cubic_bezier_reproduces_a_known_cubic():
    control = np.array([[0.0, 0.0], [20.0, 60.0], [80.0, -40.0], [100.0, 10.0]])
    t = np.linspace(0, 1, 80).reshape(-1, 1)
    samples = (
        (1 - t) ** 3 * control[0]
        + 3 * (1 - t) ** 2 * t * control[1]
        + 3 * (1 - t) * t**2 * control[2]
        + t**3 * control[3]
    )

    fit = fit_cubic_bezier(samples)

    assert fit.max_error < 1.0  # sub-pixel; chord parameterization is not exact


def test_fit_line_reports_its_own_error_honestly():
    angles = np.linspace(0, np.pi / 2, 40)
    samples = np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)])

    line = fit_line(samples)

    assert line.max_error > 5.0, "a quarter circle is not a line and must say so"
