"""Make ``run_probes`` importable from probes/tests without packaging it."""

import sys
from pathlib import Path

PROBES_DIR = Path(__file__).resolve().parents[1]
if str(PROBES_DIR) not in sys.path:
    sys.path.insert(0, str(PROBES_DIR))
