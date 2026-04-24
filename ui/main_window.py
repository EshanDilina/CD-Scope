"""
cd_scope.ui.main_window
─────────────────────────
MainWindow: the top-level QMainWindow that owns the application state
and wires every layer together.

Dependency direction:
  main_window → ui.* → analysis.* → core.* → constants
                     → db.*
                     → control.*
                     → export.*
                     → io.*
"""
from __future__ import annotations
import csv, datetime, json, math, os
from pathlib import Path

import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QApplication, QSplitter, QTabWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QToolBar, QAction,
    QTreeWidget, QTreeWidgetItem, QDoubleSpinBox, QDialog,
    QDialogButtonBox, QFileDialog, QMessageBox, QProgressDialog,
    QTextEdit, QToolButton, QComboBox, QListWidget
)
from PyQt5.QtCore  import Qt, QTimer, pyqtSignal
from PyQt5.QtGui   import QColor, QPixmap, QImage, QFont

from cd_scope.constants import (STYLESHEET, BG_VOID, BG_DEEP, BG_PANEL, BG_CARD,
BORDER, CYAN, CYAN_DIM, GREEN, AMBER, RED, PURPLE,
                            TEXT_BR, TEXT_MID, TEXT_DIM, TARGET_CD)
from cd_scope.core import (EdgeDetector, EdgeResult, SEMLoader, SEMMeta,
HitachiWaferParser, WaferSite, PatternConfig,
                            PatternAnalyzer, PatternRecognizer, PATTERN_TYPES,
                            Recipe, RecipeManager)
from cd_scope.core.models import BatchImageRecord, ScannerExposure, DoseFocusPoint
from cd_scope.analysis import (AnalysisThread, BatchAnalysisThread,
LiveAcquisitionThread, AcquisitionConfig,
                            gen_synthetic_sem, gen_synthetic_contact,
                            DoseFocusAnalyzer, CDUStatistics)
from cd_scope.db import MetroscanDB
from cd_scope.control import APCController
from cd_scope.export import MetroscanExcelExporter
from cd_scope.io import BatchConditionParser, ScannerDataParser
from cd_scope.ui.sem_viewport import SEMViewport
from cd_scope.ui.wafer_map_widget import WaferMapPanel
from cd_scope.ui.chart_widgets import (make_profile_widget, make_spc_widget,
make_histogram_widget, make_lwr_widget,
                                make_psd_widget)
from cd_scope.ui.panels import (ResultsPanel, RecipePanel, DataTablePanel,
DoseFocusPanel, APCPanel, LiveAcquisitionPanel)


# ── Helper: nm/px manual-entry dialog ─────────────────────────────────────────

class _NmpxDialog(QDialog):
    def __init__(self, current: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set nm/px manually")
        self.setStyleSheet(STYLESHEET)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Enter nm per pixel:"))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.001, 100); self.spin.setDecimals(4)
        self.spin.setValue(current)
        lay.addWidget(self.spin)
        lay.addWidget(QLabel("(Hitachi CG6300 at 100kx ≈ 0.47 nm/px)"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """
    Application shell.  Owns all state, routes signals, delegates to panels.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CD_SCOPE v1.0 — CD-SEM Analysis Suite")
        self.resize(1720, 1000)
        self.setMinimumSize(1200, 700)
        self.setStyleSheet(STYLESHEET)

        # ── State ──────────────────────────────────────────────────────────────
        self._cur_img:    np.ndarray | None = None
        self._cur_meta:   SEMMeta    | None = None
        self._cur_result: EdgeResult | None = None
        self._sites:      list[WaferSite]   = []
        self._batch_records: list[BatchImageRecord] = []
        self._scanner_fields: list[ScannerExposure] = []
        self._pat_result: dict = {}
        self._tool        = "cd"
        self._false_color = False
        self._invert      = False
        self._zoom_idx    = 3
        self._zoom_steps  = [25, 50, 75, 100, 150, 200, 300, 400]

        # ── Services ───────────────────────────────────────────────────────────
        self._detector      = EdgeDetector()
        self._pattern_cfg   = PatternConfig()
        self._recipe_mgr    = RecipeManager()
        self._current_recipe= Recipe("Default")
        self._db            = MetroscanDB()
        self._apc_ctrl      = APCController()
        self._ana_thread: AnalysisThread | None         = None
        self._batch_thread: BatchAnalysisThread | None  = None

        # ── Build UI ───────────────────────────────────────────────────────────
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._start_clock()
        QTimer.singleShot(300, self._acquire_synthetic)

    # ══════════════════════════════════════════════════════════════════════════
    # MENU BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_menu(self):
        mb = self.menuBar()

        def add(menu, label, fn=None, shortcut=None):
            a = menu.addAction(label)
            if fn:        a.triggered.connect(fn)
            if shortcut:  a.setShortcut(shortcut)

        # File
        fm = mb.addMenu("File")
        add(fm, "Open SEM Image…",          self._open_image,       "Ctrl+O")
        add(fm, "Open Image Folder…",        self._open_folder)
        fm.addSeparator()
        add(fm, "Import Batch Condition File…", self._import_batch)
        add(fm, "Save Batch Template…",      self._save_batch_template)
        add(fm, "Import Hitachi Wafer Map…", self._import_wafer_map)
        add(fm, "Import Scanner Data File…", self._import_scanner)
        add(fm, "Save Scanner Template…",    self._save_scanner_template)
        add(fm, "Import Metadata Sidecar…",  self._import_sidecar)
        fm.addSeparator()
        add(fm, "Export CSV…",               self._export_csv,       "Ctrl+E")
        add(fm, "Export to Excel (with Charts)…", self._export_excel,"Ctrl+Shift+E")
        fm.addSeparator()
        add(fm, "Exit",                      self.close,             "Ctrl+Q")

        # Measure
        mm = mb.addMenu("Measure")
        for t, k in [("CD Line","cd"),("Pitch","pitch"),("Space","space"),
                     ("Edge","edge"),("LWR","lwr"),("LER","ler")]:
            add(mm, t, lambda _=None, k=k: self._set_tool(k))
        mm.addSeparator()
        add(mm, "Clear All Measurements", self._clear_meas)

        # Analysis
        am = mb.addMenu("Analysis")
        add(am, "Run Edge Detection",        self._run_analysis,     "F5")
        add(am, "Acquire Synthetic L/S",     self._acquire_synthetic,"F6")
        add(am, "Acquire Synthetic Contacts",self._acquire_contacts, "F7")
        am.addSeparator()
        add(am, "Run Batch Analysis…",       self._run_batch,        "F8")
        add(am, "Auto-Detect Pattern",       self._auto_detect,      "Ctrl+T")
        am.addSeparator()
        add(am, "Enter nm/px Manually…",     self._manual_nmpx)

        # Pattern
        pm = mb.addMenu("Pattern")
        for pat in PATTERN_TYPES[:-1]:
            add(pm, pat, lambda _=None, p=pat: self._set_pattern(p))
        pm.addSeparator()
        add(pm, "Custom L:S Ratio…", self._custom_ls)

        # Recipe
        rm = mb.addMenu("Recipe")
        add(rm, "Recipe Manager…",          self._open_recipe_mgr,  "Ctrl+R")
        add(rm, "Save Current as Recipe…",  self._save_recipe)
        add(rm, "Add Run to History",        self._add_run_history)

        # Dose-Focus
        dm = mb.addMenu("Dose-Focus")
        add(dm, "Show Dose-Focus Panel",     self._show_df_tab,      "Ctrl+D")
        add(dm, "Load from Batch+Scanner",   self._load_df)
        add(dm, "Generate Demo Matrix",      self._demo_df)

        # Database
        dbm = mb.addMenu("Database")
        add(dbm, "Browse Database…",         self._open_db,          "Ctrl+B")
        add(dbm, "Save Wafer to DB",          self._save_wafer_db)
        add(dbm, "Save Batch to DB",          self._save_batch_db)
        add(dbm, "DB Statistics",             self._db_stats)

        # APC
        apcm = mb.addMenu("APC")
        add(apcm, "Open APC Panel",           self._show_apc_tab,    "Ctrl+A")
        add(apcm, "Feed Current CD to APC",   self._feed_apc)
        add(apcm, "CDU Statistics…",          self._show_cdu_stats)
        add(apcm, "Reset APC",                lambda: self._apc_ctrl.reset())

        # Acquire
        acqm = mb.addMenu("Acquire")
        add(acqm, "Open Live Acquisition",    self._show_live_tab,   "Ctrl+L")
        add(acqm, "Single Frame",             self._acquire_synthetic,"F6")

        # Report
        rpt = mb.addMenu("Report")
        add(rpt, "Generate PDF Report…",      self._gen_pdf,         "Ctrl+P")
        add(rpt, "Export to Excel…",          self._export_excel,    "Ctrl+Shift+E")

        # Help
        hm = mb.addMenu("Help")
        add(hm, "File Format Guide",          self._show_fmt_guide)
        add(hm, "About CD_SCOPE",            self._show_about)

    # ══════════════════════════════════════════════════════════════════════════
    # TOOLBAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_toolbar(self):
        tb = QToolBar("Main", self); tb.setMovable(False)
        self.addToolBar(tb)
        self._tbns: dict[str, QToolButton] = {}

        # Measurement tools
        for k, lbl in [("cd","⊢ CD"),("pitch","⇿ PITCH"),("space","⊣ SPACE"),
                        ("edge","◈ EDGE"),("lwr","≋ LWR"),("ler","≈ LER")]:
            b = QToolButton(); b.setText(lbl); b.setCheckable(True)
            b.setChecked(k == "cd")
            b.clicked.connect(lambda _=None, k=k: self._set_tool(k))
            tb.addWidget(b); self._tbns[k] = b

        tb.addSeparator()
        for lbl, fn in [("▶ RUN",self._run_analysis),
                         ("⟳ ACQUIRE",self._acquire_synthetic),
                         ("✕ CLEAR",self._clear_meas)]:
            b = QToolButton(); b.setText(lbl); b.clicked.connect(fn); tb.addWidget(b)

        tb.addSeparator()
        tb.addWidget(QLabel("  ZOOM: "))
        self._btn_zm = QToolButton(); self._btn_zm.setText("−"); self._btn_zm.clicked.connect(lambda: self._zoom(-1)); tb.addWidget(self._btn_zm)
        self._zoom_lbl = QToolButton(); self._zoom_lbl.setText("100%"); self._zoom_lbl.clicked.connect(self._reset_zoom); self._zoom_lbl.setFixedWidth(52); tb.addWidget(self._zoom_lbl)
        self._btn_zp = QToolButton(); self._btn_zp.setText("+"); self._btn_zp.clicked.connect(lambda: self._zoom(1)); tb.addWidget(self._btn_zp)

        tb.addSeparator()
        self._inv_btn = QToolButton(); self._inv_btn.setText("◑ INV"); self._inv_btn.setCheckable(True); self._inv_btn.clicked.connect(self._toggle_inv); tb.addWidget(self._inv_btn)
        self._fc_btn  = QToolButton(); self._fc_btn.setText("🌈 FC");  self._fc_btn.setCheckable(True); self._fc_btn.clicked.connect(self._toggle_fc);  tb.addWidget(self._fc_btn)

        tb.addSeparator()
        for lbl, fn in [("📂 OPEN",self._open_image),
                         ("📥 WAFER",self._import_wafer_map),
                         ("📦 BATCH",self._import_batch),
                         ("📡 SCANNER",self._import_scanner),
                         ("🔬 DETECT",self._auto_detect),
                         ("📋 RECIPE",self._open_recipe_mgr),
                         ("🗄 DB",self._open_db),
                         ("📡 LIVE",self._show_live_tab),
                         ("⚙ APC",self._show_apc_tab),
                         ("📄 PDF",self._gen_pdf),
                         ("⬇ EXCEL",self._export_excel)]:
            b = QToolButton(); b.setText(lbl); b.clicked.connect(fn); tb.addWidget(b)

        tb.addSeparator()
        tb.addWidget(QLabel("  PATTERN: "))
        self._pat_combo = QComboBox()
        self._pat_combo.addItems(PATTERN_TYPES); self._pat_combo.setFixedWidth(162)
        self._pat_combo.currentTextChanged.connect(self._set_pattern)
        self._pat_combo.setStyleSheet(
            f"background:{BG_CARD};color:{CYAN};border:1px solid {BORDER};"
            f"font-size:11px;padding:2px 6px;")
        tb.addWidget(self._pat_combo)

    # ══════════════════════════════════════════════════════════════════════════
    # CENTRAL WIDGET
    # ══════════════════════════════════════════════════════════════════════════

    def _build_central(self):
        c = QWidget(); self.setCentralWidget(c)
        hl = QHBoxLayout(c); hl.setContentsMargins(0,0,0,0); hl.setSpacing(0)
        hs = QSplitter(Qt.Horizontal); hs.setHandleWidth(2); hl.addWidget(hs)
        hs.addWidget(self._build_left())
        hs.addWidget(self._build_center())
        hs.addWidget(self._build_right())
        hs.setSizes([210, 1170, 330]); hs.setStretchFactor(1, 1)

    # ── Left: file browser ─────────────────────────────────────────────────────

    def _build_left(self):
        p = QWidget(); p.setFixedWidth(210)
        p.setStyleSheet(f"background:{BG_PANEL};border-right:1px solid {BORDER};")
        lay = QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        hdr = QLabel("  FILE BROWSER"); hdr.setFixedHeight(28)
        hdr.setStyleSheet(f"background:{BG_DEEP};color:{TEXT_DIM};"
                          f"font-family:'Courier New',monospace;font-size:9px;"
                          f"letter-spacing:2px;border-bottom:1px solid {BORDER};padding-left:10px;")
        lay.addWidget(hdr)

        self._tree = QTreeWidget(); self._tree.setHeaderHidden(True); self._tree.setIndentation(14)
        root = QTreeWidgetItem(self._tree, ["📁  No folder loaded"])
        root.setForeground(0, QColor(TEXT_DIM)); root.setExpanded(True)
        QTreeWidgetItem(root, ["🖼  Synthetic images"]).setForeground(0, QColor(TEXT_MID))
        self._tree.itemClicked.connect(self._tree_clicked)
        lay.addWidget(self._tree)

        # Bottom summary
        bot = QWidget(); bot.setFixedHeight(80)
        bot.setStyleSheet(f"border-top:1px solid {BORDER};")
        bl = QVBoxLayout(bot); bl.setContentsMargins(10,6,10,6); bl.setSpacing(3)
        self._sb_nm  = self._stat_lbl(bl, "nm/px",    "—")
        self._sb_fw  = self._stat_lbl(bl, "FoV (µm)", "—")
        self._sb_src = self._stat_lbl(bl, "Source",   "—")
        lay.addWidget(bot)
        return p

    def _stat_lbl(self, lay, name, val):
        w = QWidget(); w.setFixedHeight(22); rl = QHBoxLayout(w); rl.setContentsMargins(0,0,0,0)
        l = QLabel(name); l.setStyleSheet(f"color:{TEXT_MID};font-size:11px;")
        v = QLabel(val);  v.setStyleSheet(f"color:{TEXT_BR};font-family:'Courier New',monospace;font-size:11px;")
        v.setAlignment(Qt.AlignRight)
        rl.addWidget(l); rl.addStretch(); rl.addWidget(v)
        lay.addWidget(w); return v

    # ── Centre: viewport + bottom tabs ─────────────────────────────────────────

    def _build_center(self):
        p = QWidget(); lay = QVBoxLayout(p)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        vs = QSplitter(Qt.Vertical); vs.setHandleWidth(2); lay.addWidget(vs)
        self.sem_view = SEMViewport()
        self.sem_view.measure_done.connect(
            lambda nm: self._sb_meas_lbl.setText(f"Last: {nm:.2f}nm"))
        vs.addWidget(self.sem_view)
        vs.addWidget(self._build_bottom_tabs())
        vs.setSizes([560, 240]); vs.setStretchFactor(0, 1)
        return p

    def _build_bottom_tabs(self):
        p = QWidget(); lay = QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        self._btabs = QTabWidget(); lay.addWidget(self._btabs)

        self._profile_wgt = make_profile_widget(None)
        self._btabs.addTab(self._profile_wgt, "PROFILE")            # 0

        self._spc_wgt = make_spc_widget([])
        self._btabs.addTab(self._spc_wgt, "SPC")                    # 1

        hw = QWidget(); hl = QHBoxLayout(hw); hl.setContentsMargins(0,0,0,0)
        self._hist_wgt = make_histogram_widget([])
        self._lwr_wgt  = make_lwr_widget([])
        from PyQt5.QtWidgets import QFrame
        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color:{BORDER};")
        hl.addWidget(self._hist_wgt); hl.addWidget(sep); hl.addWidget(self._lwr_wgt)
        self._btabs.addTab(hw, "CD HISTOGRAM")                      # 2

        self._psd_wgt = make_psd_widget(None)
        self._btabs.addTab(self._psd_wgt, "LWR PSD")                # 3

        self._wafer_map_panel = WaferMapPanel()
        self._wafer_map_panel.site_selected.connect(self._on_site_selected)
        self._btabs.addTab(self._wafer_map_panel, "WAFER MAP")       # 4

        self._df_panel = DoseFocusPanel()
        self._btabs.addTab(self._df_panel, "DOSE-FOCUS")            # 5

        self._apc_panel = APCPanel()
        self._apc_panel.correction_ready.connect(
            lambda cur, nxt: self.statusBar().showMessage(
                f"  APC: dose {cur:.3f} → {nxt:.3f} mJ/cm²", 5000))
        self._btabs.addTab(self._apc_panel, "APC")                  # 6

        self._live_panel = LiveAcquisitionPanel(self._detector)
        self._live_panel.frame_acquired.connect(self._on_live_frame)
        self._live_panel.result_ready.connect(self._on_result)
        self._btabs.addTab(self._live_panel, "LIVE ACQ")             # 7

        self._data_table = DataTablePanel()
        self._btabs.addTab(self._data_table, "DATA TABLE")           # 8
        return p

    # ── Right: results / recipe / metadata ─────────────────────────────────────

    def _build_right(self):
        p = QWidget(); p.setFixedWidth(330)
        p.setStyleSheet(f"background:{BG_PANEL};border-left:1px solid {BORDER};")
        lay = QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        self._rtabs = QTabWidget(); lay.addWidget(self._rtabs)
        self._results = ResultsPanel(); self._rtabs.addTab(self._results, "RESULTS")
        self._recipe  = RecipePanel();  self._rtabs.addTab(self._recipe,  "RECIPE")
        self._recipe.btn_apply.clicked.connect(self._run_analysis)
        self._recipe.btn_nm.clicked.connect(self._manual_nmpx)
        self._meta_txt = QTextEdit(); self._meta_txt.setReadOnly(True)
        self._meta_txt.setStyleSheet(
            f"font-family:'Courier New',monospace;font-size:11px;"
            f"background:{BG_DEEP};border:none;")
        self._rtabs.addTab(self._meta_txt, "METADATA")
        return p

    # ══════════════════════════════════════════════════════════════════════════
    # STATUS BAR
    # ══════════════════════════════════════════════════════════════════════════

    def _build_statusbar(self):
        sb = self.statusBar(); sb.setFixedHeight(24)
        mono = f"color:{TEXT_DIM};font-family:'Courier New',monospace;font-size:10px;padding:0 8px;"
        self._sb_tool_lbl = QLabel("TOOL: CD LINE"); self._sb_tool_lbl.setStyleSheet(mono)
        self._sb_meas_lbl = QLabel("Last: —");        self._sb_meas_lbl.setStyleSheet(mono)
        self._sb_algo_lbl = QLabel("ALGO: —");         self._sb_algo_lbl.setStyleSheet(mono)
        self._sb_src_lbl  = QLabel("SRC: synthetic");  self._sb_src_lbl.setStyleSheet(mono)
        self._sb_status   = QLabel("READY")
        self._sb_status.setStyleSheet(f"color:{GREEN};font-family:'Courier New',monospace;font-size:10px;padding:0 8px;")
        self._sb_clock    = QLabel()
        self._sb_clock.setStyleSheet(mono)
        for w in [self._sb_tool_lbl, self._sb_meas_lbl,
                  self._sb_algo_lbl, self._sb_src_lbl, self._sb_status]:
            sb.addWidget(w)
            sep = QLabel("|"); sep.setStyleSheet(f"color:{BORDER};"); sb.addWidget(sep)
        sb.addPermanentWidget(self._sb_clock)

    def _start_clock(self):
        t = QTimer(self)
        t.timeout.connect(lambda: self._sb_clock.setText(
            datetime.datetime.now().strftime("%b %d, %Y  %H:%M:%S")))
        t.start(1000); t.timeout.emit()

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS — tools, zoom, display
    # ══════════════════════════════════════════════════════════════════════════

    def _set_tool(self, t: str):
        self._tool = t
        for k, b in self._tbns.items(): b.setChecked(k == t)
        self.sem_view.set_tool(t)
        self._sb_tool_lbl.setText(f"TOOL: {t.upper()}")

    def _zoom(self, d: int):
        self._zoom_idx = max(0, min(len(self._zoom_steps)-1, self._zoom_idx+d))
        z = self._zoom_steps[self._zoom_idx] / 100.0
        self._zoom_lbl.setText(f"{self._zoom_steps[self._zoom_idx]}%")
        self.sem_view.set_zoom(z)

    def _reset_zoom(self):
        self._zoom_idx = 3; self._zoom_lbl.setText("100%"); self.sem_view.set_zoom(1.0)

    def _toggle_fc(self):
        self._false_color = not self._false_color
        self._fc_btn.setChecked(self._false_color)
        if self._cur_img is not None: self._redraw()
        else: self._acquire_synthetic()

    def _toggle_inv(self):
        self._invert = not self._invert
        self._inv_btn.setChecked(self._invert)
        if self._cur_img is not None: self._redraw()
        else: self._acquire_synthetic()

    def _redraw(self):
        if self._cur_img is None: return
        img = self._cur_img.copy()
        if self._invert: img = 255 - img
        H, W = img.shape
        if self._false_color:
            t = img.astype(np.float32)/255
            r = np.clip(t*2, 0, 1)
            g = np.clip(np.where(t > 0.5, 1-(t-0.5)*2, t*2), 0, 1)
            b = np.clip(1-t*2, 0, 1)
            rgb = np.stack([(r*255).astype(np.uint8),(g*255).astype(np.uint8),(b*255).astype(np.uint8)], axis=-1)
            qi = QImage(rgb.tobytes(), W, H, W*3, QImage.Format_RGB888)
        else:
            qi = QImage(img.tobytes(), W, H, W, QImage.Format_Grayscale8)
        pix = QPixmap.fromImage(qi)
        self.sem_view.set_image(pix, self._cur_img, self._cur_meta, self._cur_result)

    def _clear_meas(self): self.sem_view.clear_measurements()

    def _set_pattern(self, pat: str):
        self._pattern_cfg = PatternConfig.from_string(pat)
        if hasattr(self, '_pat_combo'):
            if pat in PATTERN_TYPES:
                self._pat_combo.blockSignals(True)
                self._pat_combo.setCurrentIndex(PATTERN_TYPES.index(pat))
                self._pat_combo.blockSignals(False)
        self._sb_algo_lbl.setText(f"PAT: {pat[:22]}")
        self.statusBar().showMessage(f"  Pattern: {pat}", 3000)
        self._run_analysis()

    def _custom_ls(self):
        dlg = QDialog(self); dlg.setWindowTitle("Custom L:S Ratio")
        dlg.setStyleSheet(STYLESHEET); lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Line fraction:")); ls = QDoubleSpinBox(); ls.setRange(0.1,10); ls.setValue(1.0); lay.addWidget(ls)
        lay.addWidget(QLabel("Space fraction:")); ss = QDoubleSpinBox(); ss.setRange(0.1,10); ss.setValue(1.0); lay.addWidget(ss)
        bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); lay.addWidget(bb)
        if dlg.exec_() == QDialog.Accepted:
            self._pattern_cfg.ls_ratio_line  = ls.value()
            self._pattern_cfg.ls_ratio_space = ss.value()
            self._pattern_cfg.pattern_type   = "Custom L:S Ratio"
            self._pattern_cfg.is_contact     = False
            self._run_analysis()

    # ══════════════════════════════════════════════════════════════════════════
    # IMAGE LOADING
    # ══════════════════════════════════════════════════════════════════════════

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SEM Image", "",
            "SEM Images (*.tif *.tiff *.png *.jpg *.bmp);;All Files (*)")
        if not path: return
        try:
            img, meta = SEMLoader.load(path)
            self._load_image(img, meta)
            self._add_tree_file(path)
            self.statusBar().showMessage(f"  Loaded: {os.path.basename(path)}  [{meta.source}]", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Image Folder")
        if not folder: return
        exts = {'.tif','.tiff','.png','.jpg','.bmp'}
        files = sorted(f for f in os.listdir(folder) if Path(f).suffix.lower() in exts)
        if not files:
            QMessageBox.information(self, "No images", "No SEM images found."); return
        root = self._tree.invisibleRootItem(); root.takeChildren()
        fi = QTreeWidgetItem(self._tree, [f"📁  {os.path.basename(folder)}"])
        fi.setForeground(0, QColor(TEXT_MID)); fi.setExpanded(True)
        for f in files:
            ci = QTreeWidgetItem(fi, [f"🖼  {f}"])
            ci.setForeground(0, QColor(TEXT_MID))
            ci.setData(0, Qt.UserRole, os.path.join(folder, f))
        try:
            img, meta = SEMLoader.load(os.path.join(folder, files[0]))
            self._load_image(img, meta)
        except Exception: pass

    def _load_image(self, img, meta):
        self._cur_img = img; self._cur_meta = meta
        self._update_meta_panel(meta)
        self._sb_nm.setText(f"{meta.nm_per_px:.4f}")
        self._sb_fw.setText(f"{meta.field_width_nm/1000:.3f}")
        self._sb_src.setText(meta.source)
        self._sb_src_lbl.setText(f"SRC: {meta.source}")
        self._redraw(); self._run_analysis()

    def _add_tree_file(self, path):
        root = self._tree.invisibleRootItem()
        parent = root.child(0) if root.childCount() > 0 else root
        fi = QTreeWidgetItem(parent, [f"🖼  {os.path.basename(path)}"])
        fi.setForeground(0, QColor(CYAN)); fi.setData(0, Qt.UserRole, path)
        if parent != root: parent.setExpanded(True)

    def _tree_clicked(self, item, _):
        path = item.data(0, Qt.UserRole)
        if path and os.path.isfile(path):
            try:
                img, meta = SEMLoader.load(path); self._load_image(img, meta)
            except Exception as e:
                self.statusBar().showMessage(f"  Error: {e}", 4000)

    def _import_sidecar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Metadata Sidecar", "",
            "Metadata (*.txt *.json *.xml *.ini);;All Files (*)")
        if not path or not self._cur_meta: return
        txt = Path(path).read_text(errors='ignore')
        SEMLoader._keyvalue(txt, self._cur_meta)
        self._update_meta_panel(self._cur_meta)
        self._sb_nm.setText(f"{self._cur_meta.nm_per_px:.4f}")
        QMessageBox.information(self, "Loaded", f"nm/px = {self._cur_meta.nm_per_px:.4f}")

    # ══════════════════════════════════════════════════════════════════════════
    # ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════

    def _acquire_synthetic(self):
        self._set_status("ACQUIRING…", AMBER); QApplication.processEvents()
        W = max(self.sem_view.width(), 512); H = max(self.sem_view.height(), 512)
        npp = self._cur_meta.nm_per_px if self._cur_meta else 0.49
        pix, img, meta = gen_synthetic_sem(W, H, npp, perturb=0.5,
                                            false_color=self._false_color,
                                            invert=self._invert)
        self._cur_img = img; self._cur_meta = meta
        self._update_meta_panel(meta)
        self._sb_nm.setText(f"{meta.nm_per_px:.4f}")
        self._sb_fw.setText(f"{meta.field_width_nm/1000:.3f}")
        self._sb_src.setText(meta.source)
        self.sem_view.set_image(pix, img, meta, None)
        self._set_status("READY", GREEN)
        QTimer.singleShot(100, self._run_analysis)

    def _acquire_contacts(self):
        self._set_pattern("Contact Hole Array")
        self._set_status("ACQUIRING CONTACTS…", AMBER); QApplication.processEvents()
        W = max(self.sem_view.width(), 512); H = max(self.sem_view.height(), 512)
        pix, img, meta = gen_synthetic_contact(W, H, 0.49,
                                                cd_nm=self._pattern_cfg.target_cd,
                                                pitch_nm=self._pattern_cfg.target_pitch,
                                                false_color=self._false_color)
        self._cur_img = img; self._cur_meta = meta
        self._update_meta_panel(meta)
        self.sem_view.set_image(pix, img, meta, None)
        self._set_status("READY", GREEN)
        QTimer.singleShot(100, self._run_analysis)

    def _run_analysis(self):
        if self._cur_img is None:
            self._acquire_synthetic(); return
        if self._ana_thread and self._ana_thread.isRunning(): return
        det = self._recipe.get_detector()
        npp = self._cur_meta.nm_per_px if self._cur_meta else 0.49
        self._set_status("ANALYZING…", AMBER)
        self._sb_algo_lbl.setText(f"ALGO: {det.ALGOS[det.algo][:18]}")
        self._ana_thread = AnalysisThread(self._cur_img, npp, det)
        self._ana_thread.result_ready.connect(self._on_result)
        self._ana_thread.error.connect(lambda e: self._set_status("ERROR", RED))
        self._ana_thread.start()

    def _on_result(self, r: EdgeResult):
        self._cur_result = r
        # Run pattern-level analysis on top
        if self._cur_img is not None:
            npp = self._cur_meta.nm_per_px if self._cur_meta else 0.49
            pa = PatternAnalyzer(self._recipe.get_detector(), self._pattern_cfg)
            self._pat_result = pa.analyse(self._cur_img, npp)
        self.sem_view.set_edge_result(r)
        self._redraw()
        self._results.update_from_edge(r)
        self._rebuild_profile(r)
        self._rebuild_psd(r)
        if not self._pattern_cfg.is_contact:
            ls = self._pat_result.get('ls_ratio_meas', 0)
            dc = self._pat_result.get('duty_cycle', 0)
            if ls > 0:
                self.statusBar().showMessage(
                    f"  L/S: {ls:.2f}  Duty: {dc:.1f}%  "
                    f"CD bias: {self._pat_result.get('cd_bias',0):+.2f} nm", 5000)
        self._set_status("READY", GREEN)
        if r.error:
            self.statusBar().showMessage(f"  ⚠ {r.error[:100]}", 6000)

    def _rebuild_profile(self, r):
        idx = 0; old = self._btabs.widget(idx)
        new = make_profile_widget(r)
        self._btabs.removeTab(idx); self._btabs.insertTab(idx, new, "PROFILE")
        self._profile_wgt = new

    def _rebuild_psd(self, r):
        idx = 3; old = self._btabs.widget(idx)
        new = make_psd_widget(r)
        self._btabs.removeTab(idx); self._btabs.insertTab(idx, new, "LWR PSD")
        self._psd_wgt = new

    def _refresh_charts(self, sites):
        # SPC
        idx = 1; new = make_spc_widget(sites)
        self._btabs.removeTab(idx); self._btabs.insertTab(idx, new, "SPC"); self._spc_wgt = new
        # Histograms
        idx = 2
        from PyQt5.QtWidgets import QFrame
        hw = QWidget(); hl = QHBoxLayout(hw); hl.setContentsMargins(0,0,0,0); hl.setSpacing(0)
        h2 = make_histogram_widget(sites); l2 = make_lwr_widget(sites)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setStyleSheet(f"color:{BORDER};")
        hl.addWidget(h2); hl.addWidget(sep); hl.addWidget(l2)
        self._btabs.removeTab(idx); self._btabs.insertTab(idx, hw, "CD HISTOGRAM")
        self._hist_wgt = h2; self._lwr_wgt = l2

    # ══════════════════════════════════════════════════════════════════════════
    # WAFER MAP + SITE EVENTS
    # ══════════════════════════════════════════════════════════════════════════

    def _import_wafer_map(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Wafer Map", "",
            "Measurement Files (*.csv *.txt *.xml *.mdf *.map);;All Files (*)")
        if not path: return
        try:
            sites = HitachiWaferParser.parse(path)
            if not sites:
                QMessageBox.warning(self, "Parse Error", "No site data found."); return
            self._sites = sites
            self._wafer_map_panel.set_sites(sites)
            self._data_table.update_sites(sites)
            self._results.update_from_sites(sites)
            self._refresh_charts(sites)
            self._btabs.setCurrentIndex(4)
            QMessageBox.information(self, "Import OK", f"Loaded {len(sites)} sites.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _on_site_selected(self, site: WaferSite):
        self._results.update_from_sites([site])
        self.statusBar().showMessage(
            f"  Site {site.site_id}: CD={site.cd_mean:.2f}nm  "
            f"LWR={site.lwr:.2f}nm  {site.status}", 5000)

    # ══════════════════════════════════════════════════════════════════════════
    # BATCH
    # ══════════════════════════════════════════════════════════════════════════

    def _import_batch(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Batch Condition File", "",
            "Condition Files (*.csv *.json *.ini *.cfg *.txt);;All Files (*)")
        if not path: return
        try:
            records = BatchConditionParser.parse(path)
            if not records:
                QMessageBox.warning(self, "Parse Error", "No image records found."); return
            self._batch_records = records
            QMessageBox.information(self, "Loaded",
                f"Loaded {len(records)} image records.\n"
                f"Click Analysis → Run Batch Analysis to process all images.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _save_batch_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Batch Template",
            "batch_condition.csv", "CSV (*.csv)")
        if path:
            BatchConditionParser.write_template(path)
            QMessageBox.information(self, "Saved", f"Template saved:\n{path}")

    def _run_batch(self):
        if not self._batch_records:
            QMessageBox.information(self, "No Batch", "Import a batch file first."); return
        if self._batch_thread and self._batch_thread.isRunning():
            QMessageBox.warning(self, "Running", "Batch already running."); return
        prog = QProgressDialog("Running batch…", "Cancel", 0, 100, self)
        prog.setStyleSheet(STYLESHEET); prog.setMinimumWidth(400)
        prog.setWindowTitle("Batch Analysis"); prog.show()
        self._batch_thread = BatchAnalysisThread(
            self._batch_records, self._recipe.get_detector(), self._pattern_cfg)
        self._batch_thread.progress.connect(
            lambda pct, msg: (prog.setValue(pct), prog.setLabelText(msg)))
        self._batch_thread.finished_all.connect(
            lambda recs: self._on_batch_done(recs, prog))
        prog.canceled.connect(self._batch_thread.terminate)
        self._batch_thread.start()

    def _on_batch_done(self, records, prog):
        prog.close(); self._batch_records = records
        self._data_table.update_sites([])
        sites = [WaferSite(r.site_id, r.x_mm, r.y_mm, r.cd_mean,
                            r.cd_std, r.lwr_3s, r.status, r.pitch_mean, r.space_mean)
                 for r in records if r.cd_mean > 0]
        if sites:
            self._sites = sites
            self._wafer_map_panel.set_sites(sites)
            self._results.update_from_sites(sites)
            self._refresh_charts(sites)
            self._btabs.setCurrentIndex(4)
        n_pass = sum(1 for r in records if r.status=='PASS')
        n_fail = sum(1 for r in records if r.status=='FAIL')
        QMessageBox.information(self, "Batch Complete",
            f"Total: {len(records)}  PASS: {n_pass}  FAIL: {n_fail}")

    # ══════════════════════════════════════════════════════════════════════════
    # SCANNER
    # ══════════════════════════════════════════════════════════════════════════

    def _import_scanner(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Scanner Data", "",
            "Scanner Files (*.csv *.txt *.dat *.json);;All Files (*)")
        if not path: return
        try:
            fields = ScannerDataParser.parse(path)
            if not fields:
                QMessageBox.warning(self, "Parse Error", "No exposure fields found."); return
            self._scanner_fields = fields
            self._match_scanner_to_batch(fields)
            d_range = max(f.dose for f in fields) - min(f.dose for f in fields)
            f_range = max(f.focus for f in fields) - min(f.focus for f in fields)
            QMessageBox.information(self, "Loaded",
                f"Loaded {len(fields)} exposure fields.\n"
                f"Dose range: {d_range:.2f} mJ/cm²\n"
                f"Focus range: {f_range:.3f} µm")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _match_scanner_to_batch(self, fields):
        fmap = {f.field_id.lower(): f for f in fields}
        for rec in self._batch_records:
            key = rec.site_id.lower()
            if key in fmap:
                rec.dose = fmap[key].dose; rec.focus = fmap[key].focus
            elif fields:
                dists = [math.sqrt((f.x_mm-rec.x_mm)**2+(f.y_mm-rec.y_mm)**2) for f in fields]
                nearest = fields[dists.index(min(dists))]
                if min(dists) < 5.0:
                    rec.dose = nearest.dose; rec.focus = nearest.focus

    def _save_scanner_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Scanner Template",
            "scanner_data.csv", "CSV (*.csv)")
        if path:
            ScannerDataParser.write_template(path)
            QMessageBox.information(self, "Saved", f"Template saved:\n{path}")

    # ══════════════════════════════════════════════════════════════════════════
    # RECIPE MANAGER
    # ══════════════════════════════════════════════════════════════════════════

    def _open_recipe_mgr(self):
        from cd_scope.dialogs import RecipeManagerDialog
        dlg = RecipeManagerDialog(self._recipe_mgr, self._current_recipe, self)
        dlg.recipe_selected.connect(self._apply_recipe)
        dlg.exec_()

    def _apply_recipe(self, recipe: Recipe):
        self._current_recipe = recipe
        try:
            self._recipe.name.setText(recipe.name)
            self._recipe.algo.setCurrentIndex(recipe.algo)
            self._recipe.sigma.setValue(recipe.sigma_nm)
            self._recipe.tgt.setValue(recipe.target_cd)
            self._recipe.lwr_max.setValue(recipe.lwr_max)
            self._recipe.cpk_min.setValue(recipe.cpk_min)
        except Exception: pass
        if recipe.pattern_type in PATTERN_TYPES:
            self._set_pattern(recipe.pattern_type)
        else:
            self._run_analysis()
        self.statusBar().showMessage(f"  Recipe loaded: {recipe.name}", 4000)

    def _save_recipe(self):
        dlg = QDialog(self); dlg.setWindowTitle("Save Recipe"); dlg.setStyleSheet(STYLESHEET)
        lay = QVBoxLayout(dlg); lay.addWidget(QLabel("Name:"))
        from PyQt5.QtWidgets import QLineEdit
        le = QLineEdit(self._current_recipe.name); lay.addWidget(le)
        bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); lay.addWidget(bb)
        if dlg.exec_() == QDialog.Accepted:
            r = self._current_recipe; r.name = le.text() or r.name
            det = self._recipe.get_detector()
            r.algo = det.algo; r.sigma_nm = det.sigma_nm
            r.pattern_type = self._pattern_cfg.pattern_type
            try: r.target_cd = self._recipe.tgt.value()
            except Exception: pass
            self._recipe_mgr.save(r)
            QMessageBox.information(self, "Saved", f"Recipe '{r.name}' saved.")

    def _add_run_history(self):
        if not self._cur_result: return
        r = self._current_recipe
        r.add_run(self._cur_result.cd_mean, self._cur_result.cd_std,
                  self._cur_result.lwr_3s,
                  len(self._sites) or len(self._cur_result.cd_values))
        self._recipe_mgr.save(r)
        self.statusBar().showMessage(f"  Run added to '{r.name}' history.", 3000)

    # ══════════════════════════════════════════════════════════════════════════
    # DOSE-FOCUS
    # ══════════════════════════════════════════════════════════════════════════

    def _show_df_tab(self):
        for i in range(self._btabs.count()):
            if self._btabs.tabText(i) == "DOSE-FOCUS":
                self._btabs.setCurrentIndex(i); return

    def _load_df(self):
        n = self._df_panel.load_from_scanner_and_batch(
                self._scanner_fields, self._batch_records)
        if n == 0:
            QMessageBox.information(self, "No Data",
                "No dose-focus data. Import scanner + batch results first.")
        else:
            self._show_df_tab()
            self.statusBar().showMessage(f"  Dose-focus: {n} points loaded", 4000)

    def _demo_df(self):
        import random
        doses   = [27.0,28.0,29.0,30.0,31.0]
        focuses = [-0.06,-0.04,-0.02,0.0,0.02,0.04,0.06]
        pts = [DoseFocusPoint(d, f,
                              round(32+(d-29)*1.2-8*f**2+random.gauss(0,0.3),2),
                              round(abs(random.gauss(0,0.3)),2),
                              round(abs(random.gauss(2.5,0.4)),2))
               for d in doses for f in focuses]
        self._df_panel.set_points(pts); self._show_df_tab()
        self.statusBar().showMessage(f"  Demo dose-focus: {len(pts)} points", 5000)

    # ══════════════════════════════════════════════════════════════════════════
    # APC
    # ══════════════════════════════════════════════════════════════════════════

    def _show_apc_tab(self):
        for i in range(self._btabs.count()):
            if self._btabs.tabText(i) == "APC":
                self._btabs.setCurrentIndex(i); return

    def _feed_apc(self):
        if not self._cur_result or self._cur_result.cd_mean <= 0:
            QMessageBox.information(self, "No CD", "Run analysis first."); return
        cd = self._cur_result.cd_mean
        try: dose = self._apc_panel._dose_in.value()
        except: dose = 28.0
        rec = self._apc_panel.feed_measurement(cd, dose)
        recipe = self._recipe.name.text() if hasattr(self._recipe,'name') else "default"
        lot_id = self._cur_meta.lot_id  if self._cur_meta else "LOT-001"
        wfr_id = self._cur_meta.wafer_id if self._cur_meta else "W-01"
        self._db.insert_run(recipe, lot_id or "LOT-001", wfr_id or "W-01",
                            cd, self._cur_result.cd_std,
                            self._cur_result.lwr_3s, rec['correction_pct'])
        self._show_apc_tab()

    def _show_cdu_stats(self):
        if not self._sites:
            QMessageBox.information(self, "No Sites", "Import a wafer map first."); return
        from cd_scope.dialogs import CDUStatisticsDialog    
        CDUStatisticsDialog(self._sites, self).exec_()

    # ══════════════════════════════════════════════════════════════════════════
    # LIVE ACQUISITION
    # ══════════════════════════════════════════════════════════════════════════

    def _show_live_tab(self):
        for i in range(self._btabs.count()):
            if self._btabs.tabText(i) == "LIVE ACQ":
                self._btabs.setCurrentIndex(i); return

    def _on_live_frame(self, pix, img, meta):
        self._cur_img = img; self._cur_meta = meta
        self._live_panel.set_detector(self._recipe.get_detector())
        self.sem_view.set_image(pix, img, meta, self._cur_result)
        self._update_meta_panel(meta)

    # ══════════════════════════════════════════════════════════════════════════
    # AUTO PATTERN DETECTION
    # ══════════════════════════════════════════════════════════════════════════

    def _auto_detect(self):
        if self._cur_img is None:
            QMessageBox.information(self, "No Image", "Load an image first."); return
        npp    = self._cur_meta.nm_per_px if self._cur_meta else 0.49
        result = PatternRecognizer.classify(self._cur_img, npp)
        pat    = result.get('pattern', 'unknown')
        lbl    = result.get('label', 'Unknown')
        conf   = result.get('confidence', 0)
        scores = result.get('_scores', {})
        color  = {
            'line_space': CYAN, 'contact_hole': GREEN,
            'trench': AMBER,    'dot_array': PURPLE,
        }.get(pat, RED)

        dlg = QDialog(self); dlg.setWindowTitle("Pattern Recognition")
        dlg.setStyleSheet(STYLESHEET); dlg.setMinimumWidth(360)
        lay = QVBoxLayout(dlg)
        title = QLabel(f"Detected:  {lbl}")
        title.setStyleSheet(f"color:{color};font-size:15px;font-weight:bold;"
                             f"font-family:'Courier New',monospace;padding:8px;")
        lay.addWidget(title)
        lines = [f"Confidence:    {conf:.1f}%",
                 f"Duty cycle:    {result.get('duty_cycle',0):.1f}%",
                 f"Pitch (est):   {result.get('pitch_nm',0):.1f} nm",
                 f"L:S ratio:     {result.get('ls_ratio','—')}",
                 "", "Score breakdown:"] + \
                [f"  {k:<18}{v:.1f}%" for k,v in scores.items()]
        txt = QTextEdit('\n'.join(lines)); txt.setReadOnly(True)
        txt.setStyleSheet(f"background:{BG_DEEP};font-family:'Courier New',monospace;font-size:11px;")
        txt.setFixedHeight(200); lay.addWidget(txt)
        bb = QDialogButtonBox()
        btn_apply = bb.addButton("✓ Apply Pattern", QDialogButtonBox.AcceptRole)
        btn_apply.setObjectName("primary")
        bb.addButton("Cancel", QDialogButtonBox.RejectRole)
        mapping = {'line_space':'Line/Space 1:1','contact_hole':'Contact Hole Array',
                   'trench':'Line/Space 1:1','dot_array':'Contact Hole Array'}
        def do_apply():
            p = mapping.get(pat, 'Line/Space 1:1')
            ls = result.get('ls_ratio','1:1')
            if pat == 'line_space' and ':' in ls:
                p = f"Line/Space {ls}"
                if p not in PATTERN_TYPES: p = 'Line/Space 1:1'
            self._set_pattern(p); dlg.accept()
        bb.accepted.connect(do_apply); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb); dlg.exec_()

    # ══════════════════════════════════════════════════════════════════════════
    # DATABASE
    # ══════════════════════════════════════════════════════════════════════════

    def _open_db(self):
        from cd_scope.dialogs import DatabaseBrowserDialog    
        DatabaseBrowserDialog(self._db, self).exec_()

    def _save_wafer_db(self):
        if not self._sites:
            QMessageBox.information(self,"No Data","Import a wafer map first."); return
        lot_id   = (self._cur_meta.lot_id   if self._cur_meta else "") or "LOT-001"
        wafer_id = (self._cur_meta.wafer_id if self._cur_meta else "") or "W-01"
        meta_d   = {'instrument': self._cur_meta.instrument if self._cur_meta else ''}
        self._db.insert_sites_bulk(lot_id, wafer_id, self._sites, meta_d)
        QMessageBox.information(self,"Saved",
            f"Saved {len(self._sites)} sites → DB\n{lot_id}/{wafer_id}")

    def _save_batch_db(self):
        if not self._batch_records:
            QMessageBox.information(self,"No Batch","Run batch analysis first."); return
        sites = [WaferSite(r.site_id,r.x_mm,r.y_mm,r.cd_mean,r.cd_std,r.lwr_3s,
                            r.status,r.pitch_mean,r.space_mean)
                 for r in self._batch_records if r.cd_mean>0]
        if sites:
            self._db.insert_sites_bulk("LOT-BATCH","BATCH-01",sites)
            QMessageBox.information(self,"Saved",f"Saved {len(sites)} batch records.")

    def _db_stats(self):
        s = self._db.db_stats()
        QMessageBox.information(self,"DB Stats",
            f"Path:    {self._db.db_path}\n"
            f"Lots:    {s['lots']}\n"
            f"Wafers:  {s['wafers']}\n"
            f"Sites:   {s['sites']}\n"
            f"Size:    {s['size_kb']} KB")

    # ══════════════════════════════════════════════════════════════════════════
    # EXPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self,"Export CSV","CD_SCOPE.csv","CSV (*.csv)")
        if not path: return
        if self._sites:
            with open(path,'w',newline='') as f:
                w = csv.writer(f)
                w.writerow(["SITE","X_mm","Y_mm","CD_MEAN","CD_STD","LWR","PITCH","SPACE","STATUS"])
                for s in self._sites:
                    w.writerow([s.site_id,s.x_mm,s.y_mm,s.cd_mean,s.cd_std,
                                 s.lwr,s.pitch,s.space,s.status])
        elif self._cur_result:
            r = self._cur_result
            with open(path,'w',newline='') as f:
                w = csv.writer(f)
                w.writerow(["Row","Left_nm","Right_nm","CD_nm"])
                for i,(le,re,cd) in enumerate(zip(r.left_edges,r.right_edges,r.cd_values)):
                    w.writerow([i,f"{le:.3f}",f"{re:.3f}",f"{cd:.3f}"])
        self.statusBar().showMessage(f"  Exported to {path}", 4000)

    def _export_excel(self):
        from cd_scope.dialogs import ExcelExportDialog
        exp = MetroscanExcelExporter()
        exp.sites          = self._sites
        exp.batch_records  = self._batch_records
        exp.scanner_fields = self._scanner_fields
        exp.edge_result    = self._cur_result
        exp.recipe_name    = self._recipe.name.text() if hasattr(self._recipe,'name') else ""
        exp.lot_id         = self._cur_meta.lot_id    if self._cur_meta else ""
        exp.wafer_id       = self._cur_meta.wafer_id  if self._cur_meta else ""
        ExcelExportDialog(exp, self).exec_()

    def _gen_pdf(self):
        from cd_scope.dialogs import PDFReportDialog
        # Import PDF generator lazily
        try:
            from cd_scope.export.pdf_reporter import PDFReportGenerator
        except ImportError:
            QMessageBox.warning(self,"PDF","Install reportlab+matplotlib for PDF export."); return
        gen = PDFReportGenerator()
        gen.recipe_name   = self._recipe.name.text() if hasattr(self._recipe,'name') else ""
        gen.lot_id        = self._cur_meta.lot_id    if self._cur_meta else ""
        gen.wafer_id      = self._cur_meta.wafer_id  if self._cur_meta else ""
        gen.instrument    = self._cur_meta.instrument if self._cur_meta else "CD_SCOPE"
        gen.pattern_type  = self._pattern_cfg.pattern_type
        gen.sites         = self._sites
        gen.batch_records = self._batch_records
        gen.edge_result   = self._cur_result
        if hasattr(self._df_panel,'_points') and self._df_panel._points:
            gen.df_points = self._df_panel._points
            gen.df_result = self._df_panel._result
        PDFReportDialog(gen, self).exec_()

    # ══════════════════════════════════════════════════════════════════════════
    # MISC HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _manual_nmpx(self):
        current = self._cur_meta.nm_per_px if self._cur_meta else 0.49
        dlg = _NmpxDialog(current, self)
        if dlg.exec_() == QDialog.Accepted:
            npp = dlg.spin.value()
            if self._cur_meta: self._cur_meta.nm_per_px = npp
            self._sb_nm.setText(f"{npp:.4f}")
            self._run_analysis()

    def _update_meta_panel(self, m: SEMMeta):
        if not m: return
        lines = [
            f"Source:        {m.source}",
            f"Instrument:    {m.instrument}",
            f"nm/px:         {m.nm_per_px:.4f}",
            f"Magnification: ×{m.mag:,.0f}",
            f"Acc. Voltage:  {m.acc_voltage:.0f} eV",
            f"Working Dist:  {m.working_dist:.2f} mm",
            f"Image:         {m.pixel_width} × {m.pixel_height} px",
            f"Field of View: {m.field_width_nm/1000:.3f} × {m.field_height_nm/1000:.3f} µm",
            f"Recipe:        {m.recipe_name or '—'}",
            f"Lot ID:        {m.lot_id or '—'}",
            f"Wafer ID:      {m.wafer_id or '—'}",
            f"Site ID:       {m.site_id or '—'}",
            f"Date:          {m.date or '—'}",
        ]
        self._meta_txt.setPlainText('\n'.join(lines))

    def _set_status(self, msg: str, color: str = GREEN):
        self._sb_status.setText(msg)
        self._sb_status.setStyleSheet(
            f"color:{color};font-family:'Courier New',monospace;"
            f"font-size:10px;padding:0 8px;")

    def _show_fmt_guide(self):
        QMessageBox.information(self,"File Format Guide",
            "Wafer Map: CSV / XML / MDF / TXT\n"
            "Batch: CSV / JSON / INI / TXT\n"
            "Scanner: CSV / JSON / TXT\n"
            "SEM images: TIFF (Hitachi/JEOL/FEI), PNG, JPG\n\n"
            "Use File → Save Batch/Scanner Template for examples.")

    def _show_about(self):
        QMessageBox.about(self,"About CD_SCOPE v1.0",
            "<b>CD_SCOPE v1.0</b> — CD-SEM Analysis Suite<br><br>"
            "Real edge detection • Multi-pattern L/S + Contacts<br>"
            "Dose-Focus • Recipe Manager • Auto Pattern Recognition<br>"
            "PDF Report • Excel Export • SQLite Database<br>"
            "APC Run-to-Run Control • CDU Statistics<br>"
            f"<span style='color:{CYAN};'>"
            "PyQt5 · pyqtgraph · NumPy · SciPy · Pillow · scikit-image · "
            "openpyxl · reportlab · matplotlib</span>")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(150, self._acquire_synthetic)

    def closeEvent(self, ev):
        try: self._db.close()
        except Exception: pass
        super().closeEvent(ev)
