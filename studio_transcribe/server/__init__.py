"""Operator web app (Stage 4): a local FastAPI server + browser SPA to run,
configure, and monitor the transcription system.
"""

from .app import create_app

__all__ = ["create_app"]
