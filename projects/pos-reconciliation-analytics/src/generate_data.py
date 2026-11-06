"""Генератор синтетических данных терминальной сети (POS, киоски самообслуживания, банкоматы).

Создаёт два независимых источника, имитирующих реальный ландшафт:
  * terminal_journal.csv  — журнал операций со стороны терминальной сети (TMS);
  * acquiring_settlement.csv — проводки и расчёты со стороны процессинга/эквайринга.

Источники намеренно расходятся: в данные закладывается известный набор дефектов,
чтобы модуль сверки можно было проверить по эталону (см. _injected_defects.json).

Все суммы хранятся в копейках (целое число) — арифметика по деньгам без плавающей точки.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

SEP = ";"
ENCODING = "utf-8-sig"

PARTNERS = [
    {"partner_id": "P-01", "partner_name": "Северный Ритейл", "segment": "retail", "merchants": 3},
    {"partner_id": "P-02", "partner_name": "Телеком-С", "segment": "telecom", "merchants": 2},
    {"partner_id": "P-03", "partner_name": "Транспорт-Юг", "segment": "transport", "merchants": 2},
    {"partner_id": "P-04", "partner_name": "Банк Партнёр", "segment": "bank", "merchants": 2},
    {"partner_id": "P-05", "partner_name": "Аптечная сеть Здоровье+", "segment": "retail", "merchants": 2},
    {"partner_id": "P-06", "partner_name": "Топливная компания Магистраль", "segment": "fuel", "merchants": 2},
]

REGIONS = [
    ("Москва", "Москва"),
    ("Санкт-Петербург", "Санкт-Петербург"),
    ("Приволжский", "Казань"),
    ("Приволжский", "Нижний Новгород"),
    ("Уральский", "Екатеринбург"),
    ("Сибирский", "Новосибирск"),
    ("Южный", "Краснодар"),
]

DEVICE_MODELS = [
    ("Ingenico", "Move 2500", "POS"),
    ("Verifone", "VX 820", "POS"),
    ("PAX", "A920 Pro", "POS"),
    ("Sagemcom", "Kiosk S10", "KIOSK"),
    ("НТЦ Измеритель", "Киоск-М", "KIOSK"),
    ("Diebold Nixdorf", "CS 280", "ATM"),
    ("GRG Banking", "H68N", "ATM"),
]

ERROR_CODES = [
    ("ERR-05", "TIMEOUT HOST", "Таймаут ответа хоста"),
    ("ERR-11", "NO PAPER", "Закончилась бумага"),
    ("ERR-23", "CARD READER", "Ошибка чтения карты"),
    ("ERR-41", "PINPAD OFFLINE", "Пин-пад не отвечает"),
    ("ERR-52", "LINK LOST", "Потеря связи с процессингом"),
    ("ERR-63", "DISPENSER JAM", "Замятие в диспенсере"),
    ("ERR-77", "CONNECTOR DOWN", "Коннектор недоступен"),
]

DECLINE_ERRORS = ["ERR-05", "ERR-23", "ERR-41", "ERR-52"]
SLA_HOURS = {1: 4, 2: 8, 3: 24, 4: 72}

TXN_PER_DAY = {"POS": 62, "KIOSK": 118, "ATM": 74}
OP_TYPES = {
    "POS": [("PURCHASE", 0.90), ("REFUND", 0.10)],
    "KIOSK": [("PAYMENT", 0.78), ("PURCHASE", 0.22)],
    "ATM": [("CASHOUT", 0.72), ("PAYMENT", 0.28)],
}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=ENCODING) as fh:
        writer = csv.writer(fh, delimiter=SEP)
        writer.writerow(header)
        writer.writerows(rows)


def business_ts(rng: random.Random, day: date) -> datetime:
    """Время операции с суточным профилем: пик 12–19, ночной минимум."""
    roll = rng.random()
    if roll < 0.06:
        hour = rng.randint(0, 6)
        minute = rng.randint(0, 59)
    elif roll < 0.55:
        hour = rng.randint(8, 12)
        minute = rng.randint(0, 59)
    else:
        hour = rng.randint(13, 20)
        minute = rng.randint(0, 59)
    return datetime(day.year, day.month, day.day, hour, minute, rng.randint(0, 59))


def pick_weighted(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    roll = rng.random()
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if roll <= acc:
            return value
    return pairs[-1][0]


def build_devices(rng: random.Random, count: int, end_date: date) -> list[dict]:
    devices = []
    weights = [0.30, 0.22, 0.16, 0.10, 0.08, 0.08, 0.06]
    for idx in range(count):
        vendor, model, device_type = rng.choices(DEVICE_MODELS, weights=weights, k=1)[0]
        partner = rng.choice(PARTNERS)
        region, city = rng.choice(REGIONS)
        install = end_date - timedelta(days=rng.randint(60, 1500))
        status = "ACTIVE"
        if rng.random() < 0.04:
            status = "SERVICE"
        elif rng.random() < 0.02:
            status = "DECOMMISSIONED"
        devices.append(
            {
                "device_id": f"{device_type[:2]}-{100000 + idx * 7}",
                "serial": f"{vendor[:2].upper()}{rng.randint(10**8, 10**9 - 1)}",
                "vendor": vendor,
                "model": model,
                "device_type": device_type,
                "partner_id": partner["partner_id"],
                "partner_name": partner["partner_name"],
                "region": region,
                "city": city,
                "install_date": install.isoformat(),
                "status": status,
                "sw_version": f"4.{rng.randint(1, 9)}.{rng.randint(0, 20)}",
            }
        )
    return devices


def build_merchants() -> list[dict]:
    merchants = []
    seq = 1
    for partner in PARTNERS:
        for i in range(partner["merchants"]):
            merchants.append(
                {
                    "merchant_id": f"MID{seq:05d}",
                    "partner_id": partner["partner_id"],
                    "partner_name": partner["partner_name"],
                    "segment": partner["segment"],
                    "merchant_name": f"{partner['partner_name']} / точка {i + 1}",
                }
            )
            seq += 1
    return merchants


def build_incidents(rng: random.Random, devices: list[dict], days: int, end_date: date) -> list[dict]:
    incidents = []
    start_date = end_date - timedelta(days=days - 1)
    for device in devices:
        rate = {"POS": 0.06, "KIOSK": 0.34, "ATM": 0.28}[device["device_type"]]
        if device["status"] == "SERVICE":
            rate *= 2.2
        for day_offset in range(days):
            if rng.random() > rate / 3:
                continue
            day = start_date + timedelta(days=day_offset)
            opened = business_ts(rng, day)
            severity = rng.choices([1, 2, 3, 4], weights=[0.10, 0.32, 0.42, 0.16], k=1)[0]
            code, symptom_short, symptom = rng.choice(ERROR_CODES)
            if severity == 1:
                duration = rng.randint(40, 60 * 8) // (1 if rng.random() < 0.5 else 3)
            elif severity == 2:
                duration = rng.randint(30, 60 * 12)
            elif severity == 3:
                duration = rng.randint(30, 60 * 40)
            else:
                duration = rng.randint(60, 60 * 96)
            closed = opened + timedelta(minutes=duration)
            still_open = rng.random() < 0.03
            incidents.append(
                {
                    "incident_id": "",
                    "device_id": device["device_id"],
                    "opened_at": opened,
                    "closed_at": None if still_open else closed,
                    "severity": severity,
                    "error_code": code,
                    "error_text": symptom_short,
                    "symptom": symptom,
                    "source_system": rng.choice(["TMS", "SERVICE_DESK"]),
                }
            )
    incidents.sort(key=lambda item: item["opened_at"])
    for idx, incident in enumerate(incidents, start=1):
        incident["incident_id"] = f"INC-{idx:06d}"
    return incidents


def build_transactions(
    rng: random.Random,
    devices: list[dict],
    merchants: list[dict],
    days: int,
    end_date: date,
) -> list[dict]:
    """Формирует «истинный» поток операций: эталон, от которого строятся оба источника."""
    start_date = end_date - timedelta(days=days - 1)
    partner_merchants: dict[str, list[str]] = {}
    for merchant in merchants:
        partner_merchants.setdefault(merchant["partner_id"], []).append(merchant["merchant_id"])

    counter = rng.randint(10**11, 5 * 10**11)
    txns: list[dict] = []
    for device in devices:
        if device["status"] == "DECOMMISSIONED":
            continue
        base = TXN_PER_DAY[device["device_type"]]
        mids = partner_merchants[device["partner_id"]]
        for day_offset in range(days):
            day = start_date + timedelta(days=day_offset)
            weekend_boost = 1.25 if day.weekday() >= 5 else 1.0
            volume = max(0, int(rng.gauss(base, base * 0.28) * weekend_boost))
            for _ in range(volume):
                counter += 1
                rrn = f"{counter:012d}"
                ts = business_ts(rng, day)
                op_type = pick_weighted(rng, OP_TYPES[device["device_type"]])
                if device["device_type"] == "ATM":
                    amount = rng.randrange(1000, 1500000, 100)
                elif op_type == "REFUND":
                    amount = -rng.randrange(5000, 900000, 100)
                else:
                    amount = rng.randrange(15000, 780000, 100)
                status = rng.choices(["APPROVED", "DECLINED", "REVERSED"], weights=[0.885, 0.095, 0.02], k=1)[0]
                error_code = ""
                if status in {"DECLINED", "REVERSED"}:
                    error_code = rng.choice(DECLINE_ERRORS)
                txns.append(
                    {
                        "rrn": rrn,
                        "device_id": device["device_id"],
                        "device_type": device["device_type"],
                        "partner_id": device["partner_id"],
                        "merchant_id": rng.choice(mids),
                        "txn_ts": ts,
                        "op_type": op_type,
                        "amount_kop": amount,
                        "currency": "RUB",
                        "status": status,
                        "auth_code": f"{rng.randint(0, 999999):06d}",
                        "error_code": error_code,
                    }
                )
    txns.sort(key=lambda item: item["txn_ts"])
    return txns


def split_aware(rng: random.Random, items: list, share: float) -> tuple[list, list]:
    """Делит список на две непересекающиеся части с заданной долей в первой."""
    shuffled = items[:]
    rng.shuffle(shuffled)
    cut = int(len(shuffled) * share)
    return shuffled[:cut], shuffled[cut:]


def inject_defects(rng: random.Random, truth: list[dict], devices: list[dict]) -> dict:
    """Строит оба источника из эталона и фиксирует внесённые расхождения."""
    used_rrn = {t["rrn"] for t in truth}

    def new_rrn() -> str:
        while True:
            candidate = f"{rng.randint(100000000000, 999999999999):012d}"
            if candidate not in used_rrn:
                used_rrn.add(candidate)
                return candidate

    touched: set[str] = set()
    defects: dict[str, list[str]] = {
        "missing_in_acquiring": [],
        "missing_in_terminal": [],
        "terminal_only": [],
        "acquiring_only": [],
        "amount_mismatch": [],
        "status_mismatch": [],
        "timestamp_drift": [],
        "duplicate_in_acquiring": [],
    }

    candidates = list(truth)

    def take(share: float) -> list[dict]:
        nonlocal candidates
        chunk, candidates = split_aware(rng, candidates, share)
        return chunk

    for row in take(0.0040):
        defects["missing_in_acquiring"].append(row["rrn"])

    for row in take(0.0010):
        defects["missing_in_terminal"].append(row["rrn"])

    # Снимок журнала терминалов делается до мутаций: дальше правки идут только в процессинг.
    terminal_rows = [dict(t) for t in truth]

    for row in take(0.0030):
        delta = rng.choice([-1, 1]) * rng.randrange(1, 500)
        row["amount_kop"] += delta
        defects["amount_mismatch"].append(row["rrn"])

    for row in take(0.0020):
        row["status"] = "APPROVED" if row["status"] != "APPROVED" else "DECLINED"
        row["error_code"] = "" if row["status"] == "APPROVED" else "ERR-05"
        defects["status_mismatch"].append(row["rrn"])

    for row in take(0.0050):
        row["txn_ts"] = row["txn_ts"] + timedelta(minutes=rng.randint(11, 240))
        defects["timestamp_drift"].append(row["rrn"])

    dup_rows: list[dict] = []
    for row in take(0.0015):
        dup_rows.append(dict(row))
        defects["duplicate_in_acquiring"].append(row["rrn"])

    active = [d for d in devices if d["status"] != "DECOMMISSIONED"]
    for _ in range(max(1, int(len(truth) * 0.0010))):
        defects["terminal_only"].append(new_rrn())
    for _ in range(max(1, int(len(truth) * 0.0020))):
        defects["acquiring_only"].append(new_rrn())

    truth_rrn = {t["rrn"] for t in truth}
    terminal_rows = [t for t in terminal_rows if t["rrn"] not in set(defects["missing_in_terminal"])]
    acquiring_rows = [t for t in truth if t["rrn"] not in set(defects["missing_in_acquiring"])]
    acquiring_rows = acquiring_rows + dup_rows

    def synth(rrn: str) -> dict:
        device = rng.choice(active)
        day = truth[0]["txn_ts"].date() + timedelta(days=rng.randint(0, 29))
        op_type = pick_weighted(rng, OP_TYPES[device["device_type"]])
        return {
            "rrn": rrn,
            "device_id": device["device_id"],
            "device_type": device["device_type"],
            "partner_id": device["partner_id"],
            "merchant_id": f"MID{rng.randint(1, 13):05d}",
            "txn_ts": business_ts(rng, day),
            "op_type": op_type,
            "amount_kop": rng.randrange(15000, 600000, 100),
            "currency": "RUB",
            "status": rng.choice(["APPROVED", "DECLINED"]),
            "auth_code": f"{rng.randint(0, 999999):06d}",
            "error_code": "",
        }

    for rrn in defects["terminal_only"]:
        terminal_rows.append(synth(rrn))
    for rrn in defects["acquiring_only"]:
        acquiring_rows.append(synth(rrn))

    terminal_rows.sort(key=lambda item: item["txn_ts"])
    acquiring_rows.sort(key=lambda item: item["txn_ts"])
    meta = {
        "seed": None,
        "truth_rows": len(truth),
        "terminal_rows": len(terminal_rows),
        "acquiring_rows": len(acquiring_rows),
        "injected": {key: sorted(value) for key, value in defects.items()},
        "injected_counts": {key: len(value) for key, value in defects.items()},
        "known_truth_rrn_count": len(truth_rrn),
    }
    return {"terminal": terminal_rows, "acquiring": acquiring_rows, "meta": meta}


def generate(devices: int = 80, days: int = 30, seed: int = 20260101, end_date: str = "2026-10-31",
             out_dir: Path = RAW_DIR) -> dict:
    rng = random.Random(seed)
    end = date.fromisoformat(end_date)
    device_rows = build_devices(rng, devices, end)
    merchant_rows = build_merchants()
    incident_rows = build_incidents(rng, device_rows, days, end)
    truth = build_transactions(rng, device_rows, merchant_rows, days, end)
    split = inject_defects(rng, truth, device_rows)
    split["meta"]["seed"] = seed

    write_csv(
        out_dir / "devices.csv",
        ["device_id", "serial", "vendor", "model", "device_type", "partner_id", "partner_name",
         "region", "city", "install_date", "status", "sw_version"],
        [[d[k] for k in ("device_id", "serial", "vendor", "model", "device_type", "partner_id",
                         "partner_name", "region", "city", "install_date", "status", "sw_version")]
         for d in device_rows],
    )
    write_csv(
        out_dir / "merchants.csv",
        ["merchant_id", "partner_id", "partner_name", "segment", "merchant_name"],
        [[m["merchant_id"], m["partner_id"], m["partner_name"], m["segment"], m["merchant_name"]]
         for m in merchant_rows],
    )
    write_csv(
        out_dir / "incidents.csv",
        ["incident_id", "device_id", "opened_at", "closed_at", "severity", "error_code",
         "error_text", "symptom", "source_system"],
        [[i["incident_id"], i["device_id"], i["opened_at"].isoformat(sep=" "),
          i["closed_at"].isoformat(sep=" ") if i["closed_at"] else "", i["severity"],
          i["error_code"], i["error_text"], i["symptom"], i["source_system"]]
         for i in incident_rows],
    )
    txn_header = ["rrn", "device_id", "device_type", "partner_id", "merchant_id", "txn_ts",
                  "op_type", "amount_kop", "currency", "status", "auth_code", "error_code"]
    write_csv(
        out_dir / "terminal_journal.csv",
        txn_header,
        [[row[k].isoformat(sep=" ") if k == "txn_ts" else row[k] for k in txn_header]
         for row in split["terminal"]],
    )
    write_csv(
        out_dir / "acquiring_settlement.csv",
        txn_header + ["settlement_date"],
        [[row[k].isoformat(sep=" ") if k == "txn_ts" else row[k] for k in txn_header]
         + [row["txn_ts"].date().isoformat()] for row in split["acquiring"]],
    )
    meta = split["meta"]
    (out_dir / "_injected_defects.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Генерация синтетических данных терминальной сети")
    parser.add_argument("--devices", type=int, default=80, help="количество устройств")
    parser.add_argument("--days", type=int, default=30, help="горизонт данных в днях")
    parser.add_argument("--seed", type=int, default=20260101)
    parser.add_argument("--end-date", default="2026-10-31")
    parser.add_argument("--out", default=str(RAW_DIR))
    args = parser.parse_args()

    meta = generate(args.devices, args.days, args.seed, args.end_date, Path(args.out))
    print(f"устройств: {len(list(csv_reader(args.out, 'devices.csv'))) - 1}")
    print(f"операций в эталоне: {meta['truth_rows']}")
    print(f"журнал терминалов: {meta['terminal_rows']}, процессинг: {meta['acquiring_rows']}")
    print("внесённые расхождения:")
    for kind, count in meta["injected_counts"].items():
        print(f"  {kind:24s} {count}")


def csv_reader(out_dir: str, name: str):
    with open(Path(out_dir) / name, newline="", encoding=ENCODING) as fh:
        yield from csv.reader(fh, delimiter=SEP)


if __name__ == "__main__":
    main()
