"""Unit tests for Project JSON save/load round-tripping."""

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
from app.domain.project_store import load_project, save_project


def make_project() -> Project:
    crop = Crop(id="crop-0", x=1.0, y=2.0, width=30.0, height=40.0)
    icon = Icon(
        id="icon-0",
        crop=crop,
        name=IconName(value="outline-icon", is_manual=True),
        reconstruction_mode=ReconstructionMode.LINE,
        svg_document="<svg></svg>",
        quality=QualityReport(ssim=0.9, manual_review_status="pending"),
    )
    source = SourceSheet(file_path="fixtures/real/finance-icon-sheet.jpg", file_hash="abc123", width=100, height=200)
    return Project(name="test-project", source=source, icons=[icon])


def test_save_and_load_round_trip(tmp_path: Path):
    project = make_project()
    path = tmp_path / "project.json"

    save_project(project, path)
    loaded = load_project(path)

    assert loaded.name == project.name
    assert loaded.source == project.source
    assert len(loaded.icons) == 1
    assert loaded.icons[0].name.value == "outline-icon"
    assert loaded.icons[0].name.is_manual is True
    assert loaded.icons[0].reconstruction_mode == ReconstructionMode.LINE
    assert loaded.icons[0].quality.manual_review_status == "pending"
