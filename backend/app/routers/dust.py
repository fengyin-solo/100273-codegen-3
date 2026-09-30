"""扬尘监测接口：点位总览、待核表、核验入账、台账和月报。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, DustImportPayload, EntryPayload, PageResult
from app.services.dust import dust_service, ensure_dust_tables

router = APIRouter(prefix="/api/dust", tags=["扬尘监测"])

REVIEW_COLUMNS = [
    "监测点位", "点位名称", "时段", "读数", "单位", "量程下限", "量程上限",
    "超标限值", "抑尘措施", "备注", "抄录人", "超标", "措施未跟进", "状态",
    "退回原因", "覆盖说明", "source_row",
]
LEDGER_COLUMNS = [
    "监测点位", "点位名称", "时段", "读数", "单位", "抑尘措施", "备注",
    "抄录人", "超标", "措施未跟进", "覆盖来源", "batch_id", "入账时间",
]


@router.get("/points")
def list_points() -> dict[str, Any]:
    """点位总览：超标条数、待核条数和措施未跟进条数随入账结果同步更新。"""
    return {"items": dust_service.list_points(), "total": len(dust_service.list_points())}


@router.post("/imports", response_model=ActionResult)
def import_readings(payload: DustImportPayload) -> ActionResult:
    """把纸单读数整理成待核表；量程、空缺、重复、覆盖关系在服务层一次判定。"""
    result = dust_service.import_rows(payload.model_dump())
    return ActionResult(ok=bool(result.get("ok")), message=str(result.get("message")), entry=result)


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    """批次状态：只有退回清零、有效待核行全部通过时才允许入账。"""
    items = dust_service.list_batches()
    return {"items": items, "total": len(items)}


@router.get("/reviews", response_model=PageResult[dict])
def list_reviews(
    batch_id: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """读取待核表，支持按批次、状态和点位关键字筛选。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = dust_service.list_reviews(
        batch_id=batch_id, status=status, keyword=keyword, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/reviews/{entry_id}/actions", response_model=ActionResult)
def review_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条待核记录执行通过、退回或修正；已入账批次不允许再改。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = dust_service.verify_row(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/batches/{batch_id}/verify", response_model=ActionResult)
def verify_batch(batch_id: str) -> ActionResult:
    """整批核验：有任何退回或未核记录时，待核表均不算通过。"""
    batch, message = dust_service.verify_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/commit", response_model=ActionResult)
def commit_batch(batch_id: str) -> ActionResult:
    """整批入账：通过服务层事务一次落完，失败时不留半批台账。"""
    batch, message = dust_service.commit_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    month: str | None = None,
    point: str | None = None,
    only_over_limit: bool = False,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """扬尘台账：仅展示已通过整批核验并一次性入账的数据。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = dust_service.list_ledger(
        month=month, point=point, only_over_limit=only_over_limit, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/monthly-report")
def monthly_report(month: str = Query(..., description="月份格式 YYYY-MM")) -> dict[str, Any]:
    """月报行数与台账页面同口径计算，避免页面总数和报表行数不一致。"""
    if len(month) != 7 or month[4] != "-":
        raise HTTPException(status_code=400, detail="月份需使用 YYYY-MM 格式")
    return dust_service.monthly_report(month)


@router.get("/export")
def export_ledger(month: str | None = None) -> dict[str, Any]:
    """导出台账全量或指定月份数据。"""
    items, total = dust_service.list_ledger(month=month, page=1, size=10000)
    return {"module": "dust", "total": total, "items": items}


@router.get("/health-guard")
def dust_ready() -> dict[str, Any]:
    """轻量检查扬尘配置和示例数据是否已装载。"""
    ensure_dust_tables()
    return {"ok": True}
