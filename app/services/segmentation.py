"""Detect icon regions on a sheet.

Slice 1: connected components + whitespace projection, sufficient for a
regular grid sheet like the finance icon-sheet fixture. Grid analysis,
contour grouping, and proximity merging are added in slice 2.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.domain.models import Crop


def detect_crops(grayscale: np.ndarray, padding: int = 4) -> list[Crop]:
    """Return one Crop per connected foreground component, ordered by position."""
    _, binary = cv2.threshold(grayscale, 250, 255, cv2.THRESH_BINARY_INV)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    height, width = grayscale.shape
    crops: list[Crop] = []
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < 16:
            continue
        px = max(0, x - padding)
        py = max(0, y - padding)
        pw = min(width, x + w + padding) - px
        ph = min(height, y + h + padding) - py
        touches_edge = px <= 0 or py <= 0 or px + pw >= width or py + ph >= height
        crops.append(
            Crop(
                id=f"crop-{len(crops)}",
                x=float(px),
                y=float(py),
                width=float(pw),
                height=float(ph),
                touches_edge=touches_edge,
            )
        )

    crops.sort(key=lambda c: (round(c.y / 10), c.x))
    return crops
