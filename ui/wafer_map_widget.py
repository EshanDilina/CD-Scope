"""
cd_scope.ui.wafer_map_widget
──────────────────────────────
WaferCDMapWidget  — interactive wafer CD uniformity map with colourmap + statistics
WaferMapPanel     — control strip + widget wrapper used in the bottom tab
"""
from __future__ import annotations
import math
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QCheckBox, QSizePolicy, QFileDialog, QMessageBox
)
from PyQt5.QtCore  import Qt, QPointF, QRect, pyqtSignal
from PyQt5.QtGui   import (
    QColor, QPainter, QPen, QBrush, QLinearGradient, QFont
)

import pyqtgraph as pg
from pyqtgraph import mkPen

from cd_scope.constants import (    BG_VOID, BG_DEEP, BG_CARD, BG_PANEL, BORDER, BORDER_BR,
    CYAN, GREEN, AMBER, RED, TEXT_BR, TEXT_MID, TEXT_DIM,
    TARGET_CD
)
from cd_scope.core.models import WaferSite
from cd_scope.core.wafer_parser import HitachiWaferParser

class WaferCDMapWidget(QWidget):
    """
    Interactive wafer-disk CD map.

    Colours each site dot by the selected metric using a configurable
    colourmap, draws a colourbar with spec markers, and shows a
    statistics overlay.  Click a site to emit site_selected.
    """

    site_selected = pyqtSignal(object)   # WaferSite

    COLORMAPS = ['RdYlGn', 'diverging', 'viridis', 'plasma']
    METRICS   = {
        'cd_mean': 'CD Mean (nm)',
        'cd_std':  'CD σ (nm)',
        'lwr':     'LWR 3σ (nm)',
        'pitch':   'Pitch (nm)',
        'space':   'Space (nm)',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self.sites:        list[WaferSite] = []
        self.selected_idx: int             = -1
        self.colormap:     str             = 'RdYlGn'
        self.show_values:  bool            = True
        self.show_grid:    bool            = False
        self.metric:       str             = 'cd_mean'
        self.wafer_diam_mm: float          = 300.0

        self._hover_idx:    int  = -1
        self._tooltip_text: str  = ""
        self._cb_rect:      QRect = QRect()

    # ── Public ─────────────────────────────────────────────────────────────────

    def set_sites(self, sites: list[WaferSite], metric: str = 'cd_mean') -> None:
        self.sites = sites
        self.metric = metric
        self.selected_idx = -1
        self.update()

    def set_metric(self, metric: str) -> None:
        self.metric = metric
        self.update()

    def set_colormap(self, name: str) -> None:
        self.colormap = name
        self.update()

    # ── Colourmap ──────────────────────────────────────────────────────────────

    def _color(self, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        cm = self.colormap
        if cm == 'RdYlGn':
            if t < 0.5:
                r, g, b = 1.0, t*2, 0.0
            else:
                r, g, b = 1.0-(t-0.5)*2, 1.0, 0.0
        elif cm == 'diverging':
            if t < 0.5:
                f = t * 2; r,g,b = f, f, 1.0
            else:
                f = (t-0.5)*2; r,g,b = 1.0, 1-f, 1-f
        elif cm == 'viridis':
            r,g,b = self._interp([(0,(0.26,0,0.33)),(0.5,(0.13,0.57,0.55)),
                                   (1,(0.99,0.91,0.14))], t)
            return QColor(int(r*255), int(g*255), int(b*255))
        elif cm == 'plasma':
            r,g,b = self._interp([(0,(0.05,0.03,0.53)),(0.5,(0.80,0.28,0.47)),
                                   (1,(0.94,0.98,0.13))], t)
            return QColor(int(r*255), int(g*255), int(b*255))
        else:
            v = t; r,g,b = v, v, v
        return QColor(int(r*255), int(g*255), int(b*255))

    @staticmethod
    def _interp(stops: list, t: float):
        for i in range(len(stops)-1):
            t0, c0 = stops[i]; t1, c1 = stops[i+1]
            if t0 <= t <= t1:
                f = (t-t0)/(t1-t0) if t1 > t0 else 0
                return (c0[0]+(c1[0]-c0[0])*f,
                        c0[1]+(c1[1]-c0[1])*f,
                        c0[2]+(c1[2]-c0[2])*f)
        return stops[-1][1]

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(BG_VOID))

        if not self.sites:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(QFont("Courier New", 10))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No wafer map loaded\nFile → Import Wafer Map…")
            return

        cb_w = 64; cb_m = 10
        wafer_w = W - cb_w - cb_m
        cx = wafer_w // 2; cy = H // 2
        r_wafer = min(wafer_w, H) // 2 - 20

        vals = [getattr(s, self.metric, 0) for s in self.sites
                if getattr(s, self.metric, 0) > 0]
        if not vals: return
        vmin, vmax = min(vals), max(vals)
        vrange = vmax - vmin or 1.0

        # Coordinate mapping
        xs = [s.x_mm for s in self.sites]; ys = [s.y_mm for s in self.sites]
        xspan = max(abs(min(xs)), abs(max(xs)))*2 or self.wafer_diam_mm
        yspan = max(abs(min(ys)), abs(max(ys)))*2 or self.wafer_diam_mm
        scale = r_wafer / (max(xspan, yspan)/2 + 1)
        dot_r = max(6, min(20, int(r_wafer/(math.sqrt(len(self.sites))+1))))

        # Wafer disk
        p.setPen(QPen(QColor(BORDER_BR), 1.5))
        p.setBrush(QBrush(QColor("#050810")))
        p.drawEllipse(QPointF(cx, cy), r_wafer, r_wafer)

        # Grid rings
        if self.show_grid:
            p.setPen(QPen(QColor(BORDER), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            for frac in (0.25, 0.5, 0.75):
                p.drawEllipse(QPointF(cx, cy), r_wafer*frac, r_wafer*frac)

        # Site dots
        for idx, s in enumerate(self.sites):
            sx = cx + s.x_mm * scale
            sy = cy - s.y_mm * scale
            v  = getattr(s, self.metric, 0)
            t  = (v - vmin) / vrange
            col = self._color(t)

            # Shadow
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 0, 0, 70)))
            p.drawEllipse(QPointF(sx+1, sy+2), dot_r, dot_r)

            # Fill
            bg = QColor(col); bg.setAlpha(220)
            p.setBrush(QBrush(bg))
            if idx == self.selected_idx:
                p.setPen(QPen(QColor(CYAN), 2))
            elif idx == self._hover_idx:
                p.setPen(QPen(QColor(TEXT_BR), 1.5))
            else:
                border = QColor(col).darker(150)
                p.setPen(QPen(border, 1))
            p.drawEllipse(QPointF(sx, sy), dot_r, dot_r)

            # Value label
            if self.show_values and dot_r >= 10:
                lum = 0.3*(col.redF()) + 0.59*(col.greenF()) + 0.11*(col.blueF())
                p.setPen(QColor(Qt.black if 0.3 < lum < 0.85 else Qt.white))
                p.setFont(QFont("Courier New", max(6, dot_r//2-1), QFont.Bold))
                lbl = f"{v:.1f}" if v < 100 else f"{v:.0f}"
                fm = p.fontMetrics(); tw = fm.horizontalAdvance(lbl)
                p.drawText(int(sx-tw//2), int(sy+fm.ascent()//2), lbl)

        # Wafer edge + notch
        p.setPen(QPen(QColor(BORDER_BR), 1.5)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_wafer, r_wafer)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(BORDER_BR)))
        p.drawEllipse(QPointF(cx, cy+r_wafer), 5, 5)

        # Stats overlay
        p.setFont(QFont("Courier New", 8))
        mu = np.mean(vals); sg = np.std(vals, ddof=1) if len(vals)>1 else 0
        cp = (34-30)/(6*sg) if sg>0 else 999
        cpu= (34-mu)/(3*sg)  if sg>0 else 999
        cpl= (mu-30)/(3*sg)  if sg>0 else 999
        cpk= min(cpu, cpl)
        for i, line in enumerate([
            f"N = {len(vals)}", f"Mean = {mu:.2f} nm", f"3σ   = {3*sg:.2f} nm",
            f"Min  = {min(vals):.2f} nm", f"Max  = {max(vals):.2f} nm",
            f"Range= {max(vals)-min(vals):.2f} nm",
            f"Cp   = {cp:.2f}", f"Cpk  = {cpk:.2f}",
        ]):
            c_lbl = (GREEN if ('Cp' in line and '=' in line and
                               (float(line.split('=')[1].strip()) >= 1.33))
                     else TEXT_DIM)
            p.setPen(QColor(c_lbl))
            p.fillRect(QRect(8, H-len(['']*8)*14-8+i*14, 152, 13), QColor(0,0,0,120))
            p.drawText(10, H-len(['']*8)*14-8+i*14+11, line)

        # Colorbar
        cb_x = W - cb_w; cb_y = 30; cb_h = H - 60
        self._cb_rect = QRect(cb_x, cb_y, 24, cb_h)
        grad = QLinearGradient(cb_x, cb_y+cb_h, cb_x, cb_y)
        for i in range(11):
            t = i / 10.0; grad.setColorAt(t, self._color(t))
        p.setPen(QPen(QColor(BORDER_BR), 1))
        p.setBrush(QBrush(grad))
        p.drawRect(self._cb_rect)
        p.setPen(QColor(TEXT_MID)); p.setFont(QFont("Courier New", 8))
        for i in range(6):
            t = i/5.0; v = vmin + (vmax-vmin)*t
            ypos = int(cb_y + cb_h*(1-t))
            p.drawLine(cb_x+24, ypos, cb_x+28, ypos)
            p.drawText(cb_x+30, ypos+4, f"{v:.1f}")
        # Spec markers
        for spec_v, col_s, lbl_s in [(30.0,RED,'LSL'),(34.0,RED,'USL'),(32.0,CYAN,'TGT')]:
            if vmin <= spec_v <= vmax:
                t = (spec_v-vmin)/vrange
                sy2 = int(cb_y + cb_h*(1-t))
                p.setPen(QPen(QColor(col_s), 1.5))
                p.drawLine(cb_x-4, sy2, cb_x+24, sy2)
                p.setPen(QColor(col_s))
                p.setFont(QFont("Courier New", 7, QFont.Bold))
                p.drawText(cb_x-26, sy2+4, lbl_s)

        # Hover tooltip
        if self._hover_idx >= 0 and self._tooltip_text:
            s = self.sites[self._hover_idx]
            sx = cx + s.x_mm*scale; sy2 = cy - s.y_mm*scale
            lines = self._tooltip_text.split('\n')
            p.setFont(QFont("Courier New", 8))
            tw = max(p.fontMetrics().horizontalAdvance(l) for l in lines)
            th = len(lines)*14 + 10
            tx = int(min(sx+dot_r+4, W-tw-10)); ty = int(max(sy2-th//2, 5))
            p.setPen(QPen(QColor(CYAN), 1))
            p.setBrush(QBrush(QColor(BG_CARD)))
            p.drawRect(tx, ty, tw+10, th)
            p.setPen(QColor(CYAN))
            for i, line in enumerate(lines):
                p.drawText(tx+5, ty+14+i*14, line)

    # ── Mouse ──────────────────────────────────────────────────────────────────

    def _hit_test(self, mx: int, my: int) -> int:
        if not self.sites: return -1
        W, H = self.width(), self.height()
        cb_w = 64; wafer_w = W - cb_w - 10
        cx = wafer_w//2; cy = H//2
        r_wafer = min(wafer_w, H)//2 - 20
        xs = [s.x_mm for s in self.sites]; ys = [s.y_mm for s in self.sites]
        xspan = max(abs(min(xs)), abs(max(xs)))*2 or self.wafer_diam_mm
        yspan = max(abs(min(ys)), abs(max(ys)))*2 or self.wafer_diam_mm
        scale = r_wafer / (max(xspan, yspan)/2+1)
        dot_r = max(6, min(20, int(r_wafer/(math.sqrt(len(self.sites))+1))))
        best = -1; best_d = dot_r + 4
        for i, s in enumerate(self.sites):
            sx = cx + s.x_mm*scale; sy2 = cy - s.y_mm*scale
            d = math.sqrt((mx-sx)**2 + (my-sy2)**2)
            if d < best_d: best = i; best_d = d
        return best

    def mouseMoveEvent(self, ev) -> None:
        idx = self._hit_test(ev.x(), ev.y())
        if idx != self._hover_idx:
            self._hover_idx = idx
            if idx >= 0:
                s = self.sites[idx]
                self._tooltip_text = (
                    f"Site: {s.site_id}\n"
                    f"X={s.x_mm:.1f}  Y={s.y_mm:.1f} mm\n"
                    f"CD={s.cd_mean:.2f} nm\n"
                    f"σ={s.cd_std:.2f}  LWR={s.lwr:.2f} nm\n"
                    f"Pitch={s.pitch:.2f} nm\n"
                    f"Status={s.status}"
                )
            else:
                self._tooltip_text = ""
            self.update()

    def mousePressEvent(self, ev) -> None:
        idx = self._hit_test(ev.x(), ev.y())
        if idx >= 0:
            self.selected_idx = idx
            self.site_selected.emit(self.sites[idx])
            self.update()


class WaferMapPanel(QWidget):
    """Wafer map widget with controls strip."""

    site_selected = pyqtSignal(object)

    _METRIC_MAP = {
        'CD Mean': 'cd_mean', 'CD σ': 'cd_std',
        'LWR': 'lwr', 'Pitch': 'pitch', 'Space': 'space',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Controls
        ctrl = QWidget(); ctrl.setFixedHeight(34)
        ctrl.setStyleSheet(f"background:{BG_DEEP};border-bottom:1px solid {BORDER};")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(8, 4, 8, 4); cl.setSpacing(8)
        cl.addWidget(QLabel("Metric:"))
        self._metric = QComboBox()
        self._metric.addItems(list(self._METRIC_MAP.keys()))
        self._metric.currentTextChanged.connect(
            lambda t: self._map.set_metric(self._METRIC_MAP.get(t, 'cd_mean')))
        cl.addWidget(self._metric)
        cl.addWidget(QLabel("Colormap:"))
        self._cmap = QComboBox()
        self._cmap.addItems(WaferCDMapWidget.COLORMAPS)
        self._cmap.currentTextChanged.connect(lambda t: self._map.set_colormap(t))
        cl.addWidget(self._cmap)
        self._show_vals = QCheckBox("Values"); self._show_vals.setChecked(True)
        self._show_vals.stateChanged.connect(
            lambda v: (setattr(self._map, 'show_values', bool(v)), self._map.update()))
        self._show_grid = QCheckBox("Rings"); self._show_grid.setChecked(False)
        self._show_grid.stateChanged.connect(
            lambda v: (setattr(self._map, 'show_grid', bool(v)), self._map.update()))
        cl.addWidget(self._show_vals); cl.addWidget(self._show_grid)
        cl.addStretch()
        btn_load = QPushButton("📂 Import…"); btn_load.setFixedHeight(24)
        btn_load.clicked.connect(self.import_wafer_map)
        btn_demo = QPushButton("🧪 Demo"); btn_demo.setFixedHeight(24)
        btn_demo.clicked.connect(self.load_demo)
        cl.addWidget(btn_load); cl.addWidget(btn_demo)
        lay.addWidget(ctrl)

        self._map = WaferCDMapWidget()
        self._map.site_selected.connect(self.site_selected)
        lay.addWidget(self._map)

    def set_sites(self, sites: list[WaferSite]) -> None:
        metric = self._METRIC_MAP.get(self._metric.currentText(), 'cd_mean')
        self._map.set_sites(sites, metric)

    def import_wafer_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Wafer Map", "",
            "Measurement Files (*.csv *.txt *.xml *.mdf *.map);;All Files (*)")
        if not path:
            return
        try:
            sites = HitachiWaferParser.parse(path)
            if not sites:
                QMessageBox.warning(self, "Parse Error", "No site data found.")
                return
            self.set_sites(sites)
            self.site_selected.emit(sites[0])
            QMessageBox.information(
                self, "Import OK",
                f"Loaded {len(sites)} sites from:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def load_demo(self) -> None:
        self.set_sites(HitachiWaferParser.generate_demo(49))
