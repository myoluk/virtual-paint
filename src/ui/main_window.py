import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.camera import Camera
from src.config import BRUSH_SIZES, CANVAS_CONFIG_PATH, DRAW_COLORS, HSV_CONFIG_PATH
from src.tracker import ColorTracker
from src.ui.calibration_dialog import CalibrationDialog
from src.ui.paint_widget import PaintWidget


_SPINNER_FRAMES = ("◐", "◓", "◑", "◒")
_SPINNER_INTERVAL_MS = 120


def _make_close_icon(size: int, line_width: float, color: QColor) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(line_width)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    m = 3.0
    p.drawLine(m, m, size - m, size - m)
    p.drawLine(size - m, m, m, size - m)
    p.end()
    return QIcon(px)


class _TitleBar(QWidget):
    """Custom title bar: app icon, embedded menu bar, and window controls."""

    def __init__(self, window: "MainWindow", icon: QIcon) -> None:
        super().__init__(window)
        self._win = window
        self.setFixedHeight(30)
        self.setObjectName("title-bar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon.pixmap(16, 16))
        icon_lbl.setFixedSize(22, 30)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        layout.addSpacing(8)

        self.menu_bar = QMenuBar(self)
        self.menu_bar.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.menu_bar, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()

        icon_size = QSize(14, 14)
        for icon, slot, name in (
            (self._icon_minimize(), window.showMinimized, "wc-min"),
            (self._icon_maximize(), self._toggle_maximize, "wc-max"),
            (_make_close_icon(14, 1.5, QColor(120, 120, 120)), window.close, "wc-close"),
        ):
            btn = QPushButton()
            btn.setIcon(icon)
            btn.setIconSize(icon_size)
            btn.setFixedSize(46, 30)
            btn.setObjectName(name)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
            if name == "wc-max":
                self._max_btn = btn

    def _toggle_maximize(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
            self._max_btn.setIcon(self._icon_maximize())
        else:
            self._win.showMaximized()
            self._max_btn.setIcon(self._icon_restore())

    @staticmethod
    def _icon_minimize() -> QIcon:
        px = QPixmap(14, 14)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(120, 120, 120))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(2.5, 7.0, 11.5, 7.0)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_maximize() -> QIcon:
        px = QPixmap(14, 14)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(120, 120, 120))
        pen.setWidthF(1.5)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.drawRect(2.5, 2.5, 9.0, 9.0)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_restore() -> QIcon:
        px = QPixmap(14, 14)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(120, 120, 120))
        pen.setWidthF(1.5)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.drawRect(4.5, 2.5, 7.0, 7.0)
        p.fillRect(2.5, 4.5, 7, 7, Qt.GlobalColor.transparent)
        p.drawRect(2.5, 4.5, 7.0, 7.0)
        p.end()
        return QIcon(px)



class _CameraListWorker(QThread):
    """Runs Camera.list_available() off the UI thread to avoid blocking the feed."""

    finished = Signal(list)  # list[tuple[int, str]]

    def run(self) -> None:
        self.finished.emit(Camera.list_available())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Virtual Paint")
        self.setMinimumSize(1200, 600)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # Restore DWM drop shadow after the native handle is created
        QTimer.singleShot(0, self._setup_windows_frame)

        self._paint_widget = PaintWidget()

        self._color_buttons: dict[str, QPushButton] = {}
        self._size_buttons: dict[str, QPushButton] = {}
        self._active_color_name: str = "color_1"
        self._active_size_name: str = "small"
        self._canvas_bg_bgr: tuple[int, int, int] = (0, 0, 0)
        self._camera_active: bool = False
        self._select_color_acts: list[QAction] = []
        self._available_cameras: list[tuple[int, str]] = []
        self._current_camera_index: int | None = None
        self._initializing: bool = True
        # Mutable copy of all named colors; updated when user changes a swatch
        self._color_values: dict[str, tuple[int, int, int]] = dict(DRAW_COLORS)

        self._build_status_bar()
        self._build_options_bar()
        self._build_left_toolbar()
        self._build_menu_bar()
        self._build_central_widget()
        self._connect_paint_signals()
        self._load_tracker()
        self._load_canvas_config()
        self._initializing = False
        self._refresh_cameras(initial=True)
        self._apply_style()
        for btn in self.findChildren(QPushButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # --- Build UI ---

    def _build_options_bar(self) -> None:
        self._options_bar = QToolBar("Tool Options")
        self._options_bar.setMovable(False)
        self._options_bar.setFloatable(False)
        self._options_bar.setObjectName("options-bar")
        self._options_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._options_bar)

        self._options_stack = QStackedWidget()
        self._options_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        # --- Page 0: Brush ---
        brush_page = QWidget()
        brush_layout = QHBoxLayout(brush_page)
        brush_layout.setContentsMargins(4, 0, 0, 0)
        brush_layout.setSpacing(8)

        brush_lbl = QLabel("Brush")
        brush_lbl.setObjectName("options-tool-label")
        brush_layout.addWidget(brush_lbl)

        brush_layout.addWidget(self._make_vsep())

        color_lbl = QLabel("Color")
        color_lbl.setObjectName("toolbar-label")
        brush_layout.addWidget(color_lbl)

        self._opt_color_swatch = QPushButton()
        self._opt_color_swatch.setFixedSize(28, 28)
        self._opt_color_swatch.setObjectName("opt-color-swatch")
        self._opt_color_swatch.setToolTip("Active color - click to change")
        self._opt_color_swatch.clicked.connect(
            lambda: self._on_default_color_clicked(self._active_color_name)
        )
        brush_layout.addWidget(self._opt_color_swatch)

        brush_layout.addWidget(self._make_vsep())

        size_lbl = QLabel("Size")
        size_lbl.setObjectName("toolbar-label")
        brush_layout.addWidget(size_lbl)

        self._opt_brush_size_btns: dict[str, QPushButton] = {}
        for name in BRUSH_SIZES:
            btn = QPushButton(name[0].upper())
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setObjectName("opt-size-btn")
            btn.setToolTip(f"{name.capitalize()} brush size")
            btn.clicked.connect(lambda _, n=name: self._select_size(n, BRUSH_SIZES[n]))
            brush_layout.addWidget(btn)
            self._opt_brush_size_btns[name] = btn

        brush_layout.addStretch()
        self._options_stack.addWidget(brush_page)  # index 0

        # --- Page 1: Eraser ---
        eraser_page = QWidget()
        eraser_layout = QHBoxLayout(eraser_page)
        eraser_layout.setContentsMargins(4, 0, 0, 0)
        eraser_layout.setSpacing(8)

        eraser_lbl = QLabel("Eraser")
        eraser_lbl.setObjectName("options-tool-label")
        eraser_layout.addWidget(eraser_lbl)

        eraser_layout.addWidget(self._make_vsep())

        size_lbl2 = QLabel("Size")
        size_lbl2.setObjectName("toolbar-label")
        eraser_layout.addWidget(size_lbl2)

        self._opt_eraser_size_btns: dict[str, QPushButton] = {}
        for name in BRUSH_SIZES:
            btn = QPushButton(name[0].upper())
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setObjectName("opt-size-btn")
            btn.setToolTip(f"{name.capitalize()} eraser size")
            btn.clicked.connect(lambda _, n=name: self._select_size(n, BRUSH_SIZES[n]))
            eraser_layout.addWidget(btn)
            self._opt_eraser_size_btns[name] = btn

        eraser_layout.addStretch()
        self._options_stack.addWidget(eraser_page)  # index 1

        self._options_bar.addWidget(self._options_stack)

    @staticmethod
    def _make_vsep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setObjectName("options-vsep")
        return sep

    def _build_central_widget(self) -> None:
        self.setCentralWidget(self._paint_widget)

    def _close_tab(self, name: str) -> None:
        if name == "camera":
            self._paint_widget.toggle_camera_panel(False)
            if hasattr(self, "_act_camera"):
                self._act_camera.setChecked(False)
        elif name == "canvas":
            self._paint_widget.toggle_canvas_panel(False)
            if hasattr(self, "_act_canvas"):
                self._act_canvas.setChecked(False)

    def _open_tab(self, name: str) -> None:
        if name == "camera":
            self._paint_widget.toggle_camera_panel(True)
            if hasattr(self, "_act_camera"):
                self._act_camera.setChecked(True)
        elif name == "canvas":
            self._paint_widget.toggle_canvas_panel(True)
            if hasattr(self, "_act_canvas"):
                self._act_canvas.setChecked(True)

    def _build_left_toolbar(self) -> None:
        self._left_toolbar = QToolBar("Toolbar")
        self._left_toolbar.setMovable(False)
        self._left_toolbar.setFloatable(False)
        self._left_toolbar.setOrientation(Qt.Orientation.Vertical)
        self._left_toolbar.setObjectName("left-toolbar")
        self._left_toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self._left_toolbar)

        container = QWidget()
        container.setObjectName("left-panel-container")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        for i, (name, bgr) in enumerate(DRAW_COLORS.items(), 1):
            btn = self._make_color_button(name, bgr)
            btn.setToolTip(f"Color ({i})")
            layout.addWidget(btn)
            self._color_buttons[name] = btn

        reset_row = QWidget()
        reset_row_layout = QHBoxLayout(reset_row)
        reset_row_layout.setContentsMargins(0, 4, 0, 0)
        reset_row_layout.setSpacing(0)
        reset_row_layout.addStretch()
        reset_btn = QPushButton()
        reset_btn.setIcon(self._icon_reset_colors())
        reset_btn.setIconSize(QSize(14, 14))
        reset_btn.setFixedSize(18, 18)
        reset_btn.setToolTip("Reset colors")
        reset_btn.setObjectName("reset-colors-btn")
        reset_btn.clicked.connect(self._reset_colors)
        reset_row_layout.addWidget(reset_btn)
        layout.addWidget(reset_row)

        layout.addWidget(self._make_hsep())

        _dot_radii = {"small": 3, "medium": 5, "large": 8}
        _size_shortcuts = {"small": "J", "medium": "K", "large": "L"}
        for name, thickness in BRUSH_SIZES.items():
            btn = QPushButton()
            btn.setIcon(self._icon_brush_dot(_dot_radii[name]))
            btn.setIconSize(QSize(18, 18))
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setToolTip(f"{name.capitalize()} ({_size_shortcuts[name]})")
            btn.setObjectName(f"size-{name}")
            btn.clicked.connect(lambda _, t=thickness, n=name: self._select_size(n, t))
            layout.addWidget(btn)
            self._size_buttons[name] = btn

        layout.addWidget(self._make_hsep())

        self._eraser_btn = QPushButton()
        self._eraser_btn.setIcon(self._icon_eraser())
        self._eraser_btn.setIconSize(QSize(18, 18))
        self._eraser_btn.setCheckable(True)
        self._eraser_btn.setFixedSize(28, 28)
        self._eraser_btn.setToolTip("Eraser (E)")
        self._eraser_btn.setObjectName("eraser-btn")
        self._eraser_btn.clicked.connect(self._toggle_eraser)
        layout.addWidget(self._eraser_btn)

        clear_btn = QPushButton()
        clear_btn.setIcon(self._icon_trash())
        clear_btn.setIconSize(QSize(18, 18))
        clear_btn.setFixedSize(28, 28)
        clear_btn.setToolTip("Clear Canvas (C C)")
        clear_btn.setObjectName("tool-icon-btn")
        clear_btn.clicked.connect(self._paint_widget.clear_canvas)
        layout.addWidget(clear_btn)

        layout.addStretch()

        layout.addWidget(self._make_hsep())

        self._canvas_bg_btn = QPushButton()
        self._canvas_bg_btn.setFixedSize(28, 28)
        self._canvas_bg_btn.setToolTip("Canvas background color")
        self._canvas_bg_btn.setObjectName("canvas-bg-btn")
        self._canvas_bg_btn.clicked.connect(self._pick_canvas_bg)
        layout.addWidget(self._canvas_bg_btn)

        self._left_toolbar.addWidget(container)

        self._select_color("color_1", DRAW_COLORS["color_1"])
        self._select_size("small", BRUSH_SIZES["small"])

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setSizeGripEnabled(False)
        self.setStatusBar(status_bar)

        self._status_label = QLabel()
        self._status_label.setObjectName("status-msg")
        status_bar.addWidget(self._status_label)

        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(_SPINNER_INTERVAL_MS)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_idx = 0
        self._spinner_msg = ""

        self._msg_clear_timer = QTimer(self)
        self._msg_clear_timer.setSingleShot(True)
        self._msg_clear_timer.timeout.connect(self._status_label.clear)

        # Camera controls on the right side of the status bar - grouped in a container
        # so spacing is controlled internally rather than relying on addPermanentWidget gaps
        cam_group = QWidget()
        cam_layout = QHBoxLayout(cam_group)
        cam_layout.setContentsMargins(0, 0, 6, 0)
        cam_layout.setSpacing(6)

        cam_label = QLabel("Camera")
        cam_label.setObjectName("toolbar-label")
        cam_layout.addWidget(cam_label)

        self._camera_name_label = QLabel("-")
        self._camera_name_label.setObjectName("camera-name-label")
        cam_layout.addWidget(self._camera_name_label)

        self._btn_cam_toggle = QPushButton()
        self._btn_cam_toggle.setIcon(self._icon_camera(active=False))
        self._btn_cam_toggle.setIconSize(QSize(14, 14))
        self._btn_cam_toggle.setFixedSize(26, 26)
        self._btn_cam_toggle.setObjectName("status-btn")
        self._btn_cam_toggle.setToolTip("Connect camera")
        self._btn_cam_toggle.clicked.connect(self._toggle_camera_connection)
        cam_layout.addWidget(self._btn_cam_toggle)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setObjectName("status-btn")
        self._btn_refresh.clicked.connect(self._refresh_cameras)
        cam_layout.addWidget(self._btn_refresh)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("status-vsep")
        cam_layout.addWidget(sep)

        self._btn_calibrate = QPushButton("Set Tracking Color...")
        self._btn_calibrate.setObjectName("status-btn")
        self._btn_calibrate.setEnabled(False)
        self._btn_calibrate.clicked.connect(self._open_calibration)
        cam_layout.addWidget(self._btn_calibrate)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_step: int = 0
        self._btn_calibrate.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._btn_calibrate.installEventFilter(self)

        status_bar.addPermanentWidget(cam_group)

    def _connect_paint_signals(self) -> None:
        self._paint_widget.tool_color_changed.connect(self._on_virtual_color_changed)
        self._paint_widget.tool_size_changed.connect(self._on_virtual_size_changed)
        self._paint_widget.tool_eraser_changed.connect(self._on_virtual_eraser_changed)
        self._paint_widget.tool_cleared.connect(self._on_virtual_cleared)
        self._paint_widget.camera_active_changed.connect(self._btn_calibrate.setEnabled)
        self._paint_widget.camera_active_changed.connect(self._on_camera_active_changed)
        self._paint_widget.canvas_close_requested.connect(lambda: self._close_tab("canvas"))
        self._paint_widget.camera_close_requested.connect(lambda: self._close_tab("camera"))

    # --- Toolbar helpers ---

    def _exec_color_dialog(self, initial: QColor = QColor()) -> QColor:
        """Open QColorDialog with enough width for HSV/RGB spinboxes to be readable."""
        dlg = QColorDialog(initial, self)
        dlg.setMinimumWidth(540)
        return dlg.currentColor() if dlg.exec() else QColor()

    @staticmethod
    def _make_hsep() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("panel-separator")
        return line

    def _make_color_button(self, name: str, bgr: tuple[int, int, int]) -> QPushButton:
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setFixedSize(28, 28)
        btn.setToolTip(name.capitalize())
        self._apply_color_style(btn, bgr)
        btn.clicked.connect(lambda _, n=name: self._on_default_color_clicked(n))
        return btn

    @staticmethod
    def _apply_color_style(btn: QPushButton, bgr: tuple[int, int, int]) -> None:
        r, g, b = bgr[2], bgr[1], bgr[0]
        btn.setStyleSheet(
            f"QPushButton {{ background: rgb({r},{g},{b}); border-radius: 14px;"
            f" border: 2px solid transparent; }}"
            f"QPushButton:checked {{ border: 2px solid white; }}"
            f"QPushButton:hover {{ border: 2px solid rgba(255,255,255,0.5); }}"
        )

    @staticmethod
    def _icon_eraser() -> QIcon:
        px = QPixmap(18, 18)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        # Pink body
        p.setBrush(QColor(220, 120, 120))
        p.drawRoundedRect(1, 6, 11, 8, 2, 2)
        # Darker end cap
        p.setBrush(QColor(150, 70, 70))
        p.drawRoundedRect(11, 6, 6, 8, 2, 2)
        # Separator line between body and cap
        pen = QPen(QColor(255, 255, 255, 120))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(11, 7, 11, 13)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_trash() -> QIcon:
        px = QPixmap(18, 18)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(160, 160, 160))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Handle
        p.drawLine(7, 1, 11, 1)
        p.drawLine(7, 1, 7, 3)
        p.drawLine(11, 1, 11, 3)
        # Lid
        p.drawLine(2, 4, 16, 4)
        # Body
        p.drawRect(3, 5, 12, 11)
        # Vertical dividers
        p.drawLine(7, 7, 7, 14)
        p.drawLine(11, 7, 11, 14)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_color_swatch(bgr: tuple[int, int, int]) -> QIcon:
        r, g, b = bgr[2], bgr[1], bgr[0]
        px = QPixmap(16, 16)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(r, g, b))
        p.drawEllipse(2, 2, 12, 12)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_brush_dot_menu(radius: int) -> QIcon:
        px = QPixmap(16, 16)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(160, 160, 160))
        p.drawEllipse(8 - radius, 8 - radius, radius * 2, radius * 2)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_brush_dot(radius: int) -> QIcon:
        def _px(color: QColor) -> QPixmap:
            px = QPixmap(18, 18)
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(9 - radius, 9 - radius, radius * 2, radius * 2)
            p.end()
            return px

        icon = QIcon()
        icon.addPixmap(_px(QColor(100, 100, 100)), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(_px(QColor(138, 180, 255)), QIcon.Mode.Normal, QIcon.State.On)
        return icon

    @staticmethod
    def _icon_camera(active: bool) -> QIcon:
        px = QPixmap(16, 16)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(160, 160, 160) if active else QColor(75, 75, 75)
        pen = QPen(col)
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Body
        p.drawRoundedRect(0, 5, 16, 9, 2, 2)
        # Viewfinder bump on top
        p.drawRoundedRect(5, 2, 5, 4, 1, 1)
        # Lens ring
        p.drawEllipse(5, 7, 6, 6)
        if not active:
            slash_pen = QPen(QColor(200, 60, 60))
            slash_pen.setWidthF(1.8)
            slash_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(slash_pen)
            p.drawLine(2, 14, 14, 2)
        p.end()
        return QIcon(px)

    @staticmethod
    def _icon_reset_colors() -> QIcon:
        px = QPixmap(18, 18)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(110, 110, 110))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawArc(3, 3, 12, 12, 0, -270 * 16)
        p.drawLine(9, 3, 6, 1)
        p.drawLine(9, 3, 6, 5)
        p.end()
        return QIcon(px)

    # --- Tool selection ---

    def _on_default_color_clicked(self, name: str) -> None:
        btn = self._color_buttons[name]
        if self._active_color_name == name and not self._eraser_btn.isChecked():
            # Already active and not in eraser mode - re-click opens picker to change the color
            btn.setChecked(True)
            current = self._color_values[name]
            b, g, r = current
            qcolor = self._exec_color_dialog(QColor(r, g, b))
            if not qcolor.isValid():
                return
            bgr = (qcolor.blue(), qcolor.green(), qcolor.red())
            self._color_values[name] = bgr
            self._apply_color_style(btn, bgr)
            self._select_color(name, bgr)
            self._paint_widget.update_virtual_toolbar_colors(self._color_values)
            self._update_select_menu_colors()
        else:
            self._select_color(name, self._color_values[name])

    def _select_color(self, name: str, bgr: tuple[int, int, int]) -> None:
        for btn in self._color_buttons.values():
            btn.setChecked(False)
        if name in self._color_buttons:
            self._color_buttons[name].setChecked(True)
        self._eraser_btn.setChecked(False)
        self._active_color_name = name
        self._paint_widget.set_color(bgr)
        self._paint_widget.set_eraser_mode(False)
        self._apply_color_style(self._opt_color_swatch, bgr)
        self._options_stack.setCurrentIndex(0)
        self._save_app_config()

    def _select_size(self, name: str, thickness: int) -> None:
        self._active_size_name = name
        for btn in self._size_buttons.values():
            btn.setChecked(False)
        if name in self._size_buttons:
            self._size_buttons[name].setChecked(True)
        for n, btn in self._opt_brush_size_btns.items():
            btn.setChecked(n == name)
        for n, btn in self._opt_eraser_size_btns.items():
            btn.setChecked(n == name)
        self._paint_widget.set_brush_size(name, thickness)
        self._save_app_config()

    def _trigger_eraser_shortcut(self) -> None:
        new_state = not self._eraser_btn.isChecked()
        self._eraser_btn.setChecked(new_state)
        self._toggle_eraser(new_state)

    def _toggle_eraser(self, checked: bool) -> None:
        self._paint_widget.set_eraser_mode(checked)
        for btn in self._color_buttons.values():
            btn.setChecked(False)
        # Switch options bar page and sync size state
        self._options_stack.setCurrentIndex(1 if checked else 0)
        if checked:
            for n, btn in self._opt_eraser_size_btns.items():
                btn.setChecked(n == self._active_size_name)

    def _reset_colors(self) -> None:
        for name, bgr in DRAW_COLORS.items():
            if self._color_values.get(name) != bgr:
                self._color_values[name] = bgr
                self._apply_color_style(self._color_buttons[name], bgr)
        self._paint_widget.update_virtual_toolbar_colors(self._color_values)
        self._update_select_menu_colors()
        first_name = next(iter(DRAW_COLORS))
        self._select_color(first_name, self._color_values[first_name])
        self._select_size("small", BRUSH_SIZES["small"])

    def _update_select_menu_colors(self) -> None:
        for act, (name, _) in zip(self._select_color_acts, self._color_values.items()):
            act.setIcon(self._icon_color_swatch(self._color_values[name]))

    # --- Virtual toolbar signal handlers ---

    def _on_virtual_color_changed(self, bgr: tuple) -> None:
        for btn in self._color_buttons.values():
            btn.setChecked(False)
        matched_name = None
        for name, color in DRAW_COLORS.items():
            if color == bgr:
                self._color_buttons[name].setChecked(True)
                matched_name = name
                break
        self._eraser_btn.setChecked(False)
        self._active_color_name = matched_name or self._active_color_name
        self._apply_color_style(self._opt_color_swatch, bgr)
        self._options_stack.setCurrentIndex(0)

    def _on_virtual_size_changed(self, size_name: str) -> None:
        self._active_size_name = size_name
        for btn in self._size_buttons.values():
            btn.setChecked(False)
        if size_name in self._size_buttons:
            self._size_buttons[size_name].setChecked(True)
        for n, btn in self._opt_brush_size_btns.items():
            btn.setChecked(n == size_name)
        for n, btn in self._opt_eraser_size_btns.items():
            btn.setChecked(n == size_name)

    def _on_virtual_eraser_changed(self, enabled: bool) -> None:
        self._eraser_btn.setChecked(enabled)
        for btn in self._color_buttons.values():
            btn.setChecked(False)
        self._options_stack.setCurrentIndex(1 if enabled else 0)

    def _on_virtual_cleared(self) -> None:
        self._show_message("Canvas cleared")

    # --- Status bar helpers ---

    def _start_spinner(self, message: str) -> None:
        self._msg_clear_timer.stop()
        self._spinner_msg = message
        self._spinner_idx = 0
        self._tick_spinner()
        self._spinner_timer.start()

    def _tick_spinner(self) -> None:
        frame = _SPINNER_FRAMES[self._spinner_idx % len(_SPINNER_FRAMES)]
        self._status_label.setText(f"{frame}  {self._spinner_msg}")
        self._spinner_idx += 1

    def _show_message(self, text: str, timeout_ms: int = 2500) -> None:
        self._spinner_timer.stop()
        self._status_label.setText(text)
        if timeout_ms > 0:
            self._msg_clear_timer.start(timeout_ms)

    def _clear_status(self) -> None:
        self._spinner_timer.stop()
        self._msg_clear_timer.stop()
        self._status_label.clear()

    # --- Camera ---

    def _refresh_cameras(self, initial: bool = False) -> None:
        self._btn_refresh.setEnabled(False)
        self._paint_widget.stop_camera()
        msg = "Finding cameras..." if initial else "Refreshing..."
        self._paint_widget.show_camera_placeholder(msg)
        self._start_spinner(msg)
        self._list_worker = _CameraListWorker()
        self._list_worker.finished.connect(self._on_cameras_listed)
        self._list_worker.start()

    def _on_cameras_listed(self, cameras: list) -> None:
        self._available_cameras = cameras
        self._btn_refresh.setEnabled(True)
        if cameras:
            self._current_camera_index, first_label = cameras[0]
            self._camera_name_label.setText(first_label)
            self._start_spinner("Connecting...")
            self._paint_widget.start_camera(self._current_camera_index)
        else:
            self._current_camera_index = None
            self._camera_name_label.setText("-")
            self._clear_status()
            self._paint_widget.show_no_camera_placeholder()

    def _toggle_camera_connection(self) -> None:
        if self._camera_active:
            self._paint_widget.stop_camera()
            self._paint_widget.show_camera_placeholder(
                "Camera disconnected\n\nClick the camera icon to reconnect."
            )
        elif self._current_camera_index is not None:
            self._start_spinner("Connecting...")
            self._paint_widget.start_camera(self._current_camera_index)

    def _on_camera_active_changed(self, active: bool) -> None:
        self._camera_active = active
        self._btn_cam_toggle.setIcon(self._icon_camera(active=active))
        self._btn_cam_toggle.setToolTip(
            "Disconnect camera" if active else "Connect camera"
        )
        if active:
            if not self._tracking_color_configured():
                self._show_message(
                    "No tracking color set - click 'Set Tracking Color...' to begin drawing.",
                    timeout_ms=0,
                )
                self._start_btn_pulse()
            else:
                self._clear_status()
        else:
            self._stop_btn_pulse()

    # --- Calibration ---

    def _open_calibration(self) -> None:
        from src.ui.paint_widget import _MSG_CALIBRATING
        camera_index = self._current_camera_index or 0
        self._paint_widget.stop_camera()
        self._paint_widget.show_camera_placeholder(_MSG_CALIBRATING)
        self._clear_status()
        dialog = CalibrationDialog(camera_index, self._available_cameras, self)
        dialog.saved.connect(self._on_calibration_saved)
        dialog.exec()
        selected = dialog.selected_camera_index
        if selected != self._current_camera_index:
            self._current_camera_index = selected
            for idx, name in self._available_cameras:
                if idx == selected:
                    self._camera_name_label.setText(name)
                    break
        self._start_spinner("Connecting...")
        self._paint_widget.start_camera(selected)

    def _on_calibration_saved(self, hsv_min: np.ndarray, hsv_max: np.ndarray) -> None:
        self._paint_widget.set_tracker(ColorTracker(hsv_min, hsv_max))
        self._stop_btn_pulse()
        self._show_message("Tracking color saved", timeout_ms=2500)

    def _start_btn_pulse(self) -> None:
        self._pulse_step = 0
        self._pulse_timer.start()

    def _stop_btn_pulse(self) -> None:
        self._pulse_timer.stop()
        self._btn_calibrate.setStyleSheet("")

    def _tick_pulse(self) -> None:
        self._pulse_step += 1
        alpha = int(50 + (1 + math.sin(self._pulse_step * 0.15)) * 85)
        self._btn_calibrate.setStyleSheet(
            f"QPushButton#status-btn {{ border: 1px solid rgba(220,180,0,{alpha}); }}"
        )

    def _tracking_color_configured(self) -> bool:
        if not Path(HSV_CONFIG_PATH).exists():
            return False
        try:
            with open(HSV_CONFIG_PATH) as f:
                data = json.load(f)
            return data.get("min") != [0, 0, 0] or data.get("max") != [179, 255, 255]
        except Exception:
            return False

    def _load_tracker(self) -> None:
        if Path(HSV_CONFIG_PATH).exists():
            try:
                self._paint_widget.set_tracker(ColorTracker.load(HSV_CONFIG_PATH))
            except Exception:
                pass

    # --- Save ---

    def _save_canvas(self) -> None:
        default_name = datetime.now().strftime("VirtualPaint_%Y-%m-%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Drawing", default_name, "Images (*.png *.jpg)"
        )
        if path:
            self._paint_widget.save_canvas(path)
            self._show_message(f"Saved - {Path(path).name}", timeout_ms=3000)

    # --- Canvas background ---

    def _pick_canvas_bg(self) -> None:
        b, g, r = self._canvas_bg_bgr
        qcolor = self._exec_color_dialog(QColor(r, g, b))
        if not qcolor.isValid():
            return
        bgr = (qcolor.blue(), qcolor.green(), qcolor.red())
        self._canvas_bg_bgr = bgr
        self._paint_widget.set_canvas_bg(bgr)
        self._update_canvas_bg_btn(bgr)
        self._save_app_config()

    def _update_canvas_bg_btn(self, bgr: tuple[int, int, int]) -> None:
        b, g, r = bgr
        self._canvas_bg_btn.setStyleSheet(
            f"QPushButton#canvas-bg-btn {{"
            f" background: rgb({r},{g},{b});"
            f" border: 2px solid #555; border-radius: 5px; }}"
            f"QPushButton#canvas-bg-btn:hover {{ border-color: #999; }}"
        )

    def _load_canvas_config(self) -> None:
        if not Path(CANVAS_CONFIG_PATH).exists():
            return
        try:
            with open(CANVAS_CONFIG_PATH) as f:
                data = json.load(f)
            if "bg_color" in data:
                r, g, b = data["bg_color"]
                bgr = (b, g, r)
                self._canvas_bg_bgr = bgr
                self._paint_widget.set_canvas_bg(bgr)
                self._update_canvas_bg_btn(bgr)
            for name, rgb in data.get("colors", {}).items():
                r, g, b = rgb
                bgr = (b, g, r)
                if name in DRAW_COLORS:
                    self._color_values[name] = bgr
                    self._apply_color_style(self._color_buttons[name], bgr)
            self._paint_widget.update_virtual_toolbar_colors(self._color_values)
            self._update_select_menu_colors()
            active_color = data.get("active_color")
            if active_color and active_color in self._color_values:
                self._select_color(active_color, self._color_values[active_color])
            elif self._active_color_name in self._color_values:
                self._select_color(self._active_color_name, self._color_values[self._active_color_name])
            active_size = data.get("active_size")
            if active_size and active_size in BRUSH_SIZES:
                self._select_size(active_size, BRUSH_SIZES[active_size])
            if "space_pause" in data:
                self._act_space_pause.setChecked(data["space_pause"])
            if "show_detection_rect" in data:
                checked = data["show_detection_rect"]
                self._act_det_rect.setChecked(checked)
                self._paint_widget.set_show_detection_rect(checked)
        except Exception:
            pass

    def _save_app_config(self) -> None:
        if self._initializing:
            return
        modified: dict[str, list[int]] = {}
        for name, bgr in self._color_values.items():
            if name in DRAW_COLORS and DRAW_COLORS[name] != bgr:
                b, g, r = bgr
                modified[name] = [r, g, b]
        b, g, r = self._canvas_bg_bgr
        Path(CANVAS_CONFIG_PATH).parent.mkdir(exist_ok=True)
        with open(CANVAS_CONFIG_PATH, "w") as f:
            json.dump({
                "bg_color": [r, g, b],
                "colors": modified,
                "active_color": self._active_color_name,
                "active_size": self._active_size_name,
                "space_pause": self._act_space_pause.isChecked(),
                "show_detection_rect": self._act_det_rect.isChecked(),
            }, f)

    # --- Menu bar ---

    def _build_menu_bar(self) -> None:
        icon = self._make_app_icon()
        self.setWindowIcon(icon)
        self._title_bar = _TitleBar(self, icon)
        self.setMenuWidget(self._title_bar)

        mb = self._title_bar.menu_bar

        file_menu = mb.addMenu("File")
        act_save = file_menu.addAction("Save")
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._save_canvas)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("Exit")
        act_exit.triggered.connect(self.close)

        edit_menu = mb.addMenu("Edit")
        act_undo = edit_menu.addAction("Undo")
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.triggered.connect(self._undo)
        act_redo = edit_menu.addAction("Redo")
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.triggered.connect(self._redo)
        edit_menu.addSeparator()
        act_clear = edit_menu.addAction("Clear Canvas")
        act_clear.setShortcut(QKeySequence("C, C"))
        act_clear.triggered.connect(self._paint_widget.clear_canvas)
        edit_menu.addSeparator()
        self._act_space_pause = edit_menu.addAction("Hold Space to Pause Drawing")
        self._act_space_pause.setCheckable(True)
        self._act_space_pause.setChecked(True)
        self._act_space_pause.triggered.connect(self._on_space_pause_toggled)
        self._act_det_rect = edit_menu.addAction("Show Detection Rectangle")
        self._act_det_rect.setCheckable(True)
        self._act_det_rect.setChecked(True)
        self._act_det_rect.triggered.connect(self._on_det_rect_toggled)

        select_menu = mb.addMenu("Select")

        for i, (name, bgr) in enumerate(DRAW_COLORS.items(), 1):
            act = select_menu.addAction(self._icon_color_swatch(bgr), f"Color {i}")
            act.setShortcut(QKeySequence(str(i)))
            act.triggered.connect(
                lambda _, n=name: self._select_color(n, self._color_values[n])
            )
            self._select_color_acts.append(act)

        select_menu.addSeparator()

        _menu_dot_radii = {"small": 3, "medium": 5, "large": 8}
        _size_keys = {"small": "J", "medium": "K", "large": "L"}
        for name, thickness in BRUSH_SIZES.items():
            act = select_menu.addAction(
                self._icon_brush_dot_menu(_menu_dot_radii[name]), name.capitalize()
            )
            act.setShortcut(QKeySequence(_size_keys[name]))
            act.triggered.connect(lambda _, n=name, t=thickness: self._select_size(n, t))

        select_menu.addSeparator()

        act_eraser_sel = select_menu.addAction(self._icon_eraser(), "Eraser")
        act_eraser_sel.setShortcut(QKeySequence("E"))
        act_eraser_sel.triggered.connect(self._trigger_eraser_shortcut)

        view_menu = mb.addMenu("View")
        self._act_camera = view_menu.addAction("Camera")
        self._act_camera.setCheckable(True)
        self._act_camera.setChecked(True)
        self._act_camera.triggered.connect(
            lambda checked: self._open_tab("camera") if checked else self._close_tab("camera")
        )
        self._act_canvas = view_menu.addAction("Canvas")
        self._act_canvas.setCheckable(True)
        self._act_canvas.setChecked(True)
        self._act_canvas.triggered.connect(
            lambda checked: self._open_tab("canvas") if checked else self._close_tab("canvas")
        )
        help_menu = mb.addMenu("Help")
        act_about = help_menu.addAction("About")
        act_about.triggered.connect(self._show_about)

    @staticmethod
    def _make_app_icon() -> QIcon:
        px = QPixmap(48, 48)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Background
        p.setBrush(QColor(30, 45, 74))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, 44, 44, 10, 10)
        # Accent border
        pen = QPen(QColor(58, 90, 153))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(2, 2, 44, 44, 10, 10)
        # "VP" text
        p.setPen(QColor(138, 180, 255))
        font = p.font()
        font.setPixelSize(20)
        font.setBold(True)
        p.setFont(font)
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "VP")
        p.end()
        return QIcon(px)

    def nativeEvent(self, event_type: bytes, message) -> tuple[bool, int]:
        if event_type == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes.wintypes import MSG
                msg = MSG.from_address(int(message))

                if msg.message == 0x00A3:  # WM_NCLBUTTONDBLCLK
                    if msg.wParam == 2 and hasattr(self, "_title_bar"):  # HTCAPTION
                        self._title_bar._toggle_maximize()
                        return True, 0

                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                    y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value

                    # HTCAPTION on empty title bar area - enables native drag
                    if hasattr(self, "_title_bar"):
                        tb = self._title_bar
                        tb_local = tb.mapFromGlobal(QPoint(x, y))
                        if tb.rect().contains(tb_local) and tb.childAt(tb_local) is None:
                            return True, 2  # HTCAPTION

                    rx, ry, rw, rh = self.x(), self.y(), self.width(), self.height()
                    b = 5  # resize border width in pixels
                    on_left = x < rx + b
                    on_right = x > rx + rw - b
                    on_top = y < ry + b
                    on_bottom = y > ry + rh - b
                    if on_top and on_left:
                        return True, 13  # HTTOPLEFT
                    if on_top and on_right:
                        return True, 14  # HTTOPRIGHT
                    if on_bottom and on_left:
                        return True, 16  # HTBOTTOMLEFT
                    if on_bottom and on_right:
                        return True, 17  # HTBOTTOMRIGHT
                    if on_left:
                        return True, 10  # HTLEFT
                    if on_right:
                        return True, 11  # HTRIGHT
                    if on_top:
                        return True, 12  # HTTOP
                    if on_bottom:
                        return True, 15  # HTBOTTOM

            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Virtual Paint",
            "Virtual Paint\n\n"
            "A webcam-based virtual painting application.\n"
            "Draw using a colored tracking object in front of your camera.\n\n"
            "https://github.com/myoluk/virtual-paint",
        )

    # --- Undo / Redo ---

    def _undo(self) -> None:
        self._paint_widget.undo()
        self._show_message("Undo", timeout_ms=1500)

    def _redo(self) -> None:
        self._paint_widget.redo()
        self._show_message("Redo", timeout_ms=1500)

    # --- Style ---

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #1a1a1a; }

            /* Custom title bar */
            QWidget#title-bar {
                background: #222;
                border-bottom: 2px solid #1a1a1a;
            }

            /* Embedded menu bar - items styled as modern rounded buttons */
            QWidget#title-bar QMenuBar {
                background: transparent;
                border: none;
                padding: 0 4px;
                font-size: 12px;
                spacing: 3px;
            }
            QWidget#title-bar QMenuBar::item {
                background: transparent;
                color: #aaa;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 2px 10px;
                margin: 2px 2px;
            }
            QWidget#title-bar QMenuBar::item:selected {
                background: #2e2e2e;
                color: #eee;
                border-color: #3a3a3a;
            }
            QWidget#title-bar QMenuBar::item:pressed {
                background: #1e2d4a;
                color: #8ab4ff;
                border-color: #3a5a99;
            }

            /* Dropdown menus */
            QMenu {
                background: #1e1e1e;
                color: #ccc;
                border: 1px solid #333;
                padding: 4px 0 4px 8px;
                font-size: 12px;
            }
            QMenu::item { padding: 5px 32px 5px 14px; }
            QMenu::item:selected { background: #1e2d4a; color: #eee; }
            QMenu::item:disabled { color: #555; }
            QMenu::separator { background: #2e2e2e; height: 1px; margin: 3px 8px; }
            QMenu::shortcut { color: #555; }

            /* Window control buttons */
            QPushButton#wc-min, QPushButton#wc-max {
                background: transparent;
                color: #666;
                border: none;
                border-radius: 0;
                padding: 0;
                font-size: 14px;
            }
            QPushButton#wc-min:hover, QPushButton#wc-max:hover {
                background: #2e2e2e;
                color: #eee;
            }
            QPushButton#wc-min:pressed, QPushButton#wc-max:pressed {
                background: #252525;
                color: #ccc;
            }
            QPushButton#wc-close {
                background: transparent;
                color: #666;
                border: none;
                border-radius: 0;
                padding: 0;
                font-size: 14px;
                font-family: -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
            }
            QPushButton#wc-close:hover { background: #c42b1c; color: #fff; }
            QPushButton#wc-close:pressed { background: #a82315; color: #fff; }

            /* Panel headers (canvas / camera) */
            QWidget#panel-header {
                background: #1e1e1e;
                border-bottom: 1px solid #2a2a2a;
            }

            QLabel#panel-header-label {
                color: #888;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }

            QPushButton#panel-close-btn {
                background: transparent;
                color: #4a4a4a;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
            }
            QPushButton#panel-close-btn:hover {
                background: #c42b1c;
                color: #fff;
            }

            /* Status bar */
            QStatusBar {
                background: #1a1a1a;
                border-top: 1px solid #222;
                color: #555;
                font-size: 11px;
                min-height: 28px;
                padding: 0 6px;
            }
            QStatusBar QLabel#status-msg { color: #666; font-size: 11px; }
            QStatusBar QLabel#toolbar-label { color: #555; font-size: 11px; padding: 0 4px; }
            QLabel#camera-name-label {
                color: #777;
                font-size: 11px;
                padding: 0 4px;
                min-width: 80px;
                max-width: 160px;
            }
            QPushButton#status-btn {
                background: transparent;
                color: #666;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
            }
            QPushButton#status-btn:hover { background: #252525; color: #bbb; border-color: #333; }
            QPushButton#status-btn:disabled { color: #3a3a3a; }
            QFrame#status-vsep { color: #2e2e2e; max-height: 14px; margin: 0 4px; }

            QToolBar#options-bar {
                background: #1e1e1e;
                border: none;
                border-bottom: 1px solid #252525;
                padding: 3px 10px;
                spacing: 0;
            }

            QLabel#options-tool-label {
                color: #bbb;
                font-size: 12px;
                font-weight: bold;
                padding: 0 4px;
                min-width: 42px;
            }

            QFrame#options-vsep {
                color: #333;
                max-width: 1px;
                margin: 5px 4px;
            }

            QPushButton#opt-size-btn {
                background: #252525;
                color: #777;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 0;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#opt-size-btn:hover {
                background: #333;
                border-color: #484848;
                color: #ccc;
            }
            QPushButton#opt-size-btn:checked {
                background: #1e2d4a;
                border-color: #3a5a99;
                color: #8ab4ff;
            }

            QPushButton#opt-color-swatch {
                border: 2px solid transparent;
                border-radius: 5px;
                padding: 0;
            }
            QPushButton#opt-color-swatch:hover {
                border-color: rgba(255, 255, 255, 0.4);
            }

            QToolBar#left-toolbar {
                background: #222;
                border: none;
                border-right: 1px solid #222;
                padding: 0;
                spacing: 0;
            }

            QToolBar::separator {
                background: #2a2a2a;
                width: 1px;
                height: 1px;
                margin: 4px 6px;
            }

            QLabel#toolbar-label {
                color: #555;
                font-size: 11px;
                padding: 0 4px;
            }

            QPushButton {
                background: #222;
                color: #ccc;
                border: 1px solid #2e2e2e;
                border-radius: 5px;
                padding: 5px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background: #2e2e2e; border-color: #3a3a3a; color: #eee; }
            QPushButton:checked { background: #1e2d4a; border: 1px solid #3a5a99; color: #8ab4ff; }
            QPushButton:pressed { background: #181818; }

            /* Generic icon tool buttons (Clear) */
            QPushButton#tool-icon-btn {
                background: #252525;
                color: #888;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0;
            }
            QPushButton#tool-icon-btn:hover {
                background: #333;
                border-color: #484848;
                color: #ccc;
            }
            QPushButton#tool-icon-btn:pressed { background: #1a1a1a; }

            /* Eraser */
            QPushButton#eraser-btn {
                background: #252525;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0;
            }
            QPushButton#eraser-btn:hover { background: #333; border-color: #484848; }
            QPushButton#eraser-btn:checked { background: #1e3020; border-color: #3a7a45; }

            /* Size dot buttons */
            QPushButton#size-small, QPushButton#size-medium, QPushButton#size-large {
                background: #252525;
                border: 1px solid transparent;
                border-radius: 14px;
                padding: 0;
            }
            QPushButton#size-small:hover,
            QPushButton#size-medium:hover,
            QPushButton#size-large:hover {
                background: #333;
                border-color: #484848;
            }
            QPushButton#size-small:checked,
            QPushButton#size-medium:checked,
            QPushButton#size-large:checked {
                background: #1e2d4a;
                border-color: #3a5a99;
            }

            /* Canvas background button */
            QPushButton#canvas-bg-btn {
                background: #000;
                border: 2px solid #444;
                border-radius: 5px;
                padding: 0;
            }

            /* Panel horizontal separator */
            QFrame#panel-separator {
                background: #2a2a2a;
                max-height: 1px;
                border: none;
            }

            /* Reset custom colors button */
            QPushButton#reset-colors-btn {
                background: transparent;
                color: #555;
                border: none;
                border-radius: 3px;
                padding: 0;
                font-size: 12px;
            }
            QPushButton#reset-colors-btn:hover { color: #aaa; background: #333; }

            QStatusBar {
                background: #111;
                color: #555;
                border-top: 1px solid #1e1e1e;
                font-size: 11px;
            }
            QStatusBar::item { border: none; }
            QLabel#status-msg {
                color: #777;
                font-size: 11px;
                padding-left: 4px;
            }
            QLabel { color: #999; }
        """)

    def _setup_windows_frame(self) -> None:
        """Restore the DWM drop shadow removed by FramelessWindowHint (Windows only)."""
        try:
            import ctypes

            hwnd = int(self.winId())

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            margins = _MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(margins)
            )
        except Exception:
            pass

    def createPopupMenu(self):
        # Suppress the default right-click menu that lists toolbars and dock widgets
        return None

    def _on_space_pause_toggled(self, checked: bool) -> None:
        if not checked:
            self._paint_widget.set_drawing_paused(False)
        self._save_app_config()

    def _on_det_rect_toggled(self, checked: bool) -> None:
        self._paint_widget.set_show_detection_rect(checked)
        self._save_app_config()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._btn_calibrate:
            if event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                self._stop_btn_pulse()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self._act_space_pause.isChecked():
                self._paint_widget.set_drawing_paused(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self._act_space_pause.isChecked():
                self._paint_widget.set_drawing_paused(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event) -> None:
        if hasattr(self, "_list_worker") and self._list_worker.isRunning():
            self._list_worker.finished.disconnect()
            self._list_worker.quit()
            self._list_worker.wait()
        self._paint_widget.stop_camera()
        super().closeEvent(event)
