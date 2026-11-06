"""Генератор суточных рядов по терминалам с внедрёнными аномалиями.

Каждое устройство имеет свой профиль: масштаб операций, чувствительность к выходным,
долю отказов. Поверх нормального поведения внедряются известные аномалии:
  * VOLUME_DROP   — падение объёма на 55–85 % за один день;
  * VOLUME_SPIKE  — рост на 80–140 %;
  * SILENT        — устройство не проводит операций 2–3 дня подряд;
  * DECLINE_SPIKE — доля отказов вырастает в 3–5 раз.
Эталон сохраняется в data/raw/_planted_anomalies.json, чтобы точность детектора
проверялась числом, а не на глаз.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SEP = ";"
ENC = "utf-8-sig"

PARTNERS = ["Северный Ритейл", "Телеком-С", "Транспорт-Юг", "Банк Партнёр",
            "Аптечная сеть Здоровье+", "Топливная компания Магистраль"]
TYPES = [("POS", 0.62, 145), ("KIOSK", 0.26, 320), ("ATM", 0.12, 210)]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Краснодар"]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=ENC) as fh:
        writer = csv.writer(fh, delimiter=SEP)
        writer.writerow(header)
        writer.writerows(rows)


def pick_type(rng: random.Random) -> tuple[str, int]:
    roll = rng.random()
    acc = 0.0
    for name, weight, scale in TYPES:
        acc += weight
        if roll <= acc:
            return name, scale
    return TYPES[-1][0], TYPES[-1][2]


def generate(devices: int = 120, days: int = 60, seed: int = 2026,
             end_date: str = "2026-10-31", out_dir: Path = RAW,
             anomaly_rate: float = 0.006) -> dict:
    rng = random.Random(seed)
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=days - 1)

    fleet = []
    for idx in range(devices):
        dtype, scale = pick_type(rng)
        fleet.append({
            "device_id": f"{dtype[:2]}-{300000 + idx * 5}",
            "device_type": dtype,
            "partner_name": rng.choice(PARTNERS),
            "city": rng.choice(CITIES),
            "scale": scale * rng.uniform(0.55, 1.7),
            "weekend_boost": rng.uniform(1.0, 1.35),
            "decline_base": rng.uniform(0.035, 0.10),
            "trend": rng.uniform(-0.0012, 0.0018),
        })

    rows: list[dict] = []
    for device in fleet:
        for offset in range(days):
            day = start + timedelta(days=offset)
            weekday = day.weekday()
            season = 1.0 + 0.12 * ((offset % 14) / 14.0 - 0.5)
            weekend = device["weekend_boost"] if weekday >= 5 else 1.0
            trend = 1.0 + device["trend"] * offset
            base = device["scale"] * season * weekend * trend
            volume = max(0, int(rng.gauss(base, base * 0.12)))
            decline_rate = min(0.6, max(0.01, rng.gauss(device["decline_base"], 0.012)))
            declined = int(round(volume * decline_rate))
            rows.append({
                "device_id": device["device_id"],
                "device_type": device["device_type"],
                "partner_name": device["partner_name"],
                "city": device["city"],
                "txn_date": day.isoformat(),
                "txn_cnt": volume,
                "declined_cnt": declined,
                "approved_cnt": volume - declined,
                "avg_amount_kop": int(rng.gauss(185_000, 42_000)),
                "uptime_min": 1440 if rng.random() > 0.03 else rng.randint(600, 1400),
            })

    by_device: dict[str, list[dict]] = {}
    for row in rows:
        by_device.setdefault(row["device_id"], []).append(row)
    for series in by_device.values():
        series.sort(key=lambda r: r["txn_date"])

    planted: list[dict] = []
    targets = max(4, int(len(rows) * anomaly_rate))
    used: set[tuple[str, str]] = set()
    kinds = ["VOLUME_DROP", "VOLUME_SPIKE", "SILENT", "DECLINE_SPIKE"]
    for idx in range(targets):
        kind = kinds[idx % len(kinds)]
        series = rng.choice(list(by_device.values()))
        if kind == "SILENT":
            day_index = rng.randint(25, len(series) - 5)
        else:
            day_index = rng.randint(25, len(series) - 2)
        row = series[day_index]
        key = (row["device_id"], row["txn_date"])
        if key in used or row["txn_cnt"] < 20:
            continue
        used.add(key)

        if kind == "VOLUME_DROP":
            factor = rng.uniform(0.15, 0.45)
            row["txn_cnt"] = max(0, int(row["txn_cnt"] * factor))
            row["declined_cnt"] = min(row["declined_cnt"], row["txn_cnt"])
            row["approved_cnt"] = row["txn_cnt"] - row["declined_cnt"]
        elif kind == "VOLUME_SPIKE":
            factor = rng.uniform(1.8, 2.4)
            row["txn_cnt"] = int(row["txn_cnt"] * factor)
            row["approved_cnt"] = row["txn_cnt"] - row["declined_cnt"]
        elif kind == "SILENT":
            span = rng.randint(2, 3)
            for shift in range(span):
                if day_index + shift < len(series):
                    target = series[day_index + shift]
                    target["txn_cnt"] = 0
                    target["declined_cnt"] = 0
                    target["approved_cnt"] = 0
                    used.add((target["device_id"], target["txn_date"]))
            row = series[day_index]
        else:
            row["declined_cnt"] = min(row["txn_cnt"] - 1, int(row["txn_cnt"] * rng.uniform(0.3, 0.55)))
            row["approved_cnt"] = row["txn_cnt"] - row["declined_cnt"]

        planted.append({"device_id": row["device_id"], "txn_date": row["txn_date"], "kind": kind})

    rows.sort(key=lambda r: (r["device_id"], r["txn_date"]))
    header = ["device_id", "device_type", "partner_name", "city", "txn_date", "txn_cnt",
              "declined_cnt", "approved_cnt", "avg_amount_kop", "uptime_min"]
    write_csv(out_dir / "device_daily.csv", header, [[r[k] for k in header] for r in rows])

    meta = {
        "seed": seed,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "devices": len(fleet),
        "rows": len(rows),
        "planted": sorted(planted, key=lambda p: (p["device_id"], p["txn_date"])),
        "planted_counts": {kind: sum(1 for p in planted if p["kind"] == kind) for kind in kinds},
    }
    (out_dir / "_planted_anomalies.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Генерация суточных рядов по терминалам")
    parser.add_argument("--devices", type=int, default=120)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--end-date", default="2026-10-31")
    args = parser.parse_args()
    meta = generate(args.devices, args.days, args.seed, args.end_date)
    print(f"период {meta['period_start']} — {meta['period_end']}, "
          f"устройств {meta['devices']}, строк {meta['rows']}")
    for kind, count in meta["planted_counts"].items():
        print(f"  {kind:14s} {count}")


if __name__ == "__main__":
    main()
