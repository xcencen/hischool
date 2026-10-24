"""Explicit, narrowly scoped logging setup for knowledge runtime entry points."""

import logging
from threading import RLock
import time


_LOGGER_NAMES = (
    "app.knowledge.embeddings",
    "app.services.knowledge_service",
)
_HANDLER_MARKER = "_my_campus_knowledge_handler"
_CONFIGURE_LOCK = RLock()


def configure_knowledge_logging():
    """Enable controlled operational events without enabling HTTP client logs."""
    with _CONFIGURE_LOCK:
        for name in _LOGGER_NAMES:
            logger = logging.getLogger(name)
            if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
                handler = logging.StreamHandler()
                setattr(handler, _HANDLER_MARKER, True)
                handler.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    "%(asctime)sZ %(levelname)s %(name)s %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S",
                )
                formatter.converter = time.gmtime
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.disabled = False
            logger.propagate = False
