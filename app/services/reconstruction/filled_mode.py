"""Filled-icon reconstruction: interface stub only, not implemented in slice 1.

Will reconstruct filled regions from contour hierarchy + topology (holes,
components) rather than raw pixel edges, reusing app/services/geometry/
primitives.py and curve_fit.py once implemented.
"""

from __future__ import annotations

import numpy as np

from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import SvgDocument


class FilledModeStrategy(ReconstructionStrategy):
    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        raise NotImplementedError("Filled-region reconstruction: slice 2")
