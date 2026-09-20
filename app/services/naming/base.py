"""NamingProvider interface. Every provider suggests a short, lowercase,
hyphenated name for an icon crop; the caller decides how to reconcile
suggestions with user-edited (manual) names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from app.domain.models import IconName


class NamingProvider(ABC):
    @abstractmethod
    def suggest_name(self, icon_crop_rgb: np.ndarray) -> IconName:
        """Return a suggested IconName with is_manual=False."""
        raise NotImplementedError
