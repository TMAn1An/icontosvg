"""Shared geometric primitive fits: lines, circles, ellipses.

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
