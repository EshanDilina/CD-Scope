"""
cd_scope.ui.chart_widgets
───────────────────────────
Factory functions that build pyqtgraph PlotWidget instances.
Each returns a configured widget ready to drop into any layout.
"""
from __future__ import annotations
import math, random
import numpy as np
from scipy import stats as scipy_stats
from PyQt5.QtCore import Qt
from PyQt5.QtGui  import QColor

import pyqtgraph as pg
from pyqtgraph import mkPen, mkBrush

from cd_scope.constants import (    BG_VOID, TEXT_DIM, TEXT_MID, CYAN, GREEN, AMBER, RED, PURPLE,
    TARGET_CD
)
from cd_scope.core.models import EdgeResult

# ── Shared setup ──────────────────────────────────────────────────────────────

def _pg_dark() -> None:
    pg.setConfigOption('background', BG_VOID)
    pg.setConfigOption('foreground', TEXT_MID)


def _base_plot(title: str = "", x_label: str = "", y_label: str = "") -> pg.PlotWidget:
    _pg_dark()
    pw = pg.PlotWidget()
    pw.setStyleSheet(f"background:{BG_VOID};border:none;")
    pw.showGrid(x=True, y=True, alpha=0.15)
    if title:
        pw.setTitle(title, color=TEXT_DIM, size="9pt")
    if x_label:
        pw.setLabel('bottom', x_label, color=TEXT_DIM)
    if y_label:
        pw.setLabel('left',   y_label, color=TEXT_DIM)
    return pw


# ── Chart factories ────────────────────────────────────────────────────────────

def make_profile_widget(r: EdgeResult | None) -> pg.PlotWidget:
    """Intensity profile with edge overlays and CD annotation."""
    pw = _base_plot("INTENSITY PROFILE", "Position (nm)", "Intensity")

    if r and len(r.profile_x) > 0 and not r.error:
        pw.plot(r.profile_x, r.profile_y, pen=mkPen(CYAN, width=1.5))

        mn, mx = r.profile_y.min(), r.profile_y.max()
        th = mn + (mx - mn) * 0.5
        pw.plot([r.profile_x[0], r.profile_x[-1]], [th, th],
                pen=mkPen(AMBER, width=1, style=Qt.DashLine))

        for (xpx, etype) in r.edge_overlay:
            if etype in ('left', 'right'):
                ln = pg.InfiniteLine(pos=xpx * r.nm_per_px, angle=90,
                                     pen=mkPen(CYAN, width=1, style=Qt.DashLine))
                pw.addItem(ln)

        if r.cd_mean > 0 and r.edge_overlay and len(r.edge_overlay) >= 2:
            lnm = r.edge_overlay[0][0] * r.nm_per_px
            rnm = r.edge_overlay[1][0] * r.nm_per_px
            t = pg.TextItem(f"CD={r.cd_mean:.2f} nm", color=GREEN, anchor=(0.5, 1))
            t.setPos((lnm + rnm) / 2, mn + (mx - mn) * 0.55)
            pw.addItem(t)
    else:
        _demo_profile(pw)
    return pw


def _demo_profile(pw: pg.PlotWidget) -> None:
    """Fill plot with a synthetic demo when no real data is available."""
    N = 500; pitch = N / 5.0; npp = 0.49
    prof = []
    for i in range(N):
        xm = i % pitch; d = abs(xm - pitch / 2); hl = pitch * 0.5
        v = (200 + 40 * (1 - math.exp(-(hl-d)**2/18))
             if d < hl else 25 + 15 * math.exp(-(d-hl)**2/12))
        prof.append(v + random.gauss(0, 8))
    xs = np.arange(N) * npp
    pw.plot(xs, np.array(prof), pen=mkPen(CYAN, width=1.5))
    mn2, mx2 = min(prof), max(prof)
    pw.plot([xs[0], xs[-1]], [(mn2+mx2)/2]*2,
            pen=mkPen(AMBER, width=1, style=Qt.DashLine))


def make_spc_widget(sites: list) -> pg.PlotWidget:
    """SPC control chart with UCL/LCL/USL/LSL/TGT lines."""
    pw = _base_plot("SPC — CD Control Chart", "Site #", "CD (nm)")
    if not sites:
        return pw

    vals = [s.cd_mean for s in sites if s.cd_mean > 0]
    if not vals:
        return pw

    xs = np.arange(1, len(vals) + 1, dtype=float)
    pw.plot(xs, vals, pen=mkPen(CYAN, width=1.2))

    pass_pts = [(x, v) for x, v in zip(xs, vals) if 30 <= v <= 34]
    fail_pts = [(x, v) for x, v in zip(xs, vals) if not (30 <= v <= 34)]
    if pass_pts:
        px_, py_ = zip(*pass_pts)
        pw.plot(list(px_), list(py_), pen=None, symbol='o', symbolSize=5,
                symbolBrush=mkBrush(CYAN), symbolPen=None)
    if fail_pts:
        px_, py_ = zip(*fail_pts)
        pw.plot(list(px_), list(py_), pen=None, symbol='o', symbolSize=6,
                symbolBrush=mkBrush(RED), symbolPen=None)

    mu = np.mean(vals)
    sg = np.std(vals, ddof=1) if len(vals) > 1 else 0
    for yv, col, lbl, sty in [
        (34,          RED,      'USL', Qt.DashLine),
        (30,          RED,      'LSL', Qt.DashLine),
        (mu + 3*sg,   AMBER,    'UCL', Qt.DashLine),
        (mu - 3*sg,   AMBER,    'LCL', Qt.DashLine),
        (TARGET_CD,   CYAN,     'TGT', Qt.SolidLine),
    ]:
        pw.plot([xs[0], xs[-1]], [yv, yv], pen=mkPen(col, width=1, style=sty))
        t = pg.TextItem(lbl, color=col, anchor=(0, 0.5))
        t.setPos(xs[-1] + 0.3, yv)
        pw.addItem(t)
    return pw


def make_histogram_widget(sites: list) -> pg.PlotWidget:
    """CD histogram with normal-distribution overlay and spec lines."""
    pw = _base_plot("CD Histogram", "CD (nm)", "Count")
    if not sites:
        return pw

    vals = np.array([s.cd_mean for s in sites if s.cd_mean > 0])
    if len(vals) < 2:
        return pw

    y, x = np.histogram(vals, bins=min(20, len(vals)),
                         range=(vals.min()-1, vals.max()+1))
    bw = x[1] - x[0]
    for i in range(len(y)):
        c = (x[i] + x[i+1]) / 2
        col = CYAN if 30 <= c <= 34 else RED
        bg  = QColor(col); bg.setAlpha(110)
        pw.addItem(pg.BarGraphItem(x=[c], height=[y[i]], width=bw*0.88,
                                   brush=mkBrush(bg), pen=mkPen(col, width=1)))

    mu, sg = np.mean(vals), np.std(vals, ddof=1)
    xs2 = np.linspace(vals.min()-1, vals.max()+1, 200)
    ys2 = scipy_stats.norm.pdf(xs2, mu, sg) * len(vals) * bw if sg > 0 else xs2*0
    pw.plot(xs2, ys2, pen=mkPen(GREEN, width=2))

    for xv, col in [(30, RED), (34, RED), (TARGET_CD, AMBER)]:
        pw.plot([xv, xv], [0, y.max() * 1.1],
                pen=mkPen(col, width=1, style=Qt.DashLine))

    t = pg.TextItem(f"μ={mu:.2f}  σ={sg:.2f}", color=CYAN, anchor=(1, 0))
    t.setPos(vals.max(), y.max() * 1.05)
    pw.addItem(t)
    return pw


def make_lwr_widget(sites: list) -> pg.PlotWidget:
    """LWR distribution histogram with 4 nm spec line."""
    pw = _base_plot("LWR Distribution", "LWR 3σ (nm)", "Count")
    if not sites:
        return pw

    vals = np.array([s.lwr for s in sites if s.lwr > 0])
    if len(vals) < 2:
        return pw

    y, x = np.histogram(vals, bins=min(16, len(vals)))
    bw = x[1] - x[0]
    for i in range(len(y)):
        c = (x[i] + x[i+1]) / 2
        col = GREEN if c <= 4 else RED
        bg  = QColor(col); bg.setAlpha(110)
        pw.addItem(pg.BarGraphItem(x=[c], height=[y[i]], width=bw*0.88,
                                   brush=mkBrush(bg), pen=mkPen(col, width=1)))
    pw.plot([4.0, 4.0], [0, y.max()*1.1],
            pen=mkPen(RED, width=1.5, style=Qt.DashLine))
    return pw


def make_psd_widget(r: EdgeResult | None) -> pg.PlotWidget:
    """LWR power spectral density with Hurst exponent annotation."""
    pw = _base_plot("LWR Power Spectral Density",
                    "Spatial Freq. (µm⁻¹)", "PSD (nm²·µm)")
    pw.setLogMode(x=True, y=False)

    if r and len(r.psd_freq) > 2 and not r.error:
        nz   = r.psd_freq > 0
        freq = r.psd_freq[nz]
        psd  = r.psd_power[nz]
        fill = pg.FillBetweenItem(
            pg.PlotDataItem(freq, psd, pen=None),
            pg.PlotDataItem(freq, np.zeros_like(psd), pen=None),
            brush=pg.mkBrush(QColor(PURPLE).darker(300)))
        pw.addItem(fill)
        pw.plot(freq, psd, pen=mkPen(PURPLE, width=2))
        if r.hurst > 0:
            hf = np.array([freq[0], freq[-1]])
            hp = psd[0] * (hf / hf[0]) ** (-2*r.hurst - 1)
            pw.plot(hf, np.abs(hp), pen=mkPen(AMBER, width=1, style=Qt.DashLine))
            t = pg.TextItem(f"H={r.hurst:.2f}", color=AMBER, anchor=(0, 1))
            t.setPos(hf[0], np.abs(hp[0]))
            pw.addItem(t)
    else:
        freqs = np.linspace(0.5, 40, 100)
        psd   = 0.15 * np.power(1 + (freqs/3)**2, -2.3)
        psd   = np.abs(psd * (1 + np.random.randn(100)*0.1))
        pw.plot(freqs, psd, pen=mkPen(PURPLE, width=2))
    return pw
