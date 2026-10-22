"""Vercel Python entrypoint. Exposes the BeyondTopic WSGI app for all routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.server import app
