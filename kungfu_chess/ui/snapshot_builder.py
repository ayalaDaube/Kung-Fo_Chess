# Architectural note: build_snapshot belongs to the engine layer.
# This re-export exists only for backward compatibility with existing tests.
from kungfu_chess.engine.snapshot_builder import build_snapshot  # noqa: F401
