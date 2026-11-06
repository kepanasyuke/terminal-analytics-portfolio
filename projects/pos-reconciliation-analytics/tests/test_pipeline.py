"""Проверки пайплайна: генератор, сверка, контрольные суммы, обезличивание.

Запуск:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import anonymize, build_db, generate_data, run_sql  # noqa: E402

DEVICES = 24
DAYS = 10
SEED = 777

EXPECTED_MAPPING = {
    "MISSING_IN_ACQUIRING": ["missing_in_acquiring", "terminal_only"],
    "MISSING_IN_TERMINAL": ["missing_in_terminal", "acquiring_only"],
    "AMOUNT_MISMATCH": ["amount_mismatch"],
    "STATUS_MISMATCH": ["status_mismatch"],
    "TIMESTAMP_DRIFT": ["timestamp_drift"],
    "DUPLICATE_IN_ACQUIRING": ["duplicate_in_acquiring"],
}


class PipelineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.raw = cls.root / "raw"
        cls.meta = generate_data.generate(
            devices=DEVICES, days=DAYS, seed=SEED, end_date="2026-10-31", out_dir=cls.raw
        )
        cls.db_path = cls.root / "wh.sqlite"
        build_db.build(cls.db_path, raw_dir=cls.raw)
        cls.conn = sqlite3.connect(cls.db_path)
        run_sql.run_scripts(cls.conn, verbose=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        cls.tmp.cleanup()

    def query(self, sql: str) -> list[tuple]:
        return self.conn.execute(sql).fetchall()

    def test_sources_are_not_identical(self) -> None:
        terminal = self.query("SELECT COUNT(*) FROM stg_terminal")[0][0]
        acquiring = self.query("SELECT COUNT(*) FROM stg_acquiring")[0][0]
        self.assertGreater(terminal, 0)
        self.assertNotEqual(terminal, acquiring)

    def test_reconciliation_finds_exactly_injected_defects(self) -> None:
        found = dict(self.query(
            "SELECT exception_type, COUNT(*) FROM recon_exceptions GROUP BY exception_type"
        ))
        injected = self.meta["injected"]
        for exception_type, sources in EXPECTED_MAPPING.items():
            expected = sum(len(injected[source]) for source in sources)
            self.assertEqual(
                found.get(exception_type, 0), expected,
                f"{exception_type}: ожидалось {expected}, найдено {found.get(exception_type, 0)}",
            )
        self.assertEqual(sum(found.values()), sum(len(v) for v in injected.values()))

    def test_reconciliation_does_not_flag_matched_rows(self) -> None:
        flagged = {row[0] for row in self.query("SELECT rrn FROM recon_exceptions")}
        clean = self.query(
            """
            SELECT COUNT(*) FROM stg_terminal_clean t
            JOIN stg_acquiring_clean a ON a.rrn = t.rrn
            WHERE t.amount_kop = a.amount_kop AND t.status = a.status
              AND ABS((julianday(a.txn_ts) - julianday(t.txn_ts)) * 1440) <= 10
            """
        )[0][0]
        self.assertGreater(clean, 0)
        self.assertLess(len(flagged), clean)

    def test_control_totals_are_consistent_with_recon(self) -> None:
        diff_cnt, diff_amount = self.query(
            "SELECT SUM(cnt_diff), SUM(amount_diff_kop) FROM control_totals"
        )[0]
        acqu_count = self.query("SELECT COUNT(*) FROM stg_acquiring_clean")[0][0]
        term_count = self.query("SELECT COUNT(*) FROM stg_terminal_clean")[0][0]
        self.assertEqual(diff_cnt, acqu_count - term_count)

        acqu_sum = self.query("SELECT SUM(amount_kop) FROM stg_acquiring_clean")[0][0]
        term_sum = self.query("SELECT SUM(amount_kop) FROM stg_terminal_clean")[0][0]
        self.assertEqual(diff_amount, acqu_sum - term_sum)

    def test_amounts_are_integer_kopecks(self) -> None:
        types = {row[0] for row in self.query(
            "SELECT DISTINCT typeof(amount_kop) FROM stg_terminal_clean"
        )}
        self.assertEqual(types, {"integer"})
        kpi_amount = self.query("SELECT amount_kop FROM mart_kpi")[0][0]
        self.assertIsInstance(kpi_amount, int)

    def test_availability_is_within_bounds(self) -> None:
        bad = self.query(
            "SELECT COUNT(*) FROM mart_device_sla WHERE availability_pct < 0 OR availability_pct > 100"
        )[0][0]
        self.assertEqual(bad, 0)
        fleet_avg = self.query("SELECT avg_availability_pct FROM mart_kpi")[0][0]
        self.assertGreater(fleet_avg, 50)
        self.assertLessEqual(fleet_avg, 100)

    def test_open_incidents_are_capped_by_period_end(self) -> None:
        period_end = self.query("SELECT period_end FROM dim_period")[0][0]
        rows = self.query("SELECT effective_end FROM fact_incident_effective")
        self.assertTrue(rows)
        self.assertTrue(all(row[0] <= f"{period_end} 23:59:59" for row in rows))

    def test_injected_metadata_is_json_serialisable(self) -> None:
        text = json.dumps(self.meta, ensure_ascii=False)
        self.assertIn("injected", json.loads(text))


class AnonymizeCase(unittest.TestCase):
    def test_pan_keeps_bin_and_last_four(self) -> None:
        self.assertEqual(anonymize.mask_pan("4111111111111111"), "411111******1111")
        self.assertEqual(anonymize.mask_pan("2200 1234 5678 9012"), "220012******9012")

    def test_pan_not_matched_is_returned_as_is(self) -> None:
        self.assertEqual(anonymize.mask_pan("123"), "123")
        self.assertIsNone(anonymize.mask_pan(None))

    def test_tokenize_is_stable_and_salt_dependent(self) -> None:
        first = anonymize.tokenize("000000000001", "salt-a")
        second = anonymize.tokenize("000000000001", "salt-a")
        other = anonymize.tokenize("000000000001", "salt-b")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("TKN-"))

    def test_row_masking_keeps_join_keys(self) -> None:
        row = {"rrn": "000000000001", "serial": "IN123456789", "phone": "+7 916 123-45-67",
               "email": "analyst@example.ru", "amount_kop": "1500"}
        masked = anonymize.masked_row(row)
        self.assertEqual(masked["rrn"], "000000000001")
        self.assertEqual(masked["amount_kop"], "1500")
        self.assertTrue(masked["serial"].startswith("IN"))
        self.assertIn("***", masked["phone"])
        self.assertEqual(masked["email"], "a***@example.ru")


if __name__ == "__main__":
    unittest.main(verbosity=2)
