import cv2
import numpy as np
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QSizePolicy,
)

from src.camera import Camera
from src.config import HSV_CONFIG_PATH
from src.tracker import ColorTracker

_SAMPLE_RADIUS = 15
_DEFAULT_TOLERANCE = 20


class _CameraWorker(QThread):
    frame_ready = Signal(np.ndarray)

    def __init__(self, camera_index: int) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._running = False

    def run(self) -> None:
        camera = Camera(self._camera_index)
        camera.open()
        self._running = True
        while self._running:
            frame = camera.read()
            if frame is not None:
                self.frame_ready.emit(frame)
        camera.close()

    def stop(self) -> None:
        self._running = False
        self.wait()


class _ClickableLabel(QLabel):
    clicked = Signal(int, int)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.position().x(), event.position().y())
        super().mousePressEvent(event)


class CalibrationDialog(QDialog):
    saved = Signal(np.ndarray, np.ndarray)

    def __init__(
        self,
        camera_index: int,
        cameras: list[tuple[int, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._camera_index = camera_index
        self._cameras = cameras
        self._hsv_min = np.array([0, 0, 0], dtype=np.uint8)
        self._hsv_max = np.array([179, 255, 255], dtype=np.uint8)
        self._last_frame: np.ndarray | None = None
        self._click_point: tuple[int, int] | None = None
        self._sampled = False

        self.setWindowTitle("Color Calibration")
        self.setMinimumWidth(900)
        self._build_ui()
        self._apply_style()
        self._load_saved_hsv()

        self._worker = _CameraWorker(camera_index)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.start()

    @property
    def selected_camera_index(self) -> int:
        return self._camera_index

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Camera selector
        cam_row = QHBoxLayout()
        cam_lbl = QLabel("Camera:")
        cam_lbl.setFixedWidth(80)
        self._cam_selector = QComboBox()
        for idx, name in self._cameras:
            self._cam_selector.addItem(name, idx)
        for i, (idx, _) in enumerate(self._cameras):
            if idx == self._camera_index:
                self._cam_selector.setCurrentIndex(i)
                break
        self._cam_selector.currentIndexChanged.connect(self._on_camera_selector_changed)
        cam_row.addWidget(cam_lbl)
        cam_row.addWidget(self._cam_selector)
        cam_row.addStretch()
        root.addLayout(cam_row)

        # Instruction label
        self._instruction = QLabel("Click on your tracking object in the camera feed to calibrate.")
        self._instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._instruction.setObjectName("instruction")
        root.addWidget(self._instruction)

        # Preview row: camera (large, clickable) + mask (smaller)
        preview_row = QHBoxLayout()
        preview_row.setSpacing(8)

        # Camera feed - clickable
        camera_panel = QVBoxLayout()
        camera_title = QLabel("Camera - Click to sample color")
        camera_title.setObjectName("panel-title")
        self._label_camera = _ClickableLabel()
        self._label_camera.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_camera.setMinimumSize(540, 360)
        self._label_camera.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._label_camera.setObjectName("camera-label")
        self._label_camera.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self._label_camera.clicked.connect(self._on_camera_clicked)
        camera_panel.addWidget(camera_title)
        camera_panel.addWidget(self._label_camera)

        # Mask feed
        mask_panel = QVBoxLayout()
        mask_title = QLabel("Detection Preview")
        mask_title.setObjectName("panel-title")
        self._label_mask = QLabel()
        self._label_mask.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_mask.setMinimumSize(280, 360)
        self._label_mask.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._label_mask.setObjectName("mask-label")
        mask_panel.addWidget(mask_title)
        mask_panel.addWidget(self._label_mask)

        preview_row.addLayout(camera_panel, 2)
        preview_row.addLayout(mask_panel, 1)
        root.addLayout(preview_row, 1)  # stretch=1 so preview shrinks before other rows

        # Tolerance slider
        tolerance_row = QHBoxLayout()
        tolerance_label = QLabel("Tolerance:")
        tolerance_label.setFixedWidth(80)
        self._tolerance_slider = QSlider(Qt.Orientation.Horizontal)
        self._tolerance_slider.setRange(1, 60)
        self._tolerance_slider.setValue(_DEFAULT_TOLERANCE)
        self._tolerance_slider.setEnabled(False)
        self._tolerance_slider.valueChanged.connect(self._on_tolerance_changed)
        self._tolerance_value_label = QLabel(str(_DEFAULT_TOLERANCE))
        self._tolerance_value_label.setFixedWidth(28)
        self._tolerance_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        tolerance_row.addWidget(tolerance_label)
        tolerance_row.addWidget(self._tolerance_slider)
        tolerance_row.addWidget(self._tolerance_value_label)
        root.addLayout(tolerance_row)

        # Advanced toggle
        self._btn_advanced = QPushButton("Advanced ›")
        self._btn_advanced.setCheckable(True)
        self._btn_advanced.setObjectName("advanced-btn")
        self._btn_advanced.clicked.connect(self._toggle_advanced)
        root.addWidget(self._btn_advanced)

        # Advanced HSV sliders (hidden by default)
        self._advanced_widget = QWidget()
        self._advanced_widget.setObjectName("advanced-panel")
        adv_layout = QVBoxLayout(self._advanced_widget)
        adv_layout.setSpacing(6)
        adv_layout.setContentsMargins(8, 8, 8, 8)

        # Column headers
        header_row = QHBoxLayout()
        header_row.addSpacing(20)
        header_row.addWidget(self._adv_header("Min"), 1)
        header_row.addSpacing(40)
        header_row.addWidget(self._adv_header("Max"), 1)
        header_row.addSpacing(36)
        adv_layout.addLayout(header_row)

        self._sliders: dict[str, QSlider] = {}
        self._slider_labels: dict[str, QLabel] = {}

        # (channel, range_max, default_min, default_max, groove_property)
        channel_defs = [
            ("H", 179, 0, 179, "hue"),
            ("S", 255, 0, 255, "sat"),
            ("V", 255, 0, 255, "val"),
        ]
        for ch, hi, default_min, default_max, groove in channel_defs:
            row = QHBoxLayout()
            row.setSpacing(6)

            ch_lbl = QLabel(ch)
            ch_lbl.setFixedWidth(16)
            ch_lbl.setObjectName("adv-ch-label")

            min_key = f"Min {ch}"
            max_key = f"Max {ch}"

            min_slider = QSlider(Qt.Orientation.Horizontal)
            min_slider.setRange(0, hi)
            min_slider.setValue(default_min)
            min_slider.setProperty("groove", groove)
            min_slider.valueChanged.connect(self._on_advanced_slider_changed)
            self._sliders[min_key] = min_slider

            min_lbl = QLabel(str(default_min))
            min_lbl.setFixedWidth(32)
            min_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            min_lbl.setObjectName("adv-val")
            self._slider_labels[min_key] = min_lbl

            max_slider = QSlider(Qt.Orientation.Horizontal)
            max_slider.setRange(0, hi)
            max_slider.setValue(default_max)
            max_slider.setProperty("groove", groove)
            max_slider.valueChanged.connect(self._on_advanced_slider_changed)
            self._sliders[max_key] = max_slider

            max_lbl = QLabel(str(default_max))
            max_lbl.setFixedWidth(32)
            max_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            max_lbl.setObjectName("adv-val")
            self._slider_labels[max_key] = max_lbl

            row.addWidget(ch_lbl)
            row.addWidget(min_slider, 1)
            row.addWidget(min_lbl)
            row.addSpacing(8)
            row.addWidget(max_slider, 1)
            row.addWidget(max_lbl)
            adv_layout.addLayout(row)

        self._advanced_widget.setVisible(False)
        root.addWidget(self._advanced_widget)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_reset = QPushButton("Reset")
        self._btn_reset.setEnabled(False)
        self._btn_reset.clicked.connect(self._on_reset)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("btn-save")
        btn_cancel = QPushButton("Cancel")
        btn_save.clicked.connect(self._on_save)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    @staticmethod
    def _adv_header(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("adv-header")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _load_saved_hsv(self) -> None:
        if not Path(HSV_CONFIG_PATH).exists():
            return
        try:
            tracker = ColorTracker.load(HSV_CONFIG_PATH)
            self._hsv_min = tracker._hsv_min.copy()
            self._hsv_max = tracker._hsv_max.copy()
            self._sampled = True
            self._tolerance_slider.setEnabled(True)
            self._btn_reset.setEnabled(True)
            self._instruction.setText("Last saved values loaded. Click to re-sample, or adjust sliders and save.")
            self._sync_advanced_sliders()
        except Exception:
            pass

    def _on_camera_selector_changed(self) -> None:
        new_index = self._cam_selector.currentData()
        if new_index == self._camera_index:
            return
        self._camera_index = new_index
        self._click_point = None
        self._worker.stop()
        self._worker = _CameraWorker(new_index)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.start()

    def _on_camera_clicked(self, label_x: int, label_y: int) -> None:
        if self._last_frame is None:
            return
        fx, fy = self._label_to_frame_coords(self._label_camera, label_x, label_y)
        self._click_point = (fx, fy)
        self._sample_color(fx, fy, self._tolerance_slider.value())
        self._tolerance_slider.setEnabled(True)
        self._btn_reset.setEnabled(True)
        self._sampled = True
        self._instruction.setText("Adjust tolerance if needed, then click Save.")
        self._sync_advanced_sliders()

    def _label_to_frame_coords(self, label: QLabel, lx: int, ly: int) -> tuple[int, int]:
        if self._last_frame is None:
            return 0, 0
        fh, fw = self._last_frame.shape[:2]
        lw, lh = label.width(), label.height()
        scale = min(lw / fw, lh / fh)
        displayed_w = int(fw * scale)
        displayed_h = int(fh * scale)
        offset_x = (lw - displayed_w) // 2
        offset_y = (lh - displayed_h) // 2
        fx = int((lx - offset_x) * fw / displayed_w)
        fy = int((ly - offset_y) * fh / displayed_h)
        return max(0, min(fw - 1, fx)), max(0, min(fh - 1, fy))

    def _sample_color(self, fx: int, fy: int, tolerance: int) -> None:
        if self._last_frame is None:
            return
        fh, fw = self._last_frame.shape[:2]
        r = _SAMPLE_RADIUS
        x1, y1 = max(0, fx - r), max(0, fy - r)
        x2, y2 = min(fw, fx + r), min(fh, fy + r)
        region = self._last_frame[y1:y2, x1:x2]
        hsv_region = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)

        mean_h = float(np.mean(hsv_region[:, :, 0]))
        mean_s = float(np.mean(hsv_region[:, :, 1]))
        mean_v = float(np.mean(hsv_region[:, :, 2]))

        self._hsv_min = np.array([
            max(0, int(mean_h - tolerance)),
            max(0, int(mean_s - tolerance * 2)),
            max(0, int(mean_v - tolerance * 2)),
        ], dtype=np.uint8)
        self._hsv_max = np.array([
            min(179, int(mean_h + tolerance)),
            min(255, int(mean_s + tolerance * 2)),
            255,
        ], dtype=np.uint8)

    def _on_tolerance_changed(self, value: int) -> None:
        self._tolerance_value_label.setText(str(value))
        if self._click_point is not None:
            self._sample_color(self._click_point[0], self._click_point[1], value)
            self._sync_advanced_sliders()

    def _on_advanced_slider_changed(self) -> None:
        self._sampled = True
        for key, slider in self._sliders.items():
            self._slider_labels[key].setText(str(slider.value()))
        self._hsv_min = np.array([
            self._sliders["Min H"].value(),
            self._sliders["Min S"].value(),
            self._sliders["Min V"].value(),
        ], dtype=np.uint8)
        self._hsv_max = np.array([
            self._sliders["Max H"].value(),
            self._sliders["Max S"].value(),
            self._sliders["Max V"].value(),
        ], dtype=np.uint8)

    def _sync_advanced_sliders(self) -> None:
        for slider in self._sliders.values():
            slider.blockSignals(True)
        values = {
            "Min H": int(self._hsv_min[0]),
            "Min S": int(self._hsv_min[1]),
            "Min V": int(self._hsv_min[2]),
            "Max H": int(self._hsv_max[0]),
            "Max S": int(self._hsv_max[1]),
            "Max V": int(self._hsv_max[2]),
        }
        for key, val in values.items():
            self._sliders[key].setValue(val)
            self._slider_labels[key].setText(str(val))
        for slider in self._sliders.values():
            slider.blockSignals(False)

    def _toggle_advanced(self, checked: bool) -> None:
        self._advanced_widget.setVisible(checked)
        self._btn_advanced.setText("Advanced v" if checked else "Advanced ›")
        self.adjustSize()

    def _on_reset(self) -> None:
        self._click_point = None
        self._sampled = True
        self._hsv_min = np.array([0, 0, 0], dtype=np.uint8)
        self._hsv_max = np.array([179, 255, 255], dtype=np.uint8)
        self._tolerance_slider.setValue(_DEFAULT_TOLERANCE)
        self._tolerance_slider.setEnabled(False)
        self._btn_reset.setEnabled(False)
        self._instruction.setText("Click on your tracking object in the camera feed to calibrate.")
        self._sync_advanced_sliders()

    def _on_frame(self, frame: np.ndarray) -> None:
        self._last_frame = frame.copy()

        # Draw sample circle overlay if user has clicked
        display_frame = frame.copy()
        if self._click_point is not None:
            cv2.circle(display_frame, self._click_point, _SAMPLE_RADIUS, (0, 255, 0), 2)
            cv2.circle(display_frame, self._click_point, 2, (0, 255, 0), -1)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._hsv_min, self._hsv_max)
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        self._label_camera.setPixmap(self._to_pixmap(self._label_camera, display_frame))
        self._label_mask.setPixmap(self._to_pixmap(self._label_mask, mask_bgr))

    def _to_pixmap(self, label: QLabel, frame: np.ndarray) -> QPixmap:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(image).scaled(
            label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _on_save(self) -> None:
        if not self._sampled:
            QMessageBox.warning(
                self, "No Color Sampled",
                "Click on your tracking object in the camera feed before saving."
            )
            return
        tracker = ColorTracker(self._hsv_min, self._hsv_max)
        try:
            tracker.save(HSV_CONFIG_PATH)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return
        self.saved.emit(self._hsv_min.copy(), self._hsv_max.copy())
        self.accept()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #121212; }
            QLabel { color: #ccc; }
            QComboBox {
                background: #252525;
                color: #ccc;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
                min-width: 180px;
            }
            QComboBox:hover { border-color: #555; }
            QComboBox QAbstractItemView {
                background: #1e1e1e;
                color: #ccc;
                selection-background-color: #2a5298;
            }
            QLabel#instruction {
                color: #aaa;
                font-size: 12px;
                padding: 6px;
                background: #1e1e1e;
                border-radius: 4px;
            }
            QLabel#panel-title {
                color: #e0e0e0;
                font-weight: bold;
                font-size: 12px;
            }
            QLabel#camera-label, QLabel#mask-label {
                background: #1a1a1a;
                border-radius: 4px;
                border: 1px solid #2a2a2a;
            }
            QLabel#camera-label:hover { border: 1px solid #555; }
            QPushButton {
                background: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 5px 14px;
            }
            QPushButton:hover { background: #3a3a3a; }
            QPushButton:disabled { color: #555; border-color: #2a2a2a; }
            QPushButton#btn-save {
                background: #2a5298;
                border-color: #3a6bc8;
            }
            QPushButton#btn-save:hover { background: #3a6bc8; }
            QPushButton#advanced-btn {
                background: transparent;
                border: none;
                color: #888;
                text-align: left;
                padding: 2px 0;
            }
            QPushButton#advanced-btn:hover { color: #bbb; }
            /* Tolerance slider */
            QSlider::groove:horizontal {
                height: 4px;
                background: #3a3a3a;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -5px 0;
                background: #e0e0e0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:disabled { background: #555; }

            /* Advanced panel container */
            QWidget#advanced-panel {
                background: #181818;
                border: 1px solid #2a2a2a;
                border-radius: 5px;
            }
            QLabel#adv-header {
                color: #555;
                font-size: 10px;
                letter-spacing: 1px;
            }
            QLabel#adv-ch-label {
                color: #999;
                font-weight: bold;
                font-size: 12px;
            }
            QLabel#adv-val {
                color: #aaa;
                font-size: 11px;
                font-family: Consolas, monospace;
            }

            /* Hue slider - full spectrum groove */
            QSlider[groove="hue"]::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0.00 #ff0000,
                    stop:0.17 #ffff00,
                    stop:0.33 #00ff00,
                    stop:0.50 #00ffff,
                    stop:0.67 #0000ff,
                    stop:0.83 #ff00ff,
                    stop:1.00 #ff0000);
            }
            /* Saturation slider - gray to vivid */
            QSlider[groove="sat"]::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #444444,
                    stop:1 #cc44ff);
            }
            /* Value slider - dark to light */
            QSlider[groove="val"]::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #111111,
                    stop:1 #ffffff);
            }
            /* Handle for colored grooves - dark core, bright border */
            QSlider[groove="hue"]::handle:horizontal,
            QSlider[groove="sat"]::handle:horizontal,
            QSlider[groove="val"]::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -4px 0;
                background: #1e1e1e;
                border: 2px solid #dddddd;
                border-radius: 7px;
            }
        """)

    def closeEvent(self, event) -> None:
        self._worker.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        self._worker.stop()
        super().reject()
