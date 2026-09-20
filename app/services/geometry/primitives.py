"""Shared geometric primitive fits: lines, circles, rectangles.

Shared by line mode now and by filled/mixed mode later — kept independent
of any single reconstruction strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class LineSegment:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def angle_degrees(self) -> float:
        return float(np.degrees(np.arctan2(self.y2 - self.y1, self.x2 - self.x1)))

    @property
    def length(self) -> float:
        return float(np.hypot(self.x2 - self.x1, self.y2 - self.y1))


@dataclass
class Circle:
    cx: float
    cy: float
    radius: float


@dataclass
class CircleFit:
    circle: Circle
    mean_residual: float
    max_residual: float


def snap_angle(angle_degrees: float, tolerance_degrees: float = 5.0) -> float:
    """Snap a near-axis-aligned or near-45-degree angle to the exact value.

    JPEG noise on straight strokes should collapse to one stable angle
    rather than a family of near-duplicate angles.
    """
    snap_targets = (-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 180.0)
    for target in snap_targets:
        if abs(angle_degrees - target) <= tolerance_degrees:
            return target
    return angle_degrees


def snap_segment(segment: LineSegment, tolerance_degrees: float = 5.0) -> LineSegment:
    """Rotate a segment about its midpoint onto a snapped angle, if close."""
    snapped = snap_angle(segment.angle_degrees, tolerance_degrees)
    if snapped == segment.angle_degrees:
        return segment

    half_length = segment.length / 2
    radians = np.radians(snapped)
    mid_x = (segment.x1 + segment.x2) / 2
    mid_y = (segment.y1 + segment.y2) / 2
    dx = float(np.cos(radians)) * half_length
    dy = float(np.sin(radians)) * half_length
    return LineSegment(mid_x - dx, mid_y - dy, mid_x + dx, mid_y + dy)


def fit_circle(points: np.ndarray) -> CircleFit:
    """Algebraic (Kasa) least-squares circle fit over (N, 2) x/y points."""
    if len(points) < 3:
        raise ValueError("circle fit needs at least 3 points")

    x = points[:, 0].astype(float)
    y = points[:, 1].astype(float)
    design = np.column_stack([x, y, np.ones(len(x))])
    target = x**2 + y**2
    solution, *_ = np.linalg.lstsq(design, target, rcond=None)

    cx = solution[0] / 2
    cy = solution[1] / 2
    radius = float(np.sqrt(max(0.0, solution[2] + cx**2 + cy**2)))

    distances = np.hypot(x - cx, y - cy)
    residuals = np.abs(distances - radius)
    return CircleFit(
        circle=Circle(cx=float(cx), cy=float(cy), radius=radius),
        mean_residual=float(residuals.mean()),
        max_residual=float(residuals.max()),
    )


def is_axis_aligned_rectangle(points: np.ndarray, tolerance_degrees: float = 8.0) -> bool:
    """True if 4 corners form a rectangle with axis-aligned edges."""
    if len(points) != 4:
        return False

    for index in range(4):
        start = points[index]
        end = points[(index + 1) % 4]
        angle = abs(np.degrees(np.arctan2(end[1] - start[1], end[0] - start[0])))
        is_horizontal = angle <= tolerance_degrees or abs(angle - 180) <= tolerance_degrees
        is_vertical = abs(angle - 90) <= tolerance_degrees
        if not (is_horizontal or is_vertical):
            return False
    return True
