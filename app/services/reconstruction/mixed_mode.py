"""Mixed-icon reconstruction (line + filled parts): interface stub only.

Will combine LineModeStrategy and FilledModeStrategy per detected region
once both are implemented.
"""

from __future__ import annotations

import numpy as np

from app.services.reconstruction.base import ReconstructionStrategy
from app.services.svg_model import SvgDocument


class MixedModeStrategy(ReconstructionStrategy):
    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        raise NotImplementedError("Mixed line+filled reconstruction: slice 2 / Phase 2")
