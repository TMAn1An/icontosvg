"""JSON persistence for Project. Round-trippable: save(load(x)) == x."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.domain.models import (
    Crop,
    Icon,
    IconName,
    Project,
    QualityReport,
    ReconstructionMode,
    SourceSheet,
)


def save_project(project: Project, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(project), indent=2), encoding="utf-8")


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    source = SourceSheet(**data["source"])
    icons = []
    for icon_data in data["icons"]:
        crop = Crop(**icon_data["crop"])
        name = IconName(**icon_data["name"])
        quality = QualityReport(**icon_data["quality"])
        icons.append(
            Icon(
                id=icon_data["id"],
                crop=crop,
                name=name,
                reconstruction_mode=ReconstructionMode(icon_data["reconstruction_mode"]),
                svg_document=icon_data["svg_document"],
                quality=quality,
            )
        )
    return Project(name=data["name"], source=source, icons=icons)
