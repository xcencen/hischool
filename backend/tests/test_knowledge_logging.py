"""Knowledge INFO logs are visible without changing global logging behavior."""

from concurrent.futures import ThreadPoolExecutor
import importlib
import logging
import re

import pytest

from app.knowledge import logging as knowledge_logging


TARGETS = ("app.knowledge.embeddings", "app.services.knowledge_service")
OTHERS = ("httpx", "httpcore", "uvicorn.error", "unrelated.campus.logger")


def state(logger):
    return (logger.level, tuple(logger.handlers), logger.propagate,
            logger.disabled, tuple(logger.filters))


@pytest.fixture(autouse=True)
def restore_logging():
    loggers = [logging.getLogger(), *(logging.getLogger(name) for name in TARGETS + OTHERS)]
    original = {logger: state(logger) for logger in loggers}
    for name in TARGETS:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.filters = []
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
        logger.disabled = False
    yield
    for logger, saved in original.items():
        for handler in logger.handlers:
            if handler not in saved[1]:
                handler.close()
        logger.setLevel(saved[0])
        logger.handlers = list(saved[1])
        logger.propagate = saved[2]
        logger.disabled = saved[3]
        logger.filters = list(saved[4])


def test_explicit_configuration_outputs_info_for_both_modules(capsys):
    knowledge_logging.configure_knowledge_logging()
    for name in TARGETS:
        logger = logging.getLogger(name)
        assert logger.level == logging.INFO and not logger.propagate
        logger.info("knowledge_operation outcome=success local_id=offline-log-test")
        logger.debug("debug-event-should-stay-hidden")
    output = capsys.readouterr()
    assert output.out == ""
    lines = output.err.splitlines()
    assert len(lines) == 2
    for line, name in zip(lines, TARGETS):
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO "
            + re.escape(name)
            + r" knowledge_operation outcome=success local_id=offline-log-test",
            line,
        )


def test_repeated_configuration_reuses_handlers_without_duplicate_output(capsys):
    knowledge_logging.configure_knowledge_logging()
    initial = {name: tuple(logging.getLogger(name).handlers) for name in TARGETS}
    for _ in range(5):
        knowledge_logging.configure_knowledge_logging()
    for name in TARGETS:
        assert tuple(logging.getLogger(name).handlers) == initial[name]
        logging.getLogger(name).info("single-operational-event")
    assert capsys.readouterr().err.count("single-operational-event") == 2


def test_concurrent_configuration_adds_only_one_owned_handler():
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: knowledge_logging.configure_knowledge_logging(), range(12)))
    for name in TARGETS:
        assert len(logging.getLogger(name).handlers) == 1


def test_configuration_leaves_root_http_clients_and_other_loggers_unchanged():
    loggers = [logging.getLogger(), *(logging.getLogger(name) for name in OTHERS)]
    for index, logger in enumerate(loggers):
        logger.setLevel(logging.ERROR if index % 2 else logging.WARNING)
    initial = {logger: state(logger) for logger in loggers}
    knowledge_logging.configure_knowledge_logging()
    assert {logger: state(logger) for logger in loggers} == initial


def test_events_do_not_propagate_to_root_handler(capsys):
    received = []

    class RootProbe(logging.Handler):
        def emit(self, record):
            received.append(record)

    root = logging.getLogger()
    root.addHandler(RootProbe())
    knowledge_logging.configure_knowledge_logging()
    for name in TARGETS:
        logging.getLogger(name).info("module-event")
    assert received == []
    assert capsys.readouterr().err.count("module-event") == 2


def test_import_does_not_configure_logging_or_read_settings(monkeypatch):
    initial = {name: state(logging.getLogger(name)) for name in TARGETS + OTHERS}

    def forbidden(*args, **kwargs):
        raise AssertionError("Import must not configure logging")

    with monkeypatch.context() as patcher:
        patcher.setattr(logging, "getLogger", forbidden)
        patcher.setattr(logging, "basicConfig", forbidden)
        patcher.setattr(logging.Logger, "addHandler", forbidden)
        importlib.reload(knowledge_logging)
    assert {name: state(logging.getLogger(name)) for name in TARGETS + OTHERS} == initial


def test_existing_application_handler_is_preserved():
    probe = logging.NullHandler()
    logger = logging.getLogger(TARGETS[0])
    logger.addHandler(probe)
    knowledge_logging.configure_knowledge_logging()
    knowledge_logging.configure_knowledge_logging()
    assert probe in logger.handlers and len(logger.handlers) == 2
