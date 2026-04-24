"""
cd_scope.core.edge_detection
──────────────────────────────
Real CD-SEM edge detection engine.

Algorithms
  0  Gaussian Derivative  (ISO 19973, gradient-magnitude peaks)
  1  Threshold Crossing   (simple fractional threshold)
  2  Canny Contour        (scikit-image, good for noisy images)
  3  Sigmoidal Fit        (scipy curve_fit, sub-pixel accuracy)
"""
from __future__ import annotations
import math, traceback
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import welch, find_peaks

from cd_scope.core.models import EdgeResult

class EdgeDetector:
    """
    Production-grade CD-SEM edge detector.

    Usage
    -----
    det = EdgeDetector()
    det.sigma_nm = 2.5
    det.algo     = 0      # Gaussian derivative
    result = det.analyse(img_gray_uint8, nm_per_px)
    """

    ALGOS = [
        "Gaussian Derivative",
        "Threshold 50%",
        "Canny Contour",
        "Sigmoidal Fit (sub-px)",
    ]

    def __init__(self):
        self.sigma_nm   = 2.5
        self.threshold  = 0.50
        self.cd_height  = 50
        self.algo       = 0
        self.min_sep    = 3

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyse(self, img: np.ndarray, nm_per_px: float) -> EdgeResult:
        """Run full analysis pipeline. Returns EdgeResult."""
        result = EdgeResult(nm_per_px=nm_per_px, raw_img=img.copy())
        try:
            self._pipeline(img, nm_per_px, result)
        except Exception:
            result.error = traceback.format_exc()
        return result

    # ── Internal pipeline ──────────────────────────────────────────────────────

    def _pipeline(self, img: np.ndarray, npp: float, r: EdgeResult) -> None:
        H, W = img.shape
        spx  = max(1.0, self.sigma_nm / npp)

        # 1. Mean horizontal profile (central 40 % rows)
        r0, r1   = int(H * 0.30), int(H * 0.70)
        profile  = img[r0:r1, :].mean(axis=0).astype(float)
        smooth   = gaussian_filter1d(profile, sigma=spx)
        r.profile_x = np.arange(W) * npp
        r.profile_y = smooth

        # 2. Find edge pairs on mean profile
        pairs = self._edge_pairs(smooth, spx)
        if not pairs:
            r.error = "No edges detected. Check nm/px calibration and image contrast."
            return

        # 3. Per-row edge tracking (LWR/LER)
        L_rows, R_rows = [], []
        for y in range(H):
            row_s = gaussian_filter1d(img[y, :].astype(float), sigma=spx)
            rp    = self._edge_pairs(row_s, spx)
            if rp:
                L_rows.append(rp[0][0]); R_rows.append(rp[0][1])
            elif L_rows:
                L_rows.append(L_rows[-1]); R_rows.append(R_rows[-1])
            else:
                L_rows.append(pairs[0][0]); R_rows.append(pairs[0][1])

        La = np.array(L_rows, float)
        Ra = np.array(R_rows, float)
        r.left_edges  = La * npp
        r.right_edges = Ra * npp
        r.cd_values   = (Ra - La) * npp

        # 4. Pitch / Space from mean-profile pairs
        if len(pairs) >= 2:
            pc = [((pairs[i+1][0]+pairs[i+1][1])/2 - (pairs[i][0]+pairs[i][1])/2)
                  for i in range(len(pairs)-1)]
            sp = [(pairs[i+1][0] - pairs[i][1]) for i in range(len(pairs)-1)]
            r.pitch_values = np.array(pc) * npp
            r.space_values = np.array(sp) * npp
            r.pitch_mean   = float(np.mean(pc)) * npp
            r.space_mean   = float(np.mean(sp)) * npp

        # 5. CD statistics
        valid = r.cd_values[r.cd_values > 0]
        if len(valid) > 2:
            r.cd_mean = float(np.mean(valid))
            r.cd_std  = float(np.std(valid, ddof=1))
        else:
            r.cd_mean = (pairs[0][1] - pairs[0][0]) * npp if pairs else 0.0

        # 6. LWR / LER
        if len(La) > 10:
            w = Ra - La
            r.lwr_3s   = 3 * float(np.std(w,  ddof=1)) * npp
            r.ler_l_3s = 3 * float(np.std(La, ddof=1)) * npp
            r.ler_r_3s = 3 * float(np.std(Ra, ddof=1)) * npp

        # 7. Edge slope (tangent angle at CD height)
        if pairs:
            for ex, attr in [(int(pairs[0][0]), 'edge_slope_l'),
                             (int(pairs[0][1]), 'edge_slope_r')]:
                x0 = max(0, ex - int(6*spx))
                x1 = min(W-1, ex + int(6*spx))
                seg = smooth[x0:x1]
                if len(seg) > 3:
                    dy = abs(seg[-1] - seg[0])
                    dx = (x1 - x0) * npp
                    slope = dy / dx if dx > 0 else 0
                    setattr(r, attr,
                            min(90.0, math.degrees(math.atan(slope))) if slope > 0 else 90.0)

        # 8. PSD of LWR signal
        if len(La) > 32:
            width_nm = (Ra - La) * npp
            fs = 1.0 / npp
            freq, power = welch(width_nm - width_nm.mean(),
                                fs=fs, nperseg=min(len(La), 64))
            r.psd_freq  = freq  * 1000
            r.psd_power = power / 1000
            nz = (freq > 0) & (power > 0)
            if nz.sum() > 4:
                sl, *_ = np.polyfit(np.log10(freq[nz]), np.log10(power[nz]), 1)
                r.hurst = float(np.clip((1 - sl) / 2, 0, 1))
            ac = np.correlate(width_nm - width_nm.mean(),
                              width_nm - width_nm.mean(), mode='full')
            ac = ac[len(ac)//2:]
            ac /= max(ac[0], 1e-9)
            cr = np.where(ac < 1/math.e)[0]
            r.corr_len = float(cr[0]) * npp if len(cr) else 0.0

        # 9. Edge overlay list for viewport
        for lx, rx in pairs:
            r.edge_overlay.extend([
                (int(lx), 'left'), (int(rx), 'right'),
                (int((lx+rx)//2), 'center')])

        r.algo = self.ALGOS[self.algo]

    # ── Edge-pair dispatch ─────────────────────────────────────────────────────

    def _edge_pairs(self, p: np.ndarray, spx: float) -> list:
        algo = self.algo
        if   algo == 0: return self._gauss_deriv(p, spx)
        elif algo == 1: return self._threshold(p)
        elif algo == 2: return self._canny_1d(p, spx)
        else:           return self._sigmoidal(p, spx)

    # ── Algorithm implementations ──────────────────────────────────────────────

    def _gauss_deriv(self, p: np.ndarray, spx: float) -> list:
        """ISO 19973 — gradient magnitude peaks."""
        d1  = gaussian_filter1d(p, sigma=max(1, spx), order=1)
        mag = np.abs(d1)
        th  = mag.max() * 0.12
        if th < 0.3:
            return self._threshold(p)
        peaks, _ = find_peaks(mag, height=th,
                               distance=max(self.min_sep, int(spx * 0.5)))
        if len(peaks) < 2:
            return self._threshold(p)
        left_walls  = [int(pk) for pk in peaks if d1[pk] > 0]
        right_walls = [int(pk) for pk in peaks if d1[pk] < 0]
        pairs = []
        for lw in left_walls:
            nxt = [rw for rw in right_walls if rw > lw + self.min_sep]
            if nxt:
                pairs.append((float(lw), float(nxt[0])))
        if not pairs:
            all_pk = sorted(peaks)
            for i in range(0, len(all_pk) - 1, 2):
                pairs.append((float(all_pk[i]), float(all_pk[i+1])))
        return pairs[:8]

    def _threshold(self, p: np.ndarray) -> list:
        """Simple fractional threshold crossing."""
        mn, mx = p.min(), p.max()
        if mx - mn < 8:
            return []
        th     = mn + (mx - mn) * self.threshold
        bright = (p > th).astype(int)
        tr     = np.diff(bright)
        rises  = np.where(tr ==  1)[0]
        falls  = np.where(tr == -1)[0]
        pairs  = []
        for r in rises:
            nxt = [f for f in falls if f > r + self.min_sep]
            if nxt:
                pairs.append((float(r), float(nxt[0])))
        return pairs[:8]

    def _canny_1d(self, p: np.ndarray, spx: float) -> list:
        """1-D Canny via scikit-image (falls back to gauss_deriv if unavailable)."""
        try:
            from skimage import feature as skf
        except ImportError:
            return self._gauss_deriv(p, spx)
        img2d = np.stack([p] * 5, axis=0)
        rng   = img2d.max() - img2d.min()
        if rng > 0:
            img2d = (img2d - img2d.min()) / rng
        edges = skf.canny(img2d, sigma=max(1, spx))
        cols  = np.where(edges[2, :])[0]
        return [(float(cols[i]), float(cols[i+1]))
                for i in range(0, len(cols) - 1, 2)][:8]

    def _sigmoidal(self, p: np.ndarray, spx: float) -> list:
        """Sub-pixel sigmoid fit around each seed edge."""
        from scipy.optimize import curve_fit

        def sig(x, x0, a, b, c):
            return a / (1 + np.exp(-b * (x - x0))) + c

        seeds = self._gauss_deriv(p, spx)
        pairs = []
        for lx, rx in seeds:
            refined = []
            for ex in (lx, rx):
                x0 = max(0, int(ex) - int(5*spx))
                x1 = min(len(p), int(ex) + int(5*spx))
                seg = p[x0:x1]
                xs  = np.arange(len(seg), dtype=float)
                try:
                    p0 = [len(seg)/2, seg.max()-seg.min(), 1/max(spx, 0.1), seg.min()]
                    po, _ = curve_fit(sig, xs, seg, p0=p0, maxfev=300)
                    refined.append(x0 + po[0])
                except Exception:
                    refined.append(ex)
            pairs.append((refined[0], refined[1]))
        return pairs
