"""
CD_SCOPE — CD-SEM Analysis Suite
Install: pip install -e .
Run:     python -m cd_scope
"""
from setuptools import setup, find_packages

setup(
    name            = "cd_scope",
    version         = "1.0.0",
    description     = "CD-SEM metrology analysis suite",
    packages        = find_packages(),
    python_requires = ">=3.10",
    install_requires = [
        "PyQt5>=5.15",
        "pyqtgraph>=0.13",
        "numpy>=1.24",
        "scipy>=1.10",
        "Pillow>=9.0",
        "scikit-image>=0.20",
        "openpyxl>=3.1",
        "reportlab>=4.0",
        "matplotlib>=3.7",
    ],
    entry_points = {
        "console_scripts": [
            "cd_scope = cd_scope.main:run_gui",
        ],
    },
    classifiers = [
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering",
    ],
)
