"""Reconstruction strategy interface, dispatched by ReconstructionMode.

Keeping this dispatch explicit means adding filled/mixed logic later is
a matter of filling in their stub modules, not restructuring the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from app.domain.models import ReconstructionMode
from app.services.svg_model import SvgDocument


class ReconstructionStrategy(ABC):
    @abstractmethod
    def reconstruct(self, crop_grayscale: np.ndarray) -> SvgDocument:
        raise NotImplementedError


def get_strategy(mode: ReconstructionMode) -> ReconstructionStrategy:
    if mode is ReconstructionMode.LINE:
        from app.services.reconstruction.line_mode import LineModeStrategy

        return LineModeStrategy()
    if mode is ReconstructionMode.FILLED:
        from app.services.reconstruction.filled_mode import FilledModeStrategy

        return FilledModeStrategy()
    if mode is ReconstructionMode.MIXED:
        from app.services.reconstruction.mixed_mode import MixedModeStrategy

        return MixedModeStrategy()
    raise ValueError(f"Unknown reconstruction mode: {mode}")
