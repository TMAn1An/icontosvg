"""Export a single reconstructed icon as a validated SVG file.

ZIP export of all icons is deferred to slice 2.
"""

from __future__ import annotations

from pathlib import Path

from app.services.svg_model import SvgDocument, validate_svg


def export_single_svg(document: SvgDocument, output_path: str | Path) -> list[str]:
    """Write the SVG to disk. Returns validation problems (empty = valid)."""
    svg_text = document.to_xml_string()
    problems = validate_svg(svg_text)
    Path(output_path).write_text(svg_text, encoding="utf-8")
    return problems
