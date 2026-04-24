"""
cd_scope.io.batch_parser
──────────────────────────
Parse batch condition files that map image paths to metadata.

Supported formats
  .csv   — header row + data rows (auto-detects delimiter)
  .json  — list of dicts
  .ini   — [Image001] sections
  .txt   — key=value blocks or plain path lists
"""
from __future__ import annotations
import configparser, json, re
from pathlib import Path

from cd_scope.core.models import BatchImageRecord

class BatchConditionParser:
    """Parse batch condition files → list[BatchImageRecord]."""

    @classmethod
    def parse(cls, path: str) -> list[BatchImageRecord]:
        base = Path(path).parent
        txt  = Path(path).read_text(errors='ignore')
        ext  = Path(path).suffix.lower()

        if ext == '.json':
            records = cls._from_json(txt, base)
        elif ext in ('.ini', '.cfg'):
            records = cls._from_ini(txt, base)
        else:
            records = cls._from_csv(txt, base)

        if not records:
            records = cls._from_text(txt, base)
        return records

    # ── JSON ───────────────────────────────────────────────────────────────────

    @classmethod
    def _from_json(cls, txt: str, base: Path) -> list[BatchImageRecord]:
        data = json.loads(txt)
        if isinstance(data, dict):
            data = [data]
        records: list[BatchImageRecord] = []
        for d in data:
            r = BatchImageRecord()
            r.image_path   = cls._resolve(d.get('image_path') or d.get('file', ''), base)
            r.nm_per_px    = float(d.get('nm_per_px', d.get('pixelSize', 0)))
            r.site_id      = str(d.get('site_id', d.get('site', '')))
            r.lot_id       = str(d.get('lot_id', ''))
            r.wafer_id     = str(d.get('wafer_id', ''))
            r.x_mm         = float(d.get('x_mm', d.get('x', 0)))
            r.y_mm         = float(d.get('y_mm', d.get('y', 0)))
            r.dose         = float(d.get('dose', d.get('exposure_dose', 0)))
            r.focus        = float(d.get('focus', d.get('defocus', 0)))
            r.pattern_type = str(d.get('pattern_type', 'Line/Space 1:1'))
            r.target_cd    = float(d.get('target_cd', 32.0))
            r.comment      = str(d.get('comment', ''))
            if r.image_path:
                records.append(r)
        return records

    # ── INI ────────────────────────────────────────────────────────────────────

    @classmethod
    def _from_ini(cls, txt: str, base: Path) -> list[BatchImageRecord]:
        cfg = configparser.ConfigParser()
        cfg.read_string(txt)
        records: list[BatchImageRecord] = []
        for sec in cfg.sections():
            d = dict(cfg[sec])
            r = BatchImageRecord()
            r.image_path   = cls._resolve(d.get('image_path', d.get('file', '')), base)
            r.nm_per_px    = cls._flt(d.get('nm_per_px', '0'))
            r.site_id      = d.get('site_id', sec)
            r.lot_id       = d.get('lot_id', '')
            r.wafer_id     = d.get('wafer_id', '')
            r.x_mm         = cls._flt(d.get('x_mm', '0'))
            r.y_mm         = cls._flt(d.get('y_mm', '0'))
            r.dose         = cls._flt(d.get('dose', '0'))
            r.focus        = cls._flt(d.get('focus', '0'))
            r.pattern_type = d.get('pattern_type', 'Line/Space 1:1')
            r.target_cd    = cls._flt(d.get('target_cd', '32.0'))
            r.comment      = d.get('comment', '')
            if r.image_path:
                records.append(r)
        return records

    # ── CSV ────────────────────────────────────────────────────────────────────

    @classmethod
    def _from_csv(cls, txt: str, base: Path) -> list[BatchImageRecord]:
        delim = ';' if txt.count(';') > txt.count(',') else ','
        lines = [l for l in txt.splitlines() if l.strip()]
        if len(lines) < 2:
            return []

        # Locate header
        hdr_idx = 0
        for i, line in enumerate(lines):
            ll = line.lower()
            if any(k in ll for k in ('image', 'file', 'path', 'site', 'nm_per')):
                hdr_idx = i
                break

        hdr = [h.strip().lower() for h in lines[hdr_idx].split(delim)]

        def ci(*names):
            for n in names:
                for i, h in enumerate(hdr):
                    if n.lower() in h:
                        return i
            return -1

        ig  = ci('image', 'file', 'path', 'img')
        in_ = ci('nm_per_px', 'pixel_size', 'pixelsize')
        isi = ci('site_id', 'site')
        ilo = ci('lot_id', 'lot')
        iw  = ci('wafer_id', 'wafer')
        ix  = ci('x_mm', 'x', 'xcoord')
        iy  = ci('y_mm', 'y', 'ycoord')
        ido = ci('dose', 'exposure')
        ifo = ci('focus', 'defocus')
        ipt = ci('pattern_type', 'pattern')
        itc = ci('target_cd', 'target')
        ico = ci('comment')

        records: list[BatchImageRecord] = []
        for line in lines[hdr_idx + 1:]:
            row = [c.strip() for c in line.split(delim)]
            if ig < 0 or not row:
                continue
            img_path = cls._resolve(row[ig] if ig < len(row) else '', base)
            if not img_path:
                continue
            r = BatchImageRecord()
            r.image_path   = img_path
            r.nm_per_px    = cls._flt(row[in_] if 0 <= in_ < len(row) else '')
            r.site_id      = row[isi].strip() if 0 <= isi < len(row) else str(len(records)+1)
            r.lot_id       = row[ilo].strip() if 0 <= ilo < len(row) else ''
            r.wafer_id     = row[iw].strip()  if 0 <= iw  < len(row) else ''
            r.x_mm         = cls._flt(row[ix]  if 0 <= ix  < len(row) else '')
            r.y_mm         = cls._flt(row[iy]  if 0 <= iy  < len(row) else '')
            r.dose         = cls._flt(row[ido] if 0 <= ido < len(row) else '')
            r.focus        = cls._flt(row[ifo] if 0 <= ifo < len(row) else '')
            r.pattern_type = row[ipt].strip() if 0 <= ipt < len(row) else 'Line/Space 1:1'
            r.target_cd    = cls._flt(row[itc] if 0 <= itc < len(row) else '') or 32.0
            r.comment      = row[ico].strip() if 0 <= ico < len(row) else ''
            records.append(r)
        return records

    # ── Text fallback ──────────────────────────────────────────────────────────

    @classmethod
    def _from_text(cls, txt: str, base: Path) -> list[BatchImageRecord]:
        """Find image file paths anywhere in a text file."""
        IMG_EXTS = {'.tif', '.tiff', '.png', '.jpg', '.bmp'}
        records: list[BatchImageRecord] = []
        for line in txt.splitlines():
            for token in line.replace('\t', ' ').split():
                if Path(token).suffix.lower() in IMG_EXTS:
                    r = BatchImageRecord()
                    r.image_path = cls._resolve(token, base)
                    nums = [float(n) for n in re.findall(r'[\-+]?\d+\.?\d*', line)
                            if cls._safe_float(n) is not None]
                    if nums:
                        r.nm_per_px = nums[0]
                    records.append(r)
                    break
        return records

    # ── Template writer ────────────────────────────────────────────────────────

    @staticmethod
    def write_template(path: str) -> None:
        content = (
            "# CD_SCOPE Batch Condition File\n"
            "# Columns: image_path, nm_per_px, site_id, x_mm, y_mm,"
            " dose, focus, pattern_type, target_cd, comment\n"
            "# pattern_type: Line/Space 1:1 | 2:1 | 1:2 | Contact Hole Array\n"
            "image_path,nm_per_px,site_id,x_mm,y_mm,dose,focus,pattern_type,target_cd,comment\n"
            "sem_001.tif,0.47,S001,0.0,0.0,28.0,0.0,Line/Space 1:1,32.0,center\n"
            "sem_002.tif,0.47,S002,10.5,-8.2,28.5,0.0,Line/Space 1:1,32.0,\n"
            "sem_003.tif,0.47,S003,-10.0,5.0,29.0,+0.05,Line/Space 2:1,32.0,\n"
            "sem_004.tif,0.47,S004,0.0,45.0,28.0,0.0,Contact Hole Array,40.0,\n"
        )
        Path(path).write_text(content)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve(path_str: str, base: Path) -> str:
        if not path_str:
            return ''
        p = Path(path_str)
        if p.is_absolute():
            return str(p)
        return str(base / p)

    @staticmethod
    def _flt(s: str, default: float = 0.0) -> float:
        try:
            return float(re.sub(r'[^0-9.\-+Ee]', '', s))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(s: str):
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
