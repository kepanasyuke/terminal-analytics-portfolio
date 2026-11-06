"""Анализ заявок первой линии: категоризация по тексту, SLA, повторные обращения.

Считается всё на чистом Python: файл небольшой (тысячи строк), зато правила
категоризации видны и правятся без SQL-миграций.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

SEP = ";"
ENC = "utf-8-sig"

SLA_HOURS = {"P1": (2, 8), "P2": (4, 24), "P3": (8, 72)}
REPEAT_WINDOW_DAYS = 7

# Порядок важен: более узкие правила стоят раньше, иначе «чек» в вопросе
# про возврат утащит заявку в HARDWARE.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("CASH", ("наличн", "инкассац", "кассет")),
    ("CONSULT", ("как ", "как оформить", "подскаж", "спрашива", "порядок", "инструкц")),
    ("HARDWARE", ("картридер", "карт-ридер", "пин-пад", "пин пад", "принтер", "диспенсер",
                  "замятие", "замял", "не читает карт")),
    ("CONNECTIVITY", ("связ", "процессинг", "офлайн", "хост", "канал", "соединен")),
    ("SOFTWARE", ("завис", "обновл", "приложен", "перезагруз", "экран", "версия по")),
    ("ACCESS", ("доступ", "ключ", "помещен", "серверн")),
    ("PAYMENT", ("оплат", "платеж", "платёж", "проведени", "авторизац", "картой")),
]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=ENC) as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=SEP)
        writer.writeheader()
        writer.writerows(rows)


def classify(subject: str) -> str:
    text = subject.lower().replace("ё", "е")
    for category, keywords in RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "OTHER"


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def hours_between(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 3600.0, 2)


def enrich(tickets: list[dict]) -> list[dict]:
    enriched = []
    for row in tickets:
        created = parse(row["created_at"])
        first = parse(row["first_response_at"])
        closed = parse(row["closed_at"])
        priority = row["priority"]
        response_sla, resolve_sla = SLA_HOURS[priority]
        response_h = hours_between(created, first)
        resolution_h = hours_between(created, closed) if closed else None
        enriched.append({
            **row,
            "category_pred": classify(row["subject"]),
            "response_h": response_h,
            "resolution_h": resolution_h,
            "response_sla_h": response_sla,
            "resolve_sla_h": resolve_sla,
            "response_breach": response_h > response_sla,
            "resolution_breach": resolution_h is not None and resolution_h > resolve_sla,
            "is_open": closed is None,
        })
    return enriched


def mark_repeats(rows: list[dict]) -> list[dict]:
    by_device: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_device[row["device_id"]].append(row)
    for series in by_device.values():
        series.sort(key=lambda r: r["created_at"])
        previous_closed: datetime | None = None
        previous_category: str | None = None
        for row in series:
            created = parse(row["created_at"])
            repeat = False
            if previous_closed is not None:
                delta = created - previous_closed
                repeat = (timedelta(0) <= delta <= timedelta(days=REPEAT_WINDOW_DAYS)
                          and row["category_true"] == previous_category)
            row["is_repeat"] = repeat
            closed = parse(row["closed_at"])
            if closed:
                previous_closed = closed
                previous_category = row["category_true"]
    return rows


def build_marts(rows: list[dict]) -> dict[str, list[dict]]:
    total = len(rows) or 1
    closed = [r for r in rows if not r["is_open"]]

    def share(count: int, base: int = total) -> float:
        return round(100.0 * count / base, 1) if base else 0.0

    kpi = [{
        "tickets_cnt": total,
        "open_cnt": sum(1 for r in rows if r["is_open"]),
        "p1_cnt": sum(1 for r in rows if r["priority"] == "P1"),
        "repeat_cnt": sum(1 for r in rows if r["is_repeat"]),
        "repeat_rate_pct": share(sum(1 for r in rows if r["is_repeat"])),
        "response_breach_cnt": sum(1 for r in rows if r["response_breach"]),
        "resolution_breach_cnt": sum(1 for r in rows if r["resolution_breach"]),
        "avg_response_h": round(statistics.fmean(r["response_h"] for r in rows), 2),
        "avg_resolution_h": round(statistics.fmean(r["resolution_h"] for r in closed), 2) if closed else 0,
        "sla_compliance_pct": round(100.0 - 100.0 * sum(
            1 for r in rows if r["response_breach"] or r["resolution_breach"]) / total, 1),
    }]

    categories = []
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category_pred"]].append(row)
    for category, items in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        with_sla = len(items)
        categories.append({
            "category": category,
            "tickets_cnt": with_sla,
            "share_pct": share(with_sla),
            "p1_cnt": sum(1 for r in items if r["priority"] == "P1"),
            "avg_resolution_h": round(statistics.fmean(
                r["resolution_h"] for r in items if r["resolution_h"] is not None), 2)
                if any(r["resolution_h"] is not None for r in items) else 0,
            "sla_breach_pct": share(sum(
                1 for r in items if r["response_breach"] or r["resolution_breach"]), with_sla),
            "repeat_pct": share(sum(1 for r in items if r["is_repeat"]), with_sla),
        })

    sla_rows = []
    for priority, (response_sla, resolve_sla) in SLA_HOURS.items():
        items = [r for r in rows if r["priority"] == priority]
        if not items:
            continue
        done = [r for r in items if r["resolution_h"] is not None]
        sla_rows.append({
            "priority": priority,
            "tickets_cnt": len(items),
            "share_pct": share(len(items)),
            "response_sla_h": response_sla,
            "resolve_sla_h": resolve_sla,
            "avg_response_h": round(statistics.fmean(r["response_h"] for r in items), 2),
            "avg_resolution_h": round(statistics.fmean(r["resolution_h"] for r in done), 2) if done else 0,
            "response_breach_cnt": sum(1 for r in items if r["response_breach"]),
            "resolution_breach_cnt": sum(1 for r in items if r["resolution_breach"]),
            "compliance_pct": round(100.0 - 100.0 * sum(
                1 for r in items if r["response_breach"] or r["resolution_breach"]) / len(items), 1),
        })

    agents = []
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_agent[row["agent"]].append(row)
    for agent, items in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
        done = [r for r in items if r["resolution_h"] is not None]
        agents.append({
            "agent": agent,
            "tickets_cnt": len(items),
            "share_pct": share(len(items)),
            "p1_cnt": sum(1 for r in items if r["priority"] == "P1"),
            "avg_response_h": round(statistics.fmean(r["response_h"] for r in items), 2),
            "avg_resolution_h": round(statistics.fmean(r["resolution_h"] for r in done), 2) if done else 0,
            "sla_breach_pct": share(sum(
                1 for r in items if r["response_breach"] or r["resolution_breach"]), len(items)),
        })

    channels = []
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_channel[row["channel"]].append(row)
    for channel, items in sorted(by_channel.items(), key=lambda kv: -len(kv[1])):
        channels.append({
            "channel": channel,
            "tickets_cnt": len(items),
            "share_pct": share(len(items)),
            "avg_response_h": round(statistics.fmean(r["response_h"] for r in items), 2),
            "sla_breach_pct": share(sum(
                1 for r in items if r["response_breach"] or r["resolution_breach"]), len(items)),
        })

    weekly: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        created = parse(row["created_at"])
        week_start = (created - timedelta(days=created.weekday())).date().isoformat()
        weekly[week_start].append(row)
    weekly_rows = [{
        "week_start": week,
        "tickets_cnt": len(items),
        "p1_cnt": sum(1 for r in items if r["priority"] == "P1"),
        "breach_cnt": sum(1 for r in items if r["response_breach"] or r["resolution_breach"]),
        "repeat_cnt": sum(1 for r in items if r["is_repeat"]),
        "avg_response_h": round(statistics.fmean(r["response_h"] for r in items), 2),
    } for week, items in sorted(weekly.items())]

    partners: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        partners[row["partner_name"]].append(row)
    partner_rows = [{
        "partner_name": name,
        "tickets_cnt": len(items),
        "share_pct": share(len(items)),
        "p1_cnt": sum(1 for r in items if r["priority"] == "P1"),
        "repeat_pct": share(sum(1 for r in items if r["is_repeat"]), len(items)),
        "avg_resolution_h": round(statistics.fmean(
            r["resolution_h"] for r in items if r["resolution_h"] is not None), 2)
            if any(r["resolution_h"] is not None for r in items) else 0,
    } for name, items in sorted(partners.items(), key=lambda kv: -len(kv[1]))]

    repeat_devices: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["is_repeat"]:
            repeat_devices[row["device_id"]].append(row)
    device_rows = [{
        "device_id": device,
        "device_type": items[0]["device_type"],
        "partner_name": items[0]["partner_name"],
        "repeat_cnt": len(items),
        "top_category": Counter(r["category_pred"] for r in items).most_common(1)[0][0],
        "last_repeat": max(r["created_at"] for r in items),
    } for device, items in sorted(repeat_devices.items(), key=lambda kv: -len(kv[1]))]

    return {
        "mart_kpi": kpi,
        "mart_categories": categories,
        "mart_sla": sla_rows,
        "mart_agents": agents,
        "mart_channels": channels,
        "mart_weekly": weekly_rows,
        "mart_partners": partner_rows,
        "mart_repeat_devices": device_rows,
    }


def classifier_metrics(rows: list[dict]) -> dict:
    total = len(rows) or 1
    correct = sum(1 for r in rows if r["category_pred"] == r["category_true"])
    per_category = {}
    for category in sorted({r["category_true"] for r in rows}):
        true_items = [r for r in rows if r["category_true"] == category]
        pred_items = [r for r in rows if r["category_pred"] == category]
        hits = sum(1 for r in true_items if r["category_pred"] == category)
        per_category[category] = {
            "true_cnt": len(true_items),
            "pred_cnt": len(pred_items),
            "recall": round(hits / len(true_items), 3) if true_items else None,
            "precision": round(hits / len(pred_items), 3) if pred_items else None,
        }
    return {
        "tickets": len(rows),
        "accuracy": round(correct / total, 3),
        "per_category": per_category,
    }


def run(raw: Path = RAW, processed: Path = PROCESSED) -> dict:
    tickets = read_csv(raw / "tickets.csv")
    rows = mark_repeats(enrich(tickets))
    marts = build_marts(rows)
    for name, data in marts.items():
        write_csv(processed / f"{name}.csv", data)
    write_csv(processed / "tickets_enriched.csv", [{
        "ticket_id": r["ticket_id"], "created_at": r["created_at"], "priority": r["priority"],
        "channel": r["channel"], "agent": r["agent"], "device_id": r["device_id"],
        "partner_name": r["partner_name"], "subject": r["subject"],
        "category_pred": r["category_pred"], "category_true": r["category_true"],
        "response_h": r["response_h"], "resolution_h": r["resolution_h"],
        "response_breach": r["response_breach"], "resolution_breach": r["resolution_breach"],
        "is_repeat": r["is_repeat"],
    } for r in rows])
    metrics = classifier_metrics(rows)
    (processed / "classifier_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"tickets": len(rows), "metrics": metrics}


def main() -> None:
    argparse.ArgumentParser(description="Анализ заявок поддержки").parse_args()
    result = run()
    metrics = result["metrics"]
    print(f"заявок: {result['tickets']}, точность категоризации: {metrics['accuracy'] * 100:.1f} %")
    for category, stat in metrics["per_category"].items():
        print(f"  {category:13s} полнота {stat['recall']:.2f}  точность {stat['precision']:.2f}")


if __name__ == "__main__":
    main()
