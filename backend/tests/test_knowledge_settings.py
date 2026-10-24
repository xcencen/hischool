from pathlib import Path

from pydantic import ValidationError
import pytest

from app.common.exceptions import BusinessException
from app.knowledge.settings import KnowledgeSettings, load_knowledge_settings
from app.schemas.knowledge import KnowledgeSearchRequest
from app.services.knowledge_service import storage_path


def test_empty_embedding_configuration_is_explicit_and_creates_no_storage(tmp_path):
    source = tmp_path / "originals"
    index = tmp_path / "indexes"
    settings = load_knowledge_settings({"CAMPUS_KB_SOURCE_DIR": str(source), "CAMPUS_KB_INDEX_DIR": str(index)})
    assert not settings.configured
    assert settings.model == "text-embedding-v4" and settings.dimensions == 1024
    assert not source.exists() and not index.exists()


def test_configuration_does_not_expose_keys_or_take_chat_model_overrides():
    settings = load_knowledge_settings({"CAMPUS_EMBED_API_KEY": "private-test-value",
        "CAMPUS_EMBED_BASE_URL": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "CAMPUS_LLM_MODEL_ID": "unrelated-chat-model"})
    assert settings.configured and "private-test-value" not in repr(settings)
    assert settings.model == "text-embedding-v4"


@pytest.mark.parametrize("changes", [
    {"model": "other-model"}, {"dimensions": 768}, {"min_score": 2},
    {"base_url": "http://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"},
    {"base_url": "https://evil.example/compatible-mode/v1"},
    {"base_url": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"},
    {"base_url": "https://user:pass@workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"},
    {"source_dir": Path("relative")},
])
def test_invalid_embedding_and_storage_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        KnowledgeSettings(**changes)


@pytest.mark.parametrize("key,index", [("../private.pdf", False), ("a"*64+".exe", False),
                                      ("/etc/passwd", False), ("a"*64+".index", True)])
def test_storage_keys_cannot_escape_private_roots(tmp_path, key, index):
    with pytest.raises(BusinessException):
        storage_path(tmp_path, key, index=index)


@pytest.mark.parametrize("payload", [{"query": " "}, {"query": "q"*1001}, {"query": "问题", "top_k": 11},
                                    {"query": "问题", "top_k": True}, {"query": "问题", "user_id": 2}])
def test_search_has_bounded_parameters_and_no_client_identity(payload):
    with pytest.raises(ValidationError):
        KnowledgeSearchRequest.model_validate(payload)
