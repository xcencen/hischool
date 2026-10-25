"""Short-lived, resource-bound delegation; campus JWTs never reach MCP."""

from dataclasses import dataclass, field
import time
from typing import Annotated, Literal
from uuid import uuid4

import jwt
from jwt import InvalidTokenError
from pydantic import Field, ValidationError, model_validator

from app.common.exceptions import BusinessException
from app.mcp.catalog import StrictModel, TOOLS
from app.services.identity_service import active_identity
from app.utils.jwt import decode_access_token


class DelegationClaims(StrictModel):
    iss: Literal["my-campus-assistant"]
    aud: Literal["my-campus-mcp"]
    sub: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    auth_version: Annotated[int, Field(strict=True, ge=0)]
    source_jti: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", repr=False)]
    source_exp: Annotated[int, Field(strict=True, gt=0)]
    jti: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", repr=False)]
    iat: Annotated[int, Field(strict=True, gt=0)]
    exp: Annotated[int, Field(strict=True, gt=0)]
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
    scope: Literal["campus:read"]
    tools: Annotated[list[str], Field(min_length=1, max_length=6)]
    resource: Annotated[str, Field(max_length=200, repr=False)]

    @model_validator(mode="after")
    def bounded_delegation(self):
        if not 0 < self.exp - self.iat <= 60 or self.exp > self.source_exp:
            raise ValueError("Invalid delegation lifetime")
        if len(set(self.tools)) != len(self.tools) or set(self.tools) - TOOLS.keys():
            raise ValueError("Invalid delegation tool scope")
        return self


@dataclass(frozen=True)
class DelegatedToken:
    token: str = field(repr=False)
    expires_at: int
    run_id: str


def decode_delegation(token, settings):
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError("Invalid delegation")
        header = jwt.get_unverified_header(token)
        if header.get("typ") != "campus-mcp+jwt" or header.get("alg") != "HS256":
            raise ValueError("Invalid delegation header")
        value = jwt.decode(token, settings.signing_secret, algorithms=["HS256"],
            issuer="my-campus-assistant", audience="my-campus-mcp",
            options={"require": list(DelegationClaims.model_fields), "strict_aud": True})
        claims = DelegationClaims.model_validate(value)
        if (claims.resource != settings.url or claims.exp - claims.iat > settings.token_ttl_s
                or time.time() >= claims.exp):
            raise ValueError("Invalid delegation resource or lifetime")
        return claims
    except (InvalidTokenError, ValueError, TypeError, ValidationError):
        raise BusinessException("MCP 身份凭证无效或已失效", code=401) from None


async def issue_delegation(db, redis, campus_settings, mcp_settings, campus_token, *, run_id, tools):
    if mcp_settings.signing_secret == campus_settings.jwt_secret:
        raise BusinessException("MCP 签名配置无效", code=503)
    try:
        source = decode_access_token(campus_token, campus_settings)
    except (InvalidTokenError, ValueError, TypeError):
        raise BusinessException("登录已失效，请重新登录", code=401) from None
    await active_identity(db, redis, user_id=int(source["sub"]), auth_version=source["auth_version"],
                          session_jti=source["jti"], expires_at=source["exp"])
    now = int(time.time())
    try:
        claims = DelegationClaims(iss="my-campus-assistant", aud="my-campus-mcp", sub=source["sub"],
            auth_version=source["auth_version"], source_jti=source["jti"], source_exp=source["exp"],
            jti=uuid4().hex, iat=now, exp=min(now + mcp_settings.token_ttl_s, source["exp"]),
            run_id=run_id, scope="campus:read", tools=sorted(tools), resource=mcp_settings.url)
    except (ValueError, TypeError, ValidationError):
        raise BusinessException("MCP 委托范围无效", code=400) from None
    token = jwt.encode(claims.model_dump(), mcp_settings.signing_secret, algorithm="HS256",
                       headers={"typ": "campus-mcp+jwt"})
    return DelegatedToken(token, claims.exp, run_id)


async def resolve_delegation(database, redis, settings, token, *, tool=None):
    claims = decode_delegation(token, settings)
    if tool is not None and tool not in claims.tools:
        raise BusinessException("该凭证无权调用此工具", code=403)
    async with database.session_factory() as db:
        user = await active_identity(db, redis, user_id=int(claims.sub), auth_version=claims.auth_version,
            session_jti=claims.source_jti, expires_at=claims.source_exp)
    return user, claims
