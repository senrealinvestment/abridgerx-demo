"""Vercel FastAPI entrypoint for AbridgeRx clinician UI.

Vercel detects FastAPI via requirements.txt and looks for `app` in app.py
(or src/app.py). Re-exports the real app from src/ui/app.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ui.app import app as app  # noqa: E402, F401
