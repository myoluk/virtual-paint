import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

TOOLBAR_H = 56
_CELL_W = 50
_H_PAD = 6
_SEP_GAP = 14
_DWELL_THRESHOLD = 0.8
_COOLDOWN = 0.6


@dataclass
class ToolChange:
    kind: str   # "color" | "size" | "eraser" | "clear"
    value: Any = None


class _Btn:
    __slots__ = ("x", "kind", "value", "draw_color")

    def __init__(self, x: int, kind: str, value: Any, draw_color: tuple) -> None:
        self.x = x
        self.kind = kind
        self.value = value
        self.draw_color = draw_color


class VirtualToolbar:
    def __init__(
        self,
        colors: dict[str, tuple[int, int, int]],
        brush_sizes: dict[str, int],
    ) -> None:
        self._colors = colors
        self._brush_sizes = brush_sizes
        self._buttons: list[_Btn] = []
        self._sep_positions: list[int] = []
        self._frame_width: int = 0
        self._active_color: tuple[int, int, int] = next(iter(colors.values()))
        self._active_size: str = next(iter(brush_sizes.keys()))
        self._eraser_active: bool = False
        self._hovered_idx: int = -1
        self._hover_start: float = 0.0
        self._last_triggered: float = 0.0

    def _build(self, width: int) -> None:
        """Build button layout right-to-left. First color (top of left panel) is rightmost."""
        self._buttons.clear()
        self._sep_positions.clear()
        self._frame_width = width
        x = width - _H_PAD

        for name, bgr in self._colors.items():
            x -= _CELL_W
            self._buttons.append(_Btn(x, "color", (name, bgr), bgr))

        x -= _SEP_GAP // 2
        self._sep_positions.append(x)
        x -= _SEP_GAP // 2

        for name, size in self._brush_sizes.items():
            x -= _CELL_W
            self._buttons.append(_Btn(x, "size", (name, size), (180, 180, 180)))

        x -= _SEP_GAP // 2
        self._sep_positions.append(x)
        x -= _SEP_GAP // 2

        x -= _CELL_W
        self._buttons.append(_Btn(x, "eraser", None, (150, 150, 150)))

        x -= _CELL_W
        self._buttons.append(_Btn(x, "clear", None, (80, 100, 200)))

    # --- Sync state from Qt toolbar ---

    def set_color(self, color: tuple[int, int, int]) -> None:
        self._active_color = color
        self._eraser_active = False

    def set_size(self, name: str) -> None:
        self._active_size = name

    def set_eraser(self, active: bool) -> None:
        self._eraser_active = active

    def update_colors(self, colors: dict[str, tuple[int, int, int]]) -> None:
        """Replace the color palette and rebuild toolbar buttons."""
        self._colors = colors
        if self._active_color not in colors.values():
            self._active_color = next(iter(colors.values()))
        if self._frame_width > 0:
            self._build(self._frame_width)

    # --- Per-frame update ---

    def process(self, frame: np.ndarray, tip: tuple[int, int] | None) -> ToolChange | None:
        w = frame.shape[1]
        if w != self._frame_width:
            self._build(w)

        now = time.monotonic()
        new_hovered = self._find_hovered(tip)

        if new_hovered != self._hovered_idx:
            self._hovered_idx = new_hovered
            self._hover_start = now

        result = self._check_dwell(now)
        self._draw(frame, now)
        return result

    def _find_hovered(self, tip: tuple[int, int] | None) -> int:
        if tip is None:
            return -1
        tx, ty = tip
        if not (0 <= ty < TOOLBAR_H):
            return -1
        for i, btn in enumerate(self._buttons):
            if btn.x <= tx < btn.x + _CELL_W:
                return i
        return -1

    def _check_dwell(self, now: float) -> ToolChange | None:
        if self._hovered_idx < 0:
            return None
        if now - self._last_triggered < _COOLDOWN:
            return None
        if now - self._hover_start < _DWELL_THRESHOLD:
            return None

        btn = self._buttons[self._hovered_idx]
        self._last_triggered = now

        if btn.kind == "color":
            _, bgr = btn.value
            self._active_color = bgr
            self._eraser_active = False
            return ToolChange("color", btn.value)
        if btn.kind == "size":
            name, _ = btn.value
            self._active_size = name
            return ToolChange("size", btn.value)
        if btn.kind == "eraser":
            self._eraser_active = True
            return ToolChange("eraser", True)
        if btn.kind == "clear":
            return ToolChange("clear", None)
        return None

    def _draw(self, frame: np.ndarray, now: float) -> None:
        w = frame.shape[1]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, TOOLBAR_H), (15, 15, 15), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        cv2.line(frame, (0, TOOLBAR_H), (w, TOOLBAR_H), (45, 45, 45), 1)

        for sx in self._sep_positions:
            cv2.line(frame, (sx, 10), (sx, TOOLBAR_H - 10), (60, 60, 60), 1)

        for i, btn in enumerate(self._buttons):
            cx = btn.x + _CELL_W // 2
            cy = TOOLBAR_H // 2
            is_hovered = i == self._hovered_idx
            is_selected = self._is_selected(btn)
            self._draw_button(frame, btn, cx, cy, is_selected, is_hovered)

            if is_hovered:
                elapsed = min(now - self._hover_start, _DWELL_THRESHOLD)
                angle = int(elapsed / _DWELL_THRESHOLD * 360)
                if angle > 0:
                    cv2.ellipse(
                        frame, (cx, cy), (17, 17),
                        -90, 0, angle, (255, 255, 255), 2,
                    )

    def _draw_button(
        self,
        frame: np.ndarray,
        btn: _Btn,
        cx: int,
        cy: int,
        is_selected: bool,
        is_hovered: bool,
    ) -> None:
        if btn.kind == "color":
            r = 13
            cv2.circle(frame, (cx, cy), r, btn.draw_color, -1)
            if is_selected:
                cv2.circle(frame, (cx, cy), r + 3, (255, 255, 255), 2)
            elif is_hovered:
                cv2.circle(frame, (cx, cy), r + 2, (160, 160, 160), 1)

        elif btn.kind == "size":
            name = btn.value[0]
            r = {"small": 4, "medium": 8, "large": 13}.get(name, 6)
            fill = (220, 220, 220) if is_selected else (110, 110, 110)
            cv2.circle(frame, (cx, cy), r, fill, -1)
            if is_selected:
                cv2.circle(frame, (cx, cy), r + 3, (255, 255, 255), 2)

        elif btn.kind == "eraser":
            if is_selected or is_hovered:
                bx1, bx2 = btn.x + 4, btn.x + _CELL_W - 4
                bg = (55, 55, 75) if is_selected else (45, 45, 45)
                cv2.rectangle(frame, (bx1, 10), (bx2, TOOLBAR_H - 10), bg, -1)
            cv2.rectangle(frame, (cx - 11, cy - 5), (cx + 2, cy + 5), (100, 90, 160), -1)
            cv2.rectangle(frame, (cx + 2, cy - 5), (cx + 10, cy + 5), (65, 55, 100), -1)
            cv2.line(frame, (cx + 2, cy - 4), (cx + 2, cy + 4), (200, 200, 200), 1)

        elif btn.kind == "clear":
            if is_selected or is_hovered:
                bx1, bx2 = btn.x + 4, btn.x + _CELL_W - 4
                bg = (55, 55, 75) if is_selected else (45, 45, 45)
                cv2.rectangle(frame, (bx1, 10), (bx2, TOOLBAR_H - 10), bg, -1)
            col = (160, 160, 160)
            cv2.line(frame, (cx - 3, cy - 10), (cx + 3, cy - 10), col, 1)
            cv2.line(frame, (cx - 3, cy - 10), (cx - 3, cy - 8), col, 1)
            cv2.line(frame, (cx + 3, cy - 10), (cx + 3, cy - 8), col, 1)
            cv2.line(frame, (cx - 8, cy - 8), (cx + 8, cy - 8), col, 1)
            cv2.rectangle(frame, (cx - 7, cy - 6), (cx + 7, cy + 8), col, 1)
            cv2.line(frame, (cx - 3, cy - 4), (cx - 3, cy + 6), col, 1)
            cv2.line(frame, (cx + 3, cy - 4), (cx + 3, cy + 6), col, 1)

    def _is_selected(self, btn: _Btn) -> bool:
        if btn.kind == "color":
            _, bgr = btn.value
            return bgr == self._active_color and not self._eraser_active
        if btn.kind == "size":
            name, _ = btn.value
            return name == self._active_size
        if btn.kind == "eraser":
            return self._eraser_active
        return False
