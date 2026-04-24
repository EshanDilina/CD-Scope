"""
cd_scope.control.apc
──────────────────────
Advanced Process Control: EWMA run-to-run feedback controller.

Computes dose correction to drive CD back to target.

  CD_error   = CD_measured - CD_target
  EWMA_error = λ·error + (1−λ)·EWMA_prev
  dose_corr% = −gain × EWMA_error / sensitivity   (clamped ±5 %)
"""
from __future__ import annotations
import datetime

import numpy as np


class APCController:
    """
    EWMA proportional dose correction controller.

    Parameters
    ----------
    target_cd            Target CD in nm
    gain                 Controller gain 0–1 (default 0.6)
    cd_per_dose_pct      CD sensitivity: nm change per 1 % dose change
    ewma_lambda          EWMA weighting 0–1 (higher = more reactive)
    deadband_nm          Don't correct if |EWMA_error| < deadband
    """

    def __init__(self,
                 target_cd:        float = 32.0,
                 gain:             float = 0.6,
                 cd_per_dose_pct:  float = 1.0,
                 ewma_lambda:      float = 0.4,
                 deadband_nm:      float = 0.3):
        self.target_cd        = target_cd
        self.gain             = gain
        self.cd_per_dose_pct  = cd_per_dose_pct
        self.ewma_lambda      = ewma_lambda
        self.deadband_nm      = deadband_nm
        self._ewma_error      = 0.0
        self._history: list[dict] = []

    @property
    def history(self) -> list[dict]:
        return self._history

    # ── Core update ────────────────────────────────────────────────────────────

    def update(self, cd_measured: float, current_dose: float) -> dict:
        """
        Process one wafer measurement.

        Returns a record dict with action and recommended next dose.
        """
        error = cd_measured - self.target_cd
        self._ewma_error = (self.ewma_lambda * error +
                            (1 - self.ewma_lambda) * self._ewma_error)

        if abs(self._ewma_error) < self.deadband_nm:
            dose_correction_pct = 0.0
            action = "HOLD"
        else:
            dose_correction_pct = (
                -self.gain * self._ewma_error / self.cd_per_dose_pct)
            dose_correction_pct = float(np.clip(dose_correction_pct, -5.0, 5.0))
            action = "CORRECT"

        new_dose = current_dose * (1 + dose_correction_pct / 100)

        rec = {
            'run':             len(self._history) + 1,
            'cd_measured':     round(cd_measured, 3),
            'cd_error':        round(error, 3),
            'ewma_error':      round(self._ewma_error, 3),
            'dose_used':       round(current_dose, 3),
            'correction_pct':  round(dose_correction_pct, 4),
            'new_dose':        round(new_dose, 3),
            'action':          action,
            'timestamp':       datetime.datetime.now().isoformat(),
        }
        self._history.append(rec)
        return rec

    # ── Convenience ────────────────────────────────────────────────────────────

    def next_dose(self) -> float:
        """Recommended dose for the next wafer."""
        return self._history[-1]['new_dose'] if self._history else 0.0

    def reset(self) -> None:
        self._ewma_error = 0.0
        self._history.clear()

    def summary(self) -> dict:
        if not self._history:
            return {}
        errors = [r['cd_error'] for r in self._history]
        corrs  = [r['correction_pct'] for r in self._history]
        return {
            'n_runs':          len(self._history),
            'mean_error':      round(float(np.mean(errors)), 3),
            'std_error':       round(float(np.std(errors, ddof=1)) if len(errors)>1 else 0, 3),
            'max_correction':  round(float(max(abs(c) for c in corrs)), 4),
            'total_correction':round(float(sum(corrs)), 4),
            'converged':       abs(self._ewma_error) < self.deadband_nm,
        }
