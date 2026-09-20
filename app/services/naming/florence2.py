"""Optional Florence-2-based naming provider.

Requires torch and transformers, listed only in requirements-naming.txt
(never requirements.txt). Imports are deferred to __init__ so importing
this module — or the naming package as a whole — never requires torch to
be installed. The application must run fully without this file ever being
instantiated.
"""

from __future__ import annotations

import numpy as np

from app.domain.models import IconName
from app.services.naming.base import NamingProvider


class Florence2NamingProvider(NamingProvider):
    def __init__(self, model_id: str = "microsoft/Florence-2-base") -> None:
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise ImportError(
                "Florence2NamingProvider requires torch and transformers. "
                "Install them via requirements-naming.txt."
            ) from exc

        self._processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)

    def suggest_name(self, icon_crop_rgb: np.ndarray) -> IconName:
        raise NotImplementedError("Florence-2 captioning-to-slug pipeline: slice 2")
