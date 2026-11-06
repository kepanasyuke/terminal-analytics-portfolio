"""Детектор аномалий в суточных рядах терминалов.

Метод:
  * база по устройству — медиана значений за предыдущие 4 недели в тот же день
    недели (профиль выходных учится, а не считается аномалией);
  * устойчивый разброс — MAD по прошлым относительным отклонениям;
  * порог одновременно по z-оценке и по размеру эффекта: статистически заметное,
    но операционно мелкое изменение не считается аномалией.

Классы: VOLUME_DROP, VOLUME_SPIKE, SILENT, DECLINE_SPIKE.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

SEP = ";"
ENC = "utf-8-sig"

WARMUP = 21
HISTORY_DAYS = 28
MIN_EFFECT_DROP = 0.40
MIN_EFFECT_SPIKE = 0.55
Z_THRESHOLD = 3.5
SIGMA_FLOOR = 0.10
SILENT_MIN_BASELINE = 15
DECLINE_MIN_EFFECT = 0.18
DECLINE_Z = 4.0


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def robust_sigma(values: list[float], floor: float) -> float:
    if len(values) < 3:
        return floor
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    return max(floor, mad / 0.6745)


def baseline_for(series: list[dict], idx: int) -> float | None:
    """Медиана за прошлые 4 недели в тот же день недели, иначе — общая медиана."""
    if idx < WARMUP:
        return None
    weekday = date.fromisoformat(series[idx]["txn_date"]).weekday()
    history = series[max(0, idx - HISTORY_DAYS):idx]
    same_weekday = [
        float(r["txn_cnt"]) for r in history
        if date.fromisoformat(r["txn_date"]).weekday() == weekday
    ]
    if len(same_weekday) >= 2:
        return statistics.median(same_weekday)
    recent = [float(r["txn_cnt"]) for r in history]
    return statistics.median(recent) if recent else None


def make_alert(row: dict, kind: str, severity: str, observed: float, baseline: float,
               z_score: float | None, note: str) -> dict:
    deviation = (observed - baseline) / baseline * 100 if baseline else 0.0
    return {
        "alert_id": "",
        "device_id": row["device_id"],
        "device_type": row["device_type"],
        "partner_name": row["partner_name"],
        "city": row["city"],
        "txn_date": row["txn_date"],
        "kind": kind,
        "severity": severity,
        "observed": round(observed, 2),
        "baseline": round(baseline, 2),
        "deviation_pct": round(deviation, 1),
        "z_score": round(z_score, 2) if z_score is not None else None,
        "note": note,
    }


def screen_device(series: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    if len(series) < WARMUP + 5:
        return alerts

    residuals: list[float] = []
    decline_residuals: list[float] = []
    silent_until: str | None = None
    prev_decline: float | None = None

    for idx, row in enumerate(series):
        actual = float(row["txn_cnt"])
        declined = float(row["declined_cnt"])
        base = baseline_for(series, idx)
        if base is None:
            continue
        if silent_until and row["txn_date"] > silent_until:
            silent_until = None

        if base >= SILENT_MIN_BASELINE and actual == 0:
            if silent_until is None:
                span = 1
                for nxt in series[idx + 1:]:
                    if float(nxt["txn_cnt"]) == 0:
                        span += 1
                    else:
                        break
                silent_until = series[min(idx + span - 1, len(series) - 1)]["txn_date"]
                alerts.append(make_alert(
                    row, "SILENT", "HIGH", observed=actual, baseline=base, z_score=None,
                    note=f"простой {span} дн. при норме {base:.0f} операций в день",
                ))
            continue
        if silent_until and row["txn_date"] <= silent_until:
            continue

        ratio = (actual - base) / base if base else 0.0
        sigma = robust_sigma(residuals, SIGMA_FLOOR)
        z = ratio / sigma

        # Жёсткое правило: падение более 55 % проверяем всегда, даже если разброс
        # устройства высокий и z-оценка не дотягивает до порога.
        if ratio <= -MIN_EFFECT_DROP and (z <= -Z_THRESHOLD or ratio <= -0.55):
            alerts.append(make_alert(
                row, "VOLUME_DROP", "HIGH" if ratio <= -0.60 else "MEDIUM",
                observed=actual, baseline=base, z_score=z,
                note=f"объём ниже нормы на {abs(ratio) * 100:.0f} %",
            ))
            residuals.append(ratio)
        elif ratio >= MIN_EFFECT_SPIKE and z >= Z_THRESHOLD:
            alerts.append(make_alert(
                row, "VOLUME_SPIKE", "MEDIUM", observed=actual, baseline=base, z_score=z,
                note=f"объём выше нормы на {ratio * 100:.0f} %",
            ))
            residuals.append(ratio)
        else:
            residuals.append(ratio)
        if len(residuals) > 21:
            residuals.pop(0)

        if actual >= 20:
            decline_rate = declined / actual
            if prev_decline is not None:
                dev = decline_rate - prev_decline
                d_sigma = robust_sigma(decline_residuals, 0.03)
                d_z = dev / d_sigma
                if dev >= DECLINE_MIN_EFFECT and d_z >= DECLINE_Z:
                    alerts.append(make_alert(
                        row, "DECLINE_SPIKE", "MEDIUM", observed=decline_rate,
                        baseline=prev_decline, z_score=d_z,
                        note=f"доля отказов {decline_rate * 100:.1f} % против {prev_decline * 100:.1f} %",
                    ))
                decline_residuals.append(dev)
                if len(decline_residuals) > 21:
                    decline_residuals.pop(0)
            prev_decline = decline_rate

    return alerts


def detect(rows: list[dict]) -> list[dict]:
    series_by_device: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        series_by_device[row["device_id"]].append(row)

    alerts: list[dict] = []
    for series in series_by_device.values():
        series.sort(key=lambda r: r["txn_date"])
        alerts.extend(screen_device(series))

    severity_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    alerts.sort(key=lambda a: (severity_rank.get(a["severity"], 3), a["txn_date"], a["device_id"]))
    for idx, alert in enumerate(alerts, start=1):
        alert["alert_id"] = f"ALR-{idx:05d}"
    return alerts


def summarise(alerts: list[dict]) -> dict[str, list[dict]]:
    by_kind: dict[str, dict] = {}
    for alert in alerts:
        entry = by_kind.setdefault(alert["kind"], {
            "kind": alert["kind"], "alerts_cnt": 0, "devices": set(), "partners": set(),
            "high_cnt": 0, "first_date": alert["txn_date"], "last_date": alert["txn_date"],
        })
        entry["alerts_cnt"] += 1
        entry["devices"].add(alert["device_id"])
        entry["partners"].add(alert["partner_name"])
        entry["high_cnt"] += 1 if alert["severity"] == "HIGH" else 0
        entry["first_date"] = min(entry["first_date"], alert["txn_date"])
        entry["last_date"] = max(entry["last_date"], alert["txn_date"])

    summary = [{
        "kind": entry["kind"],
        "alerts_cnt": entry["alerts_cnt"],
        "devices_cnt": len(entry["devices"]),
        "partners_cnt": len(entry["partners"]),
        "high_cnt": entry["high_cnt"],
        "first_date": entry["first_date"],
        "last_date": entry["last_date"],
    } for entry in sorted(by_kind.values(), key=lambda e: -e["alerts_cnt"])]

    by_device: dict[str, dict] = {}
    for alert in alerts:
        entry = by_device.setdefault(alert["device_id"], {
            "device_id": alert["device_id"], "device_type": alert["device_type"],
            "partner_name": alert["partner_name"], "city": alert["city"],
            "alerts_cnt": 0, "high_cnt": 0, "kinds": set(), "last_alert_date": alert["txn_date"],
        })
        entry["alerts_cnt"] += 1
        entry["high_cnt"] += 1 if alert["severity"] == "HIGH" else 0
        entry["kinds"].add(alert["kind"])
        entry["last_alert_date"] = max(entry["last_alert_date"], alert["txn_date"])

    devices = [{
        "device_id": entry["device_id"],
        "device_type": entry["device_type"],
        "partner_name": entry["partner_name"],
        "city": entry["city"],
        "alerts_cnt": entry["alerts_cnt"],
        "high_cnt": entry["high_cnt"],
        "kinds": ", ".join(sorted(entry["kinds"])),
        "last_alert_date": entry["last_alert_date"],
    } for entry in sorted(by_device.values(), key=lambda e: (-e["high_cnt"], -e["alerts_cnt"]))]
    return {"by_kind": summary, "by_device": devices}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=ENC) as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=SEP)
        writer.writeheader()
        writer.writerows(rows)


def evaluate(alerts: list[dict], planted_path: Path | None = None) -> dict:
    planted_path = planted_path or (RAW / "_planted_anomalies.json")
    if not planted_path.exists():
        return {}
    planted = json.loads(planted_path.read_text(encoding="utf-8"))["planted"]
    planted_keys = {(p["device_id"], p["txn_date"], p["kind"]) for p in planted}
    found_keys = {(a["device_id"], a["txn_date"], a["kind"]) for a in alerts}
    hits = planted_keys & found_keys
    return {
        "planted": len(planted_keys),
        "alerts": len(alerts),
        "hits": len(hits),
        "recall": round(len(hits) / len(planted_keys), 3) if planted_keys else None,
        "precision": round(len(hits) / len(alerts), 3) if alerts else None,
        "missed": [list(k) for k in sorted(planted_keys - found_keys)],
        "false_alerts": [list(k) for k in sorted(found_keys - planted_keys)],
    }


def run(raw: Path = RAW, processed: Path = PROCESSED) -> dict:
    rows = read_csv(raw / "device_daily.csv")
    alerts = detect(rows)
    parts = summarise(alerts)
    write_csv(processed / "alerts.csv", alerts)
    write_csv(processed / "alerts_by_kind.csv", parts["by_kind"])
    write_csv(processed / "alerts_by_device.csv", parts["by_device"])
    metrics = evaluate(alerts, raw / "_planted_anomalies.json")
    (processed / "detection_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"alerts": len(alerts), "metrics": metrics}


def main() -> None:
    argparse.ArgumentParser(description="Поиск аномалий в суточных рядах терминалов").parse_args()
    result = run()
    metrics = result["metrics"]
    print(f"алертов: {result['alerts']}")
    if metrics:
        print(f"заложено {metrics['planted']}, найдено {metrics['hits']} "
              f"(полнота {metrics['recall']}, точность {metrics['precision']})")
        if metrics["missed"]:
            print(f"пропущено: {metrics['missed'][:5]}")
        if metrics["false_alerts"]:
            print(f"ложные: {metrics['false_alerts'][:5]}")


if __name__ == "__main__":
    main()
