# CD_SCOPE v1.0 — CD-SEM Analysis Suite

Production-grade CD-SEM metrology application. Modular OOP architecture.

---

## Quick start

```bash
pip install PyQt5 pyqtgraph numpy scipy Pillow scikit-image openpyxl reportlab matplotlib
python -m cd_scope          # launch GUI
```

---

## Package architecture

```
cd_scope/
│
├── constants.py            ← Colours, specs, STYLESHEET, capability flags
│                             (imported by every module — never imports from cd_scope)
│
├── core/                   ← Pure business logic — NO Qt, NO matplotlib
│   ├── models.py           ← Dataclasses: EdgeResult, SEMMeta, WaferSite,
│   │                         Recipe, PatternConfig, BatchImageRecord, …
│   ├── edge_detection.py   ← EdgeDetector (4 algorithms, ISO 19973)
│   ├── sem_loader.py       ← SEMLoader (Hitachi/JEOL/FEI TIFF + sidecar)
│   ├── wafer_parser.py     ← HitachiWaferParser (CSV/XML/MDF/TXT)
│   ├── pattern_engine.py   ← PatternAnalyzer + PatternRecognizer
│   └── recipe_manager.py   ← RecipeManager (JSON save/load/compare)
│
├── analysis/               ← Scientific computation + QThread workers
│   ├── threads.py          ← AnalysisThread, BatchAnalysisThread,
│   │                         LiveAcquisitionThread, AcquisitionConfig
│   ├── synthetic.py        ← gen_synthetic_sem(), gen_synthetic_contact()
│   ├── dose_focus.py       ← DoseFocusAnalyzer (Bossung + process window)
│   └── cdu_statistics.py   ← CDUStatistics (H/V bias, radial, non-linear)
│
├── db/                     ← SQLite persistence
│   └── database.py         ← MetroscanDB (lots/wafers/sites/summaries/runs)
│
├── control/                ← Process control
│   └── apc.py              ← APCController (EWMA run-to-run dose feedback)
│
├── export/                 ← Report generation
│   └── excel_exporter.py   ← MetroscanExcelExporter (6 sheets + auto-charts)
│
├── io/                     ← File parsers
│   ├── batch_parser.py     ← BatchConditionParser (CSV/JSON/INI/TXT)
│   └── scanner_parser.py   ← ScannerDataParser (ASML/generic dose-focus logs)
│
├── ui/                     ← Qt widgets (depends on all layers above)
│   ├── wafer_map_widget.py ← WaferCDMapWidget, WaferMapPanel
│   ├── sem_viewport.py     ← SEMViewport (zoom/pan/edge overlay)
│   ├── metric_widgets.py   ← MetricCard, GaugeBar
│   ├── chart_widgets.py    ← make_profile_widget(), make_spc_widget(), …
│   ├── panels.py           ← ResultsPanel, RecipePanel, DataTablePanel,
│   │                         DoseFocusPanel, APCPanel, LiveAcquisitionPanel
│   └── main_window.py      ← MainWindow (owns all state, routes signals)
│
├── main.py                 ← run_gui() entry point
└── setup.py                ← pip-installable package
```

### Dependency direction (enforced, never reversed)

```
ui → analysis → core → constants
   → db
   → control
   → export
   → io
```

Qt never appears in `core`, `db`, `control`, `io`, or `export`.

---

## Layer contracts

### `core` — pure Python dataclasses + algorithms

```python
from cd_scope.core import EdgeDetector, HitachiWaferParser, WaferSite

det = EdgeDetector()
det.algo     = 0      # 0=Gaussian deriv, 1=threshold, 2=Canny, 3=sigmoid
det.sigma_nm = 2.5
result = det.analyse(img_uint8, nm_per_px=0.47)
print(result.cd_mean, result.lwr_3s, result.pitch_mean)

sites = HitachiWaferParser.parse("wafer_map.csv")   # → list[WaferSite]
sites = HitachiWaferParser.generate_demo(49)         # synthetic demo
```

### `analysis` — scientific computation

```python
from cd_scope.analysis import (DoseFocusAnalyzer, CDUStatistics,
                                 gen_synthetic_sem)
pix, img, meta = gen_synthetic_sem(512, 512, npp=0.49)

ana = DoseFocusAnalyzer(df_points, target_cd=32.0, cd_tolerance_pct=10)
result = ana.analyse()
# result['bossung_curves'], result['dof'], result['el_pct'], result['process_window']

cdu = CDUStatistics(sites)
st  = cdu.compute_all()
# st['cdu_3s'], st['x_gradient_nm_per_mm'], st['hv_bias_nm'], st['nonlinear_cdu_3s']
```

### `db` — SQLite persistence

```python
from cd_scope.db import MetroscanDB

db = MetroscanDB()                            # ~/.cd_scope/measurements.db
db.insert_sites_bulk("LOT-001","W-01", sites)
db.insert_run("recipe_A","LOT-001","W-01", 31.8, 0.4, 2.8, dose_correction=0.02)

trend = db.get_cd_trend(lot_id="LOT-001", n=50)
lot   = db.get_lot_summary("LOT-001")
sites = db.search("FAIL", limit=100)
db.export_csv("query.csv", lot_id="LOT-001")
```

### `control` — APC

```python
from cd_scope.control import APCController

apc = APCController(target_cd=32.0, gain=0.6, cd_per_dose_pct=1.0,
                    ewma_lambda=0.4, deadband_nm=0.3)
rec = apc.update(cd_measured=32.4, current_dose=28.0)
print(rec['new_dose'], rec['action'], rec['correction_pct'])
```

### `export` — Excel

```python
from cd_scope.export import MetroscanExcelExporter

exp = MetroscanExcelExporter()
exp.sites         = sites
exp.edge_result   = edge_result
exp.scanner_fields= scanner_fields
exp.batch_records = batch_records
exp.recipe_name   = "EUV_32nm_v3"
exp.export("CD_SCOPE_report.xlsx")
# Produces: Summary, CD_Data, LWR_Data, Dose_Focus, Batch_Results, Charts
```

### `io` — file parsers

```python
from cd_scope.io import BatchConditionParser, ScannerDataParser

# Batch condition CSV/JSON/INI/TXT
records = BatchConditionParser.parse("batch.csv")   # → list[BatchImageRecord]
BatchConditionParser.write_template("template.csv") # write example file

# Scanner dose/focus log
fields = ScannerDataParser.parse("scanner.dat")     # → list[ScannerExposure]
ScannerDataParser.write_template("template.csv")
```

---

## File format reference

### Batch condition file (CSV)
```
image_path,nm_per_px,site_id,x_mm,y_mm,dose,focus,pattern_type,target_cd
sem_001.tif,0.47,S001,0.0,0.0,28.0,0.000,Line/Space 1:1,32.0
sem_002.tif,0.47,S002,10.5,-8.2,28.5,+0.020,Line/Space 2:1,32.0
sem_003.tif,0.47,S003,-10.0,5.0,29.0,0.000,Contact Hole Array,40.0
```
`pattern_type` options: `Line/Space 1:1`, `2:1`, `1:2`, `3:1`, `1:3`, `Contact Hole Array`

### Scanner data file (CSV)
```
field_id,x_mm,y_mm,dose,focus,na,sigma,wavelength,lot_id,wafer_id
F001,0.0,0.0,28.0,0.000,0.33,0.9,13.5,LOT001,W01
F002,26.0,0.0,28.5,+0.020,0.33,0.9,13.5,LOT001,W01
```

### Hitachi wafer map (CSV)
```
SiteID,X,Y,CD_Mean,CD_Sigma,LWR,Pitch,Space,Status
S001,0.0,0.0,32.14,0.43,2.81,64.03,31.89,PASS
```
Also supports: Hitachi WXML (`.xml`), MDF (`.mdf`), key=value text (`.txt`)

---

## Running

```bash
# GUI
python -m cd_scope

# Demo workflow (no files needed)
# 1. Click ACQUIRE (F6) — generates synthetic L/S image
# 2. Click RUN (F5)    — runs edge detection, shows CD/LWR/PSD
# 3. Wafer → Load Demo Map — loads 49-site demo wafer
# 4. Dose-Focus → Generate Demo Matrix — shows Bossung curves
# 5. Report → Generate PDF — exports formatted PDF
# 6. File → Export to Excel — exports .xlsx with charts
