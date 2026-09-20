"""Slices tab: view and edit detected crop boxes over the source sheet.

Slice 1 scope: move and resize a single crop box via QGraphicsView.
Rotate, split, merge, and multi-select are deferred to slice 2.
"""

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget


class SlicesTab(QWidget):
    def __init__(self, undo_stack: QUndoStack) -> None:
        super().__init__()
        self._undo_stack = undo_stack
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
