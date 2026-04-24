"""
cd_scope.core.models
─────────────────────
Pure data classes (no Qt, no numpy required at import time).
Every other module imports from here — never the reverse.
"""
from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from typing import List, Optional


# ── Measurement data ──────────────────────────────────────────────────────────

@dataclass
class EdgeResult:
    """All extracted metrology from one SEM image analysis."""
    nm_per_px:     float = 1.0
    profile_x:     object = None   # np.ndarray (nm)
    profile_y:     object = None   # np.ndarray (intensity)
    left_edges:    object = None   # np.ndarray (nm, per row)
    right_edges:   object = None   # np.ndarray (nm, per row)
    cd_values:     object = None   # np.ndarray (nm, per row)
    pitch_values:  object = None   # np.ndarray (nm)
    space_values:  object = None   # np.ndarray (nm)
    edge_overlay:  List   = field(default_factory=list)   # [(px, type_str), ...]
    cd_mean:       float = 0.0
    cd_std:        float = 0.0
    lwr_3s:        float = 0.0
    ler_l_3s:      float = 0.0
    ler_r_3s:      float = 0.0
    pitch_mean:    float = 0.0
    space_mean:    float = 0.0
    edge_slope_l:  float = 90.0
    edge_slope_r:  float = 90.0
    psd_freq:      object = None   # np.ndarray
    psd_power:     object = None   # np.ndarray
    hurst:         float = 0.0
    corr_len:      float = 0.0
    algo:          str   = ""
    error:         str   = ""
    raw_img:       object = None   # np.ndarray uint8

    def __post_init__(self):
        import numpy as np
        for attr in ('profile_x','profile_y','left_edges','right_edges',
                     'cd_values','pitch_values','space_values',
                     'psd_freq','psd_power','raw_img'):
            if getattr(self, attr) is None:
                object.__setattr__(self, attr, np.array([]))

    @property
    def is_valid(self) -> bool:
        return self.cd_mean > 0 and not self.error


@dataclass
class SEMMeta:
    """Parsed metadata from a SEM image file header."""
    nm_per_px:      float = 1.0
    mag:            float = 0.0
    acc_voltage:    float = 0.0
    working_dist:   float = 0.0
    pixel_width:    int   = 0
    pixel_height:   int   = 0
    field_width_nm: float = 0.0
    field_height_nm:float = 0.0
    instrument:     str   = "Unknown"
    recipe_name:    str   = ""
    lot_id:         str   = ""
    wafer_id:       str   = ""
    site_id:        str   = ""
    date:           str   = ""
    comment:        str   = ""
    source:         str   = "unknown"   # hitachi | jeol | fei | sidecar | estimated


@dataclass
class WaferSite:
    """One measurement site on a wafer map."""
    site_id:  str   = ""
    x_mm:     float = 0.0
    y_mm:     float = 0.0
    cd_mean:  float = 0.0
    cd_std:   float = 0.0
    lwr:      float = 0.0
    status:   str   = "PASS"
    pitch:    float = 0.0
    space:    float = 0.0
    ler_l:    float = 0.0
    ler_r:    float = 0.0
    row:      int   = 0
    col:      int   = 0
    img_file: str   = ""

    @property
    def is_pass(self) -> bool:
        return self.status == "PASS"


@dataclass
class ScannerExposure:
    """One exposure field from a scanner log."""
    field_id:    str   = ""
    x_mm:        float = 0.0
    y_mm:        float = 0.0
    dose:        float = 0.0    # mJ/cm²
    focus:       float = 0.0    # µm defocus (signed)
    sigma:       float = 0.0    # partial coherence
    na:          float = 0.0    # numerical aperture
    wavelength:  float = 13.5   # nm (EUV default)
    reticle:     str   = ""
    lot_id:      str   = ""
    wafer_id:    str   = ""
    date:        str   = ""
    slot:        int   = 0
    cd_corr:     float = 0.0    # dose correction factor
    tilt_x:      float = 0.0
    tilt_y:      float = 0.0


@dataclass
class BatchImageRecord:
    """One image entry in a batch condition file, plus analysis results."""
    image_path:   str   = ""
    nm_per_px:    float = 0.0
    site_id:      str   = ""
    lot_id:       str   = ""
    wafer_id:     str   = ""
    x_mm:         float = 0.0
    y_mm:         float = 0.0
    dose:         float = 0.0
    focus:        float = 0.0
    pattern_type: str   = "Line/Space 1:1"
    target_cd:    float = 32.0
    comment:      str   = ""
    # Filled after analysis
    cd_mean:      float = 0.0
    cd_std:       float = 0.0
    lwr_3s:       float = 0.0
    pitch_mean:   float = 0.0
    space_mean:   float = 0.0
    n_holes:      int   = 0
    status:       str   = ""
    error:        str   = ""


@dataclass
class DoseFocusPoint:
    """One CD measurement in a dose-focus matrix sweep."""
    dose:    float = 0.0
    focus:   float = 0.0
    cd_mean: float = 0.0
    cd_std:  float = 0.0
    lwr:     float = 0.0
    site_id: str   = ""


# ── Recipe ────────────────────────────────────────────────────────────────────

@dataclass
class Recipe:
    """Persisted recipe: detector settings + pattern config + spec limits."""
    name:          str   = "New Recipe"
    created:       str   = field(default_factory=lambda: datetime.datetime.now().isoformat())
    modified:      str   = field(default_factory=lambda: datetime.datetime.now().isoformat())
    description:   str   = ""
    # Edge detector
    algo:          int   = 0
    sigma_nm:      float = 2.5
    threshold:     float = 0.50
    cd_height:     int   = 50
    # Pattern
    pattern_type:  str   = "Line/Space 1:1"
    target_cd:     float = 32.0
    target_pitch:  float = 64.0
    # Spec limits
    usl:           float = 34.0
    lsl:           float = 30.0
    lwr_max:       float = 4.0
    ler_max:       float = 3.0
    cdu_max:       float = 2.0
    cpk_min:       float = 1.33
    history:       List  = field(default_factory=list)

    def add_run(self, cd_mean: float, cd_std: float,
                lwr_3s: float, n_sites: int, notes: str = "") -> None:
        self.history.append({
            'timestamp': datetime.datetime.now().isoformat(),
            'cd_mean':   round(cd_mean, 3),
            'cd_std':    round(cd_std,  3),
            'lwr_3s':    round(lwr_3s,  3),
            'n_sites':   n_sites,
            'notes':     notes,
        })
        self.modified = datetime.datetime.now().isoformat()

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        r = cls()
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r


# ── Pattern configuration ─────────────────────────────────────────────────────

PATTERN_TYPES = [
    "Line/Space 1:1",
    "Line/Space 2:1",
    "Line/Space 1:2",
    "Line/Space 3:1",
    "Line/Space 1:3",
    "Contact Hole Array",
    "Custom L:S Ratio",
]


@dataclass
class PatternConfig:
    """Describes the measurement pattern type and its expected geometry."""
    pattern_type:   str   = "Line/Space 1:1"
    ls_ratio_line:  float = 1.0
    ls_ratio_space: float = 1.0
    target_cd:      float = 32.0
    target_pitch:   float = 64.0
    target_space:   float = 32.0
    is_contact:     bool  = False
    hole_shape:     str   = "circle"
    n_cols_expected: int  = 0

    @property
    def line_fraction(self) -> float:
        return self.ls_ratio_line / (self.ls_ratio_line + self.ls_ratio_space)

    @property
    def space_fraction(self) -> float:
        return self.ls_ratio_space / (self.ls_ratio_line + self.ls_ratio_space)

    @classmethod
    def from_string(cls, s: str) -> "PatternConfig":
        import re
        cfg = cls(pattern_type=s)
        if "Contact" in s:
            cfg.is_contact = True
            return cfg
        cfg.is_contact = False
        m = re.search(r'(\d+):(\d+)', s)
        if m:
            cfg.ls_ratio_line  = float(m.group(1))
            cfg.ls_ratio_space = float(m.group(2))
        return cfg
