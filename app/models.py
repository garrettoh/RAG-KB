"""Source tickets, tenant assets, and reviewed knowledge article drafts."""

from typing import Any, Literal

from sqlalchemy import JSON, CheckConstraint, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RawTicket(Base):
    __tablename__ = "raw_tickets"

    ticket_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    summary: Mapped[str] = mapped_column(Text)
    internal_notes: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class TenantAsset(Base):
    __tablename__ = "tenant_assets"

    asset_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    asset_name: Mapped[str] = mapped_column(String)
    serial_number: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    os: Mapped[str] = mapped_column(String)


class KBDraft(Base):
    __tablename__ = "kb_drafts"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'tenant')", name="ck_kb_drafts_scope"),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'indexed')",
            name="ck_kb_drafts_status",
        ),
        CheckConstraint(
            "(scope = 'global' AND target_tenant_id IS NULL) OR "
            "(scope = 'tenant' AND target_tenant_id IS NOT NULL)",
            name="ck_kb_drafts_target_tenant",
        ),
    )

    article_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[Literal["global", "tenant"]] = mapped_column(String)
    target_tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    markdown_steps: Mapped[str] = mapped_column(Text)
    status: Mapped[Literal["pending_review", "approved", "indexed"]] = mapped_column(
        String, default="pending_review", server_default=text("'pending_review'"),
    )
