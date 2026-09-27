"""Run: python3 -m ui  (from repo root with PYTHONPATH=src, or via .venv)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("ui.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
