"""Unit tests for crop move/resize commands and undo/redo."""

from PySide6.QtGui import QUndoStack

from app.domain.commands import MoveCropCommand, ResizeCropCommand
from app.domain.models import Crop


def make_crop() -> Crop:
    return Crop(id="c1", x=0.0, y=0.0, width=50.0, height=50.0)


def test_move_crop_command_applies_and_undoes():
    crop = make_crop()
    stack = QUndoStack()
    stack.push(MoveCropCommand(crop, new_x=10.0, new_y=20.0))

    assert (crop.x, crop.y) == (10.0, 20.0)

    stack.undo()
    assert (crop.x, crop.y) == (0.0, 0.0)

    stack.redo()
    assert (crop.x, crop.y) == (10.0, 20.0)


def test_resize_crop_command_applies_and_undoes():
    crop = make_crop()
    stack = QUndoStack()
    stack.push(ResizeCropCommand(crop, new_width=80.0, new_height=90.0))

    assert (crop.width, crop.height) == (80.0, 90.0)

    stack.undo()
    assert (crop.width, crop.height) == (50.0, 50.0)
