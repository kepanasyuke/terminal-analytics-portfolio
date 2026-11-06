"""Генератор парка терминалов и потока инцидентов с договорными SLA.

Воспроизводит типичную картину сервисного контракта на парк УС/POS:
  * устройства разных типов и вендоров;
  * договоры с месячной платой, нормативами реакции и решения и штрафом за просрочку;
  * инциденты с каналами обращения, повторными обращениями и «хроническими» устройствами.

Все суммы — в копейках. Заведомо известные особенности (устройства-кандидаты на замену)
сохраняются в data/raw/_planted.json, чтобы отчёт можно было проверить тестом.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SEP = ";"
ENC = "utf-8-sig"

PARTNERS = [
    ("P-01", "Северный Ритейл", 2_400_000_00, 4, 8, 24),
    ("P-02", "Телеком-С", 1_150_000_00, 4, 8, 24),
    ("P-03", "Транспорт-Юг", 980_000_00, 2, 6, 12),
    ("P-04", "Банк Партнёр", 3_100_000_00, 2, 4, 8),
    ("P-05", "Аптечная сеть Здоровье+", 640_000_00, 8, 24, 48),
]

MODELS = [
    ("Ingenico", "Move 2500", "POS", 0.34),
    ("Verifone", "VX 820", "POS", 0.22),
    ("PAX", "A920 Pro", "POS", 0.14),
    ("Sagemcom", "Kiosk S10", "KIOSK", 0.14),
    ("НТЦ Измеритель", "Киоск-М", "KIOSK", 0.08),
    ("Diebold Nixdorf", "CS 280", "ATM", 0.08),
]

CITIES = [("Москва", "Москва"), ("Санкт-Петербург", "Санкт-Петербург"),
          ("Приволжский", "Казань"), ("Уральский", "Екатеринбург"),
          ("Сибирский", "Новосибирск"), ("Южный", "Краснодар")]

ERRORS = [
    ("ERR-05", "Таймаут ответа хоста", "LINK"),
    ("ERR-11", "Закончилась бумага", "CONSUMABLE"),
    ("ERR-23", "Ошибка чтения карты", "HARDWARE"),
    ("ERR-41", "Пин-пад не отвечает", "HARDWARE"),
    ("ERR-52", "Потеря связи с процессингом", "LINK"),
    ("ERR-63", "Замятие в диспенсере", "HARDWARE"),
    ("ERR-77", "Коннектор недоступен", "LINK"),
]

CHANNELS = [("PHONE", 0.42), ("PORTAL", 0.31), ("MONITORING", 0.27)]
INCIDENT_RATE = {"POS": 0.030, "KIOSK": 0.155, "ATM": 0.125}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=ENC) as fh:
        writer = csv.writer(fh, delimiter=SEP)
        writer.writerow(header)
        writer.writerows(rows)


def weighted(rng: random.Random, pairs):
    roll = rng.random()
    acc = 0.0
    for item in pairs:
        acc += item[-1]
        if roll <= acc:
            return item
    return pairs[-1]


def generate(devices_cnt: int = 90, days: int = 60, seed: int = 4242,
             end_date: str = "2026-10-31", out_dir: Path = RAW) -> dict:
    rng = random.Random(seed)
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=days - 1)

    contract_rows = []
    for idx, (pid, name, fee, p1, p2, p3) in enumerate(PARTNERS, start=1):
        contract_rows.append([
            f"C-{idx:03d}", pid, name, fee, p1, p2, p3,
            0.1, 10.0, "2026-01-01", "2026-12-31",
        ])

    devices = []
    for idx in range(devices_cnt):
        vendor, model, dtype, _ = weighted(rng, MODELS)
        partner = rng.choice(PARTNERS)
        region, city = rng.choice(CITIES)
        devices.append({
            "device_id": f"{dtype[:2]}-{200000 + idx * 3}",
            "serial": f"{vendor[:2].upper()}{rng.randint(10**8, 10**9 - 1)}",
            "vendor": vendor,
            "model": model,
            "device_type": dtype,
            "partner_id": partner[0],
            "partner_name": partner[1],
            "contract_id": contract_rows[[c[1] for c in contract_rows].index(partner[0])][0],
            "region": region,
            "city": city,
            "install_date": (end - timedelta(days=rng.randint(90, 1800))).isoformat(),
            "status": "ACTIVE" if rng.random() > 0.05 else "SERVICE",
        })

    # «Хронические» устройства: 3–5% парка, которые ломаются постоянно.
    chronic = rng.sample(devices, max(2, devices_cnt // 25))
    for device in chronic:
        device["status"] = "ACTIVE"

    incidents = []
    for device in devices:
        rate = INCIDENT_RATE[device["device_type"]]
        if device["status"] == "SERVICE":
            rate *= 2.0
        if device in chronic:
            rate *= 4.0
        for day_offset in range(days):
            day = start + timedelta(days=day_offset)
            occurrences = 0
            if rng.random() < rate / 2:
                occurrences = 1
            if rng.random() < rate / 12:
                occurrences = 2
            for _ in range(occurrences):
                opened = datetime(day.year, day.month, day.day,
                                  rng.randint(7, 21), rng.randint(0, 59), rng.randint(0, 59))
                severity = rng.choices([1, 2, 3, 4], weights=[0.08, 0.30, 0.44, 0.18])[0]
                code, text, family = rng.choice(ERRORS)
                contract = next(c for c in contract_rows if c[0] == device["contract_id"])
                sla_hours = {1: contract[4], 2: contract[5], 3: contract[6]}[severity] \
                    if severity in (1, 2, 3) else contract[6]
                if device in chronic:
                    sla_hours = max(2, sla_hours // 2)

                sla_minutes = sla_hours * 60
                if rng.random() < 0.92:
                    response_minutes = rng.randint(3, max(4, int(sla_minutes * 0.20)))
                else:
                    response_minutes = rng.randint(int(sla_minutes * 0.26), int(sla_minutes * 0.6))
                first_response = opened + timedelta(minutes=response_minutes)
                if rng.random() < 0.88:
                    resolution_minutes = rng.randint(
                        response_minutes + 5, max(response_minutes + 6, int(sla_minutes * 0.95)))
                else:
                    resolution_minutes = rng.randint(
                        int(sla_minutes * 1.05), int(sla_minutes * 2.2))
                closed = opened + timedelta(minutes=resolution_minutes)
                if rng.random() < 0.04:
                    closed = None
                incidents.append({
                    "incident_id": "",
                    "device_id": device["device_id"],
                    "contract_id": device["contract_id"],
                    "opened_at": opened,
                    "first_response_at": first_response,
                    "closed_at": closed,
                    "severity": severity,
                    "channel": weighted(rng, CHANNELS)[0],
                    "error_code": code,
                    "error_text": text,
                    "family": family,
                    "sla_hours": sla_hours,
                })

    incidents.sort(key=lambda row: row["opened_at"])
    for idx, incident in enumerate(incidents, start=1):
        incident["incident_id"] = f"INC-{idx:06d}"

    # Повторные обращения: тот же девайс в течение 7 дней после закрытия.
    repeats = set()
    by_device: dict[str, list[dict]] = {}
    for incident in incidents:
        by_device.setdefault(incident["device_id"], []).append(incident)
    for device_id, items in by_device.items():
        for prev, nxt in zip(items, items[1:]):
            if prev["closed_at"] and (nxt["opened_at"] - prev["closed_at"]).days <= 7:
                repeats.add(nxt["incident_id"])

    write_csv(out_dir / "period.csv",
              ["period_start", "period_end", "period_days"],
              [[start.isoformat(), end.isoformat(), days]])
    write_csv(out_dir / "contracts.csv",
              ["contract_id", "partner_id", "partner_name", "monthly_fee_kop", "p1_hours",
               "p2_hours", "p3_hours", "penalty_per_hour_pct", "penalty_cap_pct",
               "period_from", "period_to"],
              contract_rows)
    write_csv(out_dir / "devices.csv",
              ["device_id", "serial", "vendor", "model", "device_type", "partner_id",
               "partner_name", "contract_id", "region", "city", "install_date", "status"],
              [[d[k] for k in ("device_id", "serial", "vendor", "model", "device_type",
                               "partner_id", "partner_name", "contract_id", "region", "city",
                               "install_date", "status")] for d in devices])
    write_csv(out_dir / "incidents.csv",
              ["incident_id", "device_id", "contract_id", "opened_at", "first_response_at",
               "closed_at", "severity", "channel", "error_code", "error_text", "family",
               "sla_hours"],
              [[i["incident_id"], i["device_id"], i["contract_id"],
                i["opened_at"].isoformat(sep=" "),
                i["first_response_at"].isoformat(sep=" "),
                i["closed_at"].isoformat(sep=" ") if i["closed_at"] else None,
                i["severity"], i["channel"], i["error_code"], i["error_text"], i["family"],
                i["sla_hours"]] for i in incidents])

    meta = {
        "seed": seed,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "devices": len(devices),
        "incidents": len(incidents),
        "repeat_incidents": len(repeats),
        "chronic_devices": sorted(d["device_id"] for d in chronic),
    }
    (out_dir / "_planted.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Генерация парка, договоров и инцидентов")
    parser.add_argument("--devices", type=int, default=90)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--end-date", default="2026-10-31")
    args = parser.parse_args()
    meta = generate(args.devices, args.days, args.seed, args.end_date)
    print(f"период {meta['period_start']} — {meta['period_end']}")
    print(f"устройств {meta['devices']}, инцидентов {meta['incidents']}, "
          f"повторных {meta['repeat_incidents']}")


if __name__ == "__main__":
    main()
