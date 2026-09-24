"""Render the canonical Winsper waveform at real Windows icon sizes."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import sys

import numpy as np
from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "voicepilot" / "assets" / "winsper-icon.png"
OUTPUT = ROOT / "artifacts" / "icon-qa"
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def _largest_visible_component(source: Image.Image) -> Image.Image:
    """Extract the original connected W stroke without tracing or distortion."""
    rgba = np.asarray(source.convert("RGBA"))
    visible = rgba[:, :, 3] > 0
    height, width = visible.shape
    visited = np.zeros_like(visible, dtype=bool)
    largest: list[tuple[int, int]] = []

    for y in range(height):
        for x in range(width):
            if not visible[y, x] or visited[y, x]:
                continue
            component: list[tuple[int, int]] = []
            pending = deque([(x, y)])
            visited[y, x] = True
            while pending:
                current_x, current_y = pending.popleft()
                component.append((current_x, current_y))
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if (
                        0 <= next_x < width
                        and 0 <= next_y < height
                        and visible[next_y, next_x]
                        and not visited[next_y, next_x]
                    ):
                        visited[next_y, next_x] = True
                        pending.append((next_x, next_y))
            if len(component) > len(largest):
                largest = component

    if not largest:
        raise RuntimeError(f"No visible mark found in {SOURCE}")

    component_mask = np.zeros_like(visible, dtype=bool)
    for x, y in largest:
        component_mask[y, x] = True
    isolated = rgba.copy()
    isolated[~component_mask] = 0
    x_values = [point[0] for point in largest]
    y_values = [point[1] for point in largest]
    return Image.fromarray(isolated, "RGBA").crop(
        (min(x_values), min(y_values), max(x_values) + 1, max(y_values) + 1)
    )


def _resampling():
    return getattr(Image, "Resampling", Image).LANCZOS


def render_icon(mark: Image.Image, size: int) -> QImage:
    """Fit the unchanged canonical W generously inside a transparent square."""
    extent = max(1, int(round(size * 0.94)))
    scale = min(extent / mark.width, extent / mark.height)
    fitted_size = (
        max(1, int(round(mark.width * scale))),
        max(1, int(round(mark.height * scale))),
    )
    fitted = mark.resize(fitted_size, _resampling())
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        fitted,
        ((size - fitted_size[0]) // 2, (size - fitted_size[1]) // 2),
    )
    return QPixmap.fromImage(ImageQt(canvas)).toImage()


def render_contact_sheet(images: dict[int, QImage]) -> QImage:
    sheet = QImage(960, 440, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#f4f7fb"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(0, 0, 960, 220, QColor("#202226"))
    painter.setFont(QFont("Segoe UI", 10))

    sizes = (16, 20, 24, 32, 48, 64)
    centers = (115, 250, 385, 520, 655, 790)
    for row, background_y in enumerate((0, 220)):
        painter.setPen(QColor("#ffffff") if row == 0 else QColor("#172033"))
        icon_center_y = background_y + 100
        label_y = background_y + 155
        for size, center_x in zip(sizes, centers, strict=True):
            painter.drawImage(
                center_x - size // 2,
                icon_center_y - size // 2,
                images[size],
            )
            label = f"{size} px"
            label_width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(center_x - label_width // 2, label_y, label)

    painter.end()
    return sheet


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mark = _largest_visible_component(Image.open(SOURCE))
    images = {size: render_icon(mark, size) for size in SIZES}
    for size, image in images.items():
        image.save(str(OUTPUT / f"winsper-canonical-app-icon-{size}.png"))
    render_contact_sheet(images).save(
        str(OUTPUT / "winsper-canonical-app-icon-contact-sheet.png")
    )
    app.quit()


if __name__ == "__main__":
    main()
