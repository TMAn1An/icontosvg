"""SVG document builder and validator.

Emits true SVG primitives (<line>, <circle>, <ellipse>, <rect>, <path>)
rather than embedding raster data or tracing every pixel as a polygon.
Stroke width is stored in viewBox units, not screen pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


@dataclass
class StrokeStyle:
    width: float = 6.0
    color: str = "#000000"
    fill: str = "none"
    linecap: str = "round"
    linejoin: str = "round"
    miter_limit: float = 4.0


@dataclass
class SvgLine:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class SvgCircle:
    cx: float
    cy: float
    r: float


@dataclass
class SvgEllipse:
    cx: float
    cy: float
    rx: float
    ry: float


@dataclass
class SvgRect:
    x: float
    y: float
    width: float
    height: float
    rx: float = 0.0


SvgElement = SvgLine | SvgCircle | SvgEllipse | SvgRect


@dataclass
class SvgDocument:
    view_box: tuple[float, float, float, float]
    stroke_style: StrokeStyle
    elements: list[SvgElement] = field(default_factory=list)

    def to_xml_string(self) -> str:
        min_x, min_y, width, height = self.view_box
        svg = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"{min_x} {min_y} {width} {height}",
                "fill": self.stroke_style.fill,
                "stroke": self.stroke_style.color,
                "stroke-width": str(self.stroke_style.width),
                "stroke-linecap": self.stroke_style.linecap,
                "stroke-linejoin": self.stroke_style.linejoin,
            },
        )

        for element in self.elements:
            if isinstance(element, SvgLine):
                ET.SubElement(
                    svg,
                    "line",
                    {
                        "x1": str(element.x1),
                        "y1": str(element.y1),
                        "x2": str(element.x2),
                        "y2": str(element.y2),
                    },
                )
            elif isinstance(element, SvgCircle):
                ET.SubElement(
                    svg, "circle", {"cx": str(element.cx), "cy": str(element.cy), "r": str(element.r)}
                )
            elif isinstance(element, SvgEllipse):
                ET.SubElement(
                    svg,
                    "ellipse",
                    {
                        "cx": str(element.cx),
                        "cy": str(element.cy),
                        "rx": str(element.rx),
                        "ry": str(element.ry),
                    },
                )
            elif isinstance(element, SvgRect):
                attrs = {
                    "x": str(element.x),
                    "y": str(element.y),
                    "width": str(element.width),
                    "height": str(element.height),
                }
                if element.rx:
                    attrs["rx"] = str(element.rx)
                ET.SubElement(svg, "rect", attrs)

        return ET.tostring(svg, encoding="unicode")


def validate_svg(svg_text: str) -> list[str]:
    """Return a list of validation problems; empty list means valid."""
    problems: list[str] = []
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        return [f"XML parse error: {exc}"]

    if "viewBox" not in root.attrib:
        problems.append("Missing viewBox attribute")

    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag == "image":
            problems.append("Embedded raster <image> element found")

    return problems
