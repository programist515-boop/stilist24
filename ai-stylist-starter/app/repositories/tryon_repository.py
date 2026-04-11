import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tryon_job import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    TryOnJob,
)


class TryOnRepository:
    """Thin CRUD + state transitions for try-on jobs.

    The repository owns persistence only. Pipeline orchestration, provider
    selection, and storage I/O live in the service layer.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------------- create

    def create_pending(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID | None,
        user_photo_id: uuid.UUID | None,
        provider: str = "fashn",
        job_id: uuid.UUID | None = None,
    ) -> TryOnJob:
        job = TryOnJob(
            user_id=user_id,
            item_id=item_id,
            user_photo_id=user_photo_id,
            provider=provider,
            status=STATUS_PENDING,
            metadata_json={},
        )
        if job_id is not None:
            job.id = job_id
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    # ---------------------------------------------------------------- read

    def get_by_id(self, job_id: uuid.UUID) -> TryOnJob | None:
        return self.db.get(TryOnJob, job_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[TryOnJob]:
        stmt = (
            select(TryOnJob)
            .where(TryOnJob.user_id == user_id)
            .order_by(TryOnJob.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    # ---------------------------------------------------------------- transitions

    def mark_running(
        self,
        job_id: uuid.UUID,
        *,
        provider_job_id: str | None = None,
    ) -> TryOnJob | None:
        return self._update(
            job_id,
            status=STATUS_RUNNING,
            provider_job_id=provider_job_id,
        )

    def mark_succeeded(
        self,
        job_id: uuid.UUID,
        *,
        result_image_key: str,
        result_image_url: str,
        metadata: dict | None = None,
        provider_job_id: str | None = None,
    ) -> TryOnJob | None:
        return self._update(
            job_id,
            status=STATUS_SUCCEEDED,
            result_image_key=result_image_key,
            result_image_url=result_image_url,
            metadata_json=metadata or {},
            provider_job_id=provider_job_id,
            error_message=None,
        )

    def mark_failed(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
    ) -> TryOnJob | None:
        return self._update(
            job_id,
            status=STATUS_FAILED,
            error_message=error_message,
        )

    # ---------------------------------------------------------------- helpers

    def _update(self, job_id: uuid.UUID, **fields) -> TryOnJob | None:
        job = self.get_by_id(job_id)
        if job is None:
            return None
        for key, value in fields.items():
            if value is None and key == "provider_job_id" and job.provider_job_id:
                # Preserve a previously stored provider job id when later
                # transitions don't supply one.
                continue
            if hasattr(job, key):
                setattr(job, key, value)
        self.db.commit()
        self.db.refresh(job)
        return job
