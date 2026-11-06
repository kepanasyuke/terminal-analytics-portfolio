"""Проверки детектора: полнота на заложенных аномалиях, устойчивость, границы."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import detect, generate_series  # noqa: E402


def series(values: list[int], start_day: int = 1) -> list[dict]:
    return [
        {
            "device_id": "PO-TEST",
            "device_type": "POS",
            "partner_name": "Тест",
            "city": "Москва",
            "txn_date": f"2026-09-{start_day + idx:02d}" if start_day + idx <= 30
                        else f"2026-10-{start_day + idx - 30:02d}",
            "txn_cnt": value,
            "declined_cnt": 5,
            "approved_cnt": value - 5,
        }
        for idx, value in enumerate(values)
    ]


class DetectorCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raw = Path(cls.tmp.name)
        cls.meta = generate_series.generate(devices=50, days=60, seed=31337,
                                            out_dir=cls.raw)
        cls.rows = detect.read_csv(cls.raw / "device_daily.csv")
        cls.alerts = detect.detect(cls.rows)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_all_planted_anomalies_found(self) -> None:
        planted = {(p["device_id"], p["txn_date"], p["kind"]) for p in self.meta["planted"]}
        found = {(a["device_id"], a["txn_date"], a["kind"]) for a in self.alerts}
        self.assertEqual(planted - found, set(), "есть пропущенные аномалии")

    def test_precision_is_acceptable(self) -> None:
        planted = {(p["device_id"], p["txn_date"], p["kind"]) for p in self.meta["planted"]}
        found = {(a["device_id"], a["txn_date"], a["kind"]) for a in self.alerts}
        precision = len(planted & found) / len(found) if found else 0
        self.assertGreaterEqual(precision, 0.70, f"точность {precision:.2f}")

    def test_flat_series_produces_no_alerts(self) -> None:
        flat = series([200] * 40)
        self.assertEqual(detect.screen_device(flat), [])

    def test_weekend_pattern_is_not_an_anomaly(self) -> None:
        values = []
        for idx in range(60):
            weekday = (idx + 1) % 7
            values.append(320 if weekday in (5, 6) else 200)
        self.assertEqual(detect.screen_device(series(values)), [])

    def test_silent_run_detected_once(self) -> None:
        values = [200] * 30 + [0, 0, 0] + [200] * 5
        alerts = detect.screen_device(series(values))
        silent = [a for a in alerts if a["kind"] == "SILENT"]
        self.assertEqual(len(silent), 1)
        self.assertIn("3 дн", silent[0]["note"])

    def test_drop_is_detected(self) -> None:
        values = [200] * 40 + [60]
        alerts = detect.screen_device(series(values))
        self.assertTrue(any(a["kind"] == "VOLUME_DROP" for a in alerts))

    def test_robust_sigma_has_floor(self) -> None:
        self.assertEqual(detect.robust_sigma([], 0.1), 0.1)
        self.assertEqual(detect.robust_sigma([0.0, 0.0, 0.0], 0.1), 0.1)
        self.assertGreater(detect.robust_sigma([-0.5, 0.5, -0.4, 0.6], 0.1), 0.1)

    def test_alerts_are_sorted_by_severity(self) -> None:
        severities = [a["severity"] for a in self.alerts]
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        ranks = [order[s] for s in severities]
        self.assertEqual(ranks, sorted(ranks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
