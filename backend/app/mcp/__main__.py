"""Explicit private MCP service; no tables are created at startup."""


def main():
    from app.mcp.logging import configure_mcp_logging
    from app.mcp.server import create_app
    from app.mcp.settings import load_mcp_settings
    from app.knowledge.logging import configure_knowledge_logging
    import uvicorn

    configure_mcp_logging()
    configure_knowledge_logging()
    try:
        settings = load_mcp_settings()
    except (ValueError, TypeError):
        raise SystemExit("Private MCP configuration is missing or invalid") from None
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port,
                access_log=False, proxy_headers=False, server_header=False, ws="none")


if __name__ == "__main__":
    main()
