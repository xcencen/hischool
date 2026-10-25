"""Independent private MCP settings; no implicit .env loading."""

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class MCPSettings:
    signing_secret: str = field(repr=False)
    url: str = field(default="http://campus-mcp:8001/mcp", repr=False)
    token_ttl_s: int = 60
    query_timeout_s: int = 10
    knowledge_timeout_s: int = 55

    def __post_init__(self):
        if (not isinstance(self.signing_secret, str) or len(self.signing_secret) < 32
                or self.signing_secret.startswith("REPLACE")
                or any(char.isspace() for char in self.signing_secret)):
            raise ValueError("Configure an independent CAMPUS_MCP_SIGNING_SECRET of at least 32 characters")
        try:
            url = urlsplit(self.url)
            valid = (url.scheme == "http" and url.hostname in {
                "campus-mcp", "localhost", "127.0.0.1"}
                and url.port is not None and url.path == "/mcp" and not url.username
                and not url.password and not url.query and not url.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("CAMPUS_MCP_URL must name the private campus-mcp service or a loopback test endpoint")
        for value, maximum in ((self.token_ttl_s, 60), (self.query_timeout_s, 10),
                               (self.knowledge_timeout_s, 55)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Private MCP timeout/TTL is outside policy")

    @property
    def port(self):
        return urlsplit(self.url).port

    @property
    def allowed_hosts(self):
        return {urlsplit(self.url).netloc, f"localhost:{self.port}", f"127.0.0.1:{self.port}"}


def load_mcp_settings(environ=None):
    source = os.environ if environ is None else environ
    try:
        return MCPSettings(signing_secret=source.get("CAMPUS_MCP_SIGNING_SECRET", ""),
            url=source.get("CAMPUS_MCP_URL", "http://campus-mcp:8001/mcp").strip(),
            token_ttl_s=int(source.get("CAMPUS_MCP_TOKEN_TTL_S", "60")),
            query_timeout_s=int(source.get("CAMPUS_MCP_QUERY_TIMEOUT_S", "10")),
            knowledge_timeout_s=int(source.get("CAMPUS_MCP_KNOWLEDGE_TIMEOUT_S", "55")))
    except (ValueError, TypeError):
        raise ValueError("Private MCP configuration is missing or invalid") from None
