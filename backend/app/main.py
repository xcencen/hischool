"""my-campus bootstrap application, independent of legacy business services."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap.config import BootstrapSettings, load_settings
from app.bootstrap.health import HealthResponse, create_health_router, health_response


def create_app(settings: BootstrapSettings | None = None) -> FastAPI:
    """Create a minimal app without database, filesystem, or network setup."""
    settings = settings or load_settings()
    application = FastAPI(title=settings.app_name, version=settings.app_version)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.include_router(create_health_router(settings))

    @application.get("/", response_model=HealthResponse, tags=["health"])
    def root() -> HealthResponse:
        return health_response(settings)

    return application


app = create_app()
