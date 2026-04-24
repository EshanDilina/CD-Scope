"""
cd_scope.analysis.dose_focus
──────────────────────────────
Dose-focus matrix analysis: Bossung curves, process window, exposure latitude.
"""
from __future__ import annotations
import numpy as np
from cd_scope.core.models import DoseFocusPoint

class DoseFocusAnalyzer:
    """
    Analyse a dose-focus matrix and compute:
      - Bossung curves (CD vs focus at each dose level)
      - Best focus per dose
      - Depth of focus at each dose
      - Exposure latitude at best focus
      - Process window rectangle (EL × DoF)
      - Iso-CD contour
    """

    def __init__(self,
                 points: list[DoseFocusPoint],
                 target_cd: float = 32.0,
                 cd_tolerance_pct: float = 10.0):
        self.points    = points
        self.target_cd = target_cd
        self.tol_pct   = cd_tolerance_pct
        self.doses     = sorted(set(p.dose  for p in points))
        self.focuses   = sorted(set(p.focus for p in points))

    def analyse(self) -> dict:
        r: dict = {
            'bossung_curves': {},  # dose → {focus: cd}
            'best_focus':     {},  # dose → best focus µm
            'dof':            {},  # dose → DoF µm
            'el_pct':         0.0,
            'best_dose':      0.0,
            'process_window': None,  # (dose_lo, dose_hi, focus_lo, focus_hi)
            'iso_cd_contour': [],
        }

        cd_lo = self.target_cd * (1 - self.tol_pct / 100)
        cd_hi = self.target_cd * (1 + self.tol_pct / 100)

        # Build Bossung curves
        for dose in self.doses:
            pts = sorted(
                [(p.focus, p.cd_mean) for p in self.points if p.dose == dose],
                key=lambda x: x[0]
            )
            if len(pts) < 2:
                continue
            focuses = [p[0] for p in pts]
            cds     = [p[1] for p in pts]
            r['bossung_curves'][dose] = dict(zip(focuses, cds))

            diffs     = [abs(c - self.target_cd) for c in cds]
            best_idx  = diffs.index(min(diffs))
            r['best_focus'][dose] = focuses[best_idx]

            in_spec = [f for f, c in zip(focuses, cds) if cd_lo <= c <= cd_hi]
            r['dof'][dose] = (max(in_spec) - min(in_spec)) if len(in_spec) >= 2 else 0.0

        if r['dof']:
            r['best_dose'] = max(r['dof'], key=r['dof'].get)

        # Exposure latitude at best focus
        best_f = r['best_focus'].get(r['best_dose'], 0.0)
        cd_at_best_focus: dict[float, float] = {}
        for dose in self.doses:
            curve = r['bossung_curves'].get(dose, {})
            if len(curve) >= 2:
                fs = sorted(curve.keys())
                cs = [curve[f] for f in fs]
                cd_at_best_focus[dose] = float(np.interp(best_f, fs, cs))

        if cd_at_best_focus:
            in_spec_doses = [d for d, c in cd_at_best_focus.items()
                             if cd_lo <= c <= cd_hi]
            if len(in_spec_doses) >= 2:
                dose_range = max(in_spec_doses) - min(in_spec_doses)
                mid_dose   = (max(in_spec_doses) + min(in_spec_doses)) / 2
                r['el_pct'] = dose_range / mid_dose * 100 if mid_dose > 0 else 0.0

        # Process window
        best_dose = r['best_dose']
        if best_dose in r['dof']:
            dof_val   = r['dof'][best_dose]
            bf        = r['best_focus'].get(best_dose, 0.0)
            el_lo     = best_dose * (1 - r['el_pct'] / 200)
            el_hi     = best_dose * (1 + r['el_pct'] / 200)
            r['process_window'] = (el_lo, el_hi, bf - dof_val/2, bf + dof_val/2)

        # Iso-CD contour
        r['iso_cd_contour'] = [
            (p.dose, p.focus)
            for p in self.points
            if cd_lo <= p.cd_mean <= cd_hi
        ]
        return r
