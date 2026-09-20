"""Bezier and circular-arc fitting for non-straight skeleton runs.

Stub for slice 1: line mode only needs skeleton_to_segments(). This module
is where curved centerline runs, and later filled-region boundary curves,
get fit with tangent-continuous cubic Beziers (Phase 2 per the spec).
"""

from __future__ import annotations

import numpy as np


def fit_cubic_bezier(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raise NotImplementedError("Cubic Bezier fitting with tangent continuity: slice 2 / Phase 2")
