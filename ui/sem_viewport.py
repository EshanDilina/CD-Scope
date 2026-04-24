"""
cd_scope.ui.sem_viewport
──────────────────────────
SEMViewport — interactive image display widget.

  • Grayscale or false-colour rendering
  • Scroll-wheel zoom, middle-click pan
  • Left-click-drag: draw measurement rulers (CD/pitch/space/LWR/LER)
  • Auto edge overlays from EdgeResult
  • SEM parameter HUD (ACC, MAG, FoV, source)
"""
from __future__ import annotations
import math
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore    import Qt, QPointF, pyqtSignal
from PyQt5.QtGui     import (QColor, QPainter, QPen, QBrush, QPixmap, QImage,
                              QPolygonF, QCursor, QFont)

from cd_scope.constants import (    BORDER, CYAN, GREEN, AMBER, RED, PURPLE, TEXT_DIM, TEXT_BR
)
from cd_scope.core.models import EdgeResult, SEMMeta

class SEMViewport(QWidget):
    """
    Full-featured SEM image viewer with measurement tools and overlay rendering.
    """
    measure_done = pyqtSignal(float)   # emits nm value after a ruler drag

    _TOOL_COLORS = {
        'cd': GREEN, 'pitch': AMBER, 'space': CYAN,
        'lwr': PURPLE, 'ler': RED, 'edge': '#ff6688',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setStyleSheet(f"background:#000;border:1px solid {BORDER};")

        self._pixmap:  QPixmap  | None = None
        self._raw_img              = None
        self._meta:    SEMMeta   | None = None
        self._edge_result: EdgeResult | None = None

        self._zoom    = 1.0
        self._offset  = QPointF(0, 0)
        self._measurements: list[tuple] = []
        self._tool    = "cd"
        self._drawing = False
        self._p1: QPointF | None = None
        self._p2: QPointF | None = None
        self._pan_start:  QPointF | None = None
        self._pan_offset: QPointF | None = None

        self.false_color = False
        self.invert      = False
        self.show_auto   = True

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_image(self, pixmap: QPixmap, raw_img,
                  meta: SEMMeta | None = None,
                  edge_result: EdgeResult | None = None) -> None:
        self._pixmap       = pixmap
        self._raw_img      = raw_img
        self._meta         = meta
        self._edge_result  = edge_result
        self._fit()
        self.update()

    def set_edge_result(self, r: EdgeResult | None) -> None:
        self._edge_result = r
        self.update()

    def set_tool(self, tool: str) -> None:
        self._tool = tool

    def set_zoom(self, z: float) -> None:
        cx, cy = self.width() / 2, self.height() / 2
        ix = (cx - self._offset.x()) / self._zoom
        iy = (cy - self._offset.y()) / self._zoom
        self._zoom   = z
        self._offset = QPointF(cx - ix*z, cy - iy*z)
        self.update()

    def clear_measurements(self) -> None:
        self._measurements.clear()
        self.update()

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000000"))

        if not self._pixmap:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(QFont("Courier New", 11))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No image loaded\nFile → Open SEM Image…\n"
                       "or click ACQUIRE for synthetic image")
            return

        # Image
        p.save()
        p.translate(self._offset)
        p.scale(self._zoom, self._zoom)
        p.drawPixmap(0, 0, self._pixmap)
        p.restore()

        # Scanline texture
        p.setPen(Qt.NoPen)
        for y in range(0, self.height(), 4):
            p.fillRect(0, y, self.width(), 2, QColor(0, 0, 0, 6))

        # Auto edge overlay
        if self.show_auto and self._edge_result:
            self._draw_edges(p)

        # User rulers
        for meas in self._measurements:
            self._draw_ruler(p, *meas)

        # In-progress ruler
        if self._drawing and self._p1 and self._p2:
            pen = QPen(QColor(AMBER), 1.5, Qt.DashLine)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawLine(self._p1, self._p2)

        # HUD
        self._draw_hud(p)

    def _draw_edges(self, p: QPainter) -> None:
        r = self._edge_result
        if not r or not r.edge_overlay:
            return
        H  = self.height()
        ox = self._offset.x()
        z  = self._zoom
        cy = H // 2

        for xpx, etype in r.edge_overlay:
            if etype not in ('left', 'right'):
                continue
            xsc = ox + xpx * z
            col = QColor(CYAN); col.setAlpha(140)
            p.setPen(QPen(col, 1))
            p.drawLine(int(xsc), 0, int(xsc), H)

        pairs = [(r.edge_overlay[i][0], r.edge_overlay[i+1][0])
                 for i in range(0, len(r.edge_overlay)-1, 3)]
        if pairs:
            lx, rx = pairs[0]
            lxs = ox + lx*z; rxs = ox + rx*z
            p.setPen(QPen(QColor(GREEN), 1.5))
            p.drawLine(int(lxs), cy, int(rxs), cy)
            for ax, dr in [(int(lxs), 1), (int(rxs), -1)]:
                pts = [QPointF(ax, cy), QPointF(ax+dr*7, cy-4), QPointF(ax+dr*7, cy+4)]
                p.setBrush(QBrush(QColor(GREEN)))
                p.setPen(Qt.NoPen)
                p.drawPolygon(QPolygonF(pts))
            p.setPen(QColor(GREEN))
            p.setFont(QFont("Courier New", 9, QFont.Bold))
            mid_x = int((lxs + rxs) / 2) - 30
            p.fillRect(mid_x-2, cy-18, 86, 14, QColor(0, 0, 0, 140))
            p.drawText(mid_x, cy-6, f"CD: {r.cd_mean:.2f} nm")

        if len(pairs) >= 2:
            c0 = (pairs[0][0] + pairs[0][1]) / 2
            c1 = (pairs[1][0] + pairs[1][1]) / 2
            c0s = ox + c0*z; c1s = ox + c1*z
            py2 = int(H * 0.2)
            p.setPen(QPen(QColor(AMBER), 1))
            p.drawLine(int(c0s), py2, int(c1s), py2)
            pmid = int((c0s + c1s) / 2) - 25
            p.setFont(QFont("Courier New", 9))
            p.drawText(pmid, py2-4, f"P: {r.pitch_mean:.1f} nm")

    def _draw_ruler(self, p: QPainter, p1: QPointF, p2: QPointF,
                    label: str, color: str) -> None:
        pen = QPen(QColor(color), 1.5, Qt.DashLine)
        pen.setDashPattern([5, 3])
        p.setPen(pen)
        p.drawLine(p1, p2)
        mid = QPointF((p1.x()+p2.x())/2, (p1.y()+p2.y())/2)
        p.setPen(QColor(color))
        p.setFont(QFont("Courier New", 9, QFont.Bold))
        p.fillRect(int(mid.x())-2, int(mid.y())-14, 72, 14, QColor(0, 0, 0, 160))
        p.drawText(int(mid.x()), int(mid.y())-2, label)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(color)))
        for pt in (p1, p2):
            p.drawEllipse(int(pt.x())-3, int(pt.y())-3, 6, 6)

    def _draw_hud(self, p: QPainter) -> None:
        m = self._meta
        lines = []
        if m:
            lines = [
                f"ACC: {m.acc_voltage:.0f} eV  WD: {m.working_dist:.1f}mm",
                f"MAG: ×{m.mag:,.0f}  FoV: {m.field_width_nm/1000:.2f}µm",
                f"Pixel: {m.nm_per_px:.3f} nm/px  [{m.source}]",
            ]
        else:
            lines = ["Synthetic image  (no real SEM file loaded)"]

        p.setFont(QFont("Courier New", 9))
        for i, line in enumerate(lines):
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(line)
            p.fillRect(8, 8+i*16, tw+8, 14, QColor(0, 0, 0, 140))
            p.setPen(QColor(CYAN))
            p.drawText(12, 20+i*16, line)

    # ── Mouse interaction ─────────────────────────────────────────────────────

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drawing = True
            self._p1 = ev.pos()
            self._p2 = ev.pos()
        elif ev.button() == Qt.MiddleButton:
            self._pan_start  = ev.pos()
            self._pan_offset = QPointF(self._offset)
            self.setCursor(QCursor(Qt.ClosedHandCursor))

    def mouseMoveEvent(self, ev) -> None:
        if self._drawing and self._p1:
            self._p2 = ev.pos()
            self.update()
        elif self._pan_start and self._pan_offset is not None:
            d = ev.pos() - self._pan_start
            self._offset = self._pan_offset + QPointF(d.x(), d.y())
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self._drawing and self._p1:
            p2 = ev.pos()
            dx = p2.x() - self._p1.x()
            dy = p2.y() - self._p1.y()
            npp = self._meta.nm_per_px if self._meta else 1.0
            dist_nm = math.sqrt(dx*dx + dy*dy) / self._zoom * npp
            if dist_nm > 0.5:
                color = self._TOOL_COLORS.get(self._tool, GREEN)
                self._measurements.append(
                    (self._p1, p2, f"{dist_nm:.1f}nm", color))
                self.measure_done.emit(dist_nm)
            self._drawing = False
            self._p1 = None
            self._p2 = None
            self.update()
        elif ev.button() == Qt.MiddleButton:
            self._pan_start  = None
            self._pan_offset = None
            self.setCursor(QCursor(Qt.CrossCursor))

    def wheelEvent(self, ev) -> None:
        factor = 1.12 if ev.angleDelta().y() > 0 else 1/1.12
        mx, my = ev.pos().x(), ev.pos().y()
        ix = (mx - self._offset.x()) / self._zoom
        iy = (my - self._offset.y()) / self._zoom
        new_z = max(0.2, min(10.0, self._zoom * factor))
        self._offset = QPointF(mx - ix*new_z, my - iy*new_z)
        self._zoom   = new_z
        self.update()

    def resizeEvent(self, ev) -> None:
        self._fit()
        super().resizeEvent(ev)

    def _fit(self) -> None:
        if not self._pixmap:
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        if pw == 0 or ph == 0:
            return
        self._zoom   = min(ww/pw, wh/ph)
        self._offset = QPointF((ww - pw*self._zoom)/2,
                                (wh - ph*self._zoom)/2)
