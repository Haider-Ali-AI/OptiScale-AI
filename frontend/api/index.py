"""Vercel Python entrypoint; backend source is copied at build time."""
import sys
from pathlib import Path

source = Path(__file__).resolve().parents[1] / ".backend" / "src"
sys.path.insert(0, str(source))

from ads_optimizer.api import app  # noqa: E402, F401
