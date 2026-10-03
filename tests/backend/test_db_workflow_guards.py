"""Committed local workflow boundaries; all sources and scopes are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.api_models import ReviewRequest, RunRequest
from backend.catalog import ProductInput, import_products
from backend.config import Settings
from backend.errors import BackendError
from backend.models import ProcessingRun, ProviderAttempt, ReviewEvent, SourceDocument, Vendor
from backend.providers import SyntheticProvider
from backend.service import cancel_run, create_run, process_run, review_run, run_for
from backend.synthetic import generate_fixture
from backend.uploads import digest, write_source
from gate_a.database import create_db_engine
from gate_a.models import Tenant

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.postgresql


@pytest.fixture(scope="module")
def workflow_engine():
    value = os.environ.get("PO_BACKEND_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set isolated local catalog test database to exercise workflow guards")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith(("gate_a_test_backend_", "orderlens_product_rows")) or url.query):
        pytest.fail("Workflow guards require an isolated loopback synthetic test database")
    engine = create_db_engine(url, 10)
    config = Config(str(ROOT / "backend.alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def setup(workflow_engine):
    settings = Settings(_env_file=None, database_url=SecretStr(workflow_engine.url.render_as_string(hide_password=False)),
        openai_api_key=None, storage_directory=ROOT / "data" / "catalog-agent" / "workflow-tests" / uuid4().hex)
    with Session(workflow_engine, expire_on_commit=False) as session:
        tenant = Tenant(name=f"Synthetic database workflow {uuid4()}")
        session.add(tenant)
        session.flush()
        vendor = Vendor(tenant_id=tenant.id, name="Synthetic database workflow vendor")
        session.add(vendor)
        session.flush()
        import_products(session, tenant.id, vendor.id, [
            ProductInput(sku="SYN-001", description="Synthetic blue widget"),
            ProductInput(sku="SYN-002", description="Synthetic red widget")])
        data = generate_fixture()
        source = SourceDocument(tenant_id=tenant.id, vendor_id=vendor.id, sha256=digest(data), byte_size=len(data),
            media_type="application/pdf", page_count=1, storage_reference=write_source(settings.storage_directory, data))
        session.add(source)
        session.flush()
        run = create_run(session, tenant.id, source.id, uuid4().hex,
                         RunRequest(provider="synthetic", fixture_name="purchase_order"))
        session.commit()
        return settings, tenant.id, source.id, run.id


def test_locked_read_refreshes_identity_map_after_another_session_cancels(workflow_engine, setup):
    settings, tenant, source_id, run_id = setup
    with Session(workflow_engine, expire_on_commit=False) as first:
        stale = run_for(first, tenant, run_id)
        first.commit()
        assert stale.state == "created"
        with Session(workflow_engine) as second:
            cancel_run(second, tenant, run_id)
            second.commit()
        current = run_for(first, tenant, run_id, lock=True)
        assert current.state == "cancelled"


@pytest.mark.parametrize("raise_after_cancel", [False, True])
def test_cancellation_during_provider_retains_attempt_without_overwriting_cancel(workflow_engine, setup, raise_after_cancel):
    settings, tenant, source_id, run_id = setup

    class CancellingFixtureProvider(SyntheticProvider):
        def extract(self, *args, **kwargs):
            with Session(workflow_engine) as cancellation:
                cancel_run(cancellation, tenant, run_id)
                cancellation.commit()
            if raise_after_cancel:
                raise RuntimeError("Private synthetic text should never become an API error")
            return super().extract(*args, **kwargs)

    with Session(workflow_engine, expire_on_commit=False) as session:
        run = process_run(session, tenant, run_id, settings, CancellingFixtureProvider())
        assert run.state == "cancelled" and run.outcome_code == "cancelled_by_local_user"
        assert run.result is None and run.parses is None
    with Session(workflow_engine) as session:
        attempt = session.scalar(select(ProviderAttempt).where(ProviderAttempt.run_id == run_id))
        assert attempt.finished_at is not None
        assert attempt.state == ("unknown_outcome" if raise_after_cancel else "succeeded")
        assert attempt.error_code == ("provider_outcome_unknown" if raise_after_cancel else None)


def test_unexpected_provider_exception_is_persisted_and_never_blindly_retried(workflow_engine, setup):
    settings, tenant, source_id, run_id = setup

    class InterruptedFixtureProvider(SyntheticProvider):
        calls = 0
        def extract(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("private synthetic provider failure")

    provider = InterruptedFixtureProvider()
    with Session(workflow_engine, expire_on_commit=False) as session:
        run = process_run(session, tenant, run_id, settings, provider)
        assert run.state == "failed" and run.outcome_code == "unknown_outcome"
        assert process_run(session, tenant, run_id, settings, provider).state == "failed"
    with Session(workflow_engine) as session:
        attempts = list(session.scalars(select(ProviderAttempt).where(ProviderAttempt.run_id == run_id)))
        assert len(attempts) == 1 and provider.calls == 1
        assert attempts[0].state == "unknown_outcome"
        assert attempts[0].error_code == "provider_outcome_unknown"
        assert attempts[0].finished_at is not None


def test_concurrent_same_key_creates_one_run_and_conflicting_retry_fails(workflow_engine, setup):
    settings, tenant, source_id, run_id = setup
    key, barrier = uuid4().hex, Barrier(2)
    request = RunRequest(provider="synthetic", fixture_name="purchase_order")

    def create():
        with Session(workflow_engine, expire_on_commit=False) as session:
            barrier.wait(timeout=5)
            run = create_run(session, tenant, source_id, key, request)
            session.commit()
            return run.id

    with ThreadPoolExecutor(max_workers=2) as threads:
        futures = [threads.submit(create) for _ in range(2)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1]
    with Session(workflow_engine) as session:
        assert session.scalar(select(func.count()).select_from(ProcessingRun)
                              .where(ProcessingRun.tenant_id == tenant, ProcessingRun.idempotency_key == key)) == 1
        with pytest.raises(BackendError) as conflict:
            create_run(session, tenant, source_id, key, RunRequest(provider="openai"))
        assert conflict.value.code == "idempotency_payload_conflict"


def test_review_sequence_follows_actual_serialized_insertion_not_transaction_start(workflow_engine, setup):
    settings, tenant, source_id, run_id = setup
    with Session(workflow_engine, expire_on_commit=False) as session:
        run = process_run(session, tenant, run_id, settings)
        row = run.result["rows"][0]
    base = dict(action="correct", row_id=row["row_id"], reviewer="Synthetic reviewer",
                reason="Inspected synthetic source", evidence_reference=row["evidence"], field_name="quantity")
    with Session(workflow_engine, expire_on_commit=False) as early:
        early.scalar(select(func.current_timestamp()))
        # Another request completes before the earlier-started request gets the lock.
        with Session(workflow_engine, expire_on_commit=False) as later:
            first = review_run(later, tenant, run_id, ReviewRequest(**base, new_value="004"))
            later.commit()
        second = review_run(early, tenant, run_id, ReviewRequest(**base, new_value="005"))
        early.commit()
        assert second.event_sequence == first.event_sequence + 1
    with Session(workflow_engine) as session:
        values = list(session.scalars(select(ReviewEvent).where(ReviewEvent.tenant_id == tenant,
            ReviewEvent.run_id == run_id).order_by(*ReviewEvent.audit_order())))
        assert [event.new_value["value"] for event in values] == ["004", "005"]


def test_review_clock_regression_does_not_reorder_corrections(workflow_engine, setup, monkeypatch):
    import backend.service as service
    settings, tenant, source_id, run_id = setup
    with Session(workflow_engine, expire_on_commit=False) as session:
        run = process_run(session, tenant, run_id, settings)
        row = run.result["rows"][0]
    base = dict(action="correct", row_id=row["row_id"], reviewer="Fictional clock QA",
        reason="Synthetic clock-regression test", evidence_reference=row["evidence"], field_name="quantity")
    for timestamp, value in [(datetime(2026,10,2,tzinfo=timezone.utc),"002"),
                              (datetime(2025,10,2,tzinfo=timezone.utc),"003")]:
        monkeypatch.setattr(service,"now",lambda: timestamp)
        with Session(workflow_engine,expire_on_commit=False) as session:
            saved=review_run(session,tenant,run_id,ReviewRequest(**base,new_value=value))
            session.commit()
            if value=="003": assert saved.old_value["value"]=="002"
    with Session(workflow_engine) as session:
        events=list(session.scalars(select(ReviewEvent).where(ReviewEvent.run_id==run_id).order_by(*ReviewEvent.audit_order())))
        assert [event.new_value["value"] for event in events]==["002","003"]
        assert events[0].created_at>events[1].created_at
