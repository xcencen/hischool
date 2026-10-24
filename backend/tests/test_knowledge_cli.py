"""Safe operator probes, with no real configuration, database or model access."""
import json
import sys

import pytest

from app.knowledge import cli
from app.knowledge.embeddings import EmbeddingUnavailable


KEY = "private-probe-test-key"
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.fixture(autouse=True)
def isolated_probe(monkeypatch):
    monkeypatch.setenv("CAMPUS_EMBED_API_KEY", KEY)
    monkeypatch.setenv("CAMPUS_EMBED_BASE_URL", BASE)
    monkeypatch.setenv("CAMPUS_EMBED_MODEL_ID", "text-embedding-v4")
    monkeypatch.setenv("CAMPUS_EMBED_DIM", "1024")
    monkeypatch.setenv("CAMPUS_KB_MIN_SCORE", "0.3")
    monkeypatch.delenv("CAMPUS_KB_SOURCE_DIR", raising=False)
    monkeypatch.delenv("CAMPUS_KB_INDEX_DIR", raising=False)

    def forbid(*args, **kwargs):
        pytest.fail("Probe must not load campus settings or access database, Redis or real embeddings")

    monkeypatch.setattr(cli, "load_settings", forbid)
    monkeypatch.setattr(cli, "Database", forbid)
    monkeypatch.setattr(cli, "Redis", forbid)
    monkeypatch.setattr(cli.service, "embedding_client", forbid)


def run_probe(monkeypatch, *, live=False):
    monkeypatch.setattr(sys, "argv", ["knowledge", "probe", *(["--live"] if live else [])])
    cli.main()


def test_probe_checks_process_configuration_without_model_or_datastores(monkeypatch, capsys):
    run_probe(monkeypatch)
    output = capsys.readouterr()
    assert json.loads(output.out) == dict(key_loaded=True, configured=True, endpoint_configured=True,
        model="text-embedding-v4", dimensions=1024)
    assert KEY not in output.out + output.err and BASE not in output.out + output.err


def test_offline_probe_reports_missing_configuration_without_network(monkeypatch, capsys):
    monkeypatch.delenv("CAMPUS_EMBED_API_KEY")
    monkeypatch.delenv("CAMPUS_EMBED_BASE_URL")
    run_probe(monkeypatch)
    result = json.loads(capsys.readouterr().out)
    assert not result["configured"] and not result["key_loaded"] and not result["endpoint_configured"]
    assert "connectivity" not in result


def test_live_probe_uses_one_short_text_and_does_not_print_vectors(monkeypatch, capsys):
    calls = []

    class FakeEmbedder:
        async def embed_texts(self, texts):
            calls.append(texts)
            return [[0.123456789, *([0.0] * 1023)]]

    monkeypatch.setattr(cli.service, "embedding_client", lambda settings: FakeEmbedder())
    run_probe(monkeypatch, live=True)
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["configured"] and result["connectivity"]
    assert calls == [["校园知识库连通性验证"]]
    assert KEY not in output.out and BASE not in output.out and "0.123456789" not in output.out


@pytest.mark.parametrize("missing", ["CAMPUS_EMBED_API_KEY", "CAMPUS_EMBED_BASE_URL"])
def test_live_probe_requires_configuration_before_request(monkeypatch, missing, capsys):
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit) as error:
        run_probe(monkeypatch, live=True)
    assert "请先配置" in str(error.value)
    assert KEY not in str(error.value) + capsys.readouterr().out


def test_live_probe_sanitizes_sensitive_provider_failure(monkeypatch, capsys):
    class FailingEmbedder:
        async def embed_texts(self, texts):
            raise EmbeddingUnavailable("private response " + KEY + " " + BASE)

    monkeypatch.setattr(cli.service, "embedding_client", lambda settings: FailingEmbedder())
    with pytest.raises(SystemExit) as error:
        run_probe(monkeypatch, live=True)
    printable = str(error.value) + capsys.readouterr().out
    assert KEY not in printable and BASE not in printable and "private response" not in printable
    assert "百炼" in str(error.value)


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[1.0] * 1024, [1.0] * 1024], [None]])
def test_live_probe_rejects_unexpected_vector_count_or_dimensions(monkeypatch, vectors, capsys):
    class InvalidEmbedder:
        async def embed_texts(self, texts):
            return vectors

    monkeypatch.setattr(cli.service, "embedding_client", lambda settings: InvalidEmbedder())
    with pytest.raises(SystemExit) as error:
        run_probe(monkeypatch, live=True)
    printable = str(error.value) + capsys.readouterr().out
    assert "connectivity" not in printable and KEY not in printable and BASE not in printable


def test_probe_invalid_configuration_is_sanitized(monkeypatch, capsys):
    monkeypatch.setenv("CAMPUS_EMBED_DIM", "private-dimension-" + KEY)
    with pytest.raises(SystemExit) as error:
        run_probe(monkeypatch)
    printable = str(error.value) + capsys.readouterr().out
    assert KEY not in printable and "private-dimension" not in printable
    assert "Knowledge operation failed" in str(error.value)
