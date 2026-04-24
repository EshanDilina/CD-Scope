"""
CD_SCOPE v1.0 — CD-SEM Analysis Suite
=======================================
A fully modular CD-SEM metrology package.

Quick start
-----------
    python main.py               # direct launch
    python -m cd_scope           # package launch (from parent folder)
"""

__version__ = "1.0.0"
__author__  = "CD_SCOPE"

# ── core layer ────────────────────────────────────────────────────────────────
from cd_scope.core import (
    EdgeDetector, EdgeResult,
    SEMLoader, SEMMeta,
    HitachiWaferParser, WaferSite,
    PatternConfig, PatternAnalyzer, PatternRecognizer, PATTERN_TYPES,
    Recipe, RecipeManager,
    BatchImageRecord, ScannerExposure, DoseFocusPoint,
)

# ── analysis layer ────────────────────────────────────────────────────────────
from cd_scope.analysis import (
    AnalysisThread, BatchAnalysisThread,
    LiveAcquisitionThread, AcquisitionConfig,
    gen_synthetic_sem, gen_synthetic_contact,
    DoseFocusAnalyzer, CDUStatistics,
)

# ── service layers ────────────────────────────────────────────────────────────
from cd_scope.db      import MetroscanDB
from cd_scope.control import APCController
from cd_scope.export  import MetroscanExcelExporter
from cd_scope.io      import BatchConditionParser, ScannerDataParser
