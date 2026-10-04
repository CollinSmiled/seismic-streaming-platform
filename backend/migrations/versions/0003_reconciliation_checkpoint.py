"""Save successful source catalogue scan checkpoints.

Revision ID: 0003_reconciliation_checkpoint
Revises: 0002_ordered_changes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_reconciliation_checkpoint"
down_revision: str | None = "0002_ordered_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_reconciliation_checkpoints",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("source_reconciliation_checkpoints")
