"""
cd_scope.io.scanner_parser
────────────────────────────
Parse scanner exposure log files (ASML, generic).

Supported formats
  .csv / .txt  — tabular with dose/focus columns
  .json        — list of field dicts
  Key=Value    — ASML-style block files
"""
from __future__ import annotations
import json, re
from pathlib import Path

from cd_scope.core.models import ScannerExposure

class ScannerDataParser:
    """Parse scanner log files → list[ScannerExposure]."""

    @classmethod
    def parse(cls, path: str) -> list[ScannerExposure]:
        ext = Path(path).suffix.lower()
        txt = Path(path).read_text(errors='ignore')
        if ext == '.json':
            return cls._from_json(txt)
        fields = cls._from_table(txt)
        if not fields:
            fields = cls._from_keyvalue(txt)
        return fields

    # ── JSON ───────────────────────────────────────────────────────────────────

    @classmethod
    def _from_json(cls, txt: str) -> list[ScannerExposure]:
        data = json.loads(txt)
        if isinstance(data, dict):
            data = [data]
        fields: list[ScannerExposure] = []
        for d in data:
            f = ScannerExposure()
            f.field_id  = str(d.get('field_id', d.get('id', '')))
            f.x_mm      = float(d.get('x_mm', d.get('x', 0)))
            f.y_mm      = float(d.get('y_mm', d.get('y', 0)))
            f.dose      = float(d.get('dose', d.get('exposure_dose', 0)))
            f.focus     = float(d.get('focus', d.get('defocus', 0)))
            f.na        = float(d.get('na', d.get('numerical_aperture', 0)))
            f.sigma     = float(d.get('sigma', d.get('partial_coherence', 0)))
            f.wavelength= float(d.get('wavelength', 13.5))
            f.lot_id    = str(d.get('lot_id', ''))
            f.wafer_id  = str(d.get('wafer_id', ''))
            f.date      = str(d.get('date', ''))
            f.slot      = int(d.get('slot', 0))
            fields.append(f)
        return fields

    # ── Tabular ────────────────────────────────────────────────────────────────

    @classmethod
    def _from_table(cls, txt: str) -> list[ScannerExposure]:
        # Auto-detect delimiter
        delim = '\t' if txt.count('\t') > txt.count(',') else ','
        if txt.count(';') > txt.count(delim):
            delim = ';'

        lines = [l for l in txt.splitlines()
                 if l.strip() and not l.strip().startswith('#')]
        if len(lines) < 2:
            return []

        # Find header row
        hdr_idx = 0
        for i, line in enumerate(lines):
            ll = line.lower()
            if any(k in ll for k in ('dose', 'focus', 'field', 'expo', 'defocus')):
                hdr_idx = i
                break

        hdr = [h.strip().lower() for h in lines[hdr_idx].split(delim)]

        def ci(*names):
            for n in names:
                for i, h in enumerate(hdr):
                    if n.lower() in h:
                        return i
            return -1

        i_fid = ci('field', 'id', 'site')
        i_x   = ci('x_mm', 'x', 'xcoord', 'stagex')
        i_y   = ci('y_mm', 'y', 'ycoord', 'stagey')
        i_d   = ci('dose', 'exposure', 'energy')
        i_f   = ci('focus', 'defocus', 'z')
        i_na  = ci('na', 'numerical')
        i_sig = ci('sigma', 'partial')
        i_wl  = ci('wavelength', 'lambda')
        i_lot = ci('lot')
        i_wfr = ci('wafer')
        i_dt  = ci('date', 'time')

        if i_d < 0 and i_f < 0:
            return []

        fields: list[ScannerExposure] = []
        for line in lines[hdr_idx + 1:]:
            row = [c.strip() for c in line.split(delim)]
            if len(row) < 2:
                continue
            fe = ScannerExposure()
            fe.field_id  = cls._sv(row, i_fid, str(len(fields)+1))
            fe.x_mm      = cls._fv(row, i_x)
            fe.y_mm      = cls._fv(row, i_y)
            fe.dose      = cls._fv(row, i_d)
            fe.focus     = cls._fv(row, i_f)
            fe.na        = cls._fv(row, i_na)
            fe.sigma     = cls._fv(row, i_sig)
            fe.wavelength= cls._fv(row, i_wl) or 13.5
            fe.lot_id    = cls._sv(row, i_lot)
            fe.wafer_id  = cls._sv(row, i_wfr)
            fe.date      = cls._sv(row, i_dt)
            if fe.dose > 0 or fe.focus != 0:
                fields.append(fe)
        return fields

    # ── Key=Value blocks ────────────────────────────────────────────────────────

    @classmethod
    def _from_keyvalue(cls, txt: str) -> list[ScannerExposure]:
        fields: list[ScannerExposure] = []
        current: dict[str, str] = {}
        for line in txt.splitlines():
            line = line.strip()
            if not line or line.startswith(('--', '==', '##')):
                if current:
                    fe = cls._kv_to_exposure(current)
                    if fe.dose > 0:
                        fields.append(fe)
                    current = {}
                continue
            m = re.match(r'([A-Za-z_][A-Za-z0-9_ ]*)\s*[=:]\s*(.+)', line)
            if m:
                current[m.group(1).strip()] = m.group(2).strip()
        if current:
            fe = cls._kv_to_exposure(current)
            if fe.dose > 0:
                fields.append(fe)
        return fields

    @classmethod
    def _kv_to_exposure(cls, d: dict) -> ScannerExposure:
        fe = ScannerExposure()
        for k, v in d.items():
            kl = k.lower()
            try:
                fv = float(re.sub(r'[^0-9.\-+Ee]', '', v))
            except (ValueError, TypeError):
                fv = 0.0
            if 'dose' in kl or 'exposure' in kl:
                fe.dose = fv
            elif 'focus' in kl or 'defocus' in kl:
                fe.focus = fv
            elif kl in ('x', 'x_mm', 'stagex'):
                fe.x_mm = fv
            elif kl in ('y', 'y_mm', 'stagey'):
                fe.y_mm = fv
            elif 'na' in kl or 'numerical' in kl:
                fe.na = fv
            elif 'sigma' in kl or 'partial' in kl:
                fe.sigma = fv
        return fe

    # ── Template ────────────────────────────────────────────────────────────────

    @staticmethod
    def write_template(path: str) -> None:
        content = (
            "# CD_SCOPE Scanner Data File\n"
            "# Columns: field_id, x_mm, y_mm, dose, focus, na, sigma, wavelength, lot_id, wafer_id\n"
            "field_id,x_mm,y_mm,dose,focus,na,sigma,wavelength,lot_id,wafer_id\n"
            "F001,0.0,0.0,28.0,0.000,0.33,0.9,13.5,LOT001,W01\n"
            "F002,26.0,0.0,28.5,+0.020,0.33,0.9,13.5,LOT001,W01\n"
            "F003,-26.0,0.0,29.0,-0.020,0.33,0.9,13.5,LOT001,W01\n"
        )
        Path(path).write_text(content)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fv(row: list, idx: int, default: float = 0.0) -> float:
        if 0 <= idx < len(row):
            try:
                return float(re.sub(r'[^0-9.\-+Ee]', '', row[idx]))
            except (ValueError, TypeError):
                pass
        return default

    @staticmethod
    def _sv(row: list, idx: int, default: str = '') -> str:
        return row[idx].strip() if 0 <= idx < len(row) else default
