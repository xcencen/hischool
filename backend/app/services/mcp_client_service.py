"""MCP Client 封装：FastAPI 作为 MCP 客户端去调用第 6 节的 FastMCP 服务。

身份只认 JWT —— 只把请求头里的 Authorization（含 Bearer 前缀）原样转发，
工具参数里只有可选的 date，绝不下发 user_id。
"""

import json

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.common.exceptions import BusinessException
from app.config import settings


async def call_get_my_schedules(authorization: str, date: str | None = None) -> dict:
    """调用 MCP 服务的客户端"""
    # 1. 建 client —— 这是固定的模板
    client = MultiServerMCPClient(
        {
            "campus": {
                "transport": "streamable_http",
                "url": f"http://{settings.MCP_HOST}:{settings.MCP_PORT}{settings.MCP_PATH}",
                "headers": {"Authorization": authorization},
            }
        }
    )
    try:
        # 2. 拿 tool
        tools = await client.get_tools(server_name="campus")
        tool = next((t for t in tools if t.name == "get_my_schedules"), None)
        if tool is None:
            raise BusinessException(
                message="未找到工具【get_my_schedules】，请确认 MCP 服务是否正常启动"
            )
        # 3. 调用 tool
        payload = {}
        if date:
            payload["date"] = date
        result = await tool.ainvoke(payload)
    except BusinessException:
        raise
    except Exception as exc:
        # MCP 进程没起 / 中途挂掉时，转成业务错误（HTTP 200 + code），而不是被全局兜底成 500
        raise BusinessException(
            message=f"MCP 服务不可用，请确认 mcp_server 是否已启动（{type(exc).__name__}）"
        ) from exc

    # 工具返回值是 content block 列表，取 result[0]["text"] 里的 JSON 字符串再解析成 dict
    return json.loads(result[0]["text"])
