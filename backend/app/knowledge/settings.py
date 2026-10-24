"""Knowledge configuration is independent of the unfinished chat-model work."""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class KnowledgeSettings:
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = "text-embedding-v4"
    dimensions: int = 1024
    source_dir: Path = Path("/data/knowledge")
    index_dir: Path = Path("/data/faiss")
    min_score: float = 0.3

    def __post_init__(self):
        if self.model != "text-embedding-v4" or self.dimensions != 1024:
            raise ValueError("Knowledge embeddings require text-embedding-v4 / 1024 dimensions")
        if not self.source_dir.is_absolute() or not self.index_dir.is_absolute():
            raise ValueError("Knowledge storage directories must be absolute")
        if not -1 <= self.min_score <= 1:
            raise ValueError("Knowledge similarity threshold is invalid")
        if self.base_url:
            url = urlsplit(self.base_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment or "{" in self.base_url
                    or not url.path.rstrip("/").endswith("/compatible-mode/v1")):
                raise ValueError("Configure an HTTPS Bailian compatible embedding base URL")
            if not (url.hostname == "dashscope.aliyuncs.com"
                    or url.hostname.endswith(".cn-beijing.maas.aliyuncs.com")):
                raise ValueError("Configure a Bailian Beijing embedding endpoint")

    @property
    def configured(self):
        return bool(self.api_key and self.base_url)

    @property
    def provider_hash(self):
        return hashlib.sha256(self.base_url.rstrip("/").encode()).hexdigest()


def load_knowledge_settings(environ=None):
    source = os.environ if environ is None else environ
    local_root = Path("F:/my-campus-dev/data") if os.name == "nt" else Path("/data")
    return KnowledgeSettings(
        api_key=source.get("CAMPUS_EMBED_API_KEY", "").strip(),
        base_url=source.get("CAMPUS_EMBED_BASE_URL", "").strip().rstrip("/"),
        model=source.get("CAMPUS_EMBED_MODEL_ID", "text-embedding-v4").strip(),
        dimensions=int(source.get("CAMPUS_EMBED_DIM", "1024")),
        source_dir=Path(source.get("CAMPUS_KB_SOURCE_DIR") or local_root/"knowledge"),
        index_dir=Path(source.get("CAMPUS_KB_INDEX_DIR") or local_root/"faiss"),
        min_score=float(source.get("CAMPUS_KB_MIN_SCORE", "0.3")),
    )
