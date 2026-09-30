"""扬尘监测业务规则：先核后入。

流程固定为：抄表读数导入「待核表」→ 逐条与点位量程比对（超量程/空缺退回）→
同点位同时段重复抄录以最后一次为准并注明覆盖行 → 完全重复读数只留一条 →
整份待核表全部通过后才允许一次性入账，不允许半批落入台账。

口径约定（总览超标条数、月报行数都从这里出数）：
- 「超标」指读数超过点位预警值（管控口径）；超出仪表量程属于录入质量问题，退回不入账。
- 点位总览与月报全部实时汇总台账，入账后数字随之更新，不存在第二份统计来源。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

P_POINT = "dust_points"
P_BATCH = "dust_batches"
P_READING = "dust_readings"
P_LEDGER = "dust_ledger"

ROW_PASS = "通过"
ROW_REJECT = "退回"
ROW_DUP = "重复忽略"
BATCH_PENDING = "待核"
BATCH_POSTED = "已入账"
BATCH_DISCARDED = "已废弃"

ACTIVE_BATCH_STATES = {BATCH_PENDING, BATCH_POSTED}

# 抑尘措施明确填成这些字样时，判定为「没跟上」，只在表里单独备注，不拦截核验。
MEASURE_LAGGING = {"未落实", "未采取", "未跟上", "无措施", "无", "未喷淋", "未覆盖"}


class DustService:
    # ------------------------------------------------------------------ 点位总览
    def list_points(self) -> list[dict[str, Any]]:
        """点位总览：超标条数/入账条数实时从台账汇总，入账后自动随之更新。"""
        ledger = store.rows(P_LEDGER)
        points = [dict(point) for point in store.rows(P_POINT)]
        for point in points:
            code = point["点位编号"]
            own = [row for row in ledger if row.get("点位编号") == code]
            point["入账条数"] = len(own)
            point["超标条数"] = sum(1 for row in own if row.get("是否超标"))
        return points

    # ------------------------------------------------------------------ 读数导入
    def import_readings(
        self, raw_rows: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str]:
        """把一份抄表读数整理成待核批次，导入时即完成逐条核验与重复归并。"""
        if not raw_rows:
            return None, "导入内容为空，没有可整理的读数"

        points = {point["点位编号"]: point for point in store.rows(P_POINT)}
        batches = store.rows(P_BATCH)
        readings = store.rows(P_READING)

        batch_id = self._next_id(P_BATCH)
        batch = {
            "id": batch_id,
            "批次号": f"YC-{datetime.now():%Y%m%d}-{batch_id:03d}",
            "状态": BATCH_PENDING,
            "导入时间": f"{datetime.now():%Y-%m-%d %H:%M}",
            "入账时间": None,
            "原始行数": len(raw_rows),
            "通过数": 0,
            "退回数": 0,
            "重复忽略数": 0,
        }

        # 第一遍：按点位+时段分组，保留每组最后一次抄录。
        groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
        for line, raw in enumerate(raw_rows, start=1):
            code = str(raw.get("point_code") or "").strip()
            period = str(raw.get("period") or "").strip()
            groups.setdefault((code, period), []).append((line, raw))

        known_fingerprints = self._active_fingerprints(
            exclude_batch_id=None, readings=readings, batches=batches
        )
        stored: list[dict[str, Any]] = []
        for (code, period), group in groups.items():
            last_line, last_raw = group[-1]
            cover_note = ""
            if len(group) > 1:
                earlier = "、".join(f"第{line}行" for line, _ in group[:-1])
                values = {
                    (str(r.get("pm10") or "").strip(), str(r.get("pm25") or "").strip())
                    for _, r in group
                }
                if len(values) == 1:
                    cover_note = (
                        f"{earlier}与第{last_line}行为同一份读数，重复抄录只保留一条"
                        f"（保留第{last_line}行）"
                    )
                else:
                    cover_note = (
                        f"同一点位同一时段重复抄录，以最后一次（第{last_line}行）为准，"
                        f"覆盖{earlier}"
                    )
            stored.append(
                self._build_reading(
                    batch_id=batch_id,
                    line_no=last_line,
                    point_lookup=points,
                    code=code,
                    period=period,
                    raw=last_raw,
                    cover_note=cover_note,
                    known_fingerprints=known_fingerprints,
                )
            )

        # 本批保留下来的读数也登记指纹，避免同批后续再撞。
        for row in stored:
            if row["审核状态"] != ROW_DUP and row.get("指纹"):
                known_fingerprints[row["指纹"]] = (batch["批次号"], row["行号"])

        batch["通过数"] = sum(1 for row in stored if row["审核状态"] == ROW_PASS)
        batch["退回数"] = sum(1 for row in stored if row["审核状态"] == ROW_REJECT)
        batch["重复忽略数"] = sum(1 for row in stored if row["审核状态"] == ROW_DUP)

        # 批次与其待核行在同一轮落库；内存仓库里也是先凑齐再挂表，不留半截批次。
        batches.append(batch)
        readings.extend(stored)

        message = (
            f"批次 {batch['批次号']} 已整理为待核表：原始 {batch['原始行数']} 行，"
            f"通过 {batch['通过数']} 行，退回 {batch['退回数']} 行，"
            f"完全重复忽略 {batch['重复忽略数']} 行"
        )
        if batch["退回数"]:
            message += "；存在退回行，整表核验未过，不能入账"
        return batch, message

    def _build_reading(
        self,
        *,
        batch_id: int,
        line_no: int,
        point_lookup: dict[str, dict[str, Any]],
        code: str,
        period: str,
        raw: dict[str, Any],
        cover_note: str,
        known_fingerprints: dict[str, tuple[str, int]],
    ) -> dict[str, Any]:
        pm10_raw = str(raw.get("pm10") or "").strip()
        pm25_raw = str(raw.get("pm25") or "").strip()
        measure = str(raw.get("measure") or "").strip()
        measure_note = str(raw.get("measure_note") or "").strip()
        point = point_lookup.get(code)

        problems, exceed_items, _, _ = self._evaluate(point, pm10_raw, pm25_raw)
        note_parts = []
        if measure in MEASURE_LAGGING:
            note_parts.append(f"抑尘措施未跟上（填报：{measure or '未填'}）")
        if measure_note:
            note_parts.append(measure_note)

        fingerprint = self._fingerprint(code, period, pm10_raw, pm25_raw)
        duplicate_of = ""
        if not problems and fingerprint and fingerprint in known_fingerprints:
            other_batch, other_line = known_fingerprints[fingerprint]
            duplicate_of = (
                f"与批次 {other_batch} 第{other_line}行读数完全一致，"
                "同一份读数重复导入只保留一条"
            )

        if duplicate_of:
            status = ROW_DUP
        elif problems:
            status = ROW_REJECT
        else:
            status = ROW_PASS

        return {
            "id": self._next_id(P_READING),
            "批次id": batch_id,
            "行号": line_no,
            "点位编号": code,
            "点位名称": point["点位名称"] if point else "—",
            "抄录时段": period,
            "PM10读数": pm10_raw,
            "PM2.5读数": pm25_raw,
            "抑尘措施": measure or "—",
            "措施备注": "；".join(note_parts),
            "抄录人": str(raw.get("recorder") or "").strip() or "—",
            "审核状态": status,
            "退回原因": "；".join(problems),
            "覆盖说明": cover_note,
            "重复说明": duplicate_of,
            "是否超标": bool(exceed_items) and not problems,
            "超标项": "、".join(exceed_items),
            "指纹": fingerprint,
        }

    # ------------------------------------------------------------------ 批次核验/入账
    def list_batches(self) -> list[dict[str, Any]]:
        return [dict(batch) for batch in store.rows(P_BATCH)]

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self._find_batch(batch_id)
        if batch is None:
            return None
        rows = [
            dict(row)
            for row in store.rows(P_READING)
            if row.get("批次id") == batch_id
        ]
        rows.sort(key=lambda row: int(row.get("行号", 0)))
        result = dict(batch)
        result["rows"] = rows
        result["can_post"] = self._can_post(batch, rows)
        return result

    def verify_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """重新逐条核验：量程/空缺以点位当前配置为准，给出整表是否可入账的结论。"""
        batch = self._find_batch(batch_id)
        if batch is None:
            return None, f"批次 {batch_id} 不存在"
        if batch["状态"] != BATCH_PENDING:
            return None, f"批次 {batch['批次号']} 已{batch['状态']}，无需再核"

        points = {point["点位编号"]: point for point in store.rows(P_POINT)}
        rows = [
            row
            for row in store.rows(P_READING)
            if row.get("批次id") == batch_id and row["审核状态"] != ROW_DUP
        ]
        for row in rows:
            point = points.get(row["点位编号"])
            problems, exceed_items, _, _ = self._evaluate(
                point, str(row["PM10读数"]), str(row["PM2.5读数"])
            )
            row["退回原因"] = "；".join(problems)
            row["审核状态"] = ROW_REJECT if problems else ROW_PASS
            row["是否超标"] = bool(exceed_items) and not problems
            row["超标项"] = "、".join(exceed_items)

        batch["通过数"] = sum(1 for row in rows if row["审核状态"] == ROW_PASS)
        batch["退回数"] = sum(1 for row in rows if row["审核状态"] == ROW_REJECT)
        message = (
            f"批次 {batch['批次号']} 核验完成：通过 {batch['通过数']} 行，"
            f"退回 {batch['退回数']} 行，重复忽略 {batch['重复忽略数']} 行"
        )
        if batch["退回数"]:
            message += "；待核表未过，不许导入台账"
        else:
            message += "；待核表已过，可以入账"
        return self.get_batch(batch_id), message

    def post_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """整批一次性入账：先把全部台账行凑齐，再一次挂表，中途失败整批回滚。"""
        batch = self._find_batch(batch_id)
        if batch is None:
            return None, f"批次 {batch_id} 不存在"
        if batch["状态"] == BATCH_POSTED:
            return None, f"批次 {batch['批次号']} 已入账，请勿重复入账"
        if batch["状态"] == BATCH_DISCARDED:
            return None, f"批次 {batch['批次号']} 已废弃，不能入账"

        verified, message = self.verify_batch(batch_id)
        if verified is None:
            return None, message
        if not verified["can_post"]:
            return None, "待核表未过，不许导入台账（仍有退回行）"

        pass_rows = [
            row
            for row in verified["rows"]
            if row["审核状态"] == ROW_PASS
        ]
        points = {point["点位编号"]: point for point in store.rows(P_POINT)}
        ledger = store.rows(P_LEDGER)
        snapshot = len(ledger)
        next_id = self._next_id(P_LEDGER)
        try:
            new_entries: list[dict[str, Any]] = []
            posted_at = f"{datetime.now():%Y-%m-%d %H:%M}"
            for index, row in enumerate(pass_rows):
                _, _, pm10, pm25 = self._evaluate(
                    points.get(row["点位编号"]),
                    str(row["PM10读数"]),
                    str(row["PM2.5读数"]),
                )
                new_entries.append(
                    {
                        "id": next_id + index,
                        "点位编号": row["点位编号"],
                        "点位名称": row["点位名称"],
                        "抄录时段": row["抄录时段"],
                        "PM10读数": pm10,
                        "PM2.5读数": pm25,
                        "是否超标": bool(row["是否超标"]),
                        "超标项": row["超标项"],
                        "抑尘措施": row["抑尘措施"],
                        "措施备注": row["措施备注"],
                        "抄录人": row["抄录人"],
                        "入账批次": batch["批次号"],
                        "入账时间": posted_at,
                    }
                )
            # 关键：整批一次 extend 落完，任何一行没凑齐都不会走到这里。
            ledger.extend(new_entries)
            batch["状态"] = BATCH_POSTED
            batch["入账时间"] = posted_at
        except Exception:
            # 兜底回滚，保证台账不留半批。
            del ledger[snapshot:]
            raise

        return self.get_batch(batch_id), f"批次 {batch['批次号']} 已一次性入账 {len(pass_rows)} 条"

    def discard_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """整份退回：无法补齐的待核批次作废，不再占用待处理，但读数不进台账。"""
        batch = self._find_batch(batch_id)
        if batch is None:
            return None, f"批次 {batch_id} 不存在"
        if batch["状态"] != BATCH_PENDING:
            return None, f"批次 {batch['批次号']} 已{batch['状态']}，不能废弃"
        batch["状态"] = BATCH_DISCARDED
        return self.get_batch(batch_id), f"批次 {batch['批次号']} 已废弃，读数未入账"

    # ------------------------------------------------------------------ 台账与月报
    def ledger(
        self,
        *,
        point_code: str | None = None,
        month: str | None = None,
        only_exceed: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._ledger_rows(point_code=point_code, month=month, only_exceed=only_exceed)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def monthly_report(self, month: str) -> dict[str, Any]:
        """月报：明细行与汇总同一次查询产出，月报行数必然等于页面台账行数。"""
        rows = self._ledger_rows(month=month)
        summary: list[dict[str, Any]] = []
        points = {point["点位编号"]: point for point in store.rows(P_POINT)}
        for code in sorted(points):
            own = [row for row in rows if row["点位编号"] == code]
            pm10_values = [float(row["PM10读数"]) for row in own if row["PM10读数"] is not None]
            summary.append(
                {
                    "点位编号": code,
                    "点位名称": points[code]["点位名称"],
                    "入账条数": len(own),
                    "超标条数": sum(1 for row in own if row["是否超标"]),
                    "PM10平均": round(sum(pm10_values) / len(pm10_values), 1) if pm10_values else None,
                    "PM10最高": max(pm10_values) if pm10_values else None,
                }
            )
        return {
            "month": month,
            "items": rows,
            "total": len(rows),
            "exceed_total": sum(1 for row in rows if row["是否超标"]),
            "summary": summary,
        }

    # ------------------------------------------------------------------ 内部规则
    def _ledger_rows(
        self,
        *,
        point_code: str | None = None,
        month: str | None = None,
        only_exceed: bool = False,
    ) -> list[dict[str, Any]]:
        rows = [dict(row) for row in store.rows(P_LEDGER)]
        if point_code:
            rows = [row for row in rows if point_code in str(row.get("点位编号", ""))]
        if month:
            rows = [row for row in rows if str(row.get("抄录时段", "")).startswith(month)]
        if only_exceed:
            rows = [row for row in rows if row.get("是否超标")]
        rows.sort(key=lambda row: (str(row.get("抄录时段", "")), int(row.get("id", 0))))
        return rows

    def _evaluate(
        self, point: dict[str, Any] | None, pm10_raw: str, pm25_raw: str
    ) -> tuple[list[str], list[str], float | None, float | None]:
        """逐条比对：返回退回原因、超标项、解析后的两个读数。"""
        problems: list[str] = []
        exceed_items: list[str] = []

        if point is None:
            problems.append("点位编号不存在，无法核对量程")
            return problems, exceed_items, None, None

        pm10, pm10_err = self._as_number(pm10_raw, "PM10")
        pm25, pm25_err = self._as_number(pm25_raw, "PM2.5")
        if pm10_err:
            problems.append(pm10_err)
        if pm25_err:
            problems.append(pm25_err)

        if pm10 is not None and not (
            float(point["PM10量程下限"]) <= pm10 <= float(point["PM10量程上限"])
        ):
            problems.append(
                f"PM10读数{pm10:g}超出量程（{point['PM10量程下限']:g}~"
                f"{point['PM10量程上限']:g}）"
            )
        if pm25 is not None and not (
            float(point["PM2.5量程下限"]) <= pm25 <= float(point["PM2.5量程上限"])
        ):
            problems.append(
                f"PM2.5读数{pm25:g}超出量程（{point['PM2.5量程下限']:g}~"
                f"{point['PM2.5量程上限']:g}）"
            )

        # 量程之内再谈超标：超的是预警值，不退回，入账后计入点位超标条数。
        if pm10 is not None and pm10 > float(point["PM10预警值"]):
            exceed_items.append("PM10")
        if pm25 is not None and pm25 > float(point["PM2.5预警值"]):
            exceed_items.append("PM2.5")
        return problems, exceed_items, pm10, pm25

    @staticmethod
    def _as_number(raw: str, label: str) -> tuple[float | None, str | None]:
        value = raw.strip()
        if not value:
            return None, f"{label}读数空缺"
        try:
            return float(value), None
        except ValueError:
            return None, f"{label}读数无法识别：{value}"

    @staticmethod
    def _fingerprint(code: str, period: str, pm10_raw: str, pm25_raw: str) -> str:
        """同一份读数的判重指纹：点位+时段+两项读数，数值归一化后比较。"""
        def norm(raw: str) -> str:
            try:
                return f"{float(raw.strip()):g}"
            except ValueError:
                return raw.strip()

        return f"{code}|{period}|{norm(pm10_raw)}|{norm(pm25_raw)}"

    def _active_fingerprints(
        self,
        *,
        exclude_batch_id: int | None,
        readings: list[dict[str, Any]],
        batches: list[dict[str, Any]],
    ) -> dict[str, tuple[str, int]]:
        """已入账或在途批次中已保留读数的指纹，用于跨批次判重；废弃批次不参与。"""
        active_ids = {
            int(batch["id"])
            for batch in batches
            if batch["状态"] in ACTIVE_BATCH_STATES
            and int(batch["id"]) != (exclude_batch_id or -1)
        }
        fingerprints: dict[str, tuple[str, int]] = {}
        batch_no = {int(batch["id"]): batch["批次号"] for batch in batches}
        for row in readings:
            if int(row.get("批次id", 0)) not in active_ids:
                continue
            if row["审核状态"] == ROW_DUP or not row.get("指纹"):
                continue
            fingerprints[row["指纹"]] = (
                batch_no.get(int(row["批次id"]), "已入账批次"),
                int(row["行号"]),
            )
        return fingerprints

    def _find_batch(self, batch_id: int) -> dict[str, Any] | None:
        for batch in store.rows(P_BATCH):
            if int(batch.get("id", 0)) == batch_id:
                return batch
        return None

    @staticmethod
    def _can_post(batch: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
        """待核表没过不许导入台账：只要还存在退回行/没有通过行，就不能入账。"""
        if batch["状态"] != BATCH_PENDING:
            return False
        evaluated = [row for row in rows if row["审核状态"] != ROW_DUP]
        has_pass = any(row["审核状态"] == ROW_PASS for row in evaluated)
        has_reject = any(row["审核状态"] == ROW_REJECT for row in evaluated)
        return has_pass and not has_reject

    @staticmethod
    def _next_id(table: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1
