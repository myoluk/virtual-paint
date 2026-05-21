import subprocess
import sys

import cv2
import numpy as np


class Camera:
    def __init__(self, index: int = 0) -> None:
        self._index = index
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> bool:
        # DirectShow fails cleanly when another application holds the camera,
        # unlike MSMF which silently returns black frames.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self._capture = cv2.VideoCapture(self._index, backend)
        return self._capture.isOpened()

    def close(self) -> None:
        if self._capture and self._capture.isOpened():
            self._capture.release()
        self._capture = None

    def read(self) -> np.ndarray | None:
        if not self._capture or not self._capture.isOpened():
            return None
        ret, frame = self._capture.read()
        if not ret:
            return None
        return cv2.flip(frame, 1)

    def set_resolution(self, width: int, height: int) -> None:
        if self._capture:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    @property
    def index(self) -> int:
        return self._index

    @staticmethod
    def list_available() -> list[tuple[int, str]]:
        names = Camera._query_device_names()
        available = []
        name_index = 0
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        for i in range(5):
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ret, _ = cap.read()
            cap.release()
            if not ret:
                continue
            label = names[name_index] if name_index < len(names) else f"Camera {i}"
            available.append((i, label))
            name_index += 1
        return available

    @staticmethod
    def _query_device_names() -> list[str]:
        if sys.platform != "win32":
            return []
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-PnpDevice -Class Camera -Status OK"
                    " | Sort-Object InstanceId"
                    " | Select-Object -ExpandProperty FriendlyName",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            return []
