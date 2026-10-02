"""Gate A health and public contract metadata; no document processing routes."""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from sqlalchemy import Engine

from gate_a.config import Settings
from gate_a.contracts import ProductDocumentV1
from gate_a.database import EXPECTED_REVISION, create_db_engine, probe_database


class Liveness(BaseModel):
    status: Literal["alive"] = "alive"
    gate: Literal["A"] = "A"


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ready", "unavailable", "migration_required"]
    expected_revision: str


class PublicConfiguration(BaseModel):
    environment: Literal["local"]
    gate: Literal["A"] = "A"
    contract_name: Literal["ProductDocument"] = "ProductDocument"
    contract_version: Literal["1.0"] = "1.0"
    extraction_payload_finalized: Literal[False] = False
    supported_document_type: Literal["purchase_order"] = "purchase_order"


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Construct the app without connecting to PostgreSQL or requiring credentials."""
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database_engine = engine if engine is not None else create_db_engine(
            configuration.database_url.get_secret_value(),
            connect_timeout_seconds=configuration.db_connect_timeout_seconds,
        )
        application.state.database_engine = database_engine
        try:
            yield
        finally:
            if engine is None:
                database_engine.dispose()

    application = FastAPI(
        title="Advance PO Reader â€” local Gate A",
        version="0.1.0",
        description="Health, configuration and contract envelope only.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    @application.get("/health/live", response_model=Liveness)
    def liveness() -> Liveness:
        return Liveness()

    @application.get("/health/ready", response_model=Readiness,
                     responses={503: {"model": Readiness}})
    def readiness(response: Response) -> Readiness:
        database_status = probe_database(application.state.database_engine)
        if database_status != "ready":
            response.status_code = 503
        return Readiness(
            status="ready" if database_status == "ready" else "not_ready",
            database=database_status,
            expected_revision=EXPECTED_REVISION,
        )

    @application.get("/configuration", response_model=PublicConfiguration)
    def public_configuration() -> PublicConfiguration:
        return PublicConfiguration(environment=configuration.environment)

    @application.get("/contracts/product-document/v1/schema")
    def contract_schema() -> dict:
        # Metadata only; this endpoint accepts no document or observation data.
        return ProductDocumentV1.model_json_schema()

    return application
