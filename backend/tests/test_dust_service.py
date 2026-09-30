"""扬尘监测“先核后入”服务规则的标准库回归测试。"""
from __future__ import annotations

import unittest

from app.services.dust import (
    BATCHES_TABLE,
    DEFAULT_POINTS,
    LEDGER_TABLE,
    POINTS_TABLE,
    REVIEWS_TABLE,
    DustService,
)
from app.store import store


def reset_dust_tables() -> None:
    """每个用例直接重置内部扬尘表，避免模块初始化示例数据影响编号和统计。"""
    for table in (POINTS_TABLE, BATCHES_TABLE, REVIEWS_TABLE, LEDGER_TABLE):
        store._tables.pop(table, None)
        store.rows(table).clear()
    store.rows(POINTS_TABLE).extend(dict(row) for row in DEFAULT_POINTS)


class DustWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_dust_tables()
        store.rows(LEDGER_TABLE).extend(
            [
                {
                    "id": 1,
                    "监测点位": "DUST-01",
                    "时段": "2026-09-01 08:00",
                    "读数": 80.0,
                    "抑尘措施": "已喷淋",
                    "备注": "",
                    "抄录人": "测试员",
                    "超标": False,
                    "措施未跟进": False,
                    "fingerprint": "DUST-01|2026-09-01 08:00|80|已喷淋||测试员",
                }
            ]
        )
        self.service = DustService()
        self.rows = [
            {
                "监测点位": "DUST-01",
                "时段": "2026-09-10 08:00",
                "读数": "100",
                "抑尘措施": "已喷淋",
                "备注": "第一次",
                "抄录人": "张工",
            },
            {
                "监测点位": "DUST-01",
                "时段": "2026-09-10 08:00",
                "读数": "160",
                "抑尘措施": "未喷淋",
                "备注": "最后一次",
                "抄录人": "张工",
            },
            {
                "监测点位": "DUST-02",
                "时段": "2026-09-10 08:00",
                "读数": "",
                "抑尘措施": "未喷淋",
                "备注": "读数空缺",
                "抄录人": "李工",
            },
            {
                "监测点位": "DUST-03",
                "时段": "2026-09-10 08:00",
                "读数": "1200",
                "抑尘措施": "已喷淋",
                "备注": "超出量程",
                "抄录人": "王工",
            },
        ]

    def _import_and_commit(self) -> tuple[str, dict[int, dict[str, object]]]:
        result = self.service.import_rows({"values": self.rows})
        batch_id = str(result["batch_id"])
        self.assertTrue(result["ok"])

        reviews, _ = self.service.list_reviews(batch_id=batch_id, page=1, size=100)
        before_commit_total = self.service.list_ledger(page=1, size=10000)[1]
        _, blocked_message = self.service.commit_batch(batch_id)
        self.assertIn("待核表没过", blocked_message)
        self.assertEqual(self.service.list_ledger(page=1, size=10000)[1], before_commit_total)

        by_source = {int(row["source_row"]): dict(row) for row in reviews}
        for review in reviews:
            if review["状态"] == "退回":
                _, message = self.service.verify_row(
                    int(review["id"]),
                    "修正",
                    {"读数": "90", "抑尘措施": "已喷淋", "备注": "已修正"},
                )
                self.assertTrue(message)
                _, message = self.service.verify_row(int(review["id"]), "通过")
                self.assertTrue(message)
            elif review["状态"] == "待核":
                _, message = self.service.verify_row(int(review["id"]), "通过")
                self.assertTrue(message)

        _, message = self.service.verify_batch(batch_id)
        self.assertIn("可以入账", message)
        _, message = self.service.commit_batch(batch_id)
        self.assertIn("一次性入账", message)
        return batch_id, by_source

    def test_validates_dedupes_blocks_and_commits_atomically(self) -> None:
        _, by_source = self._import_and_commit()

        self.assertEqual(by_source[1]["状态"], "已覆盖")
        self.assertIn("被第 2 行覆盖", by_source[1]["覆盖说明"])
        self.assertEqual(by_source[2]["读数"], 160.0)
        self.assertTrue(by_source[2]["超标"])
        self.assertTrue(by_source[2]["措施未跟进"])
        self.assertIn("抑尘措施未跟进", by_source[2]["备注"])
        self.assertIn("覆盖第 1 行", by_source[2]["覆盖说明"])
        self.assertEqual(by_source[3]["状态"], "退回")
        self.assertIn("读数空缺", by_source[3]["退回原因"])
        self.assertEqual(by_source[4]["状态"], "退回")
        self.assertIn("读数超出量程", by_source[4]["退回原因"])

        ledger, total = self.service.list_ledger(month="2026-09", page=1, size=10000)
        self.assertEqual(total, 4)
        self.assertEqual(self.service.monthly_report("2026-09")["report_rows"], total)
        point = next(item for item in self.service.list_points() if item["point_code"] == "DUST-01")
        self.assertGreaterEqual(point["超标条数"], 1)

    def test_same_reading_imported_twice_keeps_one_record(self) -> None:
        batch_id, _ = self._import_and_commit()
        ledger, _ = self.service.list_ledger(month="2026-09", page=1, size=10000)
        accepted_rows = [
            {
                "监测点位": row["监测点位"],
                "时段": row["时段"],
                "读数": str(row["读数"]),
                "抑尘措施": row["抑尘措施"],
                "备注": str(row.get("备注", "")).replace("；抑尘措施未跟进", ""),
                "抄录人": row["抄录人"],
            }
            for row in ledger
            if row.get("batch_id") == batch_id
        ]
        repeated = self.service.import_rows({"values": accepted_rows})
        rows, _ = self.service.list_reviews(batch_id=str(repeated["batch_id"]), page=1, size=100)
        self.assertEqual(repeated["duplicate_count"], len(accepted_rows))
        self.assertTrue(all(row["状态"] == "重复导入" for row in rows))

        _, message = self.service.commit_batch(str(repeated["batch_id"]))
        self.assertIn("没有可入账", message)
        _, total = self.service.list_ledger(month="2026-09", page=1, size=10000)
        committed_batch_rows = [row for row in ledger if row.get("batch_id") == batch_id]
        self.assertEqual(total, 1 + len(committed_batch_rows))


if __name__ == "__main__":
    unittest.main()
