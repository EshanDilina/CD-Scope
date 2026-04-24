"""
cd_scope.ui.metric_widgets
────────────────────────────
Reusable KPI display widgets used throughout the right panel.

  MetricCard  — shows a metric name, value, unit, and delta hint
  GaugeBar    — compact horizontal fill bar with PASS/WARN/FAIL label
"""
from __future__ import annotations
from PyQt5.QtWidgets import QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtGui     import QPainter, QBrush, QColor, QCursor

from cd_scope.constants import (    BG_CARD, BG_DEEP, BORDER, CYAN, GREEN, AMBER, RED, TEXT_BR, TEXT_MID, TEXT_DIM
)


class MetricCard(QFrame):
    """Single KPI tile: label / big number / unit / delta hint."""

    clicked = pyqtSignal()

    _BASE_STYLE = (
        f"QFrame{{background:{BG_CARD};border:1px solid {BORDER};"
        f"border-radius:2px;}}"
    )
    _HIT_STYLE  = (
        f"QFrame{{background:rgba(0,212,255,0.10);border:1px solid {CYAN};"
        f"border-radius:2px;}}"
    )

    def __init__(self, label: str, value: str = "—", unit: str = "",
                 delta: str = "", delta_color: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setStyleSheet(self._BASE_STYLE)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 5)
        lay.setSpacing(2)

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(
            f"color:{TEXT_DIM};font-family:'Courier New',monospace;"
            f"font-size:9px;letter-spacing:1px;"
        )
        lay.addWidget(self._lbl)

        row = QHBoxLayout(); row.setSpacing(0)
        self._val  = QLabel(str(value))
        self._unit = QLabel(f" {unit}")
        self._val .setStyleSheet(
            f"color:{TEXT_BR};font-family:'Courier New',monospace;"
            f"font-size:20px;font-weight:bold;"
        )
        self._unit.setStyleSheet(
            f"color:{TEXT_MID};font-size:11px;font-family:'Courier New',monospace;"
        )
        row.addWidget(self._val); row.addWidget(self._unit); row.addStretch()
        lay.addLayout(row)

        self._delta = QLabel(delta)
        self._delta.setStyleSheet(
            f"color:{delta_color};font-family:'Courier New',monospace;font-size:10px;"
        )
        lay.addWidget(self._delta)

    # ── Public helpers ─────────────────────────────────────────────────────────

    def set_value(self, v: str, unit: str = "") -> None:
        self._val.setText(str(v))
        if unit:
            self._unit.setText(f" {unit}")

    def set_delta(self, text: str, color: str = GREEN) -> None:
        self._delta.setText(text)
        self._delta.setStyleSheet(
            f"color:{color};font-family:'Courier New',monospace;font-size:10px;"
        )

    def set_highlight(self, on: bool) -> None:
        self.setStyleSheet(self._HIT_STYLE if on else self._BASE_STYLE)

    def mousePressEvent(self, e) -> None:
        self.clicked.emit()
        super().mousePressEvent(e)


class GaugeBar(QWidget):
    """Compact fill bar showing percentage with status label."""

    def __init__(self, label: str, pct: float,
                 status: str = "good", parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lbl_w = QLabel(label)
        lbl_w.setFixedWidth(68)
        lbl_w.setStyleSheet(f"color:{TEXT_MID};font-size:11px;")
        lay.addWidget(lbl_w)

        self._bar = _GaugeFill(pct, status)
        lay.addWidget(self._bar)

        vc  = {"good": GREEN, "warn": AMBER, "fail": RED}
        vt  = {"good": "PASS", "warn": "WARN", "fail": "FAIL"}
        val = QLabel(vt.get(status, ""))
        val.setFixedWidth(36)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet(
            f"color:{vc.get(status, GREEN)};"
            f"font-family:'Courier New',monospace;font-size:10px;"
        )
        lay.addWidget(val)

    def update_status(self, pct: float, status: str) -> None:
        self._bar.pct    = pct
        self._bar.color  = {"good": GREEN, "warn": AMBER, "fail": RED}.get(status, GREEN)
        self._bar.update()


class _GaugeFill(QWidget):
    """Internal fill bar painter."""

    def __init__(self, pct: float, status: str, parent=None):
        super().__init__(parent)
        self.pct   = pct
        self.color = {"good": GREEN, "warn": AMBER, "fail": RED}.get(status, GREEN)
        self.setMinimumWidth(80)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(BG_DEEP)))
        p.drawRoundedRect(r, 3, 3)
        fw = int(r.width() * min(max(self.pct, 0), 100) / 100)
        if fw > 0:
            p.setBrush(QBrush(QColor(self.color)))
            from PyQt5.QtCore import QRect
            p.drawRoundedRect(QRect(0, 0, fw, r.height()), 3, 3)
