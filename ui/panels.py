"""
cd_scope.ui.panels
────────────────────
All right-panel and bottom-panel widgets.

  ResultsPanel         — 6 metric cards + scrollable stats + Cp/Cpk
  RecipePanel          — algorithm / spec / target editor
  DataTablePanel       — filterable site/batch table with CSV export
  DoseFocusPanel       — Bossung curves + process window chart
  APCPanel             — EWMA APC controller with live chart
  LiveAcquisitionPanel — frame-grabber UI
"""
from __future__ import annotations
import csv, datetime, math
from pathlib import Path
import numpy as np
from scipy import stats as scipy_stats
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QDoubleSpinBox,
    QSpinBox, QCheckBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import QColor, QFont
import pyqtgraph as pg
from pyqtgraph import mkPen, mkBrush

from cd_scope.constants import (    BG_VOID, BG_DEEP, BG_PANEL, BG_CARD, BORDER, CYAN, GREEN,
    AMBER, RED, PURPLE, TEXT_BR, TEXT_MID, TEXT_DIM, TARGET_CD
)
from cd_scope.core import EdgeDetector, EdgeResult, PatternConfig, PATTERN_TYPES
from cd_scope.core.models import WaferSite
from cd_scope.analysis import (DoseFocusAnalyzer, AcquisitionConfig,                         LiveAcquisitionThread, gen_synthetic_sem,
                         gen_synthetic_contact)
from cd_scope.control import APCController
from cd_scope.ui.metric_widgets import MetricCard, GaugeBar

# ══════════════════════════════════════════════════════════════════════════════
# RESULTS PANEL
# ══════════════════════════════════════════════════════════════════════════════

class ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        from PyQt5.QtWidgets import QGridLayout
        grid = QGridLayout(); grid.setSpacing(1); grid.setContentsMargins(0,0,0,0)
        self._cards: dict[str, MetricCard] = {}
        defs = [
            ("cd_mean","CD MEAN","—","nm","— vs target",TEXT_MID),
            ("cd_3s",  "CD 3σ",  "—","nm","CDU budget",TEXT_MID),
            ("lwr",    "LWR 3σ", "—","nm","Spec: <4.0",TEXT_MID),
            ("ler_l",  "LER LEFT","—","nm","Spec: <3.0",TEXT_MID),
            ("pitch",  "PITCH",  "—","nm","",TEXT_MID),
            ("space",  "SPACE",  "—","nm","",TEXT_MID),
        ]
        for idx, (k, lbl, v, u, d, c) in enumerate(defs):
            card = MetricCard(lbl, v, u, d, c)
            card.clicked.connect(
                lambda key=k: [c2.set_highlight(k2==key)
                               for k2, c2 in self._cards.items()])
            self._cards[k] = card
            grid.addWidget(card, idx//2, idx%2)

        gw = QWidget(); gw.setLayout(grid); lay.addWidget(gw)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG_PANEL};}}")
        content = QWidget()
        self._sl = QVBoxLayout(content)
        self._sl.setContentsMargins(10,10,10,10); self._sl.setSpacing(4)
        self._build_detail()
        scroll.setWidget(content); lay.addWidget(scroll)

    def _sec(self, t: str) -> None:
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{TEXT_DIM};font-family:'Courier New',monospace;"
            f"font-size:9px;letter-spacing:2px;"
            f"border-bottom:1px solid {BORDER};padding-bottom:4px;margin-top:8px;")
        self._sl.addWidget(l)

    def _row(self, name: str, val: str, c: str = TEXT_BR):
        w = QWidget(); w.setFixedHeight(24)
        rl = QHBoxLayout(w); rl.setContentsMargins(0,0,0,0)
        l = QLabel(name); l.setStyleSheet(f"color:{TEXT_MID};font-size:12px;")
        v = QLabel(val)
        v.setStyleSheet(f"color:{c};font-family:'Courier New',monospace;font-size:12px;")
        v.setAlignment(Qt.AlignRight)
        rl.addWidget(l); rl.addStretch(); rl.addWidget(v)
        self._sl.addWidget(w)
        return v

    def _build_detail(self) -> None:
        self._sec("EDGE ANALYSIS")
        self._v_esl = self._row("Edge slope L", "—°")
        self._v_esr = self._row("Edge slope R", "—°")
        self._sec("STOCHASTIC")
        self._v_lwr_s  = self._row("LWR σ",          "—")
        self._v_hurst  = self._row("Hurst exponent",  "—")
        self._v_corr   = self._row("Corr. length",    "—")
        self._sec("POPULATION")
        self._v_n    = self._row("N measurements", "—")
        self._v_min  = self._row("Min CD",         "—")
        self._v_max  = self._row("Max CD",         "—")
        self._v_skew = self._row("Skewness",       "—")
        self._v_cp   = self._row("Cp",  "—", GREEN)
        self._v_cpk  = self._row("Cpk", "—", GREEN)

        rf = QFrame()
        rf.setStyleSheet(f"background:{BG_CARD};border:1px solid {BORDER};border-radius:2px;")
        rf.setFixedHeight(58)
        rl = QVBoxLayout(rf); rl.setContentsMargins(10,6,10,6)
        self._v_result = QLabel("—")
        self._v_result.setStyleSheet(
            f"color:{TEXT_DIM};font-family:'Courier New',monospace;"
            f"font-size:18px;font-weight:bold;letter-spacing:3px;")
        self._v_ts = QLabel("")
        self._v_ts.setStyleSheet(
            f"color:{TEXT_DIM};font-family:'Courier New',monospace;font-size:10px;")
        rl.addWidget(self._v_result); rl.addWidget(self._v_ts)
        self._sl.addWidget(rf); self._sl.addStretch()

    # ── Public update methods ──────────────────────────────────────────────────

    def update_from_edge(self, r: EdgeResult) -> None:
        if not r: return
        cd = r.cd_mean; sg = r.cd_std; lwr = r.lwr_3s
        self._cards['cd_mean'].set_value(f"{cd:.2f}", "nm")
        self._cards['cd_3s'].set_value(f"{3*sg:.2f}", "nm")
        self._cards['lwr'].set_value(f"{lwr:.2f}", "nm")
        self._cards['ler_l'].set_value(f"{r.ler_l_3s:.2f}", "nm")
        self._cards['pitch'].set_value(f"{r.pitch_mean:.2f}", "nm")
        self._cards['space'].set_value(f"{r.space_mean:.2f}", "nm")
        self._v_esl.setText(f"{r.edge_slope_l:.1f}°")
        self._v_esr.setText(f"{r.edge_slope_r:.1f}°")
        self._v_lwr_s.setText(f"{lwr/3:.3f} nm")
        self._v_hurst.setText(f"{r.hurst:.3f}")
        self._v_corr.setText(f"{r.corr_len:.1f} nm")
        self._v_n.setText(str(len(r.cd_values)))
        if len(r.cd_values) > 0:
            self._v_min.setText(f"{r.cd_values.min():.2f} nm")
            self._v_max.setText(f"{r.cd_values.max():.2f} nm")
            sk = float(scipy_stats.skew(r.cd_values)) if len(r.cd_values)>3 else 0
            self._v_skew.setText(f"{sk:.3f}")
        usl, lsl = 34.0, 30.0
        cp = (usl-lsl)/(6*sg) if sg>0 else 0
        cpu = (usl-cd)/(3*sg) if sg>0 else 0
        cpl = (cd-lsl)/(3*sg) if sg>0 else 0
        cpk = min(cpu, cpl)
        self._v_cp.setText(f"{cp:.2f}")
        self._v_cp.setStyleSheet(f"color:{GREEN if cp>=1.33 else RED};"
                                  f"font-family:'Courier New',monospace;font-size:12px;")
        self._v_cpk.setText(f"{cpk:.2f}")
        self._v_cpk.setStyleSheet(f"color:{GREEN if cpk>=1.33 else RED};"
                                   f"font-family:'Courier New',monospace;font-size:12px;")
        ok = 30 <= cd <= 34 and lwr <= 4
        rc = GREEN if ok else RED
        self._v_result.setText("✓  PASS" if ok else "✗  FAIL")
        self._v_result.setStyleSheet(
            f"color:{rc};font-family:'Courier New',monospace;"
            f"font-size:18px;font-weight:bold;letter-spacing:3px;")
        self._v_ts.setText(datetime.datetime.now().strftime("Analyzed: %Y-%m-%d %H:%M:%S"))
        if r.error:
            self._v_result.setText("⚠ Error")
            self._v_result.setStyleSheet(
                f"color:{AMBER};font-family:'Courier New',monospace;font-size:14px;")

    def update_from_sites(self, sites: list[WaferSite]) -> None:
        if not sites: return
        cds  = [s.cd_mean for s in sites if s.cd_mean > 0]
        lwrs = [s.lwr for s in sites if s.lwr > 0]
        if not cds: return
        mu = np.mean(cds); sg = np.std(cds, ddof=1) if len(cds)>1 else 0
        usl, lsl = 34.0, 30.0
        cp = (usl-lsl)/(6*sg) if sg>0 else 0
        cpu= (usl-mu)/(3*sg)  if sg>0 else 0
        cpl= (mu-lsl)/(3*sg)  if sg>0 else 0
        cpk= min(cpu, cpl)
        self._cards['cd_mean'].set_value(f"{mu:.2f}", "nm")
        self._cards['cd_3s'].set_value(f"{3*sg:.2f}", "nm")
        if lwrs: self._cards['lwr'].set_value(f"{np.mean(lwrs):.2f}", "nm")
        self._v_n.setText(str(len(cds)))
        self._v_min.setText(f"{min(cds):.2f} nm")
        self._v_max.setText(f"{max(cds):.2f} nm")
        sk = float(scipy_stats.skew(cds)) if len(cds)>3 else 0
        self._v_skew.setText(f"{sk:.3f}")
        self._v_cp.setText(f"{cp:.2f}")
        self._v_cpk.setText(f"{cpk:.2f}")
        ok = 30 <= mu <= 34
        rc = GREEN if ok else RED
        self._v_result.setText("✓  PASS" if ok else "✗  FAIL")
        self._v_result.setStyleSheet(
            f"color:{rc};font-family:'Courier New',monospace;"
            f"font-size:18px;font-weight:bold;letter-spacing:3px;")
        self._v_ts.setText(datetime.datetime.now().strftime("Updated: %Y-%m-%d %H:%M:%S"))


# ══════════════════════════════════════════════════════════════════════════════
# RECIPE PANEL
# ══════════════════════════════════════════════════════════════════════════════

class RecipePanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet(f"QScrollArea{{border:none;background:{BG_PANEL};}}")
        c = QWidget(); self.setWidget(c)
        lay = QVBoxLayout(c); lay.setContentsMargins(10,10,10,10); lay.setSpacing(8)

        def grp(t):
            g = QGroupBox(t); f = QFormLayout()
            f.setSpacing(5); f.setContentsMargins(8,12,8,8)
            g.setLayout(f); lay.addWidget(g); return f

        f = grp("Recipe")
        self.name = QLineEdit("EUV_LINE_32nm_v1")
        self.feat = QComboBox(); self.feat.addItems(["Line/Space","Contact Hole","Trench"])
        f.addRow("Name:", self.name); f.addRow("Feature:", self.feat)

        f2 = grp("CD Targets")
        self.tgt   = QDoubleSpinBox(); self.tgt.setRange(1,500); self.tgt.setValue(32.0); self.tgt.setSuffix(" nm")
        self.tol   = QDoubleSpinBox(); self.tol.setRange(0.1,50); self.tol.setValue(2.0); self.tol.setSuffix(" nm")
        self.pitch_tgt = QDoubleSpinBox(); self.pitch_tgt.setRange(1,2000); self.pitch_tgt.setValue(64.0); self.pitch_tgt.setSuffix(" nm")
        f2.addRow("Target CD:", self.tgt); f2.addRow("Tolerance±:", self.tol); f2.addRow("Pitch:", self.pitch_tgt)

        f3 = grp("Edge Detection")
        self.algo  = QComboBox(); self.algo.addItems(EdgeDetector.ALGOS)
        self.sigma = QDoubleSpinBox(); self.sigma.setRange(0.5,20); self.sigma.setValue(2.5); self.sigma.setSuffix(" nm")
        self.th    = QDoubleSpinBox(); self.th.setRange(0.1,0.9); self.th.setValue(0.5); self.th.setSingleStep(0.05)
        self.cd_h  = QSpinBox(); self.cd_h.setRange(10,90); self.cd_h.setValue(50); self.cd_h.setSuffix(" %")
        f3.addRow("Algorithm:", self.algo); f3.addRow("Gauss σ:", self.sigma)
        f3.addRow("Threshold:", self.th); f3.addRow("CD Height:", self.cd_h)

        f4 = grp("Spec Limits")
        self.lwr_max = QDoubleSpinBox(); self.lwr_max.setRange(0.1,20); self.lwr_max.setValue(4.0); self.lwr_max.setSuffix(" nm")
        self.ler_max = QDoubleSpinBox(); self.ler_max.setRange(0.1,20); self.ler_max.setValue(3.0); self.ler_max.setSuffix(" nm")
        self.cdu_max = QDoubleSpinBox(); self.cdu_max.setRange(0.1,20); self.cdu_max.setValue(2.0); self.cdu_max.setSuffix(" nm")
        self.cpk_min = QDoubleSpinBox(); self.cpk_min.setRange(0.5,3.0); self.cpk_min.setValue(1.33); self.cpk_min.setSingleStep(0.1)
        f4.addRow("LWR Max:", self.lwr_max); f4.addRow("LER Max:", self.ler_max)
        f4.addRow("CDU Max:", self.cdu_max); f4.addRow("Min Cpk:", self.cpk_min)

        self.btn_apply = QPushButton("▶  APPLY RECIPE"); self.btn_apply.setObjectName("primary"); self.btn_apply.setMinimumHeight(32)
        self.btn_nm    = QPushButton("⚙  Enter nm/px manually…"); self.btn_nm.setMinimumHeight(28)
        lay.addWidget(self.btn_apply); lay.addWidget(self.btn_nm); lay.addStretch()

    def get_detector(self) -> EdgeDetector:
        d = EdgeDetector()
        d.sigma_nm  = self.sigma.value()
        d.threshold = self.th.value()
        d.algo      = self.algo.currentIndex()
        d.cd_height = self.cd_h.value()
        return d


# ══════════════════════════════════════════════════════════════════════════════
# DATA TABLE PANEL
# ══════════════════════════════════════════════════════════════════════════════

class DataTablePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Filter bar
        fb = QWidget(); fb.setFixedHeight(32)
        fb.setStyleSheet(f"background:{BG_DEEP};border-bottom:1px solid {BORDER};")
        fl = QHBoxLayout(fb); fl.setContentsMargins(8,4,8,4); fl.setSpacing(8)
        self._filt = QLineEdit(); self._filt.setPlaceholderText("Filter…"); self._filt.setFixedWidth(160)
        self._filt.textChanged.connect(self._filter)
        self._site_f = QComboBox(); self._site_f.addItem("All Sites")
        self._site_f.currentTextChanged.connect(self._filter)
        self._stat_f = QComboBox(); self._stat_f.addItems(["All","PASS","FAIL","WARN"])
        self._stat_f.currentTextChanged.connect(self._filter)
        fl.addWidget(QLabel("Filter:")); fl.addWidget(self._filt)
        fl.addWidget(QLabel("Site:")); fl.addWidget(self._site_f)
        fl.addWidget(QLabel("Status:")); fl.addWidget(self._stat_f); fl.addStretch()
        btn = QPushButton("Export CSV"); btn.setFixedHeight(22); btn.clicked.connect(self._export)
        fl.addWidget(btn); lay.addWidget(fb)

        # Table
        self._tbl = QTableWidget()
        cols = ["#","SITE","X(mm)","Y(mm)","CD_MEAN","CD_σ","LWR",
                "LER_L","LER_R","PITCH","SPACE","STATUS","IMG"]
        self._tbl.setColumnCount(len(cols))
        self._tbl.setHorizontalHeaderLabels(cols)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._tbl)
        self._all_sites: list = []

    def update_sites(self, sites: list) -> None:
        self._all_sites = sites
        self._site_f.clear(); self._site_f.addItem("All Sites")
        for sid in dict.fromkeys(
                s.site_id if hasattr(s,'site_id') else s.get('site_id','')
                for s in sites):
            self._site_f.addItem(sid)
        self._render(sites)

    def _render(self, sites: list) -> None:
        self._tbl.setRowCount(len(sites))
        for row, s in enumerate(sites):
            ok   = (s.status if hasattr(s,'status') else s.get('status','')) == 'PASS'
            vals = [
                str(row+1),
                s.site_id  if hasattr(s,'site_id')  else s.get('site_id',''),
                f"{s.x_mm:.1f}"  if hasattr(s,'x_mm')  else "—",
                f"{s.y_mm:.1f}"  if hasattr(s,'y_mm')  else "—",
                f"{s.cd_mean:.2f}" if hasattr(s,'cd_mean') else "—",
                f"{s.cd_std:.2f}"  if hasattr(s,'cd_std')  else "—",
                f"{s.lwr:.2f}"     if hasattr(s,'lwr')     else "—",
                f"{s.ler_l:.2f}"   if hasattr(s,'ler_l')   else "—",
                f"{s.ler_r:.2f}"   if hasattr(s,'ler_r')   else "—",
                f"{s.pitch:.2f}"   if hasattr(s,'pitch')   else "—",
                f"{s.space:.2f}"   if hasattr(s,'space')   else "—",
                s.status   if hasattr(s,'status')   else s.get('status',''),
                s.img_file if hasattr(s,'img_file') else "",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if col == 4:
                    item.setForeground(QColor(GREEN if ok else RED))
                elif col == 11:
                    fc = {' PASS': GREEN, 'FAIL': RED, 'WARN': AMBER}.get(
                        vals[11], TEXT_MID)
                    item.setForeground(QColor(fc))
                    f = item.font(); f.setBold(True); item.setFont(f)
                else:
                    item.setForeground(QColor(TEXT_MID))
                self._tbl.setItem(row, col, item)

    def _filter(self) -> None:
        txt  = self._filt.text().lower()
        sf   = self._site_f.currentText()
        st   = self._stat_f.currentText()
        sites = [s for s in self._all_sites
                 if (sf == "All Sites" or
                     (s.site_id if hasattr(s,'site_id') else '') == sf)
                 and (st == "All" or
                      (s.status if hasattr(s,'status') else '') == st)
                 and (not txt or txt in str(s))]
        self._render(sites)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "CD_SCOPE_wafer.csv", "CSV (*.csv)")
        if not path: return
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["#","SITE","X_mm","Y_mm","CD_MEAN","CD_STD",
                         "LWR","LER_L","LER_R","PITCH","SPACE","STATUS"])
            for i, s in enumerate(self._all_sites):
                w.writerow([i+1,
                             s.site_id if hasattr(s,'site_id') else '',
                             s.x_mm    if hasattr(s,'x_mm') else 0,
                             s.y_mm    if hasattr(s,'y_mm') else 0,
                             s.cd_mean if hasattr(s,'cd_mean') else 0,
                             s.cd_std  if hasattr(s,'cd_std') else 0,
                             s.lwr     if hasattr(s,'lwr') else 0,
                             s.ler_l   if hasattr(s,'ler_l') else 0,
                             s.ler_r   if hasattr(s,'ler_r') else 0,
                             s.pitch   if hasattr(s,'pitch') else 0,
                             s.space   if hasattr(s,'space') else 0,
                             s.status  if hasattr(s,'status') else ''])


# ══════════════════════════════════════════════════════════════════════════════
# DOSE-FOCUS PANEL
# ══════════════════════════════════════════════════════════════════════════════

class DoseFocusPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        ctrl = QWidget(); ctrl.setFixedHeight(34)
        ctrl.setStyleSheet(f"background:{BG_DEEP};border-bottom:1px solid {BORDER};")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(8,4,8,4); cl.setSpacing(8)
        cl.addWidget(QLabel("View:"))
        self._view = QComboBox()
        self._view.addItems(["Bossung Curves","CD Heatmap","Process Window","DoF vs Dose"])
        self._view.currentIndexChanged.connect(self._update)
        cl.addWidget(self._view)
        cl.addWidget(QLabel("Target:"))
        self._tgt = QDoubleSpinBox(); self._tgt.setRange(1,500); self._tgt.setValue(32.0); self._tgt.setSuffix(" nm")
        self._tgt.valueChanged.connect(self._update); cl.addWidget(self._tgt)
        cl.addWidget(QLabel("Tol:"))
        self._tol = QDoubleSpinBox(); self._tol.setRange(1,30); self._tol.setValue(10.0); self._tol.setSuffix(" %")
        self._tol.valueChanged.connect(self._update); cl.addWidget(self._tol)
        cl.addStretch()
        self._info = QLabel("No data")
        self._info.setStyleSheet(f"color:{CYAN};font-family:'Courier New',monospace;font-size:10px;")
        cl.addWidget(self._info)
        lay.addWidget(ctrl)

        pg.setConfigOption('background', BG_VOID); pg.setConfigOption('foreground', TEXT_MID)
        self._pw = pg.PlotWidget(); self._pw.setStyleSheet(f"background:{BG_VOID};border:none;")
        self._pw.showGrid(x=True, y=True, alpha=0.15); lay.addWidget(self._pw)
        self._points: list = []; self._result: dict = {}

    def set_points(self, points: list) -> None:
        self._points = points; self._update()

    def load_from_scanner_and_batch(self, scanner_fields, batch_records) -> int:
        from cd_scope.core.models import DoseFocusPoint
        pts = [DoseFocusPoint(r.dose, r.focus, r.cd_mean, r.cd_std, r.lwr_3s, r.site_id)
               for r in batch_records if r.dose > 0 and r.cd_mean > 0]
        self._points = pts; self._update(); return len(pts)

    def _update(self) -> None:
        if not self._points:
            self._pw.clear()
            self._pw.setTitle("No data — import scanner + batch results", color=TEXT_DIM, size="9pt")
            self._info.setText("No data"); return
        ana = DoseFocusAnalyzer(self._points, self._tgt.value(), self._tol.value())
        self._result = ana.analyse()
        self._pw.clear()
        v = self._view.currentIndex()
        if v == 0:   self._bossung()
        elif v == 1: self._heatmap()
        elif v == 2: self._process_window()
        else:        self._dof_curve()
        pw = self._result.get('process_window')
        el = self._result.get('el_pct', 0)
        bd = self._result.get('best_dose', 0)
        if pw:
            dof = pw[3]-pw[2]
            self._info.setText(f"Best dose: {bd:.1f}  DoF: {dof:.3f}µm  EL: {el:.1f}%")

    def _bossung(self) -> None:
        self._pw.setTitle("Bossung Curves", color=TEXT_DIM, size="9pt")
        self._pw.setLabel('bottom','Defocus (µm)',color=TEXT_DIM)
        self._pw.setLabel('left','CD (nm)',color=TEXT_DIM)
        cols = [CYAN,GREEN,AMBER,RED,PURPLE,"#ff9900","#00ffcc"]
        for i,(dose,curve) in enumerate(sorted(self._result.get('bossung_curves',{}).items())):
            fs=sorted(curve.keys()); cds=[curve[f] for f in fs]
            col=cols[i%len(cols)]
            self._pw.plot(fs,cds,pen=mkPen(col,width=2),symbol='o',symbolSize=6,
                          symbolBrush=mkBrush(col),name=f"{dose:.1f}")
        if self._points:
            f0=min(p.focus for p in self._points); f1=max(p.focus for p in self._points)
            tgt=self._tgt.value(); tol=tgt*self._tol.value()/100
            self._pw.plot([f0,f1],[tgt,tgt],pen=mkPen(TEXT_DIM,width=1,style=Qt.DashLine))
            for yv in [tgt+tol,tgt-tol]:
                self._pw.plot([f0,f1],[yv,yv],pen=mkPen(AMBER,width=1,style=Qt.DotLine))

    def _heatmap(self) -> None:
        self._pw.setTitle("CD Heatmap", color=TEXT_DIM, size="9pt")
        self._pw.setLabel('bottom','Defocus (µm)',color=TEXT_DIM)
        self._pw.setLabel('left','Dose (mJ/cm²)',color=TEXT_DIM)
        tgt=self._tgt.value()
        for p in self._points:
            dev=abs(p.cd_mean-tgt); t=min(1.0,dev/(tgt*0.15))
            col=QColor(int(255*t),int(255*(1-t)),60)
            self._pw.plot([p.focus],[p.dose],pen=None,symbol='s',symbolSize=18,
                          symbolBrush=mkBrush(col),symbolPen=None)

    def _process_window(self) -> None:
        self._pw.setTitle("Process Window", color=TEXT_DIM, size="9pt")
        self._pw.setLabel('bottom','Defocus (µm)',color=TEXT_DIM)
        self._pw.setLabel('left','Dose (mJ/cm²)',color=TEXT_DIM)
        tgt=self._tgt.value(); tol=tgt*self._tol.value()/100
        for p in self._points:
            ok=abs(p.cd_mean-tgt)<=tol
            self._pw.plot([p.focus],[p.dose],pen=None,symbol='o',symbolSize=10,
                          symbolBrush=mkBrush(GREEN if ok else RED),symbolPen=None)
        pw=self._result.get('process_window')
        if pw:
            el_lo,el_hi,dof_lo,dof_hi=pw
            rx=[dof_lo,dof_hi,dof_hi,dof_lo,dof_lo]; ry=[el_lo,el_lo,el_hi,el_hi,el_lo]
            self._pw.plot(rx,ry,pen=mkPen(CYAN,width=2))
            fill=pg.FillBetweenItem(
                pg.PlotDataItem(rx[:3],ry[:3]),
                pg.PlotDataItem([dof_lo,dof_lo,dof_hi],[el_lo,el_hi,el_hi]),
                brush=pg.mkBrush(QColor(0,212,255,30)))
            self._pw.addItem(fill)

    def _dof_curve(self) -> None:
        self._pw.setTitle("DoF vs Dose", color=TEXT_DIM, size="9pt")
        dof=self._result.get('dof',{})
        if not dof: return
        doses=sorted(dof.keys()); dofs=[dof[d] for d in doses]
        self._pw.plot(doses,dofs,pen=mkPen(AMBER,width=2),symbol='o',symbolSize=8,
                      symbolBrush=mkBrush(AMBER))


# ══════════════════════════════════════════════════════════════════════════════
# APC PANEL
# ══════════════════════════════════════════════════════════════════════════════

class APCPanel(QWidget):
    correction_ready = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._apc = APCController()
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        ctrl = QWidget(); ctrl.setFixedHeight(36)
        ctrl.setStyleSheet(f"background:{BG_DEEP};border-bottom:1px solid {BORDER};")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(8,4,8,4); cl.setSpacing(8)
        for lbl,attr,lo,hi,val,step,sfx in [
            ("Target",  'target_cd',     1.0,200.0,32.0,0.5,  " nm"),
            ("Gain",    'gain',          0.01,1.0, 0.6, 0.05, ""),
            ("dCD/d%",  'cd_per_dose_pct',0.1,5.0, 1.0, 0.1,  " nm/%"),
            ("Deadband",'deadband_nm',   0.0,2.0,  0.3, 0.05, " nm"),
        ]:
            cl.addWidget(QLabel(lbl+":"))
            sp = QDoubleSpinBox(); sp.setRange(lo,hi); sp.setValue(val)
            sp.setSingleStep(step); sp.setSuffix(sfx); sp.setFixedWidth(90)
            sp.valueChanged.connect(lambda v,a=attr: setattr(self._apc,a,v))
            cl.addWidget(sp)
        cl.addStretch()
        btn_r=QPushButton("↺ Reset"); btn_r.setFixedHeight(24); btn_r.clicked.connect(self._reset)
        cl.addWidget(btn_r); lay.addWidget(ctrl)

        inp = QWidget(); inp.setFixedHeight(34)
        inp.setStyleSheet(f"background:{BG_PANEL};border-bottom:1px solid {BORDER};")
        il = QHBoxLayout(inp); il.setContentsMargins(8,4,8,4); il.setSpacing(8)
        il.addWidget(QLabel("CD:"))
        self._cd_in = QDoubleSpinBox(); self._cd_in.setRange(1,200); self._cd_in.setValue(32.0); self._cd_in.setSuffix(" nm")
        il.addWidget(self._cd_in)
        il.addWidget(QLabel("Dose:"))
        self._dose_in = QDoubleSpinBox(); self._dose_in.setRange(0.1,200); self._dose_in.setValue(28.0); self._dose_in.setSuffix(" mJ/cm²")
        il.addWidget(self._dose_in)
        btn_f=QPushButton("▶ Feed"); btn_f.setObjectName("primary"); btn_f.setFixedHeight(26)
        btn_f.clicked.connect(self._manual_feed); il.addWidget(btn_f); il.addStretch()
        self._rec_lbl=QLabel("Recommendation: —")
        self._rec_lbl.setStyleSheet(f"color:{CYAN};font-family:'Courier New',monospace;font-size:11px;")
        il.addWidget(self._rec_lbl); lay.addWidget(inp)

        pg.setConfigOption('background',BG_VOID); pg.setConfigOption('foreground',TEXT_MID)
        self._pw=pg.PlotWidget(); self._pw.setStyleSheet(f"background:{BG_VOID};border:none;")
        self._pw.showGrid(x=True,y=True,alpha=0.15)
        self._pw.setTitle("APC — Run-to-Run Control",color=TEXT_DIM,size="9pt")
        lay.addWidget(self._pw)

        self._tbl=QTableWidget(0,7)
        self._tbl.setHorizontalHeaderLabels(["Run","CD","Error","EWMA","Dose","Corr%","NextDose"])
        self._tbl.setFixedHeight(130); self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._tbl)

    def feed_measurement(self, cd: float, dose: float) -> dict:
        rec = self._apc.update(cd, dose)
        self._refresh_chart(); self._add_row(rec)
        col = GREEN if rec['action']=='HOLD' else AMBER
        self._rec_lbl.setText(f"Action: {rec['action']}  |  "
                               f"Next dose: {rec['new_dose']:.3f} mJ/cm²  "
                               f"({rec['correction_pct']:+.3f}%)")
        self._rec_lbl.setStyleSheet(f"color:{col};font-family:'Courier New',monospace;font-size:11px;")
        self.correction_ready.emit(dose, rec['new_dose']); return rec

    def _manual_feed(self) -> None:
        self.feed_measurement(self._cd_in.value(), self._dose_in.value())

    def _refresh_chart(self) -> None:
        self._pw.clear()
        h = self._apc.history
        if not h: return
        xs   = [r['run']         for r in h]
        cds  = [r['cd_measured'] for r in h]
        errs = [r['ewma_error']  for r in h]
        self._pw.plot(xs,cds, pen=mkPen(CYAN,width=2),name="CD")
        self._pw.plot([xs[0],xs[-1]],[self._apc.target_cd]*2, pen=mkPen(TEXT_DIM,width=1,style=Qt.DashLine))
        for yv,col,sty in [(self._apc.target_cd+self._apc.deadband_nm,AMBER,Qt.DotLine),
                            (self._apc.target_cd-self._apc.deadband_nm,AMBER,Qt.DotLine)]:
            self._pw.plot([xs[0],xs[-1]],[yv,yv],pen=mkPen(col,width=1,style=sty))
        self._pw.plot(xs,errs,pen=mkPen(GREEN,width=1.5),name="EWMA Error")

    def _add_row(self, rec: dict) -> None:
        row = self._tbl.rowCount(); self._tbl.setRowCount(row+1)
        col = GREEN if rec['action']=='HOLD' else AMBER
        for c,v in enumerate([str(rec['run']),f"{rec['cd_measured']:.3f}",
                               f"{rec['cd_error']:+.3f}",f"{rec['ewma_error']:+.3f}",
                               f"{rec['dose_used']:.3f}",f"{rec['correction_pct']:+.4f}%",
                               f"{rec['new_dose']:.3f}"]):
            item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(col if c in(1,5,6) else TEXT_MID))
            self._tbl.setItem(row,c,item)
        self._tbl.scrollToBottom()

    def _reset(self) -> None:
        self._apc.reset(); self._pw.clear(); self._tbl.setRowCount(0)
        self._rec_lbl.setText("Recommendation: —")


# ══════════════════════════════════════════════════════════════════════════════
# LIVE ACQUISITION PANEL
# ══════════════════════════════════════════════════════════════════════════════

class LiveAcquisitionPanel(QWidget):
    frame_acquired = pyqtSignal(object, object, object)
    result_ready   = pyqtSignal(object)

    def __init__(self, detector: EdgeDetector, parent=None):
        super().__init__(parent)
        self._det    = detector
        self._thread = None
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        cfg_w = QWidget(); cfg_w.setFixedHeight(36)
        cfg_w.setStyleSheet(f"background:{BG_DEEP};border-bottom:1px solid {BORDER};")
        cl = QHBoxLayout(cfg_w); cl.setContentsMargins(8,4,8,4); cl.setSpacing(8)
        cl.addWidget(QLabel("Mode:"))
        self._mode=QComboBox(); self._mode.addItems(["Single","Continuous","N Frames","Triggered"])
        self._mode.setFixedWidth(130); cl.addWidget(self._mode)
        cl.addWidget(QLabel("Hz:"))
        self._fps=QDoubleSpinBox(); self._fps.setRange(0.1,10); self._fps.setValue(2.0)
        self._fps.setFixedWidth(70); cl.addWidget(self._fps)
        cl.addWidget(QLabel("N:"))
        self._nf=QSpinBox(); self._nf.setRange(1,9999); self._nf.setValue(10)
        self._nf.setFixedWidth(60); cl.addWidget(self._nf)
        self._auto_ana=QCheckBox("Auto-analyze"); self._auto_ana.setChecked(True); cl.addWidget(self._auto_ana)
        self._auto_save=QCheckBox("Auto-save TIF"); cl.addWidget(self._auto_save)
        cl.addStretch()
        self._status_lbl=QLabel("Idle")
        self._status_lbl.setStyleSheet(f"color:{TEXT_DIM};font-family:'Courier New',monospace;font-size:10px;")
        self._frame_lbl=QLabel("Frame: 0")
        self._frame_lbl.setStyleSheet(f"color:{CYAN};font-family:'Courier New',monospace;font-size:10px;")
        cl.addWidget(self._status_lbl); cl.addWidget(self._frame_lbl)
        lay.addWidget(cfg_w)

        btn_w=QWidget(); btn_w.setFixedHeight(30)
        btn_w.setStyleSheet(f"background:{BG_PANEL};border-bottom:1px solid {BORDER};")
        bl=QHBoxLayout(btn_w); bl.setContentsMargins(8,3,8,3); bl.setSpacing(6)
        self._btn_start=QPushButton("▶ START"); self._btn_start.setObjectName("primary")
        self._btn_pause=QPushButton("⏸ PAUSE"); self._btn_pause.setEnabled(False)
        self._btn_stop =QPushButton("■ STOP");  self._btn_stop.setEnabled(False)
        for b,fn in [(self._btn_start,self._start),(self._btn_pause,self._pause),(self._btn_stop,self._stop)]:
            b.setFixedHeight(24); b.clicked.connect(fn); bl.addWidget(b)
        bl.addStretch()
        self._save_dir_lbl=QLabel("~/cd_scope_images")
        self._save_dir_lbl.setStyleSheet(f"color:{TEXT_DIM};font-size:10px;"); bl.addWidget(self._save_dir_lbl)
        lay.addWidget(btn_w)

        pg.setConfigOption('background',BG_VOID); pg.setConfigOption('foreground',TEXT_MID)
        self._chart=pg.PlotWidget(); self._chart.setStyleSheet(f"background:{BG_VOID};border:none;")
        self._chart.showGrid(x=True,y=True,alpha=0.15)
        self._chart.setLabel('bottom','Frame',color=TEXT_DIM); self._chart.setLabel('left','CD (nm)',color=TEXT_DIM)
        self._chart.setTitle("Live CD",color=TEXT_DIM,size="9pt"); self._chart.setFixedHeight(160)
        lay.addWidget(self._chart)
        self._live_cds=[]; self._live_xs=[]

    def set_detector(self, det: EdgeDetector) -> None: self._det = det
    def set_nmpx(self, npp: float) -> None: self._nmpx = npp

    def _build_cfg(self) -> AcquisitionConfig:
        c = AcquisitionConfig()
        mode_map = {0:'single',1:'continuous',2:'single',3:'triggered'}
        c.mode = mode_map.get(self._mode.currentIndex(),'single')
        c.frame_rate_hz = self._fps.value()
        c.n_frames      = self._nf.value() if self._mode.currentIndex()==2 else (1 if c.mode=='single' else 0)
        c.auto_analyze  = self._auto_ana.isChecked()
        c.auto_save     = self._auto_save.isChecked()
        return c

    def _start(self) -> None:
        if self._thread and self._thread.isRunning(): return
        cfg = self._build_cfg()
        self._thread = LiveAcquisitionThread(cfg, self._det)
        self._thread.frame_ready.connect(lambda p,i,m: self.frame_acquired.emit(p,i,m))
        self._thread.analysis_ready.connect(self._on_result)
        self._thread.status_update.connect(lambda s: self._status_lbl.setText(s))
        self._thread.frame_count_upd.connect(lambda n: self._frame_lbl.setText(f"Frame: {n}"))
        self._thread.finished.connect(self._on_done)
        self._btn_start.setEnabled(False); self._btn_pause.setEnabled(True); self._btn_stop.setEnabled(True)
        self._thread.start()
        self._status_lbl.setStyleSheet(f"color:{GREEN};font-family:'Courier New',monospace;font-size:10px;")

    def _pause(self) -> None:
        if self._thread:
            if self._btn_pause.text()=="⏸ PAUSE":
                self._thread.pause(); self._btn_pause.setText("▶ RESUME")
            else:
                self._thread.resume(); self._btn_pause.setText("⏸ PAUSE")

    def _stop(self) -> None:
        if self._thread: self._thread.stop()

    def _on_result(self, r) -> None:
        self.result_ready.emit(r)
        self._live_xs.append(len(self._live_xs)+1)
        cd = r.cd_mean if r.cd_mean > 0 else float('nan')
        self._live_cds.append(cd)
        if len(self._live_cds) > 200:
            self._live_xs = self._live_xs[-200:]; self._live_cds = self._live_cds[-200:]
        self._chart.clear()
        valid = [(x,c) for x,c in zip(self._live_xs,self._live_cds) if not math.isnan(c)]
        if valid:
            xs,cs = zip(*valid)
            self._chart.plot(list(xs),list(cs),pen=mkPen(CYAN,width=1.5))
            window = min(10,len(cs))
            rm = [np.mean(cs[max(0,i-window):i+1]) for i in range(len(cs))]
            self._chart.plot(list(xs),rm,pen=mkPen(GREEN,width=1))
        if self._live_xs:
            self._chart.plot([self._live_xs[0],self._live_xs[-1]],[32,32],
                              pen=mkPen(TEXT_DIM,width=1,style=Qt.DashLine))

    def _on_done(self) -> None:
        self._btn_start.setEnabled(True); self._btn_pause.setEnabled(False); self._btn_stop.setEnabled(False)
        self._btn_pause.setText("⏸ PAUSE")
        self._status_lbl.setText("Done")
        self._status_lbl.setStyleSheet(f"color:{TEXT_DIM};font-family:'Courier New',monospace;font-size:10px;")
