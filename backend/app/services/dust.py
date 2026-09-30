"""扬尘监测业务规则：待核、退回、覆盖、整批入账与统计都收在这里。"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from threading import RLock
from typing import Any

from app.store import store

POINTS_TABLE = "dust_points"
BATCHES_TABLE = "dust_batches"
REVIEWS_TABLE = "dust_reviews"
LEDGER_TABLE = "dust_ledger"

LOCK = RLock()

POINT_FIELDS = {
    "监测点位": ["监测点位", "点位", "点位编号", "point", "point_code", "point_id"],
    "时段": ["时段", "监测时段", "记录时段", "period", "time_period"],
    "读数": ["读数", "扬尘读数", "PM10读数", "pm10", "value", "reading"],
    "抑尘措施": ["抑尘措施", "措施状态", "防尘措施", "suppression", "suppression_measure", "measure"],
    "备注": ["备注", "管控备注", "说明", "remark", "note"],
    "抄录人": ["抄录人", "记录人", "recorder", "operator"],
}

DEFAULT_POINTS = [
    {
        "id": 1,
        "point_code": "DUST-01",
        "point_name": "堆场东入口",
        "min_value": 0,
        "max_value": 1000,
        "limit_value": 150,
        "pending": False,
        "abnormal": False,
    },
    {
        "id": 2,
        "point_code": "DUST-02",
        "point_name": "1号施工区",
        "min_value": 0,
        "max_value": 1000,
        "limit_value": 150,
        "pending": False,
        "abnormal": False,
    },
    {
        "id": 3,
        "point_code": "DUST-03",
        "point_name": "材料加工区",
        "min_value": 0,
        "max_value": 1000,
        "limit_value": 150,
        "pending": False,
        "abnormal": False,
    },
    {
        "id": 4,
        "point_code": "DUST-04",
        "point_name": "西侧围挡",
        "min_value": 0,
        "max_value": 1000,
        "limit_value": 150,
        "pending": False,
        "abnormal": False,
    },
]

SEED_LEDGER = [
    {
        "id": 1,
        "batch_id": "SEED",
        "source_row": 1,
        "监测点位": "DUST-01",
        "点位名称": "堆场东入口",
        "时段": "2026-09-01 08:00",
        "读数": 96.0,
        "单位": "μg/m³",
        "抑尘措施": "已喷淋",
        "备注": "",
        "抄录人": "张工",
        "超标": False,
        "措施未跟进": False,
        "覆盖来源": "",
        "入账时间": "2026-09-01 09:00",
        "status": "已入账",
        "pending": False,
        "abnormal": False,
    },
    {
        "id": 2,
        "batch_id": "SEED",
        "source_row": 2,
        "监测点位": "DUST-02",
        "点位名称": "1号施工区",
        "时段": "2026-09-01 08:00",
        "读数": 168.0,
        "单位": "μg/m³",
        "抑尘措施": "已喷淋",
        "备注": "超标已复核，已加密喷淋",
        "抄录人": "李工",
        "超标": True,
        "措施未跟进": False,
        "覆盖来源": "",
        "入账时间": "2026-09-01 09:05",
        "status": "已入账",
        "pending": False,
        "abnormal": True,
    },
    {
        "id": 3,
        "batch_id": "SEED",
        "source_row": 3,
        "监测点位": "DUST-03",
        "点位名称": "材料加工区",
        "时段": "2026-09-02 10:00",
        "读数": 182.0,
        "单位": "μg/m³",
        "抑尘措施": "未喷淋",
        "备注": "抑尘措施未跟进",
        "抄录人": "王工",
        "超标": True,
        "措施未跟进": True,
        "覆盖来源": "",
        "入账时间": "2026-09-02 11:00",
        "status": "已入账",
        "pending": False,
        "abnormal": True,
    },
]


def ensure_dust_tables() -> None:
    """初始化扬尘配置和示例台账；内存仓库重启后仍可直接演示。"""
    if not store.rows(POINTS_TABLE):
        store.rows(POINTS_TABLE).extend(dict(row) for row in DEFAULT_POINTS)
    if not store.rows(LEDGER_TABLE):
        store.rows(LEDGER_TABLE).extend(dict(row) for row in SEED_LEDGER)
    store.rows(BATCHES_TABLE)
    store.rows(REVIEWS_TABLE)
    for row in store.rows(LEDGER_TABLE):
        if not row.get("fingerprint"):
            measure, _ = _normalize_measure(row.get("抑尘措施"))
            reading = row.get("读数")
            reading_text = f"{float(reading):g}" if reading is not None else ""
            row["fingerprint"] = "|".join(
                [
                    str(row.get("监测点位", "")).upper(),
                    str(row.get("时段", "")),
                    reading_text,
                    measure,
                    str(row.get("备注", "")),
                    str(row.get("抄录人", "")),
                ]
            )


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_measure(value: Any) -> tuple[str, bool]:
    text = _clean(value)
    if not text:
        return "未填写", False
    done_words = {"已喷淋", "已开启喷淋", "已覆盖", "已冲洗", "已雾炮", "已落实", "已跟进", "正常", "yes", "y", "true", "1"}
    pending_words = {"未喷淋", "未开启喷淋", "未覆盖", "未冲洗", "未雾炮", "未落实", "未跟进", "无", "no", "n", "false", "0"}
    if text in done_words:
        return "已喷淋", True
    if text in pending_words:
        return "未喷淋", False
    return text, text.startswith("已")


def _parse_reading(value: Any) -> tuple[float | None, str]:
    text = _clean(value)
    if not text:
        return None, "读数空缺"
    try:
        number = float(text)
    except ValueError:
        return None, f"读数不是数字：{text}"
    if number != number or number in (float("inf"), float("-inf")):
        return None, "读数不是有效数字"
    return number, ""


def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for canonical, aliases in POINT_FIELDS.items():
        for alias in aliases:
            if alias in raw:
                normalized[canonical] = raw[alias]
                break
        normalized.setdefault(canonical, "")
    return normalized


def _point_map() -> dict[str, dict[str, Any]]:
    return {str(point["point_code"]).upper(): point for point in store.rows(POINTS_TABLE)}


def _existing_fingerprints() -> set[str]:
    fingerprints: set[str] = set()
    for row in store.rows(LEDGER_TABLE):
        fingerprints.add(str(row.get("fingerprint") or ""))
    for row in store.rows(REVIEWS_TABLE):
        if row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}:
            fingerprints.add(str(row.get("fingerprint") or ""))
    fingerprints.discard("")
    return fingerprints


def _next_id(table: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1


def _refresh_batch(batch_id: str) -> dict[str, Any]:
    batch = next(row for row in store.rows(BATCHES_TABLE) if row.get("batch_id") == batch_id)
    review_rows = [row for row in store.rows(REVIEWS_TABLE) if row.get("batch_id") == batch_id]
    active_rows = [row for row in review_rows if row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}]
    rejected = [row for row in active_rows if row.get("状态") == "退回"]
    verified = [row for row in active_rows if row.get("状态") in {"已核", "已入账"}]
    pending = [row for row in active_rows if row.get("状态") == "待核"]
    over_limit = sum(1 for row in active_rows if row.get("超标"))
    measure_gap = sum(1 for row in active_rows if row.get("措施未跟进"))
    if batch.get("状态") == "已入账":
        status = "已入账"
    elif not active_rows:
        status = "已覆盖"
    elif rejected:
        status = "有退回"
    elif pending:
        status = "待核"
    else:
        status = "待入账"
    batch.update(
        {
            "总行数": len(review_rows),
            "有效行数": len(active_rows),
            "待核条数": len(pending),
            "退回条数": len(rejected),
            "已核条数": len(verified),
            "超标条数": over_limit,
            "措施未跟进条数": measure_gap,
            "状态": status,
            "可入账": status == "待入账",
        }
    )
    return batch


def _build_fingerprint(
    point_code: str,
    period: str,
    reading: float | None,
    measure: str,
    remark: str,
    recorder: str,
) -> str:
    return "|".join(
        [
            point_code,
            period,
            f"{reading:g}" if reading is not None else "",
            measure,
            remark,
            recorder,
        ]
    )


def _make_review_row(batch_id: str, source_row: int, raw: dict[str, Any], row_id: int) -> dict[str, Any]:
    normalized = _normalize_row(raw)
    point_code = _clean(normalized.get("监测点位")).upper()
    period = _clean(normalized.get("时段"))
    reading, parse_error = _parse_reading(normalized.get("读数"))
    point = _point_map().get(point_code)
    reasons: list[str] = []
    if not point_code:
        reasons.append("监测点位空缺")
    elif point is None:
        reasons.append(f"未知监测点位：{point_code}")
    if not period:
        reasons.append("时段空缺")
    if parse_error:
        reasons.append(parse_error)

    if reading is not None and point is not None:
        minimum = float(point["min_value"])
        maximum = float(point["max_value"])
        if reading < minimum or reading > maximum:
            reasons.append(f"读数超出量程 {minimum:g}~{maximum:g}")

    measure, measure_done = _normalize_measure(normalized.get("抑尘措施"))
    remark = _clean(normalized.get("备注"))
    over_limit = bool(reading is not None and point is not None and reading > float(point["limit_value"]))
    measure_gap = over_limit and not measure_done
    if measure_gap:
        measure_note = "抑尘措施未跟进"
        remark = f"{remark}；{measure_note}" if remark else measure_note

    valid = not reasons
    fingerprint = _build_fingerprint(
        point_code, period, reading, measure, remark, _clean(normalized.get("抄录人"))
    )
    return {
        "id": row_id,
        "batch_id": batch_id,
        "source_row": source_row,
        "监测点位": point_code,
        "点位名称": point.get("point_name", "") if point else "",
        "时段": period,
        "读数": reading,
        "单位": "μg/m³",
        "量程下限": point.get("min_value") if point else "",
        "量程上限": point.get("max_value") if point else "",
        "超标限值": point.get("limit_value") if point else "",
        "抑尘措施": measure,
        "备注": remark,
        "抄录人": _clean(normalized.get("抄录人")),
        "超标": over_limit,
        "措施未跟进": measure_gap,
        "状态": "待核" if valid else "退回",
        "退回原因": "；".join(reasons),
        "覆盖说明": "",
        "覆盖来源": "",
        "fingerprint": fingerprint,
    }


class DustService:
    def list_points(self) -> list[dict[str, Any]]:
        with LOCK:
            ensure_dust_tables()
            points = []
            for point in store.rows(POINTS_TABLE):
                code = str(point["point_code"]).upper()
                ledger = [row for row in store.rows(LEDGER_TABLE) if row.get("监测点位") == code]
                review_rows = [
                    row
                    for row in store.rows(REVIEWS_TABLE)
                    if row.get("监测点位") == code and row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}
                ]
                item = dict(point)
                item["台账条数"] = len(ledger)
                item["超标条数"] = sum(1 for row in ledger if row.get("超标"))
                item["待核条数"] = sum(1 for row in review_rows if row.get("状态") in {"待核", "退回"})
                item["措施未跟进条数"] = sum(1 for row in ledger if row.get("措施未跟进"))
                item["abnormal"] = item["超标条数"] > 0
                item["pending"] = item["待核条数"] > 0
                point.update({key: item[key] for key in (
                    "台账条数", "超标条数", "待核条数", "措施未跟进条数", "abnormal", "pending"
                )})
                points.append(item)
            return points

    def parse_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        values = payload.get("values")
        if isinstance(values, list):
            raw_rows = values
        elif isinstance(values, dict):
            raw_rows = values.get("rows") or values.get("items") or []
        else:
            raw_rows = payload.get("rows") or payload.get("items") or []

        if isinstance(raw_rows, str):
            text = raw_rows.strip()
            if not text:
                return []
            if text.startswith("["):
                import json

                raw_rows = json.loads(text)
            else:
                reader = csv.DictReader(io.StringIO(text))
                raw_rows = list(reader)
        if not isinstance(raw_rows, list):
            return []
        return [row for row in raw_rows if isinstance(row, dict)]

    def import_rows(self, payload: dict[str, Any]) -> dict[str, Any]:
        with LOCK:
            ensure_dust_tables()
            raw_rows = self.parse_rows(payload)
            if not raw_rows:
                return {"ok": False, "message": "没有可整理的读数，请先填写或粘贴待导入记录", "batch_id": None}

            now = datetime.now()
            batch_serial = _next_id(BATCHES_TABLE)
            batch_id = f"DUST-{now.strftime('%Y%m%d%H%M%S')}-{batch_serial:03d}"
            active_reviews = [
                row
                for row in store.rows(REVIEWS_TABLE)
                if row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}
            ]
            active_by_key = {
                (str(row.get("监测点位") or "").upper(), str(row.get("时段") or "")): row
                for row in active_reviews
            }
            existing_fingerprints = _existing_fingerprints()
            prepared: list[dict[str, Any]] = []
            next_review_id = _next_id(REVIEWS_TABLE)

            for index, raw in enumerate(raw_rows, start=1):
                row_id = next_review_id
                next_review_id += 1
                review = _make_review_row(batch_id, index, raw, row_id)
                fingerprint = str(review.get("fingerprint") or "")
                if fingerprint and fingerprint in existing_fingerprints:
                    review["状态"] = "重复导入"
                    review["退回原因"] = "同一份读数重复导入，只保留原记录"
                prepared.append(review)

            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            latest_fingerprints: set[str] = set()
            for review in reversed(prepared):
                if review["状态"] == "重复导入":
                    continue
                fingerprint = str(review.get("fingerprint") or "")
                if fingerprint and fingerprint in latest_fingerprints:
                    review["状态"] = "同批重复"
                    review["退回原因"] = "同一份读数在本批重复导入，只保留最后一条"
                else:
                    latest_fingerprints.add(fingerprint)
                key = (str(review.get("监测点位") or "").upper(), str(review.get("时段") or ""))
                groups.setdefault(key, []).append(review)

            for key, group in groups.items():
                group.reverse()
                if len(group) == 1:
                    continue
                winner = group[-1]
                duplicate_sources = [row["source_row"] for row in group[:-1] if row["状态"] == "同批重复"]
                covered_sources = [row["source_row"] for row in group[:-1] if row["状态"] != "同批重复"]
                covered_ids = [row["id"] for row in group[:-1]]
                for row in group[:-1]:
                    if row["状态"] != "同批重复":
                        row["状态"] = "已覆盖"
                        row["退回原因"] = "同一点位同一时段重复抄录，以最后一次抄录为准"
                    row["覆盖说明"] = f"被第 {winner['source_row']} 行覆盖"
                notes = []
                if duplicate_sources:
                    notes.append(f"同批重复第 {'、'.join(str(number) for number in duplicate_sources)} 行")
                if covered_sources:
                    notes.append(f"覆盖第 {'、'.join(str(number) for number in covered_sources)} 行")
                winner["覆盖说明"] = f"{'；'.join(notes)}（待核ID {'、'.join(str(identifier) for identifier in covered_ids)}）"

            for review in prepared:
                if review["状态"] in {"重复导入", "同批重复", "已覆盖"}:
                    continue
                key = (str(review.get("监测点位") or "").upper(), str(review.get("时段") or ""))
                previous = active_by_key.get(key)
                if previous is not None and previous["id"] != review["id"]:
                    previous["状态"] = "已覆盖"
                    previous["退回原因"] = "同一点位同一时段在新批次中重新抄录，以最后一次抄录为准"
                    previous["覆盖说明"] = f"被批次 {batch_id} 第 {review['source_row']} 行覆盖"
                    review["覆盖说明"] = (
                        f"{review['覆盖说明']}；" if review["覆盖说明"] else ""
                    ) + f"覆盖待核ID {previous['id']}"
                    active_by_key[key] = review
                    old_batch_id = previous.get("batch_id")
                    if old_batch_id:
                        _refresh_batch(str(old_batch_id))
                else:
                    active_by_key[key] = review

            store.rows(REVIEWS_TABLE).extend(prepared)
            batch = {
                "id": batch_serial,
                "batch_id": batch_id,
                "导入时间": now.strftime("%Y-%m-%d %H:%M:%S"),
                "状态": "待核",
                "总行数": len(prepared),
                "有效行数": 0,
                "待核条数": 0,
                "退回条数": 0,
                "已核条数": 0,
                "超标条数": 0,
                "措施未跟进条数": 0,
                "可入账": False,
            }
            store.rows(BATCHES_TABLE).append(batch)
            _refresh_batch(batch_id)
            for old_batch in store.rows(BATCHES_TABLE):
                if old_batch.get("batch_id") != batch_id and old_batch.get("状态") != "已入账":
                    _refresh_batch(str(old_batch["batch_id"]))

            duplicate_count = sum(1 for row in prepared if row["状态"] == "重复导入")
            same_batch_duplicate_count = sum(1 for row in prepared if row["状态"] == "同批重复")
            covered_count = sum(1 for row in prepared if row["状态"] == "已覆盖")
            return {
                "ok": True,
                "message": f"已整理 {len(prepared)} 行，重复导入 {duplicate_count + same_batch_duplicate_count} 行，覆盖 {covered_count} 行",
                "batch_id": batch_id,
                "total": len(prepared),
                "duplicate_count": duplicate_count + same_batch_duplicate_count,
                "cross_batch_duplicate_count": duplicate_count,
                "same_batch_duplicate_count": same_batch_duplicate_count,
                "covered_count": covered_count,
                "items": prepared,
            }

    def list_batches(self) -> list[dict[str, Any]]:
        with LOCK:
            ensure_dust_tables()
            return [_refresh_batch(str(row["batch_id"])) for row in store.rows(BATCHES_TABLE)]

    def list_reviews(
        self,
        *,
        batch_id: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        with LOCK:
            ensure_dust_tables()
            rows = store.rows(REVIEWS_TABLE)
            if batch_id:
                rows = [row for row in rows if row.get("batch_id") == batch_id]
            if status:
                rows = [row for row in rows if row.get("状态") == status]
            if keyword:
                word = keyword.strip()
                rows = [
                    row
                    for row in rows
                    if word in str(row.get("监测点位", ""))
                    or word in str(row.get("时段", ""))
                    or word in str(row.get("备注", ""))
                ]
            rows = sorted(rows, key=lambda row: (str(row.get("batch_id")), int(row.get("source_row", 0))))
            total = len(rows)
            start = max(page - 1, 0) * size
            return rows[start:start + size], total

    def verify_row(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        with LOCK:
            entry = store.find(REVIEWS_TABLE, entry_id)
            if entry is None:
                return None, f"待核记录 {entry_id} 不存在"
            batch = next((row for row in store.rows(BATCHES_TABLE) if row.get("batch_id") == entry.get("batch_id")), None)
            if batch and batch.get("状态") == "已入账":
                return None, "该批次已入账，不能再修改待核表"
            if action == "修正":
                values = values or {}
                if "读数" in values:
                    reading, error = _parse_reading(values.get("读数"))
                    if error:
                        return None, error
                    point = _point_map().get(str(entry.get("监测点位") or "").upper())
                    if point and (reading is None or reading < float(point["min_value"]) or reading > float(point["max_value"])):
                        return None, "修正后的读数仍超出量程"
                    entry["读数"] = reading
                    entry["超标"] = bool(reading is not None and point and reading > float(point["limit_value"]))
                if "抑尘措施" in values:
                    measure, _ = _normalize_measure(values.get("抑尘措施"))
                    entry["抑尘措施"] = measure
                if "备注" in values:
                    entry["备注"] = _clean(values.get("备注"))
                over_limit = bool(entry.get("超标"))
                _, measure_done = _normalize_measure(entry.get("抑尘措施"))
                entry["措施未跟进"] = over_limit and not measure_done
                if entry["措施未跟进"] and "抑尘措施未跟进" not in str(entry.get("备注", "")):
                    entry["备注"] = (str(entry.get("备注") or "") + "；抑尘措施未跟进").strip("；")
                fingerprint = _build_fingerprint(
                    str(entry.get("监测点位") or ""),
                    str(entry.get("时段") or ""),
                    entry.get("读数"),
                    str(entry.get("抑尘措施") or ""),
                    str(entry.get("备注") or ""),
                    str(entry.get("抄录人") or ""),
                )
                duplicate = any(
                    str(row.get("fingerprint") or "") == fingerprint
                    for row in store.rows(LEDGER_TABLE)
                ) or any(
                    row["id"] != entry["id"]
                    and row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}
                    and str(row.get("fingerprint") or "") == fingerprint
                    for row in store.rows(REVIEWS_TABLE)
                )
                if duplicate:
                    return None, "修正后的读数与已保留记录完全相同，请按重复抄录处理"
                entry["fingerprint"] = fingerprint
                entry["状态"] = "待核"
                entry["退回原因"] = ""
                _refresh_batch(str(entry["batch_id"]))
                return entry, "待核记录已修正，请重新核验"
            if action == "通过":
                if entry.get("状态") == "退回":
                    return None, "退回记录需先修正后才能通过"
                if entry.get("状态") in {"已覆盖", "同批重复", "重复导入"}:
                    return None, "重复或被覆盖的记录不能入账"
                entry["状态"] = "已核"
                _refresh_batch(str(entry["batch_id"]))
                return entry, "待核记录已通过"
            if action == "退回":
                reason = _clean((values or {}).get("reason") or (values or {}).get("退回原因"))
                entry["状态"] = "退回"
                entry["退回原因"] = reason or "人工核验退回"
                _refresh_batch(str(entry["batch_id"]))
                return entry, "待核记录已退回"
            return None, f"动作「{action}」不属于扬尘待核可执行范围"

    def verify_batch(self, batch_id: str) -> tuple[dict[str, Any] | None, str]:
        with LOCK:
            batch = next((row for row in store.rows(BATCHES_TABLE) if row.get("batch_id") == batch_id), None)
            if batch is None:
                return None, f"批次 {batch_id} 不存在"
            if batch.get("状态") == "已入账":
                return None, "该批次已经入账"
            rows = [row for row in store.rows(REVIEWS_TABLE) if row.get("batch_id") == batch_id]
            active = [row for row in rows if row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}]
            rejected = [row for row in active if row.get("状态") == "退回"]
            if rejected:
                numbers = "、".join(str(row["id"]) for row in rejected)
                return None, f"待核表未通过：第 {numbers} 条需退回修正后才能入账"
            for row in active:
                if row.get("状态") == "待核":
                    row["状态"] = "已核"
            batch = _refresh_batch(batch_id)
            return batch, f"批次 {batch_id} 已全部核验通过，可以入账"

    def commit_batch(self, batch_id: str) -> tuple[dict[str, Any] | None, str]:
        with LOCK:
            batch = next((row for row in store.rows(BATCHES_TABLE) if row.get("batch_id") == batch_id), None)
            if batch is None:
                return None, f"批次 {batch_id} 不存在"
            if batch.get("状态") == "已入账":
                return None, "该批次已经入账"
            rows = [row for row in store.rows(REVIEWS_TABLE) if row.get("batch_id") == batch_id]
            active = [row for row in rows if row.get("状态") not in {"已覆盖", "同批重复", "重复导入"}]
            rejected = [row for row in active if row.get("状态") != "已核"]
            if rejected:
                numbers = "、".join(str(row["id"]) for row in rejected)
                return None, f"待核表没过，不能导入台账：第 {numbers} 条尚未通过"
            if not active:
                return None, "该批次没有可入账的有效记录"

            snapshots = {
                BATCHES_TABLE: [dict(row) for row in store.rows(BATCHES_TABLE)],
                REVIEWS_TABLE: [dict(row) for row in store.rows(REVIEWS_TABLE)],
                LEDGER_TABLE: [dict(row) for row in store.rows(LEDGER_TABLE)],
            }
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for row in sorted(active, key=lambda item: int(item.get("source_row", 0))):
                    ledger_id = _next_id(LEDGER_TABLE)
                    entry = {
                        "id": ledger_id,
                        "batch_id": batch_id,
                        "source_row": row.get("source_row"),
                        "监测点位": row.get("监测点位"),
                        "点位名称": row.get("点位名称"),
                        "时段": row.get("时段"),
                        "读数": row.get("读数"),
                        "单位": row.get("单位"),
                        "抑尘措施": row.get("抑尘措施"),
                        "备注": row.get("备注"),
                        "抄录人": row.get("抄录人"),
                        "超标": row.get("超标"),
                        "措施未跟进": row.get("措施未跟进"),
                        "覆盖来源": row.get("覆盖说明", ""),
                        "fingerprint": row.get("fingerprint"),
                        "入账时间": now,
                        "status": "已入账",
                        "pending": False,
                        "abnormal": bool(row.get("超标")),
                    }
                    store.rows(LEDGER_TABLE).append(entry)
                    row["状态"] = "已入账"
                    row["入账台账ID"] = ledger_id
                batch["状态"] = "已入账"
                batch["入账时间"] = now
                _refresh_batch(batch_id)
                self.list_points()
                return _refresh_batch(batch_id), f"批次 {batch_id} 的 {len(active)} 条读数已一次性入账"
            except Exception:
                store.rows(BATCHES_TABLE)[:] = snapshots[BATCHES_TABLE]
                store.rows(REVIEWS_TABLE)[:] = snapshots[REVIEWS_TABLE]
                store.rows(LEDGER_TABLE)[:] = snapshots[LEDGER_TABLE]
                raise

    def list_ledger(
        self,
        *,
        month: str | None = None,
        point: str | None = None,
        only_over_limit: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        with LOCK:
            ensure_dust_tables()
            rows = list(store.rows(LEDGER_TABLE))
            if month:
                month = month.strip()
                rows = [row for row in rows if str(row.get("时段", "")).startswith(month)]
            if point:
                word = point.strip().upper()
                rows = [row for row in rows if word in str(row.get("监测点位", "")).upper()]
            if only_over_limit:
                rows = [row for row in rows if row.get("超标")]
            rows = sorted(rows, key=lambda row: (str(row.get("时段")), int(row.get("id", 0))))
            total = len(rows)
            start = max(page - 1, 0) * size
            return rows[start:start + size], total

    def monthly_report(self, month: str) -> dict[str, Any]:
        with LOCK:
            items, total = self.list_ledger(month=month, page=1, size=10000)
            over_limit = sum(1 for row in items if row.get("超标"))
            measure_gap = sum(1 for row in items if row.get("措施未跟进"))
            values = [float(row["读数"]) for row in items if row.get("读数") is not None]
            return {
                "month": month,
                "rows": items,
                "items": items,
                "total": total,
                "report_rows": total,
                "超标条数": over_limit,
                "措施未跟进条数": measure_gap,
                "平均读数": round(sum(values) / len(values), 2) if values else None,
            }


dust_service = DustService()
