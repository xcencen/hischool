"""Bootstrap stays independent; campus services are enabled explicitly."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap.config import BootstrapSettings, load_settings
from app.bootstrap.health import HealthResponse, create_health_router, health_response


def create_app(
    settings: BootstrapSettings | None = None, *, mode: str | None = None
) -> FastAPI:
    """Create a minimal app without database, filesystem, or network setup."""
    settings = settings or load_settings()
    mode = mode or os.environ.get("APP_MODE", "bootstrap")
    if mode not in {"bootstrap", "campus"}:
        raise ValueError("APP_MODE must be bootstrap or campus")
    lifespan = None
    if mode == "campus":
        from app.runtime import campus_lifespan

        lifespan = campus_lifespan
    application = FastAPI(
        title=settings.app_name, version=settings.app_version, lifespan=lifespan
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"] if mode == "bootstrap" else [
            "GET", "POST", "PATCH", "PUT", "DELETE"
        ],
        allow_headers=["*"],
    )
    application.include_router(create_health_router(settings))
    if mode == "campus":
        from app.runtime import router
        from app.api import api
        from app.common.exceptions import (
            BusinessException,
            business_exception_handler,
            global_excpetion_hadler,
            http_excpetion_hadler,
            validation_excpetion_hadler,
        )
        from fastapi.exceptions import RequestValidationError
        from starlette.exceptions import HTTPException

        application.include_router(router)
        application.include_router(api)
        application.add_exception_handler(BusinessException, business_exception_handler)
        application.add_exception_handler(HTTPException, http_excpetion_hadler)
        application.add_exception_handler(RequestValidationError, validation_excpetion_hadler)
        application.add_exception_handler(Exception, global_excpetion_hadler)

    @application.get("/", response_model=HealthResponse, tags=["health"])
    def root() -> HealthResponse:
        return health_response(settings)

    return application


app = create_app()
