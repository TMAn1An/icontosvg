"""Line-icon reconstruction: centerline -> stroked SVG primitives.

Emits true SVG strokes (fill="none", explicit stroke-width/cap/join) built
only from the extracted centerline — never from raw edge contours — so
blurry outer edges are never traced into a filled shape.
"""

from __future__ import annotations

import numpy as np

from app.services.geometry.centerline import (
    binarize_for_skeleton,
    extract_skeleton,
    skeleton_to_segments,
)
from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import SvgDocument, SvgLine, StrokeStyle


class LineModeStrategy(ReconstructionStrategy):
    def __init__(self, stroke_width: float = 6.0) -> None:
        self._stroke_style = StrokeStyle(
            width=stroke_width,
            color="#000000",
            linecap="round",
            linejoin="round",
        )

    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        height, width = crop_grayscale.shape
        binary = binarize_for_skeleton(crop_grayscale)
        skeleton = extract_skeleton(binary)
        segments = skeleton_to_segments(skeleton)

        document = SvgDocument(view_box=(0, 0, width, height), stroke_style=self._stroke_style)
        for segment in segments:
            document.elements.append(
                SvgLine(x1=segment.x1, y1=segment.y1, x2=segment.x2, y2=segment.y2)
            )
        return document
