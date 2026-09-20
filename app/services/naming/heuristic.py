"""Default naming provider: no ML dependencies, always available.

Produces a deterministic placeholder name from simple shape statistics
(aspect ratio, fill ratio) so the app is usable end-to-end without any
model weights. This is intentionally not meant to be accurate — it exists
so Names/Reconstruct/Export can be exercised before Florence-2 is wired in.
"""

from __future__ import annotations

import numpy as np

from app.domain.models import IconName
from app.services.naming.base import NamingProvider


class HeuristicNamingProvider(NamingProvider):
    def suggest_name(self, icon_crop_rgb: np.ndarray) -> IconName:
        height, width = icon_crop_rgb.shape[:2]
        aspect = width / height if height else 1.0

        grayscale = icon_crop_rgb.mean(axis=2)
        fill_ratio = float((grayscale < 250).mean())

        if aspect > 1.3:
            shape_word = "wide-icon"
        elif aspect < 0.77:
            shape_word = "tall-icon"
        else:
            shape_word = "icon"

        density_word = "solid" if fill_ratio > 0.35 else "outline"

        return IconName(value=f"{density_word}-{shape_word}", is_manual=False, confidence=None)
