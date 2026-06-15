"""Process-wide logging setup for the backend.

Attaches a single timestamped stderr handler to the ``app`` logger namespace so
every ``logging.getLogger("app.…")`` call (expander phases, Codex timings, job
lifecycle) is visible in the server console without duplicating uvicorn's output.
"""

from __future__ import annotations

import logging
import sys

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotently configure the ``app`` logger; safe to call more than once."""
    global _configured
    logger = logging.getLogger("app")
    logger.setLevel(level.upper())
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False  # the dedicated handler already prints; avoid double logging
    _configured = True
