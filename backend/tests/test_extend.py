from datetime import datetime, timedelta

from app.models.models import HangRail, RailPlacement, Store, WorkOrder


def _store(db):
    s = Store(name="测试店")
    db.add(s)
    db.flush()
    return s


def _order(db, store, **kw):
    kw.setdefault("ticket_code", "T-0001")
    kw.setdefault("garment_name", "测试衣")
    kw.setdefault("length_cm", 40)
    o = WorkOrder(store_id=store.id, **kw)
    db.add(o)
    db.flush()
    return o


def _placement(db, store, order):
    rail = HangRail(store_id=store.id, label="A 杆", length_cm=200)
    db.add(rail)
    db.flush()
    db.add(RailPlacement(rail_id=rail.id, order_id=order.id, start_cm=0, end_cm=order.length_cm))
    db.flush()


def test_extend_hung_success(client, db_session):
    store = _store(db_session)
    now = datetime.utcnow()
    o = _order(
        db_session, store,
        status="hung", due_at=now + timedelta(days=1), hung_at=now - timedelta(hours=6),
    )
    _placement(db_session, store, o)
    db_session.commit()

    new_due = now + timedelta(days=3)
    r = client.post("/api/extend", json={"order_id": o.id, "due_at": new_due.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "hung"
    assert body["can_extend"] is True
    assert abs(datetime.fromisoformat(body["due_at"]) - new_due) < timedelta(seconds=1)

    # 工单列表按新到期同一口径返回
    rows = client.get("/api/orders").json()
    row = next(x for x in rows if x["id"] == o.id)
    assert abs(datetime.fromisoformat(row["due_at"]) - new_due) < timedelta(seconds=1)
    assert row["can_extend"] is True


def test_extend_overdue_with_placement_back_to_hung(client, db_session):
    store = _store(db_session)
    now = datetime.utcnow()
    o = _order(
        db_session, store,
        status="overdue", due_at=now - timedelta(hours=5), hung_at=now - timedelta(days=2),
    )
    _placement(db_session, store, o)
    db_session.commit()
    assert any(x["id"] == o.id for x in client.get("/api/overdue").json())

    new_due = now + timedelta(days=2)
    r = client.post("/api/extend", json={"order_id": o.id, "due_at": new_due.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "hung"

    # 逾期列表按新到期刷新：该单不再逾期
    assert all(x["id"] != o.id for x in client.get("/api/overdue").json())


def test_extend_before_hung_at_rejected(client, db_session):
    store = _store(db_session)
    now = datetime.utcnow()
    orig_due = now - timedelta(days=2)
    # 逾期后才上杆的工单：hung_at 晚于原 due_at
    o = _order(
        db_session, store,
        status="hung", due_at=orig_due, hung_at=now - timedelta(hours=1),
    )
    _placement(db_session, store, o)
    db_session.commit()

    # 新到期晚于原 due_at，但早于 hung_at → 拒绝
    r = client.post(
        "/api/extend",
        json={"order_id": o.id, "due_at": (now - timedelta(hours=12)).isoformat()},
    )
    assert r.status_code == 400
    assert "上杆" in r.json()["detail"]

    db_session.expire_all()
    assert db_session.get(WorkOrder, o.id).due_at == orig_due


def test_extend_not_later_than_due_rejected(client, db_session):
    store = _store(db_session)
    now = datetime.utcnow()
    o = _order(
        db_session, store,
        status="hung", due_at=now + timedelta(days=1), hung_at=now - timedelta(hours=1),
    )
    _placement(db_session, store, o)
    db_session.commit()

    r = client.post(
        "/api/extend",
        json={"order_id": o.id, "due_at": (now + timedelta(hours=1)).isoformat()},
    )
    assert r.status_code == 400
    assert "晚于原到期" in r.json()["detail"]


def test_extend_non_hung_rejected(client, db_session):
    store = _store(db_session)
    now = datetime.utcnow()
    ready = _order(db_session, store, ticket_code="T-R", status="ready", due_at=now + timedelta(days=1))
    picked = _order(
        db_session, store, ticket_code="T-P", status="picked",
        due_at=now + timedelta(days=1), hung_at=now - timedelta(days=1),
    )
    pure_overdue = _order(
        db_session, store, ticket_code="T-O", status="overdue",
        due_at=now - timedelta(days=1),  # 无占位
    )
    db_session.commit()

    for o in (ready, picked, pure_overdue):
        r = client.post(
            "/api/extend",
            json={"order_id": o.id, "due_at": (now + timedelta(days=3)).isoformat()},
        )
        assert r.status_code == 400, (o.status, r.text)
        assert "不可延期" in r.json()["detail"]


def test_extend_missing_order(client):
    r = client.post(
        "/api/extend",
        json={"order_id": 999, "due_at": datetime.utcnow().isoformat()},
    )
    assert r.status_code == 404
