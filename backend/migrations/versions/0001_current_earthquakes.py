"""Create the current earthquake projection.

Revision ID: 0001_current_earthquakes
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_current_earthquakes"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "earthquake_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_action", sa.String(16)),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(precision=53), nullable=False),
        sa.Column("longitude", sa.Float(precision=53), nullable=False),
        sa.Column("depth_km", sa.Float(precision=53)),
        sa.Column("magnitude", sa.Float(precision=53)),
        sa.Column("magnitude_type", sa.String(32)),
        sa.Column("region", sa.String(255)),
        sa.Column("source_catalog", sa.String(64)),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "persisted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("source = 'EMSC'", name="ck_source_emsc"),
        sa.CheckConstraint(
            "source_action IN ('create', 'update')", name="ck_source_action"
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_longitude_range"),
        sa.CheckConstraint(
            "depth_km > '-Infinity'::float8 AND depth_km < 'Infinity'::float8",
            name="ck_depth_finite",
        ),
        sa.CheckConstraint(
            "magnitude > '-Infinity'::float8 AND magnitude < 'Infinity'::float8",
            name="ck_magnitude_finite",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_content_sha256"
        ),
    )
    op.create_index(
        "ix_earthquake_events_event_time", "earthquake_events", ["event_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_earthquake_events_event_time", table_name="earthquake_events")
    op.drop_table("earthquake_events")
