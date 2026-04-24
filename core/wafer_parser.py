"""
cd_scope.core.wafer_parser
────────────────────────────
Parse Hitachi CD-SEM wafer measurement output files.

Supported formats
  .csv  — semicolon- or comma-delimited, flexible column order
  .xml  — Hitachi WXML namespace-agnostic parser
  .txt / .mdf — key=value block format + column-table fallback
  .map  — simple site map format

Also provides generate_demo() for testing.
"""
from __future__ import annotations
import csv, math, random, re
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from cd_scope.core.models import WaferSite
from cd_scope.constants import TARGET_CD

class HitachiWaferParser:
    """Parse Hitachi wafer map files → list[WaferSite]."""

    @classmethod
    def parse(cls, path: str) -> list[WaferSite]:
        ext = Path(path).suffix.lower()
        txt = Path(path).read_text(errors='ignore')
        if ext == '.xml':
            return cls._xml(txt)
        if ext == '.csv':
            return cls._csv(txt)
        if ext in ('.txt', '.mdf', '.map'):
            return cls._text(txt)
        # Auto-detect
        for fn in (cls._xml, cls._csv, cls._text):
            try:
                sites = fn(txt)
                if sites:
                    return sites
            except Exception:
                pass
        raise ValueError(f"Could not parse wafer map: {path}")

    # ── XML ────────────────────────────────────────────────────────────────────

    @classmethod
    def _xml(cls, txt: str) -> list[WaferSite]:
        root = ET.fromstring(txt)
        sites: list[WaferSite] = []

        SITE_TAGS = {'site', 'measuresite', 'point', 'die', 'measurement'}

        for el in root.iter():
            tag = el.tag.split('}')[-1].lower()
            if tag not in SITE_TAGS:
                continue

            def gv(*names: str) -> str:
                for n in names:
                    for k, v in el.attrib.items():
                        if k.split('}')[-1].lower() == n.lower(): return v
                    for child in el:
                        ct = child.tag.split('}')[-1].lower()
                        if ct == n.lower(): return (child.text or '').strip()
                return ''

            def fv(*names: str) -> float:
                v = gv(*names)
                try:   return float(re.sub(r'[^0-9.\-]', '', v))
                except: return 0.0

            cd = fv('CD', 'CDMean', 'cd_mean', 'MeasuredCD', 'Value')
            if cd <= 0:
                continue

            sid   = gv('SiteID', 'ID', 'Name', 'id') or str(len(sites)+1)
            xmm   = fv('X', 'XCoord', 'x_mm', 'StageX')
            ymm   = fv('Y', 'YCoord', 'y_mm', 'StageY')
            cdst  = fv('CDSigma', 'CDStd', 'Sigma')
            lwr   = fv('LWR', 'lwr')
            pitch = fv('Pitch', 'pitch')
            space = fv('Space', 'space')
            lerl  = fv('LER_L', 'LERL')
            lerr  = fv('LER_R', 'LERR')
            st    = gv('Status', 'Pass', 'Result').upper()
            if not st:
                st = 'PASS' if abs(cd - TARGET_CD) < 3 else 'FAIL'

            sites.append(WaferSite(sid, xmm, ymm, cd, cdst, lwr,
                                    st, pitch, space, lerl, lerr))
        return sites

    # ── CSV ────────────────────────────────────────────────────────────────────

    @classmethod
    def _csv(cls, txt: str) -> list[WaferSite]:
        delim  = ';' if txt.count(';') > txt.count(',') else ','
        lines  = [l for l in txt.splitlines() if l.strip()]
        if not lines:
            return []

        # Locate header row
        hdr_idx = 0
        for i, line in enumerate(lines):
            ll = line.lower()
            if any(k in ll for k in ('site', 'cd', 'x_', 'y_', 'xcoord', 'ycoord')):
                hdr_idx = i; break

        hdr = [h.strip().lower() for h in lines[hdr_idx].split(delim)]

        def ci(*names: str) -> int:
            for n in names:
                for i, h in enumerate(hdr):
                    if n.lower() in h: return i
            return -1

        i_site = ci('site_id', 'site', 'id')
        i_x    = ci('x_mm', 'x', 'xcoord', 'stage_x')
        i_y    = ci('y_mm', 'y', 'ycoord', 'stage_y')
        i_cd   = ci('cd_mean', 'cd', 'mean', 'measured')
        i_cds  = ci('cd_sigma', 'sigma', 'std')
        i_lwr  = ci('lwr', 'roughness')
        i_pit  = ci('pitch')
        i_sp   = ci('space')
        i_lerl = ci('ler_l', 'lerl')
        i_lerr = ci('ler_r', 'lerr')
        i_st   = ci('status', 'pass', 'result', 'judge')
        i_imgf = ci('image', 'file', 'img')

        def fget(row: list, idx: int, default: float = 0.0) -> float:
            if 0 <= idx < len(row):
                try: return float(re.sub(r'[^0-9.\-]', '', row[idx]))
                except: pass
            return default

        def sget(row: list, idx: int, default: str = '') -> str:
            return row[idx].strip() if 0 <= idx < len(row) else default

        sites: list[WaferSite] = []
        for line in lines[hdr_idx+1:]:
            row = [c.strip() for c in line.split(delim)]
            if len(row) < 2:
                continue
            cd = fget(row, i_cd)
            if cd <= 0:
                continue
            st = sget(row, i_st).upper() or ('PASS' if abs(cd-TARGET_CD) < 3 else 'FAIL')
            sites.append(WaferSite(
                site_id  = sget(row, i_site, str(len(sites)+1)),
                x_mm     = fget(row, i_x),
                y_mm     = fget(row, i_y),
                cd_mean  = cd,
                cd_std   = fget(row, i_cds),
                lwr      = fget(row, i_lwr),
                status   = st,
                pitch    = fget(row, i_pit),
                space    = fget(row, i_sp),
                ler_l    = fget(row, i_lerl),
                ler_r    = fget(row, i_lerr),
                img_file = sget(row, i_imgf),
            ))
        return sites

    # ── Text / MDF ─────────────────────────────────────────────────────────────

    @classmethod
    def _text(cls, txt: str) -> list[WaferSite]:
        sites: list[WaferSite] = []

        # Strategy 1: key=value blocks separated by blank lines
        blocks = re.split(r'\n\s*\n|\[Site|\[SITE', txt)
        for block in blocks:
            d: dict[str, str] = {}
            for line in block.splitlines():
                m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_ ]*)\s*[=:]\s*(.+)', line)
                if m:
                    d[m.group(1).lower().strip()] = m.group(2).strip()
            cd = 0.0
            for k in ('cd', 'cd_mean', 'measured_cd'):
                if k in d:
                    try: cd = float(re.sub(r'[^0-9.\-]', '', d[k])); break
                    except: pass
            if cd <= 0:
                continue

            def dv(k: str, *keys: str) -> float:
                for kk in (k,) + keys:
                    if kk in d:
                        try: return float(re.sub(r'[^0-9.\-]', '', d[kk]))
                        except: pass
                return 0.0

            st = d.get('status', d.get('judge', d.get('result', ''))).upper()
            if not st:
                st = 'PASS' if abs(cd - TARGET_CD) < 3 else 'FAIL'

            sites.append(WaferSite(
                site_id = d.get('siteid', d.get('site', str(len(sites)+1))),
                x_mm    = dv('x', 'x_mm', 'xcoord'),
                y_mm    = dv('y', 'y_mm', 'ycoord'),
                cd_mean = cd,
                cd_std  = dv('cd_sigma', 'sigma'),
                lwr     = dv('lwr'),
                status  = st,
            ))

        if sites:
            return sites

        # Strategy 2: column-aligned numeric table
        for line in txt.splitlines():
            nums = re.findall(r'[\-+]?\d+\.?\d*', line)
            if len(nums) >= 4:
                try:
                    xmm = float(nums[0]); ymm = float(nums[1]); cd = float(nums[2])
                    if 10 < cd < 200:
                        sites.append(WaferSite(
                            site_id = str(len(sites)+1),
                            x_mm    = xmm, y_mm = ymm,
                            cd_mean = cd,
                            cd_std  = float(nums[3]) if len(nums) > 3 else 0,
                            lwr     = float(nums[4]) if len(nums) > 4 else 0,
                            status  = 'PASS' if abs(cd - TARGET_CD) < 3 else 'FAIL',
                        ))
                except Exception:
                    pass
        return sites

    # ── Demo generator ─────────────────────────────────────────────────────────

    @staticmethod
    def generate_demo(n_sites: int = 49,
                      wafer_diam_mm: float = 300,
                      target_cd: float = TARGET_CD,
                      seed: int = 42) -> list[WaferSite]:
        """Generate a realistic demo wafer map with radial CD gradient."""
        rng     = random.Random(seed)
        sites:  list[WaferSite] = []
        r_wafer = wafer_diam_mm / 2
        cols    = int(math.sqrt(n_sites)) + 2
        step    = wafer_diam_mm / (cols - 1)
        sid     = 1

        for row in range(cols):
            for col in range(cols):
                x = -r_wafer + col * step
                y = -r_wafer + row * step
                if math.sqrt(x*x + y*y) > r_wafer * 0.95:
                    continue

                r_norm  = math.sqrt(x*x + y*y) / r_wafer
                cd_bias = 0.8 * r_norm**2 * (1 if rng.random() > 0.5 else -1)
                cd      = target_cd + cd_bias + rng.gauss(0, 0.5)
                lwr     = abs(2.5 + rng.gauss(0, 0.4))

                st = ('PASS' if 30 <= cd <= 34 and lwr <= 4
                      else 'FAIL' if cd < 30 or cd > 34
                      else 'WARN')

                sites.append(WaferSite(
                    site_id = f"S{sid:03d}",
                    x_mm    = round(x, 1),
                    y_mm    = round(y, 1),
                    cd_mean = round(cd, 2),
                    cd_std  = round(rng.uniform(0.2, 0.8), 2),
                    lwr     = round(lwr, 2),
                    status  = st,
                    pitch   = round(64 + rng.gauss(0, 0.3), 2),
                    space   = round(32 + rng.gauss(0, 0.3), 2),
                ))
                sid += 1
                if len(sites) >= n_sites:
                    return sites
        return sites
