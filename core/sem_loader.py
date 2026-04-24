"""
cd_scope.core.sem_loader
──────────────────────────
Load real SEM images (.tif/.png/.jpg) and extract pixel calibration from metadata.

Supported metadata sources
  Hitachi  — TIFF tag 34682 (XML block)
  JEOL     — TIFF tag 50431
  FEI/Thermo — TIFF tag 34118
  Sidecar  — .txt / .json / .xml next to the image file
  Fallback — estimate from image width (1 µm field assumed)
"""
from __future__ import annotations
import json, re
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from cd_scope.core.models import SEMMeta

class SEMLoader:
    """
    Load SEM images and extract calibration metadata.

    Returns
    -------
    img  : np.ndarray, shape (H, W), dtype uint8, grayscale
    meta : SEMMeta
    """

    HIT_XML  = 34682
    HIT_DATA = 34683
    JEOL_TAG = 50431
    FEI_TAG  = 34118

    @classmethod
    def load(cls, path: str) -> tuple[np.ndarray, SEMMeta]:
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("Pillow not installed — run: pip install Pillow")

        meta = SEMMeta()
        img_pil = Image.open(path).convert("L")
        img     = np.array(img_pil, dtype=np.uint8)
        meta.pixel_width  = img.shape[1]
        meta.pixel_height = img.shape[0]

        ext = Path(path).suffix.lower()
        if ext in ('.tif', '.tiff'):
            cls._parse_tiff(img_pil, meta)
        else:
            cls._try_sidecar(path, meta)

        # Fallback calibration
        if meta.nm_per_px <= 0 or meta.nm_per_px > 100:
            meta.nm_per_px = 1000.0 / meta.pixel_width
            meta.source    = "estimated"

        meta.field_width_nm  = meta.nm_per_px * meta.pixel_width
        meta.field_height_nm = meta.nm_per_px * meta.pixel_height
        return img, meta

    # ── TIFF tag dispatcher ────────────────────────────────────────────────────

    @classmethod
    def _parse_tiff(cls, img_pil, meta: SEMMeta) -> None:
        try:
            tags = img_pil.tag_v2
        except AttributeError:
            return

        for tag in (cls.HIT_XML, cls.HIT_DATA, 34681, 34680):
            if tag in tags:
                raw = cls._tag_str(tags[tag])
                if '<' in raw and cls._hitachi_xml(raw, meta):
                    meta.source = 'hitachi'; return
                if cls._keyvalue(raw, meta):
                    meta.source = 'hitachi_kv'; return

        if cls.JEOL_TAG in tags:
            cls._keyvalue(cls._tag_str(tags[cls.JEOL_TAG]), meta)
            meta.instrument = 'JEOL'; meta.source = 'jeol'; return

        if cls.FEI_TAG in tags:
            cls._fei(cls._tag_str(tags[cls.FEI_TAG]), meta)
            meta.source = 'fei'; return

        if 270 in tags:
            desc = cls._tag_str(tags[270])
            if '<' in desc:
                cls._hitachi_xml(desc, meta)
            else:
                cls._keyvalue(desc, meta)
            if meta.nm_per_px > 0:
                meta.source = 'image_description'

    # ── Format parsers ─────────────────────────────────────────────────────────

    @classmethod
    def _hitachi_xml(cls, xml_str: str, meta: SEMMeta) -> bool:
        xml_str = xml_str.replace('\x00', '').replace('\ufeff', '').strip()
        if not xml_str.startswith('<'):
            idx = xml_str.find('<')
            if idx < 0: return False
            xml_str = xml_str[idx:]
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return False

        def get(*names: str) -> str:
            for name in names:
                for el in root.iter():
                    if el.tag.lower().endswith(name.lower()):
                        v = (el.text or '').strip()
                        if v: return v
                    for k, v in el.attrib.items():
                        if k.lower() == name.lower() and v.strip():
                            return v.strip()
            return ''

        def flt(*names: str) -> float:
            v = get(*names)
            try:   return float(re.sub(r'[^0-9.\-]', '', v))
            except: return 0.0

        ps = get('PixelSize', 'ScanSize', 'FieldSize', 'pixelsize')
        if ps:
            v = flt('PixelSize', 'ScanSize', 'FieldSize')
            if v > 0:
                if v > 100:  meta.nm_per_px = v / meta.pixel_width
                elif v > 1:  meta.nm_per_px = v
                else:        meta.nm_per_px = v * 1000

        mag = flt('Magnification', 'Mag')
        if mag > 0:
            meta.mag = mag
            if meta.nm_per_px <= 0:
                meta.nm_per_px = 47000.0 / (mag * (meta.pixel_width / 512.0))

        meta.acc_voltage  = flt('AcceleratingVoltage', 'AccVoltage', 'kV')
        meta.working_dist = flt('WorkingDistance', 'WD')
        meta.recipe_name  = get('RecipeName', 'Recipe')
        meta.lot_id       = get('LotID', 'Lot')
        meta.wafer_id     = get('WaferID', 'Wafer')
        meta.site_id      = get('SiteID', 'Site')
        meta.date         = get('DateTime', 'Date')
        meta.instrument   = get('InstrumentID', 'Instrument') or 'Hitachi'
        return meta.nm_per_px > 0

    @classmethod
    def _keyvalue(cls, text: str, meta: SEMMeta) -> bool:
        found = False
        tl = text.lower()
        kv_map = [
            ('nm_per_px',    [r'pixel.?size\s*[=:]\s*([\d.]+)']),
            ('mag',          [r'mag(?:nification)?\s*[=:]\s*([\d.]+)']),
            ('acc_voltage',  [r'acc.*volt.*[=:]\s*([\d.]+)', r'kv\s*[=:]\s*([\d.]+)']),
            ('working_dist', [r'w\.?d\.?\s*[=:]\s*([\d.]+)']),
        ]
        for field_name, pats in kv_map:
            for pat in pats:
                m = re.search(pat, tl)
                if m:
                    try:
                        setattr(meta, field_name, float(m.group(1)))
                        found = True
                    except Exception:
                        pass
                    break
        return found

    @classmethod
    def _fei(cls, text: str, meta: SEMMeta) -> None:
        for line in text.splitlines():
            kv = line.split('=', 1)
            if len(kv) != 2:
                continue
            k, v = kv[0].strip().lower(), kv[1].strip()
            try:
                if 'pixelwidth' in k:
                    meta.nm_per_px = float(v) * 1e9
                elif 'hfw' in k:
                    meta.nm_per_px = float(v) * 1e9 / max(meta.pixel_width, 1)
                elif 'voltage' in k:
                    meta.acc_voltage = float(v)
                elif 'magnification' in k:
                    meta.mag = float(v)
            except ValueError:
                pass
        meta.instrument = 'FEI/Thermo'

    @classmethod
    def _try_sidecar(cls, path: str, meta: SEMMeta) -> None:
        base   = Path(path).stem
        parent = Path(path).parent
        for ext in ('.txt', '.json', '.xml', '.ini'):
            sp = parent / (base + ext)
            if not sp.exists():
                continue
            txt = sp.read_text(errors='ignore')
            if ext == '.json':
                try:
                    d = json.loads(txt)
                    for k, attr in [('nm_per_px', 'nm_per_px'),
                                    ('pixelSize', 'nm_per_px'),
                                    ('mag',       'mag'),
                                    ('accVoltage','acc_voltage')]:
                        if k in d:
                            try: setattr(meta, attr, float(d[k]))
                            except Exception: pass
                    meta.source = 'sidecar_json'
                    return
                except Exception:
                    pass
            cls._keyvalue(txt, meta)
            if meta.nm_per_px > 0:
                meta.source = 'sidecar_txt'
                return

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _tag_str(raw) -> str:
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode('utf-8', errors='ignore')
        if isinstance(raw, tuple):
            raw = raw[0] if raw else ''
        return str(raw)
