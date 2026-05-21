from pathlib import Path

import cv2
import numpy as np

from src.config import MAX_UNDO_STEPS


class Painter:
    def __init__(
        self,
        width: int,
        height: int,
        bg_color: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        self._width = width
        self._height = height
        self._bg_color = bg_color
        self.canvas = np.empty((height, width, 3), dtype=np.uint8)
        self.canvas[:] = bg_color
        self._history: list[np.ndarray] = []
        self._redo_stack: list[np.ndarray] = []

    def begin_stroke(self) -> None:
        self._history.append(self.canvas.copy())
        if len(self._history) > MAX_UNDO_STEPS:
            self._history.pop(0)
        self._redo_stack.clear()

    def draw_line(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int],
        thickness: int,
    ) -> None:
        cv2.line(self.canvas, start, end, color, thickness)

    def erase(self, center: tuple[int, int], radius: int) -> None:
        cv2.circle(self.canvas, center, radius, self._bg_color, -1)

    def clear(self) -> None:
        self._history.append(self.canvas.copy())
        if len(self._history) > MAX_UNDO_STEPS:
            self._history.pop(0)
        self._redo_stack.clear()
        self.canvas = np.empty((self._height, self._width, 3), dtype=np.uint8)
        self.canvas[:] = self._bg_color

    def set_bg_color(self, bg_color: tuple[int, int, int]) -> None:
        self._history.append(self.canvas.copy())
        if len(self._history) > MAX_UNDO_STEPS:
            self._history.pop(0)
        self._redo_stack.clear()
        self._bg_color = bg_color
        self.canvas = np.empty((self._height, self._width, 3), dtype=np.uint8)
        self.canvas[:] = self._bg_color

    def undo(self) -> None:
        if not self._history:
            return
        self._redo_stack.append(self.canvas.copy())
        self.canvas = self._history.pop()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._history.append(self.canvas.copy())
        self.canvas = self._redo_stack.pop()

    def save(self, path: Path | str) -> None:
        cv2.imwrite(str(path), self.canvas)

    def composite(self, frame: np.ndarray) -> np.ndarray:
        bg_layer = np.empty_like(self.canvas)
        bg_layer[:] = self._bg_color
        diff = cv2.absdiff(self.canvas, bg_layer)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
        mask_inv = cv2.bitwise_not(mask)
        frame_part = cv2.bitwise_and(frame, frame, mask=mask_inv)
        paint_part = cv2.bitwise_and(self.canvas, self.canvas, mask=mask)
        return cv2.add(frame_part, paint_part)

    def resize(self, width: int, height: int) -> None:
        # Resize preserves drawn content; bg_color is already baked into the canvas.
        self.canvas = cv2.resize(self.canvas, (width, height))
        self._width = width
        self._height = height
        self._history.clear()
        self._redo_stack.clear()
