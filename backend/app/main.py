"""FastAPI entrypoint for the Cozmo backend."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.config import get_settings
from app.middleware.logging import configure_logging
from app.routers import agents, calls, health, knowledge, metrics, webhooks
from app.services.agent_config_service import AgentConfigService
from app.services.livekit_service import LiveKitService
from app.services.livekit_webhook_auth import LiveKitWebhookVerifier
from app.services.mongo import MongoResources
from app.services.session_service import SessionService
from app.services.webhook_ingestion import WebhookEventDeduplicator, WebhookIngestionService

LOGGER = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the backend API."""

    settings = get_settings()
    configure_logging(settings.environment, settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        mongo_resources = None
        application.state.mongo = None
        application.state.session_service = None
        application.state.agent_config_service = None
        application.state.webhook_service = None
        application.state.livekit_service = LiveKitService.from_settings(settings)
        application.state.livekit_webhook_verifier = LiveKitWebhookVerifier.from_settings(settings)
        application.state.telephony_setup = application.state.livekit_service.validation_report()
        application.state.mongo_ready = False

        try:
            mongo_resources = MongoResources.from_connection_string(
                mongo_uri=settings.mongo_uri,
                database_name=settings.mongo_database or "cozmo",
                server_selection_timeout_ms=settings.mongo_server_selection_timeout_ms,
            )
            if settings.auto_create_indexes:
                mongo_resources.ensure_indexes()
            application.state.mongo = mongo_resources
            application.state.session_service = SessionService(
                call_sessions=mongo_resources.call_sessions,
                transcripts=mongo_resources.transcripts,
            )
            application.state.agent_config_service = AgentConfigService(
                repository=mongo_resources.agent_configs,
            )
            application.state.webhook_service = WebhookIngestionService(
                session_service=application.state.session_service,
                agent_config_service=application.state.agent_config_service,
                deduplicator=WebhookEventDeduplicator(mongo_resources.webhook_events),
            )
            application.state.mongo_ready = True
        except Exception:
            LOGGER.exception("Failed to initialize Mongo resources")

        try:
            yield
        finally:
            if mongo_resources is not None:
                mongo_resources.close()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.settings = settings

    application.include_router(health.router)
    application.include_router(metrics.router)
    application.include_router(webhooks.router)
    application.include_router(calls.router)
    application.include_router(knowledge.router)
    application.include_router(agents.router)

    @application.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "environment": settings.environment}

    return application


app = create_app()
