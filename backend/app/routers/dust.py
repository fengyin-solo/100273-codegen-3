"""扬尘监测接口：先核后入。

- POST /import          一份抄表读数整理成待核批次（量程比对、重复归并同时完成）
- GET  /batches、/batches/{id}   批次与待核表
- POST /batches/{id}/verify      整表复核
- POST /batches/{id}/post        待核表通过后一次性入账（原子，不留半批）
- POST /batches/{id}/discard     整份退回废弃
- GET  /ledger、/monthly-report  台账与月报（同一数据源，行数一致）
- GET  /points                   点位总览（超标条数随入账更新）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, DustImportPayload, PageResult
from app.services.dust import DustService

router = APIRouter(prefix="/api/dust", tags=["扬尘监测"])

service = DustService()


@router.get("/points")
def list_points() -> dict[str, object]:
    """点位总览：超标条数实时汇总台账。"""
    points = service.list_points()
    return {
        "total": len(points),
        "exceed_total": sum(int(point["超标条数"]) for point in points),
        "items": points,
    }


@router.post("/import", response_model=ActionResult)
def import_readings(payload: DustImportPayload) -> ActionResult:
    """把抄表读数整理为待核批次；空缺/超量程行直接标退回，重复读数只留一条。"""
    rows = [row.model_dump() for row in payload.rows]
    batch, message = service.import_readings(rows)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/batches")
def list_batches() -> dict[str, object]:
    """导入批次列表（含通过/退回计数），供选择待核批次。"""
    items = service.list_batches()
    return {"total": len(items), "items": items}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, object]:
    """读取一份待核表：每行的退回原因、覆盖说明、重复忽略都在这里。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
    return batch


@router.post("/batches/{batch_id}/verify", response_model=ActionResult)
def verify_batch(batch_id: int) -> ActionResult:
    """整表复核：按点位当前量程重跑逐条比对，给出能否入账的结论。"""
    batch, message = service.verify_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=bool(batch.get("can_post")), message=message, entry=batch)


@router.post("/batches/{batch_id}/post", response_model=ActionResult)
def post_batch(batch_id: int) -> ActionResult:
    """待核表全部通过后一次性入账；仍有退回行则整批拦下，台账不留半批。"""
    batch, message = service.post_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/discard", response_model=ActionResult)
def discard_batch(batch_id: int) -> ActionResult:
    """整份退回：废弃无法补齐的待核批次，读数不进台账。"""
    batch, message = service.discard_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    point_code: str | None = Query(default=None, description="按点位编号过滤"),
    month: str | None = Query(default=None, description="按月份过滤，如 2026-09"),
    only_exceed: bool = Query(default=False, description="只看超标入账行"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """扬尘台账：月报页与页面表格共用这一份查询结果。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.ledger(
        point_code=point_code, month=month, only_exceed=only_exceed, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/monthly-report")
def monthly_report(month: str = Query(description="报表月份，格式 YYYY-MM")) -> dict[str, object]:
    """月报：明细行数 total 与同条件下台账页面行数完全一致。"""
    return service.monthly_report(month)
