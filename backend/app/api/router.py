from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import HangRail, RailPlacement, Store, WorkOrder
from app.schemas.schemas import (
    ExtendRequest,
    HangRequest,
    OccupancyOut,
    OccupancySeg,
    OrderOut,
    PickupRequest,
    RailOut,
    StoreOut,
)
from app.services.rail_engine import Segment, first_fit

api_router = APIRouter()


def _has_active_placement(db: Session, order_id: int) -> bool:
    return (
        db.scalar(
            select(RailPlacement.id)
            .where(RailPlacement.order_id == order_id, RailPlacement.active == 1)
            .limit(1)
        )
        is not None
    )


def _can_extend(db: Session, order: WorkOrder) -> bool:
    """hung 工单可延期；overdue 但仍在杆上（有占位）的工单同口径可延期。"""
    return order.status == "hung" or (
        order.status == "overdue" and _has_active_placement(db, order.id)
    )


def _attach_can_extend(db: Session, orders):
    for o in orders:
        o.can_extend = _can_extend(db, o)
    return orders


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/stores", response_model=list[StoreOut])
def stores(db: Session = Depends(get_db)):
    return db.scalars(select(Store).order_by(Store.id)).all()


@api_router.get("/rails", response_model=list[RailOut])
def rails(db: Session = Depends(get_db)):
    return db.scalars(select(HangRail).order_by(HangRail.id)).all()


@api_router.get("/orders", response_model=list[OrderOut])
def orders(db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkOrder).order_by(WorkOrder.id.desc())).all()
    return _attach_can_extend(db, rows)


@api_router.get("/occupancy/{rail_id}", response_model=OccupancyOut)
def occupancy(rail_id: int, db: Session = Depends(get_db)):
    rail = db.get(HangRail, rail_id)
    if not rail:
        raise HTTPException(404, "挂杆不存在")
    placements = db.scalars(
        select(RailPlacement).where(RailPlacement.rail_id == rail_id, RailPlacement.active == 1)
    ).all()
    segs = []
    for p in placements:
        order = db.get(WorkOrder, p.order_id)
        if not order:
            continue
        segs.append(
            OccupancySeg(
                order_id=order.id,
                ticket_code=order.ticket_code,
                garment_name=order.garment_name,
                start_cm=p.start_cm,
                end_cm=p.end_cm,
            )
        )
    segs.sort(key=lambda s: s.start_cm)
    return OccupancyOut(rail_id=rail.id, label=rail.label, length_cm=rail.length_cm, segments=segs)


@api_router.post("/hang", response_model=OrderOut)
def hang(body: HangRequest, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, body.order_id)
    if not order:
        raise HTTPException(404, "工单不存在")
    if order.status not in ("ready", "overdue"):
        raise HTTPException(400, "工单状态不可上杆")
    rail_q = select(HangRail).where(HangRail.store_id == order.store_id)
    if body.rail_id:
        rail_q = rail_q.where(HangRail.id == body.rail_id)
    rails = db.scalars(rail_q.order_by(HangRail.id)).all()
    if not rails:
        raise HTTPException(404, "无可用挂杆")

    for rail in rails:
        active = db.scalars(
            select(RailPlacement).where(RailPlacement.rail_id == rail.id, RailPlacement.active == 1)
        ).all()
        occupied = [Segment(p.start_cm, p.end_cm) for p in active]
        place = first_fit(rail.length_cm, occupied, order.length_cm)
        if place is None:
            continue
        db.add(
            RailPlacement(
                rail_id=rail.id,
                order_id=order.id,
                start_cm=place.start_cm,
                end_cm=place.end_cm,
            )
        )
        order.status = "hung"
        order.hung_at = datetime.utcnow()
        db.commit()
        db.refresh(order)
        order.can_extend = _can_extend(db, order)
        return order

    raise HTTPException(409, "挂杆空间不足")


@api_router.post("/pickup", response_model=OrderOut)
def pickup(body: PickupRequest, db: Session = Depends(get_db)):
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == body.ticket_code))
    if not order:
        raise HTTPException(404, "取件码无效")
    if order.status != "hung":
        raise HTTPException(400, "工单未在挂杆上")
    placements = db.scalars(
        select(RailPlacement).where(RailPlacement.order_id == order.id, RailPlacement.active == 1)
    ).all()
    for p in placements:
        p.active = 0
    order.status = "picked"
    db.commit()
    db.refresh(order)
    order.can_extend = _can_extend(db, order)
    return order


@api_router.post("/extend", response_model=OrderOut)
def extend(body: ExtendRequest, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, body.order_id)
    if not order:
        raise HTTPException(404, "工单不存在")
    if not _can_extend(db, order):
        raise HTTPException(400, "当前状态不可延期（仅挂杆中、含逾期未取的工单可延期）")
    new_due = body.due_at
    if new_due.tzinfo is not None:
        new_due = new_due.astimezone(timezone.utc).replace(tzinfo=None)
    if new_due <= order.due_at:
        raise HTTPException(400, "新到期必须晚于原到期时间")
    if order.hung_at and new_due < order.hung_at:
        raise HTTPException(400, "新到期不得早于上杆时间")
    order.due_at = new_due
    if order.status == "overdue" and new_due > datetime.utcnow():
        order.status = "hung"
    db.commit()
    db.refresh(order)
    order.can_extend = _can_extend(db, order)
    return order


@api_router.post("/overdue/scan", response_model=list[OrderOut])
def overdue_scan(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    hung = db.scalars(select(WorkOrder).where(WorkOrder.status == "hung")).all()
    marked = []
    for o in hung:
        if o.due_at < now:
            o.status = "overdue"
            marked.append(o)
    ready = db.scalars(select(WorkOrder).where(WorkOrder.status == "ready")).all()
    for o in ready:
        if o.due_at < now:
            o.status = "overdue"
            marked.append(o)
    db.commit()
    return _attach_can_extend(db, marked)


@api_router.get("/overdue", response_model=list[OrderOut])
def overdue_list(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(WorkOrder).where(WorkOrder.status == "overdue").order_by(WorkOrder.due_at)
    ).all()
    return _attach_can_extend(db, rows)
