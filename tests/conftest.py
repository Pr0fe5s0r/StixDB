from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SDK_SRC = ROOT / "sdk" / "src"
for path in (ROOT, SDK_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
