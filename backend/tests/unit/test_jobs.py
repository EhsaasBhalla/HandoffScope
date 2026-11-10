"""Unit tests for Job service and fallback execution without Redis."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import all models to resolve mapper relationships
import app.modules.workspaces.models  # noqa
import app.modules.projects.models  # noqa
import app.modules.handover_cases.models  # noqa
import app.modules.sources.models  # noqa
import app.modules.ingestion.models  # noqa
import app.modules.documents.models  # noqa
import app.modules.jobs.models  # noqa
import app.modules.audit.models  # noqa

from app.db.base import Base
from app.db.enums import JobType
from app.modules.jobs.service import enqueue_job


def test_enqueue_job_local_thread_fallback():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        job = enqueue_job(
            db,
            job_type=JobType.DOCUMENT_PARSE,
            params={"test": "data"},
            queue_name="test-queue",
        )
        assert job.id is not None
        assert job.job_type == JobType.DOCUMENT_PARSE
    finally:
        db.close()
