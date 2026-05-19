"""add_crowdsourcing_columns_and_report_reactions"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET

revision = 'e597e3cc5765'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("direction", sa.String(32), nullable=True))
    op.add_column("reports", sa.Column("active_trip_id", sa.Integer, sa.ForeignKey("active_trips.id"), nullable=True))
    op.add_column("reports", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("confirm_count", sa.Integer, server_default="0", nullable=False))
    op.add_column("reports", sa.Column("deny_count", sa.Integer, server_default="0", nullable=False))
    op.create_index("ix_reports_route_dir_expires", "reports", ["route_id", "direction", "expires_at"])

    op.create_table(
        "report_reactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reaction", sa.String(8), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("source_ip", INET, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_report_reactions_report_user", "report_reactions", ["report_id", "user_id"])
    op.create_index("ix_report_reactions_report_reaction", "report_reactions", ["report_id", "reaction"])


def downgrade() -> None:
    op.drop_index("ix_report_reactions_report_reaction", table_name="report_reactions")
    op.drop_constraint("uq_report_reactions_report_user", "report_reactions", type_="unique")
    op.drop_table("report_reactions")
    op.drop_index("ix_reports_route_dir_expires", table_name="reports")
    op.drop_column("reports", "deny_count")
    op.drop_column("reports", "confirm_count")
    op.drop_column("reports", "expires_at")
    op.drop_column("reports", "active_trip_id")
    op.drop_column("reports", "direction")
