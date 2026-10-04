"""Assign committed projection changes an ordered cursor.

Revision ID: 0002_ordered_changes
Revises: 0001_current_earthquakes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ordered_changes"
down_revision: str | None = "0001_current_earthquakes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "earthquake_change_clock",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("last_cursor", sa.BigInteger, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_change_clock_singleton"),
        sa.CheckConstraint("last_cursor >= 0", name="ck_change_clock_nonnegative"),
    )
    op.execute("INSERT INTO earthquake_change_clock (id, last_cursor) VALUES (1, 0)")
    op.add_column(
        "earthquake_events",
        sa.Column("change_cursor", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "earthquake_events",
        sa.Column("created_cursor", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_change_cursor_nonnegative", "earthquake_events", "change_cursor >= 0"
    )
    op.create_check_constraint(
        "ck_created_cursor_range",
        "earthquake_events",
        "created_cursor >= 0 AND created_cursor <= change_cursor",
    )
    op.create_index(
        "ix_earthquake_events_change_cursor", "earthquake_events", ["change_cursor"]
    )


def downgrade() -> None:
    op.drop_index("ix_earthquake_events_change_cursor", table_name="earthquake_events")
    op.drop_constraint("ck_created_cursor_range", "earthquake_events", type_="check")
    op.drop_constraint(
        "ck_change_cursor_nonnegative", "earthquake_events", type_="check"
    )
    op.drop_column("earthquake_events", "created_cursor")
    op.drop_column("earthquake_events", "change_cursor")
    op.drop_table("earthquake_change_clock")
