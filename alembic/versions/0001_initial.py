"""initial campaign records and audit log

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-19 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("keitaro_campaign_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("geo_codes", sa.JSON(), nullable=False),
        sa.Column("initial_offer_id", sa.Integer(), nullable=True),
        sa.Column("domain_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("traffic_source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_campaign_records_keitaro_campaign_id",
        "campaign_records",
        ["keitaro_campaign_id"],
        unique=True,
    )

    op.create_table(
        "campaign_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("keitaro_campaign_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_campaign_audit_logs_keitaro_campaign_id",
        "campaign_audit_logs",
        ["keitaro_campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_campaign_created",
        "campaign_audit_logs",
        ["keitaro_campaign_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_campaign_created", table_name="campaign_audit_logs")
    op.drop_index(
        "ix_campaign_audit_logs_keitaro_campaign_id", table_name="campaign_audit_logs"
    )
    op.drop_table("campaign_audit_logs")
    op.drop_index("ix_campaign_records_keitaro_campaign_id", table_name="campaign_records")
    op.drop_table("campaign_records")
