"""Centerline extraction for line icons.

Pipeline: binarize -> skeletonize -> extract connected skeleton pixel
chains -> simplify to line segments. Deliberately does not touch the raw
contour/edges, so it cannot degrade into tracing both sides of a blurry
stroke (see docs/reference/rough-conversion-reference.png for the failure
mode this avoids).
"""

from __future__ import annotations

import numpy as np
from skimage.morphology import skeletonize

from app.services.geometry.primitives import LineSegment, snap_angle


def binarize_for_skeleton(grayscale: np.ndarray, threshold: int = 200) -> np.ndarray:
    return grayscale < threshold


def extract_skeleton(binary: np.ndarray) -> np.ndarray:
    return skeletonize(binary)


def skeleton_to_segments(skeleton: np.ndarray, min_length: float = 3.0) -> list[LineSegment]:
    """Reduce a skeleton mask to a small set of stable line segments.

    Slice-1 approach: find skeleton pixel coordinates, fit a single
    dominant segment per connected skeleton component via endpoint
    extremes, then snap the resulting angle. Curve-aware fitting for
    non-straight strokes is extended in curve_fit.py.
    """
    from scipy.ndimage import label

    labeled, num_components = label(skeleton, structure=np.ones((3, 3)))
    segments: list[LineSegment] = []

    for component_id in range(1, num_components + 1):
        ys, xs = np.where(labeled == component_id)
        if len(xs) < 2:
            continue

        idx_a = int(np.argmin(xs + ys))
        idx_b = int(np.argmax(xs + ys))
        x1, y1 = float(xs[idx_a]), float(ys[idx_a])
        x2, y2 = float(xs[idx_b]), float(ys[idx_b])

        segment = LineSegment(x1=x1, y1=y1, x2=x2, y2=y2)
        if segment.length < min_length:
            continue

        snapped_angle = snap_angle(segment.angle_degrees)
        if snapped_angle != segment.angle_degrees:
            length = segment.length
            angle_radians = np.radians(snapped_angle)
            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = np.cos(angle_radians) * length / 2, np.sin(angle_radians) * length / 2
            segment = LineSegment(mid_x - dx, mid_y - dy, mid_x + dx, mid_y + dy)

        segments.append(segment)

    return segments
