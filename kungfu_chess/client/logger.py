"""
Client-side logging setup.

Call ``setup_client_logging(log_path)`` once at startup (from app.py).
All client modules use ``logging.getLogger(__name__)`` — because they live
under the ``kungfu_chess.client`` package, their records propagate to the
``kungfu_chess.client`` logger configured here.

SRP: this module only owns handler wiring; it adds no log calls of its own.
"""
from __future__ import annotations

import logging


def setup_client_logging(log_path: str, level: int = logging.DEBUG) -> None:
    """
    Attach a FileHandler to the ``kungfu_chess.client`` logger.

    Safe to call multiple times — skips setup if a FileHandler for the same
    path is already attached (prevents duplicate entries in tests).

    Parameters
    ----------
    log_path
        Absolute or relative path to the log file.  Comes from
        ``GameConfig.client_log_path`` so it is never hardcoded.
    level
        Logging level for the handler and the logger itself.
    """
    client_logger = logging.getLogger("kungfu_chess.client")
    # Avoid adding duplicate handlers (e.g. when called twice in tests).
    for h in client_logger.handlers:
        if isinstance(h, logging.FileHandler) and h.baseFilename == log_path:
            return

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    client_logger.setLevel(level)
    client_logger.addHandler(handler)
    client_logger.propagate = False
