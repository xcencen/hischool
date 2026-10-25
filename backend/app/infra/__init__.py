"""Infrastructure helpers (Redis runtime primitives, logging).

These modules are imported lazily by the agent; they are never part of the
bootstrap import chain, so they do not affect ``import app.main``.
"""
