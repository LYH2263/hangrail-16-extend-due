from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import HangRail, RailPlacement, Store, WorkOrder


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    db = TestingSession()

    store = Store(name="测试店")
    db.add(store)
    db.flush()
    rail = HangRail(store_id=store.id, label="A 杆", length_cm=200)
    db.add(rail)
    db.flush()

    t0 = datetime(2026, 9, 20, 12, 0, 0)
    hung = WorkOrder(
        store_id=store.id, ticket_code="E-001", garment_name="大衣", length_cm=40,
        status="hung", due_at=t0 + timedelta(days=1), hung_at=t0,
    )
    overdue_on_rail = WorkOrder(
        store_id=store.id, ticket_code="E-002", garment_name="西装", length_cm=30,
        status="overdue", due_at=t0 - timedelta(days=1), hung_at=t0,
    )
    pure_overdue = WorkOrder(
        store_id=store.id, ticket_code="E-003", garment_name="裙子", length_cm=30,
        status="overdue", due_at=t0 - timedelta(days=2), hung_at=None,
    )
    ready = WorkOrder(
        store_id=store.id, ticket_code="E-004", garment_name="衬衫", length_cm=20,
        status="ready", due_at=t0 + timedelta(days=1), hung_at=None,
    )
    picked = WorkOrder(
        store_id=store.id, ticket_code="E-005", garment_name="风衣", length_cm=40,
        status="picked", due_at=t0 + timedelta(days=1), hung_at=t0 - timedelta(days=2),
    )
    db.add_all([hung, overdue_on_rail, pure_overdue, ready, picked])
    db.flush()
    db.add_all(
        [
            RailPlacement(rail_id=rail.id, order_id=hung.id, start_cm=0, end_cm=40),
            RailPlacement(rail_id=rail.id, order_id=overdue_on_rail.id, start_cm=40, end_cm=70),
            RailPlacement(rail_id=rail.id, order_id=picked.id, start_cm=70, end_cm=110, active=0),
        ]
    )
    db.commit()

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, db
    app.dependency_overrides.clear()
    db.close()


def test_extend_success(session):
    client, db = session
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == "E-001"))
    new_due = order.due_at + timedelta(days=3)
    res = client.post(f"/api/orders/{order.id}/extend", json={"due_at": new_due.isoformat()})
    assert res.status_code == 200
    data = res.json()
    assert datetime.fromisoformat(data["due_at"]) == new_due
    assert data["status"] == "hung"
    db.expire_all()
    assert db.get(WorkOrder, order.id).due_at == new_due


def test_extend_overdue_on_rail_revives_and_leaves_overdue_list(session):
    client, db = session
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == "E-002"))
    new_due = datetime(2026, 9, 23, 12, 0, 0)
    res = client.post(f"/api/orders/{order.id}/extend", json={"due_at": new_due.isoformat()})
    assert res.status_code == 200
    assert res.json()["status"] == "hung"
    overdue = client.get("/api/overdue").json()
    assert all(o["ticket_code"] != "E-002" for o in overdue)


def test_extend_reject_before_hung_at(session):
    client, db = session
    # E-002: due_at=09-19, hung_at=09-20；新到期晚于原 due 但早于 hung_at
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == "E-002"))
    new_due = datetime(2026, 9, 20, 11, 0, 0)
    res = client.post(f"/api/orders/{order.id}/extend", json={"due_at": new_due.isoformat()})
    assert res.status_code == 400
    assert "hung" in res.text or "挂杆" in res.text


def test_extend_reject_not_later_than_original(session):
    client, db = session
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == "E-001"))
    res = client.post(
        f"/api/orders/{order.id}/extend",
        json={"due_at": order.due_at.isoformat()},
    )
    assert res.status_code == 400


@pytest.mark.parametrize("ticket", ["E-003", "E-004", "E-005"])
def test_extend_reject_non_hung(session, ticket):
    client, db = session
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == ticket))
    new_due = datetime(2026, 10, 1, 0, 0, 0)
    res = client.post(f"/api/orders/{order.id}/extend", json={"due_at": new_due.isoformat()})
    assert res.status_code == 400


def test_extend_unknown_order(session):
    client, _ = session
    res = client.post("/api/orders/9999/extend", json={"due_at": "2026-10-01T00:00:00"})
    assert res.status_code == 404
