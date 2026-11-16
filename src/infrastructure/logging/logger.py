"""
src/infrastructure/logging/logger.py

Single global logger for the bridge daemon, without request-scoped
contextvars: this process has no HTTP
request/user identity worth stamping onto every line, just device I/O. `cfg.log_level` throttles the
stdout handler; `cfg.log_format` picks text vs. JSON for a log
aggregator (Loki/Elastic).
"""

import json
import logging
from datetime import UTC
from datetime import datetime
from typing import Any

from src.infrastructure.config import cfg


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


log = logging.getLogger("glados-terminal")
log.setLevel(logging.DEBUG)

if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(cfg.log_level)  # throttles stdout only, logger stays DEBUG
    if cfg.log_format == "json":
        _handler.setFormatter(_JsonFormatter())
    else:
        _handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
    log.addHandler(_handler)
    log.propagate = False  # don't double-print via uvicorn's root handler
