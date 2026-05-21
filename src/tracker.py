import json
from pathlib import Path

import cv2
import numpy as np

from src.config import HSV_CONFIG_PATH, MIN_CONTOUR_AREA


class ColorTracker:
    def __init__(self, hsv_min: np.ndarray, hsv_max: np.ndarray) -> None:
        self._hsv_min = hsv_min
        self._hsv_max = hsv_max

    def detect(
        self, frame: np.ndarray
    ) -> tuple[tuple[int, int] | None, tuple[int, int, int, int] | None]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._hsv_min, self._hsv_max)
        mask = cv2.erode(mask, None, iterations=1)
        mask = cv2.dilate(mask, None, iterations=2)
        mask = cv2.medianBlur(mask, 13)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < MIN_CONTOUR_AREA:
            return None, None

        rect = cv2.boundingRect(largest)
        x, y, w, _ = rect
        tip = (x + w // 2, y)
        return tip, rect

    def update_range(self, hsv_min: np.ndarray, hsv_max: np.ndarray) -> None:
        self._hsv_min = hsv_min
        self._hsv_max = hsv_max

    def save(self, path: Path | str = HSV_CONFIG_PATH) -> None:
        data = {
            "min": self._hsv_min.tolist(),
            "max": self._hsv_max.tolist(),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path: Path | str = HSV_CONFIG_PATH) -> "ColorTracker":
        with open(path, "r") as f:
            data = json.load(f)
        return cls(
            hsv_min=np.array(data["min"], dtype=np.uint8),
            hsv_max=np.array(data["max"], dtype=np.uint8),
        )

    @classmethod
    def default(cls) -> "ColorTracker":
        return cls(
            hsv_min=np.array([0, 0, 0], dtype=np.uint8),
            hsv_max=np.array([179, 255, 255], dtype=np.uint8),
        )
