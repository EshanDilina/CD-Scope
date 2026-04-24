"""
cd_scope.analysis.cdu_statistics
───────────────────────────────────
CDU spatial decomposition: global, radial, H/V gradients, within/across die.
"""
from __future__ import annotations
import numpy as np
from cd_scope.core.models import WaferSite
from cd_scope.constants import USL, LSL

class CDUStatistics:
    """
    Decompose CD uniformity into spatial frequency components.

    Input: list of WaferSite (or dicts with x_mm, y_mm, cd_mean)
    """

    def __init__(self, sites: list):
        self.sites = sites

    def compute_all(self) -> dict:
        if not self.sites:
            return {}

        def get(s, attr, default=0.0):
            if hasattr(s, attr): return getattr(s, attr)
            return s.get(attr, default)

        cds = np.array([get(s, 'cd_mean') for s in self.sites])
        xs  = np.array([get(s, 'x_mm')    for s in self.sites])
        ys  = np.array([get(s, 'y_mm')    for s in self.sites])

        mu = float(np.mean(cds))
        sg = float(np.std(cds, ddof=1)) if len(cds) > 1 else 0.0
        usl, lsl = USL, LSL

        result: dict = {
            'n':       len(cds),
            'cd_mean': round(mu, 3),
            'cd_std':  round(sg, 3),
            'cdu_3s':  round(3*sg, 3),
            'range':   round(float(cds.max() - cds.min()), 3),
        }

        # Cp / Cpk
        cp   = (usl - lsl) / (6*sg) if sg > 0 else 0.0
        cpu  = (usl - mu)  / (3*sg) if sg > 0 else 0.0
        cpl  = (mu - lsl)  / (3*sg) if sg > 0 else 0.0
        result['cp']  = round(cp, 3)
        result['cpk'] = round(min(cpu, cpl), 3)

        # Radial gradient
        r = np.sqrt(xs**2 + ys**2)
        if len(r) > 3 and r.std() > 0:
            m, _ = np.polyfit(r, cds, 1)
            rr   = float(np.corrcoef(r, cds)[0, 1]**2)
        else:
            m, rr = 0.0, 0.0
        result['radial_gradient_nm_per_mm'] = round(float(m), 4)
        result['radial_r2']                 = round(rr, 3)

        # X / Y gradients
        if len(xs) > 3:
            mx, _ = np.polyfit(xs, cds, 1)
            my, _ = np.polyfit(ys, cds, 1)
        else:
            mx = my = 0.0
        result['x_gradient_nm_per_mm'] = round(float(mx), 4)
        result['y_gradient_nm_per_mm'] = round(float(my), 4)
        result['hv_bias_nm']           = round(abs(float(mx) - float(my)), 4)

        # Within-die CDU (local neighbours within 5 mm radius)
        within = []
        for i in range(len(self.sites)):
            nbrs = cds[((xs - xs[i])**2 + (ys - ys[i])**2) < 25]
            if len(nbrs) > 1:
                within.append(float(np.std(nbrs, ddof=1)))
        result['within_die_cdu_3s'] = round(3*np.mean(within) if within else 0, 3)
        result['across_die_cdu_3s'] = round(3*sg, 3)

        # Spatial decomposition (plane fit)
        if len(cds) > 6:
            try:
                A      = np.column_stack([np.ones(len(xs)), xs, ys])
                coeffs, *_ = np.linalg.lstsq(A, cds, rcond=None)
                cd_plane   = A @ coeffs
                residuals  = cds - cd_plane
                result['mean_offset_nm']   = round(float(coeffs[0] - mu), 3)
                result['linear_cdu_3s']    = round(3*float(np.std(cd_plane - mu, ddof=1)), 3)
                result['nonlinear_cdu_3s'] = round(3*float(np.std(residuals, ddof=1)), 3)
            except Exception:
                pass

        return result

    def pattern_density_correction(
        self,
        target_cd: float,
        density_map: dict,
        sensitivity_nm_per_10pct: float = 0.5,
    ) -> list[tuple[str, float]]:
        """
        Correct CD for local pattern density effects.

        density_map  : {site_id: density_fraction 0–1}
        sensitivity  : nm CD shift per 10 % density change (EUV typical ≈0.5)

        Returns list of (site_id, corrected_cd).
        """
        result = []
        for s in self.sites:
            sid  = s.site_id if hasattr(s, 'site_id') else s.get('site_id', '')
            cd   = s.cd_mean  if hasattr(s, 'cd_mean')  else s.get('cd_mean', 0)
            dens = density_map.get(sid, 0.5)
            corr = (dens - 0.5) * 2 * sensitivity_nm_per_10pct
            result.append((sid, round(cd - corr, 3)))
        return result
