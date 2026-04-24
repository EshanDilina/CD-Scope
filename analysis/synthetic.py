"""
cd_scope.analysis.synthetic
─────────────────────────────
Synthetic SEM image generators used for demos and live-acquisition simulation.
Replace _grab_frame() in LiveAcquisitionThread with real camera calls in production.
"""
from __future__ import annotations
import math, random

import numpy as np
from PyQt5.QtGui import QImage, QPixmap

from cd_scope.core.models import SEMMeta

def gen_synthetic_sem(
    W: int = 512, H: int = 512,
    npp: float = 0.49,
    perturb: float = 0.0,
    false_color: bool = False,
    invert: bool = False,
    brightness: float = 0,
    contrast: float = 1.0,
) -> tuple:
    """
    Generate a synthetic line/space grating SEM image.

    Returns (QPixmap, np.ndarray uint8, SEMMeta)
    """
    img = np.zeros((H, W), dtype=np.float32)
    pitch    = W / 6.0
    half_line = pitch * 0.5
    lwr      = np.random.randn(H) * (2.5 + perturb * 3)
    xs       = np.arange(W, dtype=np.float32)

    for y in range(H):
        xmod = xs % pitch
        dist = np.abs(xmod - pitch / 2)
        hl   = half_line + lwr[y]
        sig  = 3.0
        v = np.where(
            dist < hl,
            200 + 40 * (1 - np.exp(-(hl - dist)**2 / (2*sig**2))),
            25  + 15 * np.exp(-np.maximum(dist - hl, 0)**2 / (2*sig**2)),
        )
        img[y] = v + np.random.randn(W).astype(np.float32) * 10

    img = np.clip(img * contrast + brightness, 0, 255).astype(np.uint8)
    if invert:
        img = 255 - img

    meta               = SEMMeta()
    meta.nm_per_px     = npp
    meta.pixel_width   = W
    meta.pixel_height  = H
    meta.mag           = 1e5
    meta.acc_voltage   = 800
    meta.working_dist  = 4.1
    meta.field_width_nm  = npp * W
    meta.field_height_nm = npp * H
    meta.source        = "synthetic"
    meta.instrument    = "CD_SCOPE Simulator"

    pix = _to_pixmap(img, false_color)
    return pix, img, meta


def gen_synthetic_contact(
    W: int = 512, H: int = 512,
    npp: float = 0.49,
    n_cols: int = 5,
    n_rows: int = 4,
    cd_nm: float = 40.0,
    pitch_nm: float = 80.0,
    perturb: float = 0.0,
    false_color: bool = False,
) -> tuple:
    """
    Generate a synthetic contact-hole array SEM image.

    Returns (QPixmap, np.ndarray uint8, SEMMeta)
    """
    img       = np.full((H, W), 200, dtype=np.float32)
    pitch_px  = pitch_nm / npp
    r_px      = cd_nm / 2 / npp

    x_start = (W - (n_cols - 1) * pitch_px) / 2
    y_start = (H - (n_rows - 1) * pitch_px) / 2

    for row in range(n_rows):
        for col in range(n_cols):
            cx = x_start + col * pitch_px + random.gauss(0, perturb / npp)
            cy = y_start + row * pitch_px + random.gauss(0, perturb / npp)
            r_x = r_px * (1 + random.gauss(0, 0.04))
            r_y = r_px * (1 + random.gauss(0, 0.04))
            x0  = max(0, int(cx - r_x * 2))
            x1  = min(W, int(cx + r_x * 2))
            y0  = max(0, int(cy - r_y * 2))
            y1  = min(H, int(cy + r_y * 2))
            for y in range(y0, y1):
                for x in range(x0, x1):
                    dx = (x - cx) / r_x
                    dy = (y - cy) / r_y
                    d  = math.sqrt(dx*dx + dy*dy)
                    if d < 1:
                        img[y, x] = 25 + 20*d + random.gauss(0, 8)
                    elif d < 1.4:
                        img[y, x] = 25 + (200-25)*(d-1)/0.4 + random.gauss(0, 8)

    img = np.clip(img + np.random.randn(H, W) * 8, 0, 255).astype(np.uint8)

    meta               = SEMMeta()
    meta.nm_per_px     = npp
    meta.pixel_width   = W
    meta.pixel_height  = H
    meta.source        = "synthetic_contact"
    meta.instrument    = "CD_SCOPE Simulator"
    meta.field_width_nm  = npp * W
    meta.field_height_nm = npp * H

    pix = _to_pixmap(img, false_color)
    return pix, img, meta


def _to_pixmap(img: np.ndarray, false_color: bool = False) -> "QPixmap":
    """Convert a grayscale uint8 ndarray to QPixmap."""
    H, W = img.shape
    if false_color:
        t = img.astype(np.float32) / 255.0
        r = np.clip(t * 2,           0, 1)
        g = np.clip(np.where(t > 0.5, 1 - (t-0.5)*2, t*2), 0, 1)
        b = np.clip(1 - t * 2,       0, 1)
        rgb = np.stack(
            [(r*255).astype(np.uint8),
             (g*255).astype(np.uint8),
             (b*255).astype(np.uint8)],
            axis=-1)
        qi = QImage(rgb.tobytes(), W, H, W*3, QImage.Format_RGB888)
    else:
        qi = QImage(img.tobytes(), W, H, W, QImage.Format_Grayscale8)
    return QPixmap.fromImage(qi)
