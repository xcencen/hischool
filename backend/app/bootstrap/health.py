"""Dependency-free application health metadata."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.bootstrap.config import BootstrapSettings


class HealthData(BaseModel):
    name: str
    version: str
    status: Literal["ok"] = "ok"


class HealthResponse(BaseModel):
    code: Literal[200] = 200
    message: Literal["ok"] = "ok"
    data: HealthData


def health_response(settings: BootstrapSettings) -> HealthResponse:
    return HealthResponse(
        data=HealthData(name=settings.app_name, version=settings.app_version)
    )


def create_health_router(settings: BootstrapSettings) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return health_response(settings)

    return router
