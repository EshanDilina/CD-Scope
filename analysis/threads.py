"""
cd_scope.analysis.threads
───────────────────────────
Background QThread workers.  All heavy computation runs here, not on the
GUI thread.  Workers communicate via pyqtSignal only.
"""
from __future__ import annotations
import datetime, math, threading, time, traceback
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from cd_scope.core import (    EdgeDetector, EdgeResult,
    SEMLoader, SEMMeta,
    PatternConfig, PatternAnalyzer,
    BatchImageRecord,
)
from cd_scope.analysis.synthetic import gen_synthetic_sem, gen_synthetic_contact

# ── Single-image analysis ──────────────────────────────────────────────────────

class AnalysisThread(QThread):
    """Runs EdgeDetector.analyse() off the GUI thread."""
    progress     = pyqtSignal(int, str)
    result_ready = pyqtSignal(object)   # EdgeResult
    error        = pyqtSignal(str)

    def __init__(self, img: np.ndarray, npp: float,
                 detector: EdgeDetector, parent=None):
        super().__init__(parent)
        self._img = img
        self._npp = npp
        self._det = detector

    def run(self) -> None:
        self.progress.emit(10, "Preprocessing…")
        time.sleep(0.03)
        self.progress.emit(35, "Running edge detection…")
        result = self._det.analyse(self._img, self._npp)
        self.progress.emit(75, "Computing LWR / PSD…")
        time.sleep(0.03)
        self.progress.emit(100, "Done.")
        if result.error:
            self.error.emit(result.error)
        self.result_ready.emit(result)


# ── Batch image analysis ───────────────────────────────────────────────────────

class BatchAnalysisThread(QThread):
    """Runs EdgeDetector + PatternAnalyzer on a list of BatchImageRecord."""
    progress     = pyqtSignal(int, str)
    record_done  = pyqtSignal(int, object)   # (index, BatchImageRecord)
    finished_all = pyqtSignal(list)          # list[BatchImageRecord]

    def __init__(self, records: list[BatchImageRecord],
                 detector: EdgeDetector,
                 base_cfg: PatternConfig,
                 parent=None):
        super().__init__(parent)
        self._records  = records
        self._detector = detector
        self._base_cfg = base_cfg

    def run(self) -> None:
        n = len(self._records)
        for i, rec in enumerate(self._records):
            self.progress.emit(
                int(i / n * 100),
                f"[{i+1}/{n}] {Path(rec.image_path).name}"
            )
            self._process_one(i, rec)
        self.progress.emit(100, "Batch complete.")
        self.finished_all.emit(self._records)

    def _process_one(self, idx: int, rec: BatchImageRecord) -> None:
        try:
            img, meta = SEMLoader.load(rec.image_path)
            npp       = rec.nm_per_px if rec.nm_per_px > 0 else meta.nm_per_px
            pat_cfg   = PatternConfig.from_string(rec.pattern_type)
            pat_cfg.target_cd = rec.target_cd
            pa  = PatternAnalyzer(self._detector, pat_cfg)
            res = pa.analyse(img, npp)

            if pat_cfg.is_contact:
                rec.cd_mean = res.get('cd_mean', 0)
                rec.cd_std  = res.get('cd_std', 0)
                rec.n_holes = res.get('n_holes', 0)
                rec.status  = ('PASS' if abs(rec.cd_mean - rec.target_cd) < 3
                               else 'FAIL')
            else:
                rec.cd_mean   = res.get('cd_mean', 0)
                rec.cd_std    = res.get('cd_std', 0)
                rec.lwr_3s    = res.get('lwr_3s', 0)
                rec.pitch_mean= res.get('pitch_mean', 0)
                rec.space_mean= res.get('space_mean', 0)
                ok = 30 <= rec.cd_mean <= 34 and rec.lwr_3s <= 4
                rec.status = 'PASS' if ok else 'FAIL'

            rec.error = res.get('error', '')
        except Exception:
            rec.error  = traceback.format_exc()[:300]
            rec.status = 'ERROR'

        self.record_done.emit(idx, rec)


# ── Live acquisition ───────────────────────────────────────────────────────────

class AcquisitionConfig:
    def __init__(self):
        self.mode           = "single"       # single | continuous | triggered
        self.frame_rate_hz  = 2.0
        self.auto_analyze   = True
        self.auto_save      = False
        self.save_dir       = str(Path.home() / 'cd_scope_images')
        self.n_frames       = 1              # 0 = unlimited
        self.nm_per_px      = 0.49
        self.perturb        = 0.5
        self.pattern_type   = "Line/Space 1:1"
        self.trigger_source = "manual"


class LiveAcquisitionThread(QThread):
    """
    Simulated frame-grabber loop.
    In production: replace _grab_frame() with your camera SDK call.
    """
    frame_ready     = pyqtSignal(object, object, object)  # QPixmap, img, SEMMeta
    analysis_ready  = pyqtSignal(object)                  # EdgeResult
    status_update   = pyqtSignal(str)
    frame_count_upd = pyqtSignal(int)

    def __init__(self, cfg: AcquisitionConfig,
                 detector: EdgeDetector,
                 parent=None):
        super().__init__(parent)
        self._cfg      = cfg
        self._det      = detector
        self._frame_n  = 0
        self._stop_evt = threading.Event()
        self._paused   = False

    def run(self) -> None:
        self._stop_evt.clear()
        interval = 1.0 / max(self._cfg.frame_rate_hz, 0.1)

        while not self._stop_evt.is_set():
            if self._paused:
                self._stop_evt.wait(0.1)
                continue

            pix, img, meta = self._grab_frame()
            self._frame_n += 1
            self.frame_ready.emit(pix, img, meta)
            self.frame_count_upd.emit(self._frame_n)

            if self._cfg.auto_analyze:
                r = self._det.analyse(img, meta.nm_per_px)
                self.analysis_ready.emit(r)
                self.status_update.emit(
                    f"Frame {self._frame_n}: "
                    f"CD={r.cd_mean:.2f}nm  LWR={r.lwr_3s:.2f}nm")

            if self._cfg.auto_save:
                self._save_frame(img, self._frame_n)

            if self._cfg.mode == 'single':
                break
            elif (self._cfg.n_frames > 0
                  and self._frame_n >= self._cfg.n_frames):
                break

            self._stop_evt.wait(interval)

    def _grab_frame(self):
        """Synthetic frame — replace with real camera SDK."""
        cfg     = self._cfg
        W = H   = 512
        npp     = cfg.nm_per_px
        perturb = cfg.perturb * (1 + 0.3 * math.sin(self._frame_n * 0.5))
        if 'Contact' in cfg.pattern_type:
            return gen_synthetic_contact(W, H, npp, perturb=perturb * 2)
        return gen_synthetic_sem(W, H, npp, perturb=perturb)

    def _save_frame(self, img: np.ndarray, n: int) -> None:
        try:
            from PIL import Image as PILImage
            d  = Path(self._cfg.save_dir)
            d.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            PILImage.fromarray(img).save(str(d / f"frame_{n:04d}_{ts}.tif"))
        except Exception:
            pass

    def pause(self)  -> None: self._paused = True
    def resume(self) -> None: self._paused = False
    def stop(self)   -> None: self._stop_evt.set()
