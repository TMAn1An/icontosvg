"""Undoable commands for crop editing and renaming, built on QUndoCommand."""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from app.domain.models import Crop, IconName


class MoveCropCommand(QUndoCommand):
    def __init__(self, crop: Crop, new_x: float, new_y: float) -> None:
        super().__init__("Move crop")
        self._crop = crop
        self._old_x, self._old_y = crop.x, crop.y
        self._new_x, self._new_y = new_x, new_y

    def redo(self) -> None:
        self._crop.x, self._crop.y = self._new_x, self._new_y

    def undo(self) -> None:
        self._crop.x, self._crop.y = self._old_x, self._old_y


class ResizeCropCommand(QUndoCommand):
    def __init__(self, crop: Crop, new_width: float, new_height: float) -> None:
        super().__init__("Resize crop")
        self._crop = crop
        self._old_width, self._old_height = crop.width, crop.height
        self._new_width, self._new_height = new_width, new_height

    def redo(self) -> None:
        self._crop.width, self._crop.height = self._new_width, self._new_height

    def undo(self) -> None:
        self._crop.width, self._crop.height = self._old_width, self._old_height


class RenameIconCommand(QUndoCommand):
    def __init__(self, icon_name: IconName, new_value: str) -> None:
        super().__init__("Rename icon")
        self._icon_name = icon_name
        self._old_value = icon_name.value
        self._old_is_manual = icon_name.is_manual
        self._new_value = new_value

    def redo(self) -> None:
        self._icon_name.value = self._new_value
        self._icon_name.is_manual = True

    def undo(self) -> None:
        self._icon_name.value = self._old_value
        self._icon_name.is_manual = self._old_is_manual
