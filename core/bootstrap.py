"""Entry point that also works with Python's isolated embedded distribution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
