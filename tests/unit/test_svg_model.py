"""Unit tests for SVG document construction and validation."""

from app.services.svg_model import (
    SvgCircle,
    SvgDocument,
    SvgLine,
    SvgPolyline,
    StrokeStyle,
    validate_svg,
)


def test_to_xml_string_includes_stroke_attributes_not_fill():
    document = SvgDocument(
        view_box=(0, 0, 100, 100),
        stroke_style=StrokeStyle(width=6.0, color="#000000", linecap="round", linejoin="round"),
        elements=[SvgLine(x1=0, y1=0, x2=10, y2=10)],
    )
    svg_text = document.to_xml_string()

    assert 'fill="none"' in svg_text
    assert 'stroke="#000000"' in svg_text
    assert 'stroke-width="6"' in svg_text
    assert 'stroke-linecap="round"' in svg_text
    assert "<line" in svg_text


def test_coordinates_are_rounded_to_two_decimals():
    document = SvgDocument(
        view_box=(0, 0, 10, 10),
        stroke_style=StrokeStyle(),
        elements=[SvgLine(x1=1.234567, y1=2.0, x2=3.0, y2=4.0)],
    )
    assert 'x1="1.23"' in document.to_xml_string()


def test_polyline_is_emitted_with_point_pairs():
    document = SvgDocument(
        view_box=(0, 0, 10, 10),
        stroke_style=StrokeStyle(),
        elements=[SvgPolyline(points=[(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)])],
    )
    svg_text = document.to_xml_string()

    assert '<polyline points="0,0 5,1 10,0"' in svg_text
    assert validate_svg(svg_text) == []


def test_anchor_count_sums_across_element_types():
    document = SvgDocument(
        view_box=(0, 0, 10, 10),
        stroke_style=StrokeStyle(),
        elements=[
            SvgLine(x1=0, y1=0, x2=1, y2=1),
            SvgPolyline(points=[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]),
            SvgCircle(cx=5, cy=5, r=2),
        ],
    )
    assert document.anchor_count() == 6


def test_validate_svg_accepts_well_formed_document():
    document = SvgDocument(view_box=(0, 0, 10, 10), stroke_style=StrokeStyle())
    assert validate_svg(document.to_xml_string()) == []


def test_validate_svg_rejects_embedded_raster_image():
    svg_text = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<image href="data:image/png;base64,AAAA"/></svg>'
    )
    problems = validate_svg(svg_text)
    assert any("image" in problem.lower() for problem in problems)


def test_validate_svg_rejects_malformed_xml():
    problems = validate_svg("<svg><line></svg>")
    assert problems
