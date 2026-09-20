"""SVG document builder and validator.

Emits true SVG primitives (<line>, <circle>, <ellipse>, <rect>, <path>)
rather than embedding raster data or tracing every pixel as a polygon.
Stroke width is stored in viewBox units, not screen pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


def _num(value: float) -> str:
    """Format a coordinate with 2-decimal precision, no trailing zeros."""
    return f"{round(float(value), 2):g}"


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


@dataclass
class SvgPolyline:
    """A connected run of line segments. Closed runs repeat the first point."""

    points: list[tuple[float, float]]


@dataclass
class PathMoveTo:
    x: float
    y: float


@dataclass
class PathLineTo:
    x: float
    y: float


@dataclass
class PathArcTo:
    """Elliptical-arc command. Circular arcs set rx == ry."""

    rx: float
    ry: float
    large_arc: bool
    sweep: bool
    x: float
    y: float


@dataclass
class PathCubicTo:
    x1: float
    y1: float
    x2: float
    y2: float
    x: float
    y: float


PathCommand = PathMoveTo | PathLineTo | PathArcTo | PathCubicTo


@dataclass
class SvgPath:
    """A single stroke mixing straight, arc and cubic sections.

    Used when one centerline branch needs more than one kind of section,
    so the whole stroke stays a single editable path rather than being
    broken into disconnected pieces.
    """

    commands: list[PathCommand]
    closed: bool = False

    def to_d(self) -> str:
        parts: list[str] = []
        for command in self.commands:
            if isinstance(command, PathMoveTo):
                parts.append(f"M {_num(command.x)} {_num(command.y)}")
            elif isinstance(command, PathLineTo):
                parts.append(f"L {_num(command.x)} {_num(command.y)}")
            elif isinstance(command, PathArcTo):
                parts.append(
                    f"A {_num(command.rx)} {_num(command.ry)} 0 "
                    f"{int(command.large_arc)} {int(command.sweep)} "
                    f"{_num(command.x)} {_num(command.y)}"
                )
            elif isinstance(command, PathCubicTo):
                parts.append(
                    f"C {_num(command.x1)} {_num(command.y1)} "
                    f"{_num(command.x2)} {_num(command.y2)} "
                    f"{_num(command.x)} {_num(command.y)}"
                )
        if self.closed:
            parts.append("Z")
        return " ".join(parts)

    def anchor_count(self) -> int:
        """On-curve points; Bezier handles are not anchors in editing terms."""
        return sum(1 for command in self.commands if not isinstance(command, PathMoveTo)) + 1


SvgElement = SvgLine | SvgCircle | SvgEllipse | SvgRect | SvgPolyline | SvgPath


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
                "viewBox": f"{_num(min_x)} {_num(min_y)} {_num(width)} {_num(height)}",
                "fill": self.stroke_style.fill,
                "stroke": self.stroke_style.color,
                "stroke-width": _num(self.stroke_style.width),
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
                        "x1": _num(element.x1),
                        "y1": _num(element.y1),
                        "x2": _num(element.x2),
                        "y2": _num(element.y2),
                    },
                )
            elif isinstance(element, SvgCircle):
                ET.SubElement(
                    svg,
                    "circle",
                    {"cx": _num(element.cx), "cy": _num(element.cy), "r": _num(element.r)},
                )
            elif isinstance(element, SvgEllipse):
                ET.SubElement(
                    svg,
                    "ellipse",
                    {
                        "cx": _num(element.cx),
                        "cy": _num(element.cy),
                        "rx": _num(element.rx),
                        "ry": _num(element.ry),
                    },
                )
            elif isinstance(element, SvgRect):
                attrs = {
                    "x": _num(element.x),
                    "y": _num(element.y),
                    "width": _num(element.width),
                    "height": _num(element.height),
                }
                if element.rx:
                    attrs["rx"] = _num(element.rx)
                ET.SubElement(svg, "rect", attrs)
            elif isinstance(element, SvgPolyline):
                points = " ".join(f"{_num(x)},{_num(y)}" for x, y in element.points)
                ET.SubElement(svg, "polyline", {"points": points})
            elif isinstance(element, SvgPath):
                ET.SubElement(svg, "path", {"d": element.to_d()})

        return ET.tostring(svg, encoding="unicode")

    def anchor_count(self) -> int:
        """Total on-curve anchors across all elements, for quality reporting."""
        total = 0
        for element in self.elements:
            if isinstance(element, SvgLine):
                total += 2
            elif isinstance(element, SvgPolyline):
                total += len(element.points)
            elif isinstance(element, SvgPath):
                total += element.anchor_count()
            else:
                total += 1
        return total


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
