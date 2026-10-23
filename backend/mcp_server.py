"""FastMCP Streamable HTTP 服务。在 backend/ 下执行：python mcp_server.py"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

from app.config import settings
from app.database import SessionLocal
from app.dependencies.mcp_auth import user_id_from_authorization
from app.services.schedule_service import list_schedules_as_dict

mcp = FastMCP("campus-course-agent")


def _current_user_id() -> int:
    """从当前的 HTTP 的请求头拿到 authorization 然后解析出 user_id"""
    # get_http_headers() 默认返回除少数传输类头以外的全部请求头（含 authorization），
    # 且键统一为小写；无需（也不能）传 include={"authorization"}（旧版 API）。
    headers = get_http_headers() or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    return user_id_from_authorization(auth)


@mcp.tool()
def get_my_schedules(
    date: Annotated[
        str | None,
        Field(
            description="可选参数，上课的日期，格式：YYYY-MM-DD，不传则返回全部的课表"
        ),
    ] = None,
) -> dict:
    """查询当前登录用户个人的课程列表"""
    try:
        user_id = _current_user_id()
        db = SessionLocal()
        try:
            items = list_schedules_as_dict(db, user_id, date)
            return {"items": items, "count": len(items)}
        finally:
            db.close()
    except Exception as exc:
        return {"error": f"查询课表失败 {exc}", "items": []}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        path=settings.MCP_PATH,
        uvicorn_config={"ws": "websockets"},
    )
