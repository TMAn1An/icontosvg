"""Detect icon regions on a sheet.

Slice 1 pipeline: threshold -> connected components -> speckle rejection ->
proximity merge -> padding -> reading-order sort.

The proximity merge is essential, not an optimization: a single icon is
routinely made of many disconnected components (an outer wallet outline,
the dollar glyph inside it, and every individual dash of a dashed line),
so raw connected components over-segments roughly 5x on a real sheet.
Grid analysis and contour-hierarchy grouping are added in slice 2.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.domain.models import Crop

# Ink threshold. Deliberately below the anti-aliasing halo (~250) so that
# soft JPEG edges do not inflate every component box.
INK_THRESHOLD = 200

# Components smaller than this are JPEG speckle, not icon parts.
MIN_COMPONENT_AREA = 12

# Two components within this many pixels belong to the same icon. Must sit
# between the largest intra-icon gap (dash spacing, detached sparkles) and
# the smallest inter-icon gutter; validated against the finance sheet,
# where icons are ~130px wide on a ~205px pitch (~75px gutters).
MERGE_DISTANCE = 24


def _component_boxes(grayscale: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return raw (x1, y1, x2, y2) boxes for each ink component."""
    _, binary = cv2.threshold(grayscale, INK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    boxes = []
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < MIN_COMPONENT_AREA:
            continue
        boxes.append((int(x), int(y), int(x + w), int(y + h)))
    return boxes


def _merge_nearby(
    boxes: list[tuple[int, int, int, int]], merge_distance: int
) -> list[tuple[int, int, int, int]]:
    """Union boxes that are nested, overlapping, or within merge_distance.

    Repeats until stable, because merging two parts can bring the union
    within range of a third.
    """
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        result: list[tuple[int, int, int, int]] = []
        for box in merged:
            x1, y1, x2, y2 = box
            for index, existing in enumerate(result):
                ex1, ey1, ex2, ey2 = existing
                gap_x = max(ex1 - x2, x1 - ex2)
                gap_y = max(ey1 - y2, y1 - ey2)
                if gap_x <= merge_distance and gap_y <= merge_distance:
                    result[index] = (
                        min(x1, ex1),
                        min(y1, ey1),
                        max(x2, ex2),
                        max(y2, ey2),
                    )
                    changed = True
                    break
            else:
                result.append(box)
        merged = result
    return merged


def detect_crops(
    grayscale: np.ndarray,
    padding: int = 4,
    merge_distance: int = MERGE_DISTANCE,
) -> list[Crop]:
    """Return one Crop per detected icon, in reading order.

    Padding is applied once, after merging, so a multi-part icon is not
    padded once per part.
    """
    boxes = _merge_nearby(_component_boxes(grayscale), merge_distance)
    if not boxes:
        return []

    height, width = grayscale.shape
    median_area = float(np.median([(x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in boxes]))

    crops: list[Crop] = []
    for x1, y1, x2, y2 in boxes:
        px1 = max(0, x1 - padding)
        py1 = max(0, y1 - padding)
        px2 = min(width, x2 + padding)
        py2 = min(height, y2 + padding)

        # A box far larger than typical probably swallowed two icons; a box
        # far smaller is probably a stray fragment. Flag, never discard.
        area = (x2 - x1) * (y2 - y1)
        uncertain = area > median_area * 2.5 or area < median_area * 0.15

        crops.append(
            Crop(
                id="",
                x=float(px1),
                y=float(py1),
                width=float(px2 - px1),
                height=float(py2 - py1),
                touches_edge=px1 <= 0 or py1 <= 0 or px2 >= width or py2 >= height,
                uncertain_grouping=uncertain,
            )
        )

    crops = _sort_reading_order(crops)
    for index, crop in enumerate(crops):
        crop.id = f"crop-{index}"
    return crops


def _sort_reading_order(crops: list[Crop]) -> list[Crop]:
    """Sort top-to-bottom then left-to-right, banding crops into rows.

    Banding by half the median height tolerates icons on the same row
    whose tops differ by a few pixels.
    """
    if not crops:
        return []

    row_tolerance = float(np.median([crop.height for crop in crops])) / 2
    by_vertical_position = sorted(crops, key=lambda crop: crop.y + crop.height / 2)

    rows: list[list[Crop]] = [[by_vertical_position[0]]]
    for crop in by_vertical_position[1:]:
        current_row = rows[-1]
        row_center = np.mean([c.y + c.height / 2 for c in current_row])
        if abs((crop.y + crop.height / 2) - row_center) <= row_tolerance:
            current_row.append(crop)
        else:
            rows.append([crop])

    ordered: list[Crop] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda crop: crop.x))
    return ordered
