from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
HSV_CONFIG_PATH = BASE_DIR / "assets" / "hsv_config.json"
CANVAS_CONFIG_PATH = BASE_DIR / "assets" / "canvas_config.json"

# BGR color values
DRAW_COLORS: dict[str, tuple[int, int, int]] = {
    "color_1": (236, 56, 131),
    "color_2": (255, 134, 58),
    "color_3": (0, 255, 36),
    "color_4": (0, 0, 220),
    "color_5": (11, 190, 255),
}

BRUSH_SIZES: dict[str, int] = {
    "small": 3,
    "medium": 7,
    "large": 11,
}

MIN_CONTOUR_AREA = 1000
MAX_UNDO_STEPS = 50
