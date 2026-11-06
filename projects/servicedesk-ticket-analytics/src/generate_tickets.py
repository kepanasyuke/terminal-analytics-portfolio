"""Генератор заявок первой линии поддержки терминального парка.

Каждая заявка — текст обращения, канал, приоритет, сроки и «истинная» категория,
известная только генератору. Категория нужна, чтобы измерить качество
автоматической классификации по ключевым словам, а не оценивать её на глаз.
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

CATEGORIES = {
    "PAYMENT": [
        "Терминал не проводит оплату картой",
        "Отказ при оплате, клиент не может оплатить",
        "Ошибка проведения платежа на кассе",
        "Не проходит оплата бесконтактной картой",
    ],
    "CONNECTIVITY": [
        "Нет связи с процессингом",
        "Терминал офлайн, не выходит на хост",
        "Пропала связь, не поднимается канал",
        "Ошибка соединения при авторизации",
    ],
    "HARDWARE": [
        "Не читает карту, ошибка картридера",
        "Пин-пад не реагирует на нажатия",
        "Замятие чека в принтере",
        "Диспенсер замял купюру",
    ],
    "CASH": [
        "Не хватает наличных в кассете",
        "Требуется инкассация терминала",
        "Кассета переполнена, нужен вывоз",
        "Инкассация не приехала по графику",
    ],
    "SOFTWARE": [
        "Терминал завис после обновления",
        "Приложение не запускается на терминале",
        "Белый экран, требуется перезагрузка",
        "Не обновляется версия ПО на устройстве",
    ],
    "CONSULT": [
        "Как отменить операцию клиенту",
        "Как оформить возврат по чеку",
        "Клиент спрашивает, где взять копию чека",
        "Подскажите порядок проведения возврата",
    ],
    "ACCESS": [
        "Нет доступа к терминалу, помещение закрыто",
        "Нужен доступ к инженерному меню",
        "Не пускают к устройству, нет ключа",
        "Требуется доступ в серверную для осмотра",
    ],
}

# Формулировки, которых нет в правилах категоризации: живая речь без ключевых слов.
# Они нужны, чтобы точность правил измерялась честно, а не на тех же словах,
# из которых правила собраны.
HARD_PHRASES = {
    "PAYMENT": ["Клиент говорит, что деньги списались дважды"],
    "CONNECTIVITY": ["Устройство не отвечает на пинги"],
    "HARDWARE": ["Экран треснул после падения"],
    "CASH": ["Купюры закончились, терминал не выдаёт"],
    "SOFTWARE": ["Устройство издаёт звуковой сигнал"],
    "CONSULT": ["Нужна помощь по возврату"],
    "ACCESS": ["Инженер не может попасть на объект"],
}

NOISE_SUFFIX = ["", " (срочно)", ", точка на входе", ", второй терминал", " — повторили"]

CHANNELS = [("PHONE", 0.44), ("PORTAL", 0.31), ("EMAIL", 0.15), ("CHAT", 0.10)]
PRIORITIES = [("P1", 0.10), ("P2", 0.34), ("P3", 0.56)]
SLA_HOURS = {"P1": (2, 8), "P2": (4, 24), "P3": (8, 72)}

AGENTS = ["А. Морозова", "И. Северов", "К. Белова", "Д. Гарин", "М. Полякова",
          "С. Тимофеев", "Е. Ковалёва", "Р. Асланов"]

PARTNERS = ["Северный Ритейл", "Телеком-С", "Транспорт-Юг", "Банк Партнёр",
            "Аптечная сеть Здоровье+", "Топливная компания Магистраль"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Краснодар"]

RESOLUTIONS = {
    "PAYMENT": "Проверен канал и настройки эквайринга, операция проведена повторно",
    "CONNECTIVITY": "Перезапущен канал связи, терминал вышел на хост",
    "HARDWARE": "Заявка передана на выезд инженера, узел заменён",
    "CASH": "Согласован выезд инкассации, кассета заменена",
    "SOFTWARE": "Выполнена удалённая перезагрузка, версия ПО обновлена",
    "CONSULT": "Дана инструкция, обращение закрыто без выезда",
    "ACCESS": "Вопрос доступа согласован с администратором объекта",
}


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


def generate(tickets: int = 2500, days: int = 60, seed: int = 777,
             end_date: str = "2026-10-31", out_dir: Path = RAW) -> dict:
    rng = random.Random(seed)
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=days - 1)

    devices = [
        (f"{dtype}-{400000 + idx * 7}", dtype, rng.choice(PARTNERS), rng.choice(CITIES))
        for idx, dtype in enumerate(
            ["POS" if rng.random() < 0.6 else ("KIOSK" if rng.random() < 0.7 else "ATM")
             for _ in range(140)]
        )
    ]

    rows = []
    category_weights = [
        ("PAYMENT", 0.22), ("CONNECTIVITY", 0.19), ("HARDWARE", 0.17), ("CASH", 0.11),
        ("SOFTWARE", 0.13), ("CONSULT", 0.12), ("ACCESS", 0.06),
    ]
    for idx in range(tickets):
        day = start + timedelta(days=rng.randint(0, days - 1))
        created = datetime(day.year, day.month, day.day, rng.randint(7, 21),
                           rng.randint(0, 59), rng.randint(0, 59))
        category = weighted(rng, category_weights)[0]
        if rng.random() < 0.14:
            subject = rng.choice(HARD_PHRASES[category]) + rng.choice(NOISE_SUFFIX)
        else:
            subject = rng.choice(CATEGORIES[category]) + rng.choice(NOISE_SUFFIX)
        device_id, device_type, partner, city = rng.choice(devices)
        channel = weighted(rng, CHANNELS)[0]
        priority = weighted(rng, PRIORITIES)[0]
        response_sla, resolve_sla = SLA_HOURS[priority]

        if rng.random() < 0.94:
            response_minutes = rng.randint(2, max(3, response_sla * 55))
        else:
            response_minutes = rng.randint(response_sla * 60, response_sla * 150)
        first_response = created + timedelta(minutes=response_minutes)

        if rng.random() < 0.90:
            resolve_minutes = rng.randint(response_minutes + 10, max(response_minutes + 20, resolve_sla * 55))
        else:
            resolve_minutes = rng.randint(resolve_sla * 60, resolve_sla * 180)
        closed = created + timedelta(minutes=resolve_minutes)
        if rng.random() < 0.03:
            closed = None

        rows.append({
            "ticket_id": "",
            "created_at": created,
            "first_response_at": first_response,
            "closed_at": closed,
            "channel": channel,
            "priority": priority,
            "device_id": device_id,
            "device_type": device_type,
            "partner_name": partner,
            "city": city,
            "agent": rng.choice(AGENTS),
            "subject": subject,
            "resolution": RESOLUTIONS[category],
            "category_true": category,
        })

    rows.sort(key=lambda r: r["created_at"])
    for idx, row in enumerate(rows, start=1):
        row["ticket_id"] = f"SD-{idx:06d}"

    header = ["ticket_id", "created_at", "first_response_at", "closed_at", "channel",
              "priority", "device_id", "device_type", "partner_name", "city", "agent",
              "subject", "resolution", "category_true"]
    write_csv(out_dir / "tickets.csv", header, [[
        row["ticket_id"],
        row["created_at"].isoformat(sep=" "),
        row["first_response_at"].isoformat(sep=" "),
        row["closed_at"].isoformat(sep=" ") if row["closed_at"] else None,
        row["channel"], row["priority"], row["device_id"], row["device_type"],
        row["partner_name"], row["city"], row["agent"], row["subject"],
        row["resolution"], row["category_true"],
    ] for row in rows])

    meta = {
        "seed": seed,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "tickets": len(rows),
        "devices": len(devices),
        "categories": {c: sum(1 for r in rows if r["category_true"] == c) for c in CATEGORIES},
    }
    (out_dir / "_tickets_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Генерация заявок поддержки")
    parser.add_argument("--tickets", type=int, default=2500)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--end-date", default="2026-10-31")
    args = parser.parse_args()
    meta = generate(args.tickets, args.days, args.seed, args.end_date)
    print(f"период {meta['period_start']} — {meta['period_end']}, заявок {meta['tickets']}")
    for name, count in meta["categories"].items():
        print(f"  {name:13s} {count}")


if __name__ == "__main__":
    main()
