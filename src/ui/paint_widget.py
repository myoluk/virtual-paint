import time

import cv2
import numpy as np
from PySide6.QtCore import QRect, QSize, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSplitter, QSplitterHandle, QVBoxLayout, QWidget,
)

from src.camera import Camera
from src.config import BRUSH_SIZES, DRAW_COLORS
from src.painter import Painter
from src.tracker import ColorTracker
from src.ui.virtual_toolbar import TOOLBAR_H, ToolChange, VirtualToolbar

_TARGET_FPS = 30
_FRAME_INTERVAL = 1.0 / _TARGET_FPS
_MAX_READ_FAILURES = 15

_MSG_UNAVAILABLE = (
    "Camera unavailable\n\n"
    "Another application may be using the camera.\n"
    "Close it and click Refresh to reconnect."
)

_MSG_NOT_FOUND = (
    "No camera detected\n\n"
    "If another application is using the camera,\n"
    "close it and click Refresh."
)
_MSG_CONNECTING = "Connecting to camera..."
_MSG_CALIBRATING = (
    "Calibration is open\n\n"
    "Camera feed will resume\n"
    "when you close the dialog."
)


def _panel_close_icon() -> QIcon:
    px = QPixmap(10, 10)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(80, 80, 80))
    pen.setWidthF(1.3)
    p.setPen(pen)
    p.drawLine(1, 1, 9, 9)
    p.drawLine(9, 1, 1, 9)
    p.end()
    return QIcon(px)


class _FrameLabel(QLabel):
    """QLabel that scales its frame on each paintEvent; supports a placeholder state."""

    def __init__(self, bg_color: str = "#000", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._placeholder_msg: str | None = None
        self._placeholder_base: str = ""
        self._dot_count: int = 0
        self._bg_color = bg_color
        self.setStyleSheet(f"background: {bg_color};")

        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._tick_dots)

    def set_frame(self, image: QImage) -> None:
        self._dot_timer.stop()
        self._image = image
        self._placeholder_msg = None
        self.update()

    def set_placeholder(self, message: str) -> None:
        self._image = None
        if message.endswith("..."):
            self._placeholder_base = message[:-3]
            self._dot_count = 3
            self._placeholder_msg = message
            self._dot_timer.start()
        else:
            self._placeholder_base = ""
            self._dot_timer.stop()
            self._placeholder_msg = message
        self.update()

    def _tick_dots(self) -> None:
        self._dot_count = self._dot_count % 3 + 1
        self._placeholder_msg = self._placeholder_base + "." * self._dot_count
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._image is not None:
            scaled = self._image.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.fillRect(self.rect(), QColor(self._bg_color))
            painter.drawImage(x, y, scaled)
            return

        painter.fillRect(self.rect(), QColor("#0d0d0d"))

        if self._placeholder_msg is None:
            return

        cx = self.width() // 2
        cy = self.height() // 2 - 24

        # Camera body
        bw, bh = 58, 40
        bx, by = cx - bw // 2, cy - bh // 2
        painter.setPen(QPen(QColor("#3a3a3a"), 2))
        painter.setBrush(QBrush(QColor("#1a1a1a")))
        painter.drawRoundedRect(bx, by, bw, bh, 5, 5)

        # Lens outer
        painter.setPen(QPen(QColor("#3a3a3a"), 2))
        painter.setBrush(QBrush(QColor("#111")))
        painter.drawEllipse(cx - 12, cy - 12, 24, 24)

        # Lens inner
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#2a2a2a")))
        painter.drawEllipse(cx - 7, cy - 7, 14, 14)

        # Viewfinder bump
        painter.setPen(QPen(QColor("#3a3a3a"), 2))
        painter.setBrush(QBrush(QColor("#1a1a1a")))
        painter.drawRoundedRect(cx - 8, by - 6, 16, 8, 3, 3)

        # Flash dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#2e2e2e")))
        painter.drawEllipse(bx + 7, by + 8, 7, 7)

        # Message
        painter.setPen(QColor("#484848"))
        font = QFont()
        font.setPixelSize(12)
        painter.setFont(font)
        text_y = cy + 32

        if self._dot_timer.isActive() and self._placeholder_base:
            # Anchor layout to "base + ..." width so base text never shifts.
            # Draw base and active dots at independently fixed x positions.
            metrics = painter.fontMetrics()
            full_w = metrics.horizontalAdvance(self._placeholder_base + "...")
            base_x = max(16, (self.width() - full_w) // 2)
            dot_x = base_x + metrics.horizontalAdvance(self._placeholder_base)
            baseline_y = text_y + metrics.ascent()
            painter.drawText(base_x, baseline_y, self._placeholder_base)
            painter.drawText(dot_x, baseline_y, "." * self._dot_count)
        else:
            text_rect = QRect(16, text_y, self.width() - 32, self.height() - text_y)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._placeholder_msg,
            )


class _SplitterHandle(QSplitterHandle):
    """Splitter handle that equalizes panel sizes on double-click."""

    def mouseDoubleClickEvent(self, event) -> None:
        splitter = self.splitter()
        total = sum(splitter.sizes())
        half = total // 2
        splitter.setSizes([half, total - half])


class _Splitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:
        return _SplitterHandle(self.orientation(), self)


class CameraWorker(QThread):
    detection_ready = Signal(np.ndarray, object, object)
    camera_unavailable = Signal()

    def __init__(self, camera_index: int, tracker: ColorTracker) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._tracker = tracker
        self._running = False
        self._frame_consumed = True  # backpressure flag

    def mark_consumed(self) -> None:
        self._frame_consumed = True

    def run(self) -> None:
        camera = Camera(self._camera_index)
        if not camera.open():
            self.camera_unavailable.emit()
            return
        camera.set_resolution(1280, 720)
        self._running = True
        last_time = 0.0
        fail_count = 0
        while self._running:
            now = time.monotonic()
            if now - last_time < _FRAME_INTERVAL:
                time.sleep(_FRAME_INTERVAL - (now - last_time))
                continue
            if not self._frame_consumed:
                # UI still processing previous frame - skip this tick
                last_time = now
                continue
            frame = camera.read()
            if frame is None:
                fail_count += 1
                if fail_count >= _MAX_READ_FAILURES:
                    self.camera_unavailable.emit()
                    break
                last_time = now
                continue
            fail_count = 0
            tip, rect = self._tracker.detect(frame)
            self._frame_consumed = False
            self.detection_ready.emit(frame, tip, rect)
            last_time = time.monotonic()
        camera.close()

    def stop(self) -> None:
        self._running = False
        self.wait()


class PaintWidget(QWidget):
    tool_color_changed = Signal(object)   # bgr tuple
    tool_size_changed = Signal(str)       # size name
    tool_eraser_changed = Signal(bool)
    tool_cleared = Signal()
    camera_active_changed = Signal(bool)  # True when frames flowing, False otherwise
    canvas_close_requested = Signal()
    camera_close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tracker: ColorTracker = ColorTracker.default()
        self._painter: Painter | None = None
        self._prev_tip: tuple[int, int] | None = None
        self._active_color: tuple[int, int, int] = next(iter(DRAW_COLORS.values()))
        self._active_size_name: str = next(iter(BRUSH_SIZES.keys()))
        self._brush_thickness: int = next(iter(BRUSH_SIZES.values()))
        self._eraser_mode: bool = False
        self._canvas_bg: tuple[int, int, int] = (0, 0, 0)  # BGR
        self._worker: CameraWorker | None = None
        self._vtoolbar = VirtualToolbar(DRAW_COLORS, BRUSH_SIZES)
        self._saved_splitter_sizes: list[int] = [600, 600]
        self._camera_active: bool = False
        self._drawing_paused: bool = False
        self._show_detection_rect: bool = True
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = _Splitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #555; }"
        )

        # Canvas panel
        self._canvas_container = QWidget()
        self._canvas_container.setObjectName("panel-container")
        canvas_vbox = QVBoxLayout(self._canvas_container)
        canvas_vbox.setContentsMargins(0, 0, 0, 0)
        canvas_vbox.setSpacing(0)
        canvas_vbox.addWidget(self._make_panel_header("Canvas", self.canvas_close_requested))
        self._canvas_label = _FrameLabel("#1a1a1a")
        canvas_vbox.addWidget(self._canvas_label)
        self._canvas_container.setMinimumWidth(100)

        # Camera panel
        self._camera_container = QWidget()
        self._camera_container.setObjectName("panel-container")
        camera_vbox = QVBoxLayout(self._camera_container)
        camera_vbox.setContentsMargins(0, 0, 0, 0)
        camera_vbox.setSpacing(0)
        camera_vbox.addWidget(self._make_panel_header("Camera", self.camera_close_requested))
        self._camera_label = _FrameLabel("#1a1a1a")
        camera_vbox.addWidget(self._camera_label)
        self._camera_container.setMinimumWidth(100)

        self._splitter.addWidget(self._canvas_container)
        self._splitter.addWidget(self._camera_container)
        self._splitter.setSizes([600, 600])

        layout.addWidget(self._splitter)

    @staticmethod
    def _make_panel_header(label: str, close_signal: Signal) -> QWidget:
        header = QWidget()
        header.setObjectName("panel-header")
        header.setFixedHeight(28)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 4, 0)
        h_layout.setSpacing(0)
        lbl = QLabel(label)
        lbl.setObjectName("panel-header-label")
        h_layout.addWidget(lbl)
        h_layout.addStretch()
        btn = QPushButton()
        btn.setIcon(_panel_close_icon())
        btn.setIconSize(QSize(10, 10))
        btn.setObjectName("panel-close-btn")
        btn.setFixedSize(18, 18)
        btn.clicked.connect(close_signal)
        h_layout.addWidget(btn)
        return header

    # --- Camera control ---

    def start_camera(self, camera_index: int) -> None:
        if self._worker:
            self._worker.detection_ready.disconnect(self._on_detection)
            self._worker.camera_unavailable.disconnect(self._on_camera_unavailable)
            self._worker.stop()
            self._worker.deleteLater()
        self._set_camera_active(False)
        self._camera_label.set_placeholder(_MSG_CONNECTING)
        self._worker = CameraWorker(camera_index, self._tracker)
        self._worker.detection_ready.connect(self._on_detection)
        self._worker.camera_unavailable.connect(self._on_camera_unavailable)
        self._worker.start()

    def stop_camera(self) -> None:
        if self._worker:
            self._worker.detection_ready.disconnect(self._on_detection)
            self._worker.camera_unavailable.disconnect(self._on_camera_unavailable)
            self._worker.stop()
            self._worker.deleteLater()
            self._worker = None
        self._set_camera_active(False)

    def show_camera_placeholder(self, message: str) -> None:
        self._camera_label.set_placeholder(message)
        self._set_camera_active(False)

    def show_no_camera_placeholder(self) -> None:
        self._camera_label.set_placeholder(_MSG_NOT_FOUND)
        self._set_camera_active(False)

    def toggle_camera_panel(self, visible: bool) -> None:
        if visible:
            self._camera_container.setVisible(True)
            if self._canvas_container.isVisible():
                self._splitter.setSizes(self._saved_splitter_sizes)
        else:
            if self._canvas_container.isVisible():
                self._saved_splitter_sizes = self._splitter.sizes()
            self._camera_container.setVisible(False)

    def toggle_canvas_panel(self, visible: bool) -> None:
        if visible:
            self._canvas_container.setVisible(True)
            if self._camera_container.isVisible():
                self._splitter.setSizes(self._saved_splitter_sizes)
        else:
            if self._camera_container.isVisible():
                self._saved_splitter_sizes = self._splitter.sizes()
            self._canvas_container.setVisible(False)

    def update_virtual_toolbar_colors(self, colors: dict[str, tuple[int, int, int]]) -> None:
        self._vtoolbar.update_colors(colors)

    # --- Tool setters ---

    def set_tracker(self, tracker: ColorTracker) -> None:
        self._tracker = tracker
        if self._worker:
            self._worker._tracker = tracker

    def set_color(self, color: tuple[int, int, int]) -> None:
        self._active_color = color
        self._eraser_mode = False
        self._vtoolbar.set_color(color)

    def set_brush_size(self, name: str, thickness: int) -> None:
        self._active_size_name = name
        self._brush_thickness = thickness
        self._vtoolbar.set_size(name)

    def set_canvas_bg(self, bgr: tuple[int, int, int]) -> None:
        self._canvas_bg = bgr
        if self._painter:
            self._painter.set_bg_color(bgr)

    def set_eraser_mode(self, enabled: bool) -> None:
        self._eraser_mode = enabled
        self._vtoolbar.set_eraser(enabled)

    def set_show_detection_rect(self, visible: bool) -> None:
        self._show_detection_rect = visible

    def set_drawing_paused(self, paused: bool) -> None:
        self._drawing_paused = paused
        if paused:
            self._prev_tip = None

    def clear_canvas(self) -> None:
        if self._painter:
            self._painter.clear()

    def undo(self) -> None:
        if self._painter:
            self._painter.undo()

    def redo(self) -> None:
        if self._painter:
            self._painter.redo()

    def save_canvas(self, path: str) -> None:
        if self._painter:
            self._painter.save(path)

    # --- Internal helpers ---

    def _set_camera_active(self, active: bool) -> None:
        if self._camera_active != active:
            self._camera_active = active
            self.camera_active_changed.emit(active)

    # --- Frame processing ---

    def _on_detection(
        self,
        frame: np.ndarray,
        tip: tuple[int, int] | None,
        rect: tuple[int, int, int, int] | None,
    ) -> None:
        if self._worker:
            self._worker.mark_consumed()

        self._set_camera_active(True)

        h, w = frame.shape[:2]
        if self._painter is None:
            self._painter = Painter(w, h, bg_color=self._canvas_bg)
        elif self._painter.canvas.shape[:2] != (h, w):
            self._painter.resize(w, h)

        in_toolbar = tip is not None and tip[1] < TOOLBAR_H
        drawing_tip = None if (tip is None or in_toolbar) else tip

        if drawing_tip is not None and not self._drawing_paused:
            if self._prev_tip is None:
                self._painter.begin_stroke()
            if self._eraser_mode:
                self._painter.erase(drawing_tip, self._brush_thickness + 15)
            elif self._prev_tip is not None:
                self._painter.draw_line(
                    self._prev_tip, drawing_tip,
                    self._active_color, self._brush_thickness,
                )
        self._prev_tip = None if self._drawing_paused else drawing_tip

        composite = self._painter.composite(frame)

        if self._show_detection_rect and rect is not None:
            rx, ry, rw, rh = rect
            cv2.rectangle(composite, (rx, ry), (rx + rw, ry + rh), self._active_color, 2)

        tool_change = self._vtoolbar.process(composite, tip)
        if tool_change is not None:
            self._apply_tool_change(tool_change)

        if drawing_tip is not None:
            ind_color = (255, 255, 255) if self._eraser_mode else self._active_color
            cv2.circle(composite, drawing_tip, self._brush_thickness + 3, ind_color, 2)

        self._canvas_label.set_frame(self._numpy_to_qimage(self._painter.canvas))
        self._camera_label.set_frame(self._numpy_to_qimage(composite))

    def _on_camera_unavailable(self) -> None:
        # Worker already stopped itself; clear the reference so the device is fully released.
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        self._set_camera_active(False)
        self._camera_label.set_placeholder(_MSG_UNAVAILABLE)

    def _apply_tool_change(self, change: ToolChange) -> None:
        if change.kind == "color":
            _, bgr = change.value
            self._active_color = bgr
            self._eraser_mode = False
            self.tool_color_changed.emit(bgr)
        elif change.kind == "size":
            name, size = change.value
            self._active_size_name = name
            self._brush_thickness = size
            self.tool_size_changed.emit(name)
        elif change.kind == "eraser":
            self._eraser_mode = True
            self.tool_eraser_changed.emit(True)
        elif change.kind == "clear":
            if self._painter:
                self._painter.clear()
            self.tool_cleared.emit()

    @staticmethod
    def _numpy_to_qimage(frame: np.ndarray) -> QImage:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
