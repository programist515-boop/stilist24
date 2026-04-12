"""user_photos table + tryon_jobs columns

Adds the ``user_photos`` table (canonical user photo references for try-on
and analysis) and extends ``tryon_jobs`` with the columns needed for
provider tracking, structured errors, deterministic storage references,
and explicit ``updated_at``.

Revision ID: 0003_user_photos_tryon
Revises: 0002_wardrobe_image_key
Create Date: 2026-04-11 00:00:00.000000

Note on the short revision id: alembic's default ``alembic_version.version_num``
column is ``VARCHAR(32)``. The original descriptive id
``0003_user_photos_and_tryon_columns`` is 34 chars long and triggers a
``StringDataRightTruncation`` on stamp. The id is kept deliberately short
here so nothing else has to be touched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_user_photos_tryon"
down_revision = "0002_wardrobe_image_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_photos table -----------------------------------------------
    op.create_table(
        "user_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("image_key", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_photos_user_id",
        "user_photos",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_photos_user_slot",
        "user_photos",
        ["user_id", "slot"],
        unique=False,
    )

    # --- tryon_jobs columns ----------------------------------------------
    op.add_column(
        "tryon_jobs",
        sa.Column("user_photo_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tryon_jobs_user_photo_id",
        "tryon_jobs",
        "user_photos",
        ["user_photo_id"],
        ["id"],
    )
    op.add_column(
        "tryon_jobs",
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="fashn",
        ),
    )
    op.add_column(
        "tryon_jobs",
        sa.Column("provider_job_id", sa.String(), nullable=True),
    )
    op.add_column(
        "tryon_jobs",
        sa.Column("result_image_key", sa.String(), nullable=True),
    )
    op.add_column(
        "tryon_jobs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "tryon_jobs",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "tryon_jobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tryon_jobs_user_id",
        "tryon_jobs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tryon_jobs_user_id", table_name="tryon_jobs")
    op.drop_column("tryon_jobs", "updated_at")
    op.drop_column("tryon_jobs", "metadata_json")
    op.drop_column("tryon_jobs", "error_message")
    op.drop_column("tryon_jobs", "result_image_key")
    op.drop_column("tryon_jobs", "provider_job_id")
    op.drop_column("tryon_jobs", "provider")
    op.drop_constraint(
        "fk_tryon_jobs_user_photo_id", "tryon_jobs", type_="foreignkey"
    )
    op.drop_column("tryon_jobs", "user_photo_id")

    op.drop_index("ix_user_photos_user_slot", table_name="user_photos")
    op.drop_index("ix_user_photos_user_id", table_name="user_photos")
    op.drop_table("user_photos")
