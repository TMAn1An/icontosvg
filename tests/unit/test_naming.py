"""Unit tests for the heuristic naming provider and rename command rules."""

import numpy as np
from PySide6.QtGui import QUndoStack

from app.domain.commands import RenameIconCommand
from app.domain.models import IconName
from app.services.naming.heuristic import HeuristicNamingProvider


def test_heuristic_provider_returns_non_manual_name():
    provider = HeuristicNamingProvider()
    crop = np.full((40, 40, 3), 255, dtype=np.uint8)

    name = provider.suggest_name(crop)

    assert name.value
    assert name.is_manual is False


def test_heuristic_provider_is_deterministic_for_same_input():
    provider = HeuristicNamingProvider()
    crop = np.full((30, 60, 3), 200, dtype=np.uint8)

    first = provider.suggest_name(crop)
    second = provider.suggest_name(crop)

    assert first.value == second.value


def test_rename_command_marks_name_manual_and_is_undoable():
    icon_name = IconName(value="auto-name", is_manual=False)
    stack = QUndoStack()

    stack.push(RenameIconCommand(icon_name, "user-chosen-name"))
    assert icon_name.value == "user-chosen-name"
    assert icon_name.is_manual is True

    stack.undo()
    assert icon_name.value == "auto-name"
    assert icon_name.is_manual is False
