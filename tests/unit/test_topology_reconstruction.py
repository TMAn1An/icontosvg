"""Regression tests for the topology-first reconstruction pipeline.

Each test here pins one of the failures that made the previous
per-branch curve classifier a regression (preserved at tag
`failed-experiment/curve-classification-v1`). They are written against
observable output -- the emitted SVG elements -- rather than against
internal diagnostics, so that a future rewrite of the fitter cannot make
them pass by renaming a field.

Every synthetic fixture is blurred and JPEG-compressed before it is
reconstructed, because the real input is a compressed raster sheet and a
pipeline that only survives crisp synthetic edges is not useful.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from app.services.preprocessing import load_sheet
from app.services.reconstruction.line_mode import LineModeStrategy
from app.services.segmentation import detect_crops
from app.services.svg_model import (
    PathArcTo,
    PathCubicTo,
    PathLineTo,
    PathMoveTo,
    SvgCircle,
    SvgEllipse,
    SvgLine,
    SvgPath,
    SvgPolyline,
    SvgRect,
    validate_svg,
)

THICKNESS = 4


# --- fixtures ------------------------------------------------------------


def blank(height: int, width: int) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def blur(image: np.ndarray, sigma: float = 1.4) -> np.ndarray:
    """Approximate the softness of a compressed raster sheet."""
    blurred = cv2.GaussianBlur(image, (0, 0), sigma)
    encoded = cv2.imencode(".jpg", blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 72])[1]
    return cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)


def build(image: np.ndarray) -> tuple[LineModeStrategy, object]:
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(image))
    return strategy, document


def element_kinds(document) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in document.elements:
        counts[type(element).__name__] = counts.get(type(element).__name__, 0) + 1
    return counts


def path_commands(document) -> list[str]:
    kinds: list[str] = []
    for element in document.elements:
        if isinstance(element, SvgPath):
            kinds.extend(type(c).__name__ for c in element.commands)
    return kinds


def element_length(element) -> float:
    """Approximate drawn length, used for the zero-length check."""
    if isinstance(element, SvgLine):
        return math.hypot(element.x2 - element.x1, element.y2 - element.y1)
    if isinstance(element, SvgCircle):
        return 2.0 * math.pi * element.r
    if isinstance(element, SvgEllipse):
        return math.pi * (element.rx + element.ry)
    if isinstance(element, SvgRect):
        return 2.0 * (element.width + element.height)
    if isinstance(element, SvgPolyline):
        points = np.asarray(element.points, dtype=float)
        if len(points) < 2:
            return 0.0
        return float(np.sum(np.hypot(*np.diff(points, axis=0).T)))
    if isinstance(element, SvgPath):
        total = 0.0
        cursor = None
        for command in element.commands:
            if isinstance(command, PathMoveTo):
                cursor = (command.x, command.y)
            elif isinstance(command, PathLineTo):
                if cursor:
                    total += math.hypot(command.x - cursor[0], command.y - cursor[1])
                cursor = (command.x, command.y)
            elif isinstance(command, PathArcTo):
                if cursor:
                    total += math.hypot(command.x - cursor[0], command.y - cursor[1])
                cursor = (command.x, command.y)
            elif isinstance(command, PathCubicTo):
                if cursor:
                    total += math.hypot(command.x - cursor[0], command.y - cursor[1])
                cursor = (command.x, command.y)
        return total
    return 0.0


def segment_lengths(element) -> list[float]:
    """Per-segment lengths inside one element, for the degenerate check."""
    lengths: list[float] = []
    if isinstance(element, SvgPath):
        cursor = None
        for command in element.commands:
            if isinstance(command, PathMoveTo):
                cursor = (command.x, command.y)
                continue
            target = (command.x, command.y)
            if cursor is not None:
                lengths.append(math.hypot(target[0] - cursor[0], target[1] - cursor[1]))
            cursor = target
    elif isinstance(element, SvgPolyline):
        points = np.asarray(element.points, dtype=float)
        for a, b in zip(points, points[1:]):
            lengths.append(float(np.hypot(*(b - a))))
    else:
        lengths.append(element_length(element))
    return lengths


def endpoints_of(element) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if isinstance(element, SvgLine):
        return (element.x1, element.y1), (element.x2, element.y2)
    if isinstance(element, SvgPolyline):
        return tuple(element.points[0]), tuple(element.points[-1])
    if isinstance(element, SvgPath):
        starts = [c for c in element.commands if isinstance(c, PathMoveTo)]
        if not starts:
            return None
        last = element.commands[-1]
        if isinstance(last, PathMoveTo):
            return None
        return (starts[0].x, starts[0].y), (last.x, last.y)
    return None


# --- 1. dollar sign: two crossing strokes -------------------------------


def dollar_sign_crop() -> np.ndarray:
    sheet = load_sheet("fixtures/real/finance-icon-sheet.jpg")
    crops = detect_crops(sheet.grayscale)
    crop = next(c for c in crops if c.id == "crop-21")
    return sheet.grayscale[
        int(crop.y) : int(crop.y + crop.height), int(crop.x) : int(crop.x + crop.width)
    ]


def test_dollar_sign_is_one_vertical_stroke_crossing_one_continuous_s():
    """The glyph is two strokes that cross, not four fragments.

    This is the failure that motivated the topology-first rewrite: the
    old pipeline cut the glyph at the two crossings and fitted each of
    the four ~15px pieces separately, which cannot produce a continuous
    S. Junction pairing by tangent continuity has to reassemble both
    strokes *before* anything is fitted.
    """
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())
    diagnostics = strategy.diagnostics

    assert diagnostics.topology["junctions"] >= 2, (
        "the vertical bar crosses the S twice; if no junctions are seen the "
        f"crossing-number computation is wrong: {diagnostics.topology}"
    )
    assert diagnostics.junction_pairings >= 2, (
        f"both crossings must pair branches through: {diagnostics.junction_pairings}"
    )

    # The bar: one continuous, essentially vertical stroke spanning the
    # glyph, not two stubs above and below the S.
    verticals = [
        e
        for e in document.elements
        if isinstance(e, SvgLine)
        and abs(e.x2 - e.x1) < 3.0
        and abs(e.y2 - e.y1) > 15.0
    ]
    assert len(verticals) == 1, (
        f"expected exactly one continuous vertical bar, got {len(verticals)}: "
        f"{element_kinds(document)}"
    )

    # The S: one open curved path carried by cubics, long enough to be
    # the whole glyph rather than one of its halves.
    curved = [
        e
        for e in document.elements
        if isinstance(e, SvgPath)
        and any(isinstance(c, PathCubicTo) for c in e.commands)
        and element_length(e) > 20.0
    ]
    assert len(curved) == 1, (
        f"expected one continuous S carried by cubics: {path_commands(document)}"
    )

    # The bar has to cross the S rather than stop at it: its span must
    # cover the S's vertical extent from above and below.
    bar = verticals[0]
    s_ends = endpoints_of(curved[0])
    bar_top, bar_bottom = sorted((bar.y1, bar.y2))
    s_top, s_bottom = sorted((s_ends[0][1], s_ends[1][1]))
    assert bar_top <= s_top + 2.0 and bar_bottom >= s_bottom - 2.0, (
        f"the bar stops at the S instead of crossing it: bar {bar_top}-{bar_bottom}, "
        f"S {s_top}-{s_bottom}"
    )

    # The surrounding coin ring is circular evidence and must survive.
    assert any(isinstance(e, SvgCircle) for e in document.elements), element_kinds(
        document
    )


def test_dollar_sign_s_curve_is_not_closed():
    """An S has two free ends. Nothing may close it with `Z`."""
    strategy = LineModeStrategy()
    document = strategy.reconstruct(dollar_sign_crop())
    for element in document.elements:
        if isinstance(element, SvgPath) and any(
            isinstance(c, PathCubicTo) for c in element.commands
        ):
            assert not element.closed, f"the S was wrongly closed: {element.to_d()}"


# --- 2. seven separate straight dashes ----------------------------------


def dashes_image() -> np.ndarray:
    image = blank(140, 140)
    for index in range(7):
        y = 20 + index * 16
        cv2.line(image, (25, y), (115, y), 0, THICKNESS)
    return image


def test_seven_dashes_stay_seven_straight_lines():
    """Seven disconnected straight dashes, and nothing bent.

    The rejected classifier turned every one of these into a cubic,
    visibly bowing them. A straight baseline that already fits within
    tolerance must block every curve candidate outright.
    """
    _, document = build(dashes_image())

    lines = [e for e in document.elements if isinstance(e, SvgLine)]
    assert len(lines) == 7, (
        f"expected 7 dashes as <line>, got {element_kinds(document)}"
    )
    assert not any(isinstance(e, SvgPath) for e in document.elements), (
        f"no dash may become a path: {path_commands(document)}"
    )
    for line in lines:
        assert abs(line.y2 - line.y1) < 1.0, f"dash is not horizontal: {line}"


# --- 3. rounded capsule --------------------------------------------------


def capsule_image() -> np.ndarray:
    image = blank(120, 200)
    cv2.line(image, (50, 45), (150, 45), 0, THICKNESS)
    cv2.line(image, (50, 95), (150, 95), 0, THICKNESS)
    cv2.ellipse(image, (50, 70), (25, 25), 0, 90, 270, 0, THICKNESS)
    cv2.ellipse(image, (150, 70), (25, 25), 0, -90, 90, 0, THICKNESS)
    return image


def test_capsule_keeps_round_ends_and_never_becomes_pointed():
    """A pill must not acquire corners where its round ends were.

    The rejected output pinched both ends into points. The corner
    radius has to survive as real curve geometry.
    """
    _, document = build(capsule_image())

    rects = [e for e in document.elements if isinstance(e, SvgRect)]
    if rects:
        rect = rects[0]
        # A capsule's radius is half its short side.
        assert rect.rx >= min(rect.width, rect.height) * 0.35, (
            f"round ends were flattened: rx={rect.rx} on {rect.width}x{rect.height}"
        )
        return

    # Otherwise the ends must at least be carried by arcs or cubics.
    commands = path_commands(document)
    assert any(k in commands for k in ("PathArcTo", "PathCubicTo")), (
        f"the round ends became straight geometry: {commands} {element_kinds(document)}"
    )


# --- 4. sharp triangular arrowhead --------------------------------------


def arrowhead_image() -> np.ndarray:
    image = blank(120, 120)
    points = np.array([[60, 20], [95, 90], [25, 90]], dtype=np.int32)
    cv2.polylines(image, [points], True, 0, THICKNESS)
    return image


@pytest.mark.parametrize("sigma", [0.0, 1.4, 2.0])
def test_arrowhead_keeps_three_sharp_corners(sigma: float):
    """A triangular arrowhead is three straight sides meeting at points.

    Parametrized over blur because the earlier failure -- a rounded,
    blob-like arrowhead carried by cubics -- only appeared once the
    edges were soft. A 3-corner polygon has to win at every sharpness.
    """
    image = arrowhead_image()
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(image, sigma) if sigma else image)

    assert "PathCubicTo" not in path_commands(document), (
        f"a sharp arrowhead must not be carried by cubics: {path_commands(document)}"
    )
    assert "PathArcTo" not in path_commands(document), (
        f"a sharp arrowhead must not be carried by arcs: {path_commands(document)}"
    )

    polylines = [e for e in document.elements if isinstance(e, SvgPolyline)]
    assert len(polylines) == 1, (
        f"the arrowhead must be one straight-sided outline: {element_kinds(document)}"
    )
    points = polylines[0].points
    # Closed triangle: three distinct corners, first repeated to close.
    assert len(points) == 4, f"expected 3 corners plus closure: {points}"
    assert math.dist(points[0], points[-1]) < 1.0, f"outline is not closed: {points}"

    corners = np.asarray(points[:3], dtype=float)
    expected = np.array([[60.0, 20.0], [95.0, 90.0], [25.0, 90.0]])
    # The centerline apex of a stroked corner sits inside the drawn
    # vertex by roughly half the stroke width over the tangent of the
    # half-angle -- about 7px at the sharp tip once the edges are soft.
    # That inset is correct geometry, so the tolerance allows for it;
    # a *rounded* corner shows up as an extra vertex, caught above.
    for corner in expected:
        assert float(np.min(np.linalg.norm(corners - corner, axis=1))) < 9.0, (
            f"corner {corner} was rounded away: {points}"
        )


def test_arrowhead_is_a_single_closed_stroke():
    """Whatever primitive wins, the outline stays one closed loop.

    This part passes today and guards against the other half of the old
    failure: the arrowhead splitting into unrelated fragments.
    """
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(arrowhead_image()))
    assert strategy.diagnostics.stroke_count == 1, (
        f"the outline fragmented: {strategy.diagnostics.stroke_count} strokes"
    )
    assert len(document.elements) == 1, element_kinds(document)


# --- 5. rounded rectangle ------------------------------------------------


def rounded_rect_image() -> np.ndarray:
    image = blank(160, 200)
    cv2.rectangle(image, (30, 30), (170, 130), 0, THICKNESS)
    # Round the corners by overdrawing white and re-adding quarter arcs.
    radius = 20
    for cx, cy, start, end in (
        (30 + radius, 30 + radius, 180, 270),
        (170 - radius, 30 + radius, 270, 360),
        (170 - radius, 130 - radius, 0, 90),
        (30 + radius, 130 - radius, 90, 180),
    ):
        x0, y0 = cx - radius, cy - radius
        cv2.rectangle(
            image, (x0 - 3, y0 - 3), (x0 + 2 * radius + 3, y0 + 2 * radius + 3), 255, -1
        )
    cv2.rectangle(image, (30 + radius, 30), (170 - radius, 130), 0, THICKNESS)
    cv2.rectangle(image, (30, 30 + radius), (170, 130 - radius), 0, THICKNESS)
    cv2.rectangle(
        image, (30 + radius, 30 + radius), (170 - radius, 130 - radius), 255, -1
    )
    for cx, cy, start, end in (
        (30 + radius, 30 + radius, 180, 270),
        (170 - radius, 30 + radius, 270, 360),
        (170 - radius, 130 - radius, 0, 90),
        (30 + radius, 130 - radius, 90, 180),
    ):
        cv2.ellipse(image, (cx, cy), (radius, radius), 0, start, end, 0, THICKNESS)
    return image


def test_rounded_rectangle_is_a_rect_with_a_real_corner_radius():
    """Four straight sides plus four corner arcs -- one `<rect rx>`."""
    _, document = build(rounded_rect_image())

    rects = [e for e in document.elements if isinstance(e, SvgRect)]
    assert rects, f"expected a rounded <rect>: {element_kinds(document)}"
    rect = rects[0]
    assert rect.rx > 2.0, f"corner radius was lost: rx={rect.rx}"
    assert rect.rx < min(rect.width, rect.height) / 2.0 + 1.0, (
        f"corner radius exceeds the capsule limit: rx={rect.rx}"
    )


# --- 6. circle containing another symbol --------------------------------


def coin_image() -> np.ndarray:
    """A ring with an unrelated symbol inside, not touching it."""
    image = blank(160, 160)
    cv2.circle(image, (80, 80), 55, 0, THICKNESS)
    cv2.line(image, (80, 45), (80, 115), 0, THICKNESS)
    cv2.line(image, (55, 60), (105, 60), 0, THICKNESS)
    return image


def test_circle_containing_a_symbol_keeps_both_separate():
    """The ring stays a circle; the inner symbol stays its own geometry."""
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(coin_image()))

    circles = [e for e in document.elements if isinstance(e, SvgCircle)]
    assert len(circles) == 1, (
        f"the enclosing ring must be one circle: {element_kinds(document)}"
    )
    assert 50.0 < circles[0].r < 60.0, f"ring radius drifted: {circles[0].r}"

    inner = [e for e in document.elements if not isinstance(e, SvgCircle)]
    assert inner, "the inner symbol was swallowed by the ring"
    # Nothing inside may be merged into the ring's own path.
    for element in inner:
        assert element_length(element) < 2.0 * math.pi * circles[0].r


# --- 7. straight presentation-board edge --------------------------------


def board_image() -> np.ndarray:
    """A presentation board: a rectangle on a stand, all edges straight."""
    image = blank(160, 180)
    cv2.rectangle(image, (25, 20), (155, 105), 0, THICKNESS)
    cv2.line(image, (90, 105), (90, 135), 0, THICKNESS)
    cv2.line(image, (60, 135), (120, 135), 0, THICKNESS)
    return image


def test_presentation_board_edges_stay_straight():
    """No board edge may bow. The rejected output curved the left side."""
    _, document = build(board_image())

    assert "PathCubicTo" not in path_commands(document), (
        f"a board edge was bent into a curve: {path_commands(document)}"
    )
    assert "PathArcTo" not in path_commands(document), (
        f"a board edge became an arc: {path_commands(document)}"
    )

    rects = [e for e in document.elements if isinstance(e, SvgRect)]
    if rects:
        assert not rects[0].rx, f"square board corners were rounded: {rects[0]}"


# --- 8. S-shaped curve ---------------------------------------------------


def s_curve_image() -> np.ndarray:
    image = blank(160, 120)
    points = []
    for step in range(200):
        t = step / 199.0
        y = 20.0 + t * 120.0
        x = 60.0 + 28.0 * math.sin(t * 2.0 * math.pi)
        points.append([x, y])
    cv2.polylines(
        image, [np.array(points, dtype=np.int32)], False, 0, THICKNESS, cv2.LINE_AA
    )
    return image


def test_s_curve_uses_cubics_and_never_a_single_arc():
    """An S changes curvature sign, so no single arc can represent it."""
    _, document = build(s_curve_image())

    commands = path_commands(document)
    assert commands.count("PathCubicTo") >= 2, (
        f"an S needs at least two cubics: {commands} {element_kinds(document)}"
    )
    assert "PathArcTo" not in commands, (
        f"a single-signed arc cannot carry an S: {commands}"
    )
    assert not any(
        isinstance(e, (SvgCircle, SvgEllipse)) for e in document.elements
    ), element_kinds(document)


# --- 9. open curve with near-touching endpoints -------------------------


def near_closed_arc_image() -> np.ndarray:
    """A C with a visible gap -- endpoints close, but the stroke is open."""
    image = blank(160, 160)
    cv2.ellipse(image, (80, 80), (55, 55), 0, 20, 340, 0, THICKNESS)
    return image


def test_open_curve_with_close_endpoints_is_not_closed():
    """Proximity is not closure. A gap in the raster stays a gap."""
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(near_closed_arc_image()))

    assert not any(
        isinstance(e, (SvgCircle, SvgEllipse, SvgRect)) for e in document.elements
    ), f"an open C was completed into a closed primitive: {element_kinds(document)}"

    for element in document.elements:
        if isinstance(element, SvgPath):
            assert not element.closed, f"wrongly closed with Z: {element.to_d()}"

    gaps = [
        math.dist(*ends)
        for ends in (endpoints_of(e) for e in document.elements)
        if ends is not None
    ]
    assert gaps and max(gaps) > 3.0, (
        f"the gap was fitted away; endpoint separation {gaps}"
    )


# --- 10. no zero-length elements anywhere -------------------------------


ALL_FIXTURES = {
    "dashes": dashes_image,
    "capsule": capsule_image,
    "arrowhead": arrowhead_image,
    "rounded_rect": rounded_rect_image,
    "coin": coin_image,
    "board": board_image,
    "s_curve": s_curve_image,
    "near_closed_arc": near_closed_arc_image,
}


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_no_zero_length_elements_or_segments(name: str):
    """Zero-length output is never valid; the old pipeline emitted it.

    Checked on every fixture rather than one, because a degenerate
    element is a pipeline-wide defect, not a shape-specific one.
    """
    strategy = LineModeStrategy()
    document = strategy.reconstruct(blur(ALL_FIXTURES[name]()))

    for element in document.elements:
        assert element_length(element) >= 0.5, f"zero-length element: {element}"
        for length in segment_lengths(element):
            assert length >= 0.5, f"zero-length segment inside {element}"

    assert validate_svg(document.to_xml_string()) == []


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_reported_degenerate_removals_are_zero(name: str):
    """Degenerates should not be generated, not merely filtered out."""
    strategy = LineModeStrategy()
    strategy.reconstruct(blur(ALL_FIXTURES[name]()))
    assert strategy.diagnostics.removed_degenerate == 0
