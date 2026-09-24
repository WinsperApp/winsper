from __future__ import annotations

import sys
from pathlib import Path

from .brand import APP_USER_MODEL_ID

_ASSETS = Path(__file__).parent / "assets"
_ICON_PNG = _ASSETS / "winsper-icon.png"
_APP_ICON_PNG = _ASSETS / "winsper-app-icon.png"
_LOGO_PNG = _ASSETS / "winsper-logo.png"



def set_windows_app_user_model_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def logo_pixmap(QPixmap, size: int):
    return _png_pixmap(QPixmap, _ICON_PNG, size, size)


def app_icon_pixmap(QPixmap, size: int):
    """Return the canonical square W mark used by Windows icon surfaces."""
    try:
        from PIL.ImageQt import ImageQt

        return QPixmap.fromImage(ImageQt(create_app_icon_image(size)))
    except Exception:
        pixmap = QPixmap(size, size)
        pixmap.fill(0x00000000)
        return pixmap


def qt_window_icon(QIcon, QPixmap):
    """Build a DPI-safe, multi-resolution Windows icon from the brand W."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        pixmap = app_icon_pixmap(QPixmap, size)
        if not pixmap.isNull():
            icon.addPixmap(pixmap)
    return icon


def logo_with_text_pixmap(QPixmap, width: int, text_color: str | None = None):
    """Render the original wordmark with exact theme-aware text coloring."""
    try:
        return _png_wordmark_pixmap(QPixmap, width, text_color)
    except Exception:
        return logo_pixmap(QPixmap, 32)


def _png_wordmark_pixmap(QPixmap, width: int, text_color: str | None = None):
    from PIL import Image as PILImage
    from PIL.ImageQt import ImageQt

    img = _crop_transparent_padding(PILImage.open(_LOGO_PNG).convert("RGBA"))
    if text_color:
        from PIL import ImageColor
        import numpy as np

        pixels = np.array(img)
        # Wordmark asset contains a clear gap between waveform and text.
        alpha_columns = (pixels[:, :, 3] > 10).any(axis=0)
        visible_columns = np.flatnonzero(alpha_columns)
        gaps = np.diff(visible_columns)
        split = int(visible_columns[int(gaps.argmax()) + 1]) if gaps.size else int(pixels.shape[1] * 0.4)
        text_pixels = pixels[:, split:, :]
        visible = text_pixels[:, :, 3] > 0
        text_pixels[visible, :3] = ImageColor.getrgb(text_color)
        img = PILImage.fromarray(pixels, "RGBA")
    image_width, image_height = img.size
    new_height = int(image_height * width / image_width) if image_width else width
    img = img.resize((width, new_height), _resampling(PILImage))
    return QPixmap.fromImage(ImageQt(img))


def _crop_transparent_padding(img):
    """Crop fully transparent border rows and columns from a PIL RGBA image."""
    try:
        import numpy as np

        pixels = np.array(img)
        mask = pixels[:, :, 3] > 10
        rows = mask.any(axis=1)
        columns = mask.any(axis=0)
        if not rows.any() or not columns.any():
            return img
        row_min = int(rows.argmax())
        row_max = int(len(rows) - rows[::-1].argmax())
        column_min = int(columns.argmax())
        column_max = int(len(columns) - columns[::-1].argmax())
        return img.crop((column_min, row_min, column_max, row_max))
    except Exception:
        return img


def _crop_and_pad_to_square(img):
    """Crop transparent borders and center the result on a square canvas."""
    try:
        from PIL import Image as PILImage

        cropped = _crop_transparent_padding(img)
        width, height = cropped.size
        if width == height:
            return cropped
        side = max(width, height)
        square = PILImage.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(cropped, ((side - width) // 2, (side - height) // 2))
        return square
    except Exception:
        return img


def _fit_on_square(img, size: int, *, fill: float = 0.88):
    """Fit an image inside a transparent square without clipping its edges."""
    from PIL import Image as PILImage

    cropped = _crop_transparent_padding(img)
    width, height = cropped.size
    if width <= 0 or height <= 0:
        return PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    extent = max(1, int(round(size * max(0.5, min(1.0, fill)))))
    scale = min(extent / width, extent / height)
    fitted_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    fitted = cropped.resize(fitted_size, _resampling(PILImage))
    canvas = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        fitted,
        ((size - fitted_size[0]) // 2, (size - fitted_size[1]) // 2),
    )
    return canvas


def _png_pixmap(QPixmap, path: Path, width: int, height: int):
    """Load, crop, square, and scale a PNG into a QPixmap."""
    try:
        from PIL import Image as PILImage
        from PIL.ImageQt import ImageQt

        img = PILImage.open(path).convert("RGBA")
        img = _crop_and_pad_to_square(img)
        img = img.resize((width, height), _resampling(PILImage))
        return QPixmap.fromImage(ImageQt(img))
    except Exception:
        pixmap = QPixmap(width, height)
        pixmap.fill(0x00000000)
        return pixmap


def _resampling(image_module):
    try:
        return image_module.Resampling.LANCZOS
    except AttributeError:
        return image_module.LANCZOS


def create_logo_image(size: int = 256):
    """Return the complete icon fitted into a square canvas."""
    try:
        from PIL import Image

        img = Image.open(_ICON_PNG).convert("RGBA")
        img = _crop_and_pad_to_square(img)
        return img.resize((size, size), _resampling(Image))
    except Exception:
        return _fallback_image(size)


def create_app_icon_image(size: int = 256):
    """Return the undistorted canonical W app mark on transparent pixels."""
    try:
        from PIL import Image

        img = Image.open(_APP_ICON_PNG).convert("RGBA")
        return _fit_on_square(img, size, fill=0.90)
    except Exception:
        return _fallback_image(size)


def create_tray_icon_image(size: int = 64):
    """Return the canonical square W mark for the Windows notification area."""
    return create_app_icon_image(size)


def _fallback_image(size: int = 64):
    """Create a basic gradient fallback when packaged assets are unavailable."""
    from PIL import Image

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(size):
        interpolation = x / max(1, size - 1)
        red = int(139 * interpolation)
        green = int(200 + (63 - 200) * interpolation)
        for y in range(size):
            img.putpixel((x, y), (red, green, 255, 255))
    return img
