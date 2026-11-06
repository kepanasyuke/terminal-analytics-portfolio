"""Проверки аналитики заявок: правила категоризации, SLA, повторные обращения."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import analyze, generate_tickets  # noqa: E402


class ClassifierCase(unittest.TestCase):
    def test_templates_are_recognised(self) -> None:
        cases = {
            "Терминал не проводит оплату картой": "PAYMENT",
            "Нет связи с процессингом": "CONNECTIVITY",
            "Не читает карту, ошибка картридера": "HARDWARE",
            "Не хватает наличных в кассете": "CASH",
            "Терминал завис после обновления": "SOFTWARE",
            "Как оформить возврат по чеку": "CONSULT",
            "Нужен доступ к инженерному меню": "ACCESS",
        }
        for subject, expected in cases.items():
            self.assertEqual(analyze.classify(subject), expected, subject)

    def test_unknown_text_falls_into_other(self) -> None:
        self.assertEqual(analyze.classify("Клиент говорит, что деньги списались дважды"), "OTHER")

    def test_consult_beats_hardware_keyword(self) -> None:
        self.assertEqual(analyze.classify("Как оформить возврат по чеку"), "CONSULT")


class RulesOnGeneratedDataCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raw = Path(cls.tmp.name) / "raw"
        cls.out = Path(cls.tmp.name) / "processed"
        cls.meta = generate_tickets.generate(tickets=400, days=30, seed=555, out_dir=cls.raw)
        cls.result = analyze.run(raw=cls.raw, processed=cls.out)
        cls.rows = analyze.mark_repeats(analyze.enrich(analyze.read_csv(cls.raw / "tickets.csv")))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_accuracy_is_reasonable(self) -> None:
        accuracy = self.result["metrics"]["accuracy"]
        self.assertGreater(accuracy, 0.75, f"точность {accuracy}")
        self.assertLess(accuracy, 0.99, "правила не должны совпадать с генератором идеально")

    def test_sla_uses_priority_norms(self) -> None:
        for row in self.rows:
            response_sla, resolve_sla = analyze.SLA_HOURS[row["priority"]]
            self.assertEqual(row["response_sla_h"], response_sla)
            self.assertEqual(row["resolve_sla_h"], resolve_sla)
            self.assertEqual(row["response_breach"], row["response_h"] > response_sla)

    def test_resolution_breach_ignores_open_tickets(self) -> None:
        for row in self.rows:
            if row["is_open"]:
                self.assertFalse(row["resolution_breach"])
                self.assertIsNone(row["resolution_h"])

    def test_repeat_requires_same_category(self) -> None:
        rows = sorted(self.rows, key=lambda r: (r["device_id"], r["created_at"]))
        last: dict[str, tuple] = {}
        for row in rows:
            created = datetime.fromisoformat(row["created_at"])
            if row["device_id"] in last:
                closed, category = last[row["device_id"]]
                expected = (timedelta(0) <= created - closed <= timedelta(days=7)
                            and category == row["category_true"])
                self.assertEqual(row["is_repeat"], expected, row["ticket_id"])
            if row["closed_at"]:
                last[row["device_id"]] = (datetime.fromisoformat(row["closed_at"]),
                                          row["category_true"])

    def test_marts_are_written(self) -> None:
        for name in ("mart_kpi", "mart_categories", "mart_sla", "mart_agents",
                     "mart_weekly", "mart_partners", "mart_repeat_devices"):
            self.assertTrue((self.out / f"{name}.csv").exists(), name)
        metrics = json.loads((self.out / "classifier_metrics.json").read_text(encoding="utf-8"))
        self.assertIn("per_category", metrics)

    def test_sla_share_sums_to_total(self) -> None:
        kpi = self.result_row = analyze.read_csv(self.out / "mart_kpi.csv")[0]
        sla_rows = analyze.read_csv(self.out / "mart_sla.csv")
        self.assertEqual(sum(int(r["tickets_cnt"]) for r in sla_rows),
                         int(kpi["tickets_cnt"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
