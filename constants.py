"""
cd_scope.constants
───────────────────
All colour tokens, spec defaults, and optional-library capability flags.
Import this module first; nothing in the package imports from UI modules here.
"""

# ── Colour tokens ──────────────────────────────────────────────────────────────
BG_VOID    = "#070a0f"
BG_DEEP    = "#0b0f17"
BG_PANEL   = "#0f1520"
BG_CARD    = "#141c2a"
BG_HOVER   = "#1a2438"
BORDER     = "#1e2d45"
BORDER_BR  = "#2a4060"
CYAN       = "#00d4ff"
CYAN_DIM   = "#006880"
GREEN      = "#00ff88"
AMBER      = "#ffb300"
RED        = "#ff3355"
PURPLE     = "#9966ff"
TEXT_BR    = "#e8f4ff"
TEXT_MID   = "#7a9ab8"
TEXT_DIM   = "#3a5470"

# ── Process spec defaults ──────────────────────────────────────────────────────
TARGET_CD    = 32.0   # nm
USL          = 34.0   # nm
LSL          = 30.0   # nm
LWR_MAX      = 4.0    # nm  3σ
LER_MAX      = 3.0    # nm  3σ
CPK_MIN      = 1.33
EUV_WAVELENGTH = 13.5  # nm

# ── Optional library flags ────────────────────────────────────────────────────
try:
    from PIL import Image as _PIL
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    from skimage import feature as _skf   # noqa: F401
    SKIMAGE_OK = True
except ImportError:
    SKIMAGE_OK = False

try:
    import openpyxl as _xl                # noqa: F401
    EXCEL_OK = True
except ImportError:
    EXCEL_OK = False

try:
    import matplotlib as _mpl             # noqa: F401
    MPL_OK = True
except ImportError:
    MPL_OK = False

try:
    import reportlab as _rl               # noqa: F401
    RL_OK = True
except ImportError:
    RL_OK = False

# ── Qt stylesheet (generated once, shared by all UI modules) ──────────────────
STYLESHEET = f"""
QWidget{{background:{BG_PANEL};color:{TEXT_BR};font-family:'Segoe UI',sans-serif;font-size:13px;}}
QMainWindow{{background:{BG_VOID};}}
QMenuBar{{background:{BG_DEEP};color:{TEXT_MID};border-bottom:1px solid {BORDER};padding:2px 4px;font-size:12px;}}
QMenuBar::item:selected{{background:{BG_HOVER};color:{TEXT_BR};}}
QMenu{{background:{BG_CARD};color:{TEXT_MID};border:1px solid {BORDER};}}
QMenu::item:selected{{background:{BG_HOVER};color:{CYAN};}}
QToolBar{{background:{BG_PANEL};border-bottom:1px solid {BORDER};spacing:3px;padding:3px 6px;}}
QToolBar QToolButton{{background:{BG_CARD};color:{TEXT_MID};border:1px solid {BORDER};border-radius:2px;padding:3px 10px;font-size:11px;font-weight:600;min-height:22px;}}
QToolBar QToolButton:hover{{border-color:{CYAN_DIM};color:{CYAN};background:rgba(0,212,255,0.08);}}
QToolBar QToolButton:checked{{border-color:{CYAN};color:{CYAN};background:rgba(0,212,255,0.12);}}
QSplitter::handle{{background:{BORDER};width:2px;height:2px;}}
QTreeWidget{{background:{BG_PANEL};color:{TEXT_MID};border:none;outline:none;font-size:12px;}}
QTreeWidget::item{{padding:4px;border-left:2px solid transparent;}}
QTreeWidget::item:selected{{background:rgba(0,212,255,0.10);color:{CYAN};border-left:2px solid {CYAN};}}
QTreeWidget::item:hover{{background:{BG_HOVER};color:{TEXT_BR};}}
QTabWidget::pane{{border:none;background:{BG_PANEL};}}
QTabBar::tab{{background:{BG_DEEP};color:{TEXT_DIM};padding:6px 14px;border:none;border-bottom:2px solid transparent;font-size:10px;font-weight:700;letter-spacing:1px;}}
QTabBar::tab:selected{{color:{CYAN};border-bottom:2px solid {CYAN};background:{BG_PANEL};}}
QTabBar::tab:hover{{color:{TEXT_MID};background:{BG_HOVER};}}
QTableWidget{{background:{BG_VOID};color:{TEXT_MID};gridline-color:{BORDER};border:none;font-family:'Courier New',monospace;font-size:11px;}}
QTableWidget::item{{padding:3px 8px;border-bottom:1px solid {BORDER};}}
QTableWidget::item:selected{{background:rgba(0,212,255,0.12);color:{CYAN};}}
QHeaderView::section{{background:{BG_DEEP};color:{TEXT_DIM};padding:5px 8px;border:none;border-bottom:1px solid {BORDER};font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;}}
QScrollBar:vertical{{background:{BG_DEEP};width:8px;border:none;}}
QScrollBar::handle:vertical{{background:{BORDER_BR};border-radius:4px;min-height:20px;}}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
QScrollBar:horizontal{{background:{BG_DEEP};height:8px;border:none;}}
QScrollBar::handle:horizontal{{background:{BORDER_BR};border-radius:4px;}}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{{background:{BG_DEEP};color:{TEXT_BR};border:1px solid {BORDER};border-radius:2px;padding:4px 8px;font-family:'Courier New',monospace;font-size:12px;}}
QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{CYAN};}}
QComboBox::drop-down{{border:none;width:20px;}}
QComboBox QAbstractItemView{{background:{BG_CARD};color:{TEXT_MID};border:1px solid {BORDER};selection-background-color:rgba(0,212,255,0.15);}}
QPushButton{{background:{BG_CARD};color:{TEXT_MID};border:1px solid {BORDER};border-radius:2px;padding:6px 14px;font-size:11px;font-weight:600;letter-spacing:1px;}}
QPushButton:hover{{border-color:{CYAN_DIM};color:{CYAN};background:rgba(0,212,255,0.08);}}
QPushButton#primary{{border-color:{CYAN};color:{CYAN};background:rgba(0,212,255,0.10);}}
QPushButton#primary:hover{{background:rgba(0,212,255,0.20);}}
QGroupBox{{color:{TEXT_DIM};border:1px solid {BORDER};border-radius:3px;margin-top:16px;padding-top:8px;font-family:'Courier New',monospace;font-size:9px;letter-spacing:2px;}}
QGroupBox::title{{subcontrol-origin:margin;left:10px;padding:0 6px;color:{TEXT_DIM};background:{BG_PANEL};}}
QStatusBar{{background:{BG_DEEP};color:{TEXT_DIM};border-top:1px solid {BORDER};font-family:'Courier New',monospace;font-size:10px;}}
QTextEdit{{background:{BG_DEEP};color:{TEXT_MID};border:1px solid {BORDER};font-family:'Courier New',monospace;font-size:11px;}}
QListWidget{{background:{BG_DEEP};color:{TEXT_MID};border:1px solid {BORDER};font-size:12px;}}
QListWidget::item:selected{{background:rgba(0,212,255,0.12);color:{CYAN};}}
"""
