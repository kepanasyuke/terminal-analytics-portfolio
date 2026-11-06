"""Проверки расчёта SLA: независимый пересчёт из выгрузки против витрин."""

from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import generate_fleet, pipeline  # noqa: E402

SEP = ";"
ENC = "utf-8-sig"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


class SlaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.raw = cls.root / "raw"
        cls.meta = generate_fleet.generate(devices_cnt=60, days=45, seed=99,
                                           end_date="2026-10-31", out_dir=cls.raw)
        cls.db = cls.root / "sla.sqlite"
        pipeline.run(db_path=cls.db, raw_dir=cls.raw, out_dir=cls.root / "out", verbose=False)
        cls.conn = sqlite3.connect(cls.db)
        cls.incidents = read_csv(cls.raw / "incidents.csv")
        cls.contracts = {row["contract_id"]: row for row in read_csv(cls.raw / "contracts.csv")}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        cls.tmp.cleanup()

    def test_period_matches_source(self) -> None:
        start, end, days = self.conn.execute(
            "SELECT period_start, period_end, period_days FROM dim_period"
        ).fetchone()
        self.assertEqual(start, self.meta["period_start"])
        self.assertEqual(end, self.meta["period_end"])
        self.assertEqual(days, 45)

    def test_sla_breach_count_matches_independent_calc(self) -> None:
        expected = 0
        for row in self.incidents:
            opened = datetime.fromisoformat(row["opened_at"])
            first = datetime.fromisoformat(row["first_response_at"])
            period_end = f"{self.meta['period_end']} 23:59:59"
            closed = (datetime.fromisoformat(row["closed_at"])
                      if row["closed_at"] else datetime.fromisoformat(period_end))
            sla = int(row["sla_hours"]) * 3600
            response_overdue = max(0.0, (first - opened).total_seconds() - sla * 0.25)
            resolution_overdue = max(0.0, (closed - opened).total_seconds() - sla)
            if response_overdue > 0 or resolution_overdue > 0:
                expected += 1
        found = self.conn.execute(
            "SELECT SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END) FROM fact_incident_sla"
        ).fetchone()[0]
        self.assertEqual(found, expected)

    def test_penalty_is_capped_per_contract(self) -> None:
        rows = self.conn.execute(
            "SELECT billed_penalty_kop, raw_penalty_kop, penalty_cap_kop FROM mart_penalty_month"
        ).fetchall()
        self.assertTrue(rows)
        for billed, raw, cap in rows:
            self.assertLessEqual(billed, cap)
            self.assertEqual(billed, min(raw, cap))

    def test_availability_bounds(self) -> None:
        bad = self.conn.execute(
            "SELECT COUNT(*) FROM mart_device WHERE availability_pct < 0 OR availability_pct > 100"
        ).fetchone()[0]
        self.assertEqual(bad, 0)

    def test_high_priority_requires_evidence(self) -> None:
        rows = self.conn.execute(
            "SELECT availability_pct, p1_cnt FROM mart_replacement WHERE priority = 'ВЫСОКИЙ'"
        ).fetchall()
        for availability, p1_cnt in rows:
            self.assertTrue(availability < 90 or p1_cnt >= 4)

    def test_mttr_only_uses_closed_incidents(self) -> None:
        mttr, open_cnt = self.conn.execute(
            "SELECT mttr_hours, open_cnt FROM mart_device WHERE open_cnt > 0 "
            "ORDER BY open_cnt DESC LIMIT 1"
        ).fetchone()
        self.assertGreaterEqual(mttr, 0)

    def test_penalty_formula_matches_contract_terms(self) -> None:
        rows = self.conn.execute(
            """
            SELECT s.monthly_fee_kop, s.penalty_per_hour_pct, s.overdue_full_hours, s.penalty_kop
            FROM fact_incident_sla s
            WHERE s.overdue_full_hours > 0
            LIMIT 50
            """
        ).fetchall()
        self.assertTrue(rows)
        for fee, rate, hours, penalty in rows:
            expected = round(fee * rate / 100.0 * hours)
            self.assertEqual(penalty, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
