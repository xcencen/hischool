"""Controlled private-service events; only explicit CLI startup configures logging."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


_private_call = ContextVar("campus_mcp_private_call", default=False)
_filter_lock = Lock()


class PrivateCallFilter(logging.Filter):
    def filter(self, record):
        return not _private_call.get()


_private_filter = PrivateCallFilter()


@contextmanager
def private_client_logs():
    """Suppress dependency payload logs only in this call and its child tasks."""
    with _filter_lock:
        names = {"mcp.client.streamable_http", "mcp.shared.session", "httpx"}
        names.update(name for name in tuple(logging.root.manager.loggerDict)
                     if name.startswith(("mcp.", "httpcore.")))
        for name in names:
            logger = logging.getLogger(name)
            if _private_filter not in logger.filters:
                logger.addFilter(_private_filter)
    token = _private_call.set(True)
    try:
        yield
    finally:
        _private_call.reset(token)


def configure_mcp_logging():
    logger = logging.getLogger("app.mcp")
    if not any(getattr(handler, "name", None) == "campus-mcp" for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.name = "campus-mcp"
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # This is a dedicated MCP process: retain our controlled events, suppress SDK
    # internals that may include untrusted RPC arguments or exception bodies.
    for name in ("mcp", "fastmcp", "httpx", "httpcore"):
        dependency = logging.getLogger(name)
        dependency.handlers = [logging.NullHandler()]
        dependency.propagate = False
        dependency.setLevel(logging.CRITICAL + 1)
