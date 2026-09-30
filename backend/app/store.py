"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS

POINTS_TABLE = "dust_points"


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def ensure_dust_tables(self) -> None:
        """懒加载扬尘工作流数据，避免 store 与业务服务在模块导入期形成循环依赖。"""
        if POINTS_TABLE in self._tables:
            return
        from app.services.dust import dust_service, ensure_dust_tables

        ensure_dust_tables()
        dust_service.list_points()

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        self.ensure_dust_tables()
        modules: list[dict[str, object]] = []
        # 扬尘的台账、批次和待核行属于内部工作流数据；全局总览只汇总点位卡片。
        overview_tables = {
            name for name in self._tables
            if not name.startswith("dust_") or name == "dust_points"
        }
        for name in self.module_names():
            if name not in overview_tables:
                continue
            rows = self.rows(name)
            display_name = "扬尘监测" if name == "dust_points" else name
            modules.append({
                "name": display_name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
