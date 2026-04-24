"""
cd_scope.core.pattern_engine
──────────────────────────────
Pattern-aware analysis wrapper and auto-recognition.

PatternAnalyzer   — wraps EdgeDetector for any L:S ratio or contact holes
PatternRecognizer — classify image pattern type from pixel statistics alone
"""
from __future__ import annotations
import math, traceback
import numpy as np
from scipy.ndimage import gaussian_filter1d, gaussian_filter

from cd_scope.core.models import PatternConfig, EdgeResult
from cd_scope.core.edge_detection import EdgeDetector

class PatternAnalyzer:
    """
    Extends EdgeDetector with pattern-specific interpretation.

    For Line/Space patterns: computes CD bias, duty cycle, measured L:S ratio.
    For Contact Holes: finds individual holes, measures diameter, ellipticity,
        circularity, per-hole LWR, pitch_x/pitch_y.
    """

    def __init__(self, detector: EdgeDetector, pattern_cfg: PatternConfig):
        self.det = detector
        self.cfg = pattern_cfg

    def analyse(self, img: np.ndarray, npp: float) -> dict:
        if self.cfg.is_contact:
            return self._contacts(img, npp)
        return self._line_space(img, npp)

    # ── Line / Space ───────────────────────────────────────────────────────────

    def _line_space(self, img: np.ndarray, npp: float) -> dict:
        r = self.det.analyse(img, npp)
        result = {
            'type':         self.cfg.pattern_type,
            'edge_result':  r,
            'cd_mean':      r.cd_mean,
            'cd_std':       r.cd_std,
            'space_mean':   r.space_mean,
            'space_std':    0.0,
            'pitch_mean':   r.pitch_mean,
            'pitch_std':    0.0,
            'lwr_3s':       r.lwr_3s,
            'ler_l_3s':     r.ler_l_3s,
            'ler_r_3s':     r.ler_r_3s,
            'ls_ratio_meas': 0.0,
            'duty_cycle':    0.0,
            'cd_bias':       0.0,
            'space_bias':    0.0,
            'error':         r.error,
        }

        if r.pitch_mean > 0:
            exp_line  = r.pitch_mean * self.cfg.line_fraction
            exp_space = r.pitch_mean * self.cfg.space_fraction
            result['cd_bias']    = r.cd_mean    - exp_line
            result['space_bias'] = r.space_mean - exp_space
            if r.cd_mean > 0:
                result['duty_cycle'] = r.cd_mean / r.pitch_mean * 100
            if r.space_mean > 0 and r.cd_mean > 0:
                result['ls_ratio_meas'] = r.cd_mean / r.space_mean

        if len(r.space_values) > 1:
            result['space_std'] = float(np.std(r.space_values, ddof=1))
        if len(r.pitch_values) > 1:
            result['pitch_std'] = float(np.std(r.pitch_values, ddof=1))
        return result

    # ── Contact Holes ──────────────────────────────────────────────────────────

    def _contacts(self, img: np.ndarray, npp: float) -> dict:
        H, W = img.shape
        result = {
            'type':             'Contact Hole Array',
            'edge_result':      None,
            'holes':            [],
            'cd_mean':          0.0,
            'cd_std':           0.0,
            'cd_x_mean':        0.0,
            'cd_y_mean':        0.0,
            'ellipticity':      0.0,
            'pitch_x':          0.0,
            'pitch_y':          0.0,
            'n_holes':          0,
            'cdr_3s':           0.0,
            'lwr_3s':           0.0,
            'circularity_mean': 0.0,
            'error':            '',
        }
        try:
            mn, mx = img.min(), img.max()
            if mx - mn < 20:
                result['error'] = "Insufficient contrast for contact detection"
                return result

            smooth = gaussian_filter(img.astype(float), sigma=max(1, 2.0/npp))
            th     = mn + (mx - mn) * 0.45
            dark   = (smooth < th).astype(np.uint8)

            from scipy.ndimage import label
            labeled, n = label(dark)
            if n == 0:
                result['error'] = "No dark regions (contacts) found"
                return result

            exp_r_px = self.cfg.target_cd / 2 / npp
            min_area = math.pi * (exp_r_px * 0.3) ** 2
            max_area = math.pi * (exp_r_px * 2.0) ** 2

            holes: list[dict] = []
            from scipy.ndimage import center_of_mass
            for idx in range(1, n+1):
                region = (labeled == idx)
                area   = region.sum()
                if not (min_area <= area <= max_area):
                    continue
                rows = np.where(region.any(axis=1))[0]
                cols = np.where(region.any(axis=0))[0]
                if len(rows) < 3 or len(cols) < 3:
                    continue
                cd_y = (rows[-1] - rows[0]) * npp
                cd_x = (cols[-1] - cols[0]) * npp
                cy, cx = center_of_mass(region)
                diam = math.sqrt(cd_x * cd_y)
                circ = min(cd_x, cd_y) / max(cd_x, cd_y) if max(cd_x, cd_y) > 0 else 0
                holes.append({
                    'cx': cx*npp, 'cy': cy*npp,
                    'cd_x': cd_x, 'cd_y': cd_y,
                    'diameter': diam,
                    'circularity': circ,
                    'area_nm2': area * npp**2,
                    'lwr': self._perimeter_roughness(region, npp),
                })

            if not holes:
                result['error'] = (f"No contacts matched expected size "
                                   f"~{self.cfg.target_cd:.0f} nm")
                return result

            diams = [h['diameter']    for h in holes]
            cd_xs = [h['cd_x']        for h in holes]
            cd_ys = [h['cd_y']        for h in holes]
            circs = [h['circularity'] for h in holes]
            lwrs  = [h['lwr']         for h in holes]

            result['holes']             = holes
            result['n_holes']           = len(holes)
            result['cd_mean']           = float(np.mean(diams))
            result['cd_std']            = float(np.std(diams, ddof=1)) if len(diams)>1 else 0
            result['cd_x_mean']         = float(np.mean(cd_xs))
            result['cd_y_mean']         = float(np.mean(cd_ys))
            result['ellipticity']       = abs(result['cd_x_mean'] - result['cd_y_mean'])
            result['cdr_3s']            = 3 * result['cd_std']
            result['lwr_3s']            = float(np.mean(lwrs)) if lwrs else 0
            result['circularity_mean']  = float(np.mean(circs))

            if len(holes) >= 2:
                cxs = np.array([h['cx'] for h in holes])
                cys = np.array([h['cy'] for h in holes])
                order = np.lexsort((cxs, cys))
                cxs, cys = cxs[order], cys[order]
                dx = np.diff(cxs); dy = np.diff(cys)
                px = dx[np.abs(dx) > np.abs(dy)]
                py = dy[np.abs(dy) >= np.abs(dx)]
                if len(px): result['pitch_x'] = float(np.median(np.abs(px)))
                if len(py): result['pitch_y'] = float(np.median(np.abs(py)))

        except Exception:
            result['error'] = traceback.format_exc()
        return result

    @staticmethod
    def _perimeter_roughness(region: np.ndarray, npp: float) -> float:
        try:
            from scipy.ndimage import binary_erosion
            eroded   = binary_erosion(region)
            perim    = region & ~eroded
            py, px   = np.where(perim)
            if len(py) < 8:
                return 0.0
            cx, cy = px.mean(), py.mean()
            r      = np.sqrt((px - cx)**2 + (py - cy)**2)
            return float(np.std(r, ddof=1)) * npp * 3
        except Exception:
            return 0.0


# ── Pattern Recognizer ────────────────────────────────────────────────────────

class PatternRecognizer:
    """
    Classify SEM image pattern type from pixel statistics alone.

    Returns
    -------
    dict with keys: pattern, label, confidence, duty_cycle, pitch_nm,
                    ls_ratio, _scores
    """

    LABELS = {
        'line_space':   'Line/Space',
        'contact_hole': 'Contact Hole Array',
        'trench':       'Trench/Space',
        'dot_array':    'Dot Array',
        'unknown':      'Unknown',
    }

    @classmethod
    def classify(cls, img: np.ndarray, npp: float = 1.0) -> dict:
        result = {
            'pattern':    'unknown',
            'label':      'Unknown',
            'confidence': 0.0,
            'duty_cycle': 50.0,
            'pitch_nm':   0.0,
            'ls_ratio':   '1:1',
        }
        try:
            f = cls._features(img, npp)
            scores = {
                'line_space':   cls._score_ls(f),
                'contact_hole': cls._score_contact(f),
                'trench':       cls._score_trench(f),
                'dot_array':    cls._score_dot(f),
            }
            best  = max(scores, key=scores.get)
            total = sum(scores.values()) or 1.0
            result['pattern']    = best
            result['label']      = cls.LABELS[best]
            result['confidence'] = round(scores[best] / total * 100, 1)
            result['_scores']    = {k: round(v*100/total, 1) for k, v in scores.items()}

            dc, pitch = cls._duty_pitch(img, npp, best)
            result['duty_cycle'] = round(dc, 1)
            result['pitch_nm']   = round(pitch, 2)

            if best in ('line_space', 'trench') and dc > 0:
                lf = dc / 100; sf = 1 - lf
                if lf > 0 and sf > 0:
                    rv = lf / sf
                    for num, den in [(1,1),(2,1),(1,2),(3,1),(1,3)]:
                        if abs(rv - num/den) < 0.15:
                            result['ls_ratio'] = f"{num}:{den}"; break
                    else:
                        result['ls_ratio'] = f"{lf:.2f}:{sf:.2f}"
        except Exception:
            result['error'] = traceback.format_exc()
        return result

    @classmethod
    def _features(cls, img: np.ndarray, npp: float) -> dict:
        H, W   = img.shape
        mn, mx = float(img.min()), float(img.max())
        contrast = mx - mn

        hist, _ = np.histogram(img.flatten(), bins=64, range=(0, 255))
        hist_n  = hist / hist.sum()
        bimodal = cls._bimodality(hist_n)

        mid_row   = img[H//3:2*H//3, :]
        profile_x = mid_row.mean(axis=0).astype(float)
        ac_x      = cls._autocorr(profile_x - profile_x.mean())
        pitch_x, str_x = cls._find_period(ac_x, npp)

        mid_col   = img[:, W//3:2*W//3]
        profile_y = mid_col.mean(axis=1).astype(float)
        ac_y      = cls._autocorr(profile_y - profile_y.mean())
        pitch_y, str_y = cls._find_period(ac_y, npp)

        isotropy = 1.0 - abs(str_x - str_y) / max(str_x + str_y, 1e-9)
        dark_frac = float((img < (mn + contrast * 0.4)).mean())

        from scipy.ndimage import sobel
        gx  = sobel(img.astype(float), axis=1)
        gy  = sobel(img.astype(float), axis=0)
        edge_density = float(np.sqrt(gx**2 + gy**2).mean()) / max(contrast, 1)

        h_var = float(profile_x.std())
        v_var = float(profile_y.std())
        return {
            'contrast':          contrast,
            'bimodal':           bimodal,
            'period_strength_x': str_x,
            'period_strength_y': str_y,
            'pitch_x':           pitch_x,
            'pitch_y':           pitch_y,
            'isotropy':          isotropy,
            'dark_frac':         dark_frac,
            'edge_density':      edge_density,
            'stripe_h':          h_var / max(v_var, 1e-3),
            'stripe_v':          v_var / max(h_var, 1e-3),
        }

    @staticmethod
    def _bimodality(hist_n: np.ndarray) -> float:
        peaks = [(i, hist_n[i]) for i in range(1, len(hist_n)-1)
                 if hist_n[i] > hist_n[i-1] and hist_n[i] > hist_n[i+1]]
        if len(peaks) >= 2:
            peaks.sort(key=lambda x: -x[1])
            return float(min(peaks[0][1], peaks[1][1]))
        return 0.0

    @staticmethod
    def _autocorr(x: np.ndarray) -> np.ndarray:
        n   = len(x)
        res = np.correlate(x, x, mode='full')
        return res[n-1:] / max(res[n-1], 1e-9)

    @staticmethod
    def _find_period(ac: np.ndarray, npp: float) -> tuple[float, float]:
        if len(ac) < 4:
            return 0.0, 0.0
        peaks = [(i, float(ac[i])) for i in range(2, len(ac)-1)
                 if ac[i] > ac[i-1] and ac[i] > ac[i+1] and ac[i] > 0.1]
        if peaks:
            best = max(peaks, key=lambda x: x[1])
            return best[0] * npp, best[1]
        return 0.0, 0.0

    @staticmethod
    def _score_ls(f: dict)      -> float:
        return max(0, f['bimodal']*2 + min(f['stripe_h'],3)*0.8 +
                   f['period_strength_x']*1.5 + (1-f['isotropy'])*0.5 +
                   min(f['edge_density']*3, 1.5))

    @staticmethod
    def _score_contact(f: dict) -> float:
        return max(0, f['isotropy']*2.5 + f['period_strength_x']*0.8 +
                   f['period_strength_y']*0.8 + f['dark_frac']*1.5 +
                   f['bimodal']*1.0)

    @staticmethod
    def _score_trench(f: dict)  -> float:
        return max(0, f['bimodal']*1.5 + min(f['stripe_v'],3)*0.8 +
                   f['period_strength_y']*1.2 + f['dark_frac']*0.8)

    @staticmethod
    def _score_dot(f: dict)     -> float:
        return max(0, f['isotropy']*1.5 + (1-f['dark_frac'])*1.0 +
                   f['period_strength_x']*0.7 + f['period_strength_y']*0.7)

    @classmethod
    def _duty_pitch(cls, img: np.ndarray, npp: float, pattern: str
                    ) -> tuple[float, float]:
        H, W = img.shape
        mn, mx = float(img.min()), float(img.max())
        contrast = mx - mn
        if contrast < 10:
            return 50.0, 0.0
        profile = img[H//3:2*H//3, :].mean(axis=0).astype(float)
        th      = mn + contrast * 0.5
        bright  = (profile >= th)
        duty    = bright.sum() / W * 100
        ac      = cls._autocorr(profile - profile.mean())
        pitch, _ = cls._find_period(ac, npp)
        return duty, pitch
