"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS

# 扬尘监测的内部底表（点位/批次/待核表/台账），不单独作为业务模块出现在总览。
DUST_TABLES = {"dust_points", "dust_batches", "dust_readings", "dust_ledger"}


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in DUST_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        modules.append(self._dust_overview())
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}

    def _dust_overview(self) -> dict[str, object]:
        """扬尘监测卡片：超标条数与点位总览、月报同口径，实时汇总台账。"""
        ledger = self.rows("dust_ledger")
        pending_batch_ids = {
            int(batch["id"])
            for batch in self.rows("dust_batches")
            if batch.get("状态") == "待核"
        }
        return {
            "name": "扬尘监测",
            # 已入账读数条数（月报行数即由此过滤月份而来）
            "created": len(ledger),
            # 待处理 = 待核批次里尚未结案（非完全重复忽略）的读数
            "pending": sum(
                1
                for row in self.rows("dust_readings")
                if int(row.get("批次id", 0)) in pending_batch_ids
                and row.get("审核状态") != "重复忽略"
            ),
            "abnormal": sum(1 for row in ledger if row.get("是否超标")),
        }


store = Store()
