"""
cd_scope.db.database
──────────────────────
SQLite-backed measurement store.  All reads and writes are thread-safe.
"""
from __future__ import annotations
import csv, datetime, sqlite3, threading
from pathlib import Path

import numpy as np

from cd_scope.core.models import WaferSite
from cd_scope.constants import USL, LSL

class MetroscanDB:
    """
    Persistent measurement database.

    Tables
    ------
    lots            lot_id, created, recipe, notes
    wafers          wafer_id, lot_id, slot, date, instrument, operator, notes
    sites           full per-site measurement row
    wafer_summaries pre-aggregated Cp/Cpk/CDU per wafer
    run_history     APC-logged run records
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS lots (
        lot_id  TEXT PRIMARY KEY,
        created TEXT,
        recipe  TEXT,
        notes   TEXT
    );
    CREATE TABLE IF NOT EXISTS wafers (
        wafer_id   TEXT,
        lot_id     TEXT,
        slot       INTEGER,
        date       TEXT,
        instrument TEXT,
        operator   TEXT,
        notes      TEXT,
        PRIMARY KEY(lot_id, wafer_id),
        FOREIGN KEY(lot_id) REFERENCES lots(lot_id)
    );
    CREATE TABLE IF NOT EXISTS sites (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_id         TEXT,
        wafer_id       TEXT,
        site_id        TEXT,
        x_mm           REAL,
        y_mm           REAL,
        cd_mean        REAL,
        cd_std         REAL,
        lwr_3s         REAL,
        ler_l          REAL,
        ler_r          REAL,
        pitch          REAL,
        space          REAL,
        duty_cycle     REAL,
        dose           REAL,
        focus          REAL,
        pattern_type   TEXT,
        status         TEXT,
        image_path     TEXT,
        algo           TEXT,
        hurst          REAL,
        corr_len       REAL,
        edge_slope_l   REAL,
        edge_slope_r   REAL,
        n_holes        INTEGER DEFAULT 0,
        timestamp      TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS wafer_summaries (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_id    TEXT,
        wafer_id  TEXT,
        cd_mean   REAL,
        cd_std    REAL,
        cdu_3s    REAL,
        lwr_mean  REAL,
        cp        REAL,
        cpk       REAL,
        n_sites   INTEGER,
        n_pass    INTEGER,
        n_fail    INTEGER,
        timestamp TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS run_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_name     TEXT,
        lot_id          TEXT,
        wafer_id        TEXT,
        cd_mean         REAL,
        cd_std          REAL,
        lwr_3s          REAL,
        dose_correction REAL DEFAULT 0,
        timestamp       TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_sites_lot_wafer  ON sites(lot_id, wafer_id);
    CREATE INDEX IF NOT EXISTS idx_sites_timestamp  ON sites(timestamp);
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = str(Path.home() / '.cd_scope' / 'measurements.db')
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn   = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()
        self._lock   = threading.Lock()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _exe(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _exe_many(self, sql: str, rows: list) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    # ── Write API ──────────────────────────────────────────────────────────────

    def ensure_lot(self, lot_id: str, recipe: str = "", notes: str = "") -> None:
        self._exe(
            "INSERT OR IGNORE INTO lots VALUES(?,?,?,?)",
            (lot_id, datetime.datetime.now().isoformat(), recipe, notes))
        self._conn.commit()

    def ensure_wafer(self, lot_id: str, wafer_id: str,
                     slot: int = 0, instrument: str = "", operator: str = "") -> None:
        self.ensure_lot(lot_id)
        self._exe(
            "INSERT OR IGNORE INTO wafers VALUES(?,?,?,?,?,?,?)",
            (wafer_id, lot_id, slot,
             datetime.datetime.now().isoformat(), instrument, operator, ""))
        self._conn.commit()

    def insert_sites_bulk(self, lot_id: str, wafer_id: str,
                          sites: list[WaferSite],
                          meta: dict | None = None) -> None:
        """Insert all sites from a wafer map in one transaction."""
        self.ensure_wafer(
            lot_id, wafer_id,
            instrument=(meta or {}).get('instrument', ''),
            operator  =(meta or {}).get('operator', ''),
        )
        rows = []
        for s in sites:
            duty = s.cd_mean / s.pitch * 100 if s.pitch > 0 else 0.0
            rows.append((
                lot_id, wafer_id, s.site_id, s.x_mm, s.y_mm,
                s.cd_mean, s.cd_std, s.lwr, s.ler_l, s.ler_r,
                s.pitch, s.space, round(duty, 2),
                0, 0, '', s.status, '', '', 0, 0, 90, 90, 0
            ))
        self._exe_many("""
            INSERT INTO sites
            (lot_id,wafer_id,site_id,x_mm,y_mm,
             cd_mean,cd_std,lwr_3s,ler_l,ler_r,
             pitch,space,duty_cycle,dose,focus,
             pattern_type,status,image_path,algo,
             hurst,corr_len,edge_slope_l,edge_slope_r,n_holes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)

        # Compute and store summary
        cds = [s.cd_mean for s in sites if s.cd_mean > 0]
        if cds:
            mu  = np.mean(cds)
            sg  = np.std(cds, ddof=1) if len(cds) > 1 else 0
            cp  = (USL - LSL) / (6*sg) if sg > 0 else 0
            cpu = (USL - mu) / (3*sg)  if sg > 0 else 0
            cpl = (mu - LSL) / (3*sg)  if sg > 0 else 0
            lwrs = [s.lwr for s in sites if s.lwr > 0] or [0]
            self._exe("""
                INSERT INTO wafer_summaries
                (lot_id,wafer_id,cd_mean,cd_std,cdu_3s,lwr_mean,
                 cp,cpk,n_sites,n_pass,n_fail)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (lot_id, wafer_id,
                  round(mu, 3), round(sg, 3), round(3*sg, 3),
                  round(np.mean(lwrs), 3),
                  round(cp, 3), round(min(cpu, cpl), 3),
                  len(sites),
                  sum(1 for s in sites if s.status == 'PASS'),
                  sum(1 for s in sites if s.status == 'FAIL')))
            self._conn.commit()

    def insert_run(self, recipe_name: str, lot_id: str, wafer_id: str,
                   cd_mean: float, cd_std: float, lwr_3s: float,
                   dose_correction: float = 0) -> None:
        self._exe("""
            INSERT INTO run_history
            (recipe_name,lot_id,wafer_id,cd_mean,cd_std,lwr_3s,dose_correction)
            VALUES(?,?,?,?,?,?,?)
        """, (recipe_name, lot_id, wafer_id,
              round(cd_mean, 3), round(cd_std, 3),
              round(lwr_3s, 3), round(dose_correction, 4)))
        self._conn.commit()

    # ── Read API ───────────────────────────────────────────────────────────────

    def get_lots(self) -> list[dict]:
        return [dict(r) for r in
                self._exe("SELECT * FROM lots ORDER BY created DESC")]

    def get_wafers(self, lot_id: str | None = None) -> list[dict]:
        if lot_id:
            return [dict(r) for r in self._exe(
                "SELECT * FROM wafers WHERE lot_id=? ORDER BY date DESC",
                (lot_id,))]
        return [dict(r) for r in
                self._exe("SELECT * FROM wafers ORDER BY date DESC")]

    def get_sites(self, lot_id: str | None = None,
                  wafer_id: str | None = None,
                  limit: int = 500) -> list[dict]:
        if lot_id and wafer_id:
            sql = "SELECT * FROM sites WHERE lot_id=? AND wafer_id=? ORDER BY timestamp DESC LIMIT ?"
            rows = self._exe(sql, (lot_id, wafer_id, limit))
        elif lot_id:
            sql = "SELECT * FROM sites WHERE lot_id=? ORDER BY timestamp DESC LIMIT ?"
            rows = self._exe(sql, (lot_id, limit))
        else:
            rows = self._exe("SELECT * FROM sites ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def get_cd_trend(self, recipe_name: str | None = None,
                     lot_id: str | None = None,
                     n: int = 100) -> list[dict]:
        if lot_id:
            rows = self._exe(
                "SELECT cd_mean,cd_std,lwr_3s,timestamp FROM sites "
                "WHERE lot_id=? ORDER BY timestamp DESC LIMIT ?",
                (lot_id, n))
        elif recipe_name:
            rows = self._exe(
                "SELECT cd_mean,cd_std,lwr_3s,timestamp FROM run_history "
                "WHERE recipe_name=? ORDER BY timestamp DESC LIMIT ?",
                (recipe_name, n))
        else:
            rows = self._exe(
                "SELECT cd_mean,cd_std,lwr_3s,timestamp FROM sites "
                "ORDER BY timestamp DESC LIMIT ?", (n,))
        return [dict(r) for r in rows]

    def get_wafer_summary(self, lot_id: str, wafer_id: str) -> dict:
        row = self._exe(
            "SELECT * FROM wafer_summaries WHERE lot_id=? AND wafer_id=? "
            "ORDER BY timestamp DESC LIMIT 1",
            (lot_id, wafer_id)).fetchone()
        return dict(row) if row else {}

    def get_lot_summary(self, lot_id: str) -> dict:
        rows = self._exe(
            "SELECT cd_mean,cd_std,cp,cpk,n_sites FROM wafer_summaries "
            "WHERE lot_id=?", (lot_id,)).fetchall()
        if not rows:
            return {}
        cds = [r['cd_mean'] for r in rows]
        return {
            'n_wafers':    len(rows),
            'cd_mean':     round(np.mean(cds), 3),
            'cd_std':      round(np.std(cds, ddof=1) if len(cds)>1 else 0, 3),
            'cp_mean':     round(np.mean([r['cp'] for r in rows]), 3),
            'cpk_min':     round(min(r['cpk'] for r in rows), 3),
            'total_sites': sum(r['n_sites'] for r in rows),
        }

    def search(self, query: str, limit: int = 200) -> list[dict]:
        q = f"%{query}%"
        rows = self._exe("""
            SELECT * FROM sites
            WHERE lot_id LIKE ? OR wafer_id LIKE ?
               OR site_id LIKE ? OR status LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (q, q, q, q, limit))
        return [dict(r) for r in rows]

    def delete_wafer(self, lot_id: str, wafer_id: str) -> None:
        self._exe("DELETE FROM sites WHERE lot_id=? AND wafer_id=?",
                  (lot_id, wafer_id))
        self._exe("DELETE FROM wafer_summaries WHERE lot_id=? AND wafer_id=?",
                  (lot_id, wafer_id))
        self._conn.commit()

    def db_stats(self) -> dict:
        return {
            'lots':    self._exe("SELECT COUNT(*) FROM lots").fetchone()[0],
            'wafers':  self._exe("SELECT COUNT(*) FROM wafers").fetchone()[0],
            'sites':   self._exe("SELECT COUNT(*) FROM sites").fetchone()[0],
            'size_kb': Path(self.db_path).stat().st_size // 1024,
        }

    def export_csv(self, path: str,
                   lot_id: str | None = None,
                   wafer_id: str | None = None) -> int:
        sites = self.get_sites(lot_id=lot_id, wafer_id=wafer_id, limit=100_000)
        if not sites:
            return 0
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=sites[0].keys())
            w.writeheader()
            w.writerows(sites)
        return len(sites)

    def close(self) -> None:
        self._conn.close()
