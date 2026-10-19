import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_raw_ticket_round_trips_every_field(session):
    from app.models import RawTicket

    session.add(RawTicket(ticket_id=101, company_id=7, summary="VPN down",
                          internal_notes="Checked logs", resolution="Renewed certificate",
                          raw_payload={"id": 101, "custom": ["one", {"active": True}]}))
    session.commit()
    session.expunge_all()
    ticket = session.get(RawTicket, 101)
    assert (ticket.ticket_id, ticket.company_id, ticket.summary, ticket.internal_notes,
            ticket.resolution, ticket.raw_payload) == (
        101, 7, "VPN down", "Checked logs", "Renewed certificate",
        {"id": 101, "custom": ["one", {"active": True}]},
    )


def test_tenant_asset_round_trips_every_field(session):
    from app.models import TenantAsset

    session.add(TenantAsset(asset_id=202, company_id=7, asset_name="Laptop-01",
                            serial_number="ABC123", type="Laptop", os="Windows 11"))
    session.commit()
    session.expunge_all()
    asset = session.get(TenantAsset, 202)
    assert (asset.asset_id, asset.company_id, asset.asset_name, asset.serial_number,
            asset.type, asset.os) == (202, 7, "Laptop-01", "ABC123", "Laptop", "Windows 11")


@pytest.mark.parametrize(("scope", "tenant"), [("global", None), ("tenant", 7)])
def test_kb_draft_round_trips_fields_and_defaults_to_pending_review(session, scope, tenant):
    from app.models import KBDraft

    draft = KBDraft(scope=scope, target_tenant_id=tenant, category="Networking",
                    title="Repair VPN", summary="Renew an expired certificate",
                    markdown_steps="1. Open settings\n2. Renew certificate")
    session.add(draft)
    session.commit()
    article_id = draft.article_id
    assert isinstance(article_id, int)
    session.expunge_all()
    draft = session.get(KBDraft, article_id)
    assert (draft.scope, draft.target_tenant_id, draft.category, draft.title,
            draft.summary, draft.markdown_steps, draft.status) == (
        scope, tenant, "Networking", "Repair VPN", "Renew an expired certificate",
        "1. Open settings\n2. Renew certificate", "pending_review",
    )


@pytest.mark.parametrize("status", ["pending_review", "approved", "indexed"])
def test_sqlite_accepts_each_valid_draft_status(db_engine, status):
    with db_engine.begin() as connection:
        connection.execute(text("INSERT INTO kb_drafts (scope, category, title, summary, markdown_steps, status) VALUES ('global', 'Network', 'Title', 'Summary', 'Steps', :status)"), {"status": status})


@pytest.mark.parametrize(("scope", "tenant", "status"), [
    ("other", None, "pending_review"),
    ("global", None, "published"),
    ("global", 7, "approved"),
    ("tenant", None, "approved"),
    (None, None, "pending_review"),
    ("global", None, None),
])
def test_sqlite_rejects_invalid_draft_scope_status_or_target(db_engine, scope, tenant, status):
    with pytest.raises(IntegrityError), db_engine.begin() as connection:
        connection.execute(text("INSERT INTO kb_drafts (scope, target_tenant_id, category, title, summary, markdown_steps, status) VALUES (:scope, :tenant, 'Network', 'Title', 'Summary', 'Steps', :status)"),
                           {"scope": scope, "tenant": tenant, "status": status})


def test_sqlite_applies_default_status_for_direct_inserts(db_engine):
    with db_engine.begin() as connection:
        connection.execute(text("INSERT INTO kb_drafts (scope, category, title, summary, markdown_steps) VALUES ('global', 'Network', 'Title', 'Summary', 'Steps')"))
        assert connection.scalar(text("SELECT status FROM kb_drafts")) == "pending_review"


@pytest.mark.parametrize(("table", "column"), [
    ("raw_tickets", "company_id"), ("tenant_assets", "company_id"),
    ("kb_drafts", "target_tenant_id"),
])
def test_tenant_lookup_columns_have_indexes(db_engine, table, column):
    assert any(column in index["column_names"] for index in inspect(db_engine).get_indexes(table))
