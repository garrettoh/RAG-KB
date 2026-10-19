import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session


def test_module_exports_session_factory_bound_to_engine():
    from app.database import SessionLocal, engine

    with SessionLocal() as session:
        assert session.get_bind() is engine
        assert session.scalar(text("SELECT 1")) == 1


def test_request_session_closes_after_success(application):
    from app.database import get_db

    sessions = []

    @application.get("/session-probe")
    def probe(session: Session = Depends(get_db)):
        sessions.append(session)
        assert session.scalar(text("SELECT 1")) == 1
        return {"ok": True}

    with TestClient(application) as client:
        assert client.get("/session-probe").json() == {"ok": True}
    with pytest.raises(InvalidRequestError):
        sessions[0].execute(text("SELECT 1"))


def test_failed_request_rolls_back_and_closes_session(application):
    from app.database import get_db
    from app.models import RawTicket

    sessions = []
    rollbacks = []

    @application.post("/failed-write")
    def failed_write(session: Session = Depends(get_db)):
        sessions.append(session)
        event.listen(session, "after_rollback", lambda _: rollbacks.append(True))
        session.add(RawTicket(ticket_id=1, company_id=7, summary="VPN down",
                              internal_notes="", resolution="", raw_payload={}))
        session.flush()
        raise HTTPException(status_code=409, detail="Rejected write")

    with TestClient(application) as client:
        assert client.post("/failed-write").status_code == 409
        assert rollbacks == [True]
        with application.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(RawTicket)) == 0
    with pytest.raises(InvalidRequestError):
        sessions[0].execute(text("SELECT 1"))


def test_successful_request_does_not_commit_uncommitted_changes(application):
    from app.database import get_db
    from app.models import RawTicket

    @application.post("/uncommitted-write")
    def uncommitted_write(session: Session = Depends(get_db)):
        session.add(RawTicket(ticket_id=2, company_id=7, summary="VPN down",
                              internal_notes="", resolution="", raw_payload={}))
        session.flush()
        return {"ok": True}

    with TestClient(application) as client:
        assert client.post("/uncommitted-write").status_code == 200
        with application.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(RawTicket)) == 0
