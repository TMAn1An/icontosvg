"""Unit tests for SVG document construction and validation."""

from app.services.svg_model import SvgDocument, SvgLine, StrokeStyle, validate_svg


def test_to_xml_string_includes_stroke_attributes_not_fill():
    document = SvgDocument(
        view_box=(0, 0, 100, 100),
        stroke_style=StrokeStyle(width=6.0, color="#000000", linecap="round", linejoin="round"),
        elements=[SvgLine(x1=0, y1=0, x2=10, y2=10)],
    )
    svg_text = document.to_xml_string()

    assert 'fill="none"' in svg_text
    assert 'stroke="#000000"' in svg_text
    assert 'stroke-width="6.0"' in svg_text
    assert "<line" in svg_text


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
