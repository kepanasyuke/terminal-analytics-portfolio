"""Обезличивание данных перед передачей заказчику.

Правила:
  * номер карты (PAN) — остаётся BIN (первые 6) и последние 4 цифры;
  * серийный номер устройства — префикс вендора + маска;
  * телефон и e-mail — маскируются;
  * RRN и идентификаторы устройств по умолчанию НЕ маскируются (по ним идёт сверка),
    но при необходимости псевдонимизируются: одна и та же операция получает
    один и тот же токен, поэтому соединения в отчёте не ломаются.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

SEP = ";"
ENCODING = "utf-8-sig"

PAN_RE = re.compile(r"^\d{12,19}$")
PHONE_RE = re.compile(r"^(\+?7|8)?[\s\-()]*(\d{3})[\s\-()]*(\d{3})[\s\-()]*(\d{2})[\s\-()]*(\d{2})$")
EMAIL_RE = re.compile(r"^([^@]{1,64})@(.+)$")

DEFAULT_SALT = "project-salt-change-me"


def mask_pan(pan: str | None) -> str | None:
    digits = re.sub(r"\D", "", pan or "")
    if not PAN_RE.match(digits):
        return pan
    return f"{digits[:6]}{'*' * (len(digits) - 10)}{digits[-4:]}"


def mask_serial(serial: str | None) -> str | None:
    if not serial:
        return serial
    cleaned = str(serial).strip()
    if len(cleaned) <= 4:
        return "*" * len(cleaned)
    return f"{cleaned[:2]}{'*' * (len(cleaned) - 6)}{cleaned[-4:]}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    match = PHONE_RE.match(str(phone).strip())
    if not match:
        return phone
    return f"+7 *** ***-**-{match.group(5)}"


def mask_email(email: str | None) -> str | None:
    if not email:
        return email
    match = EMAIL_RE.match(str(email).strip())
    if not match:
        return email
    local, domain = match.group(1), match.group(2)
    head = local[:1] if local else ""
    return f"{head}***@{domain}"


def tokenize(value: str | None, salt: str = DEFAULT_SALT, prefix: str = "TKN") -> str | None:
    if value in (None, ""):
        return value
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest.upper()}"


def masked_row(row: dict, salt: str = DEFAULT_SALT, tokenize_ids: bool = False) -> dict:
    result = dict(row)
    for column, value in row.items():
        lowered = column.lower()
        if lowered in {"pan", "card_number", "pan_masked"}:
            result[column] = mask_pan(value)
        elif lowered in {"serial", "serial_number"}:
            result[column] = mask_serial(value)
        elif lowered in {"phone", "msisdn", "phone_number"}:
            result[column] = mask_phone(value)
        elif lowered in {"email", "e_mail"}:
            result[column] = mask_email(value)
        elif tokenize_ids and lowered in {"rrn", "auth_code"}:
            result[column] = tokenize(value, salt, prefix="RRN")
    return result


def anonymize_file(source: Path, target: Path, salt: str = DEFAULT_SALT,
                   tokenize_ids: bool = False) -> int:
    with source.open(newline="", encoding=ENCODING) as fh:
        reader = csv.DictReader(fh, delimiter=SEP)
        header = reader.fieldnames or []
        rows = [masked_row(row, salt, tokenize_ids) for row in reader]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding=ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=header, delimiter=SEP)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Обезличивание выгрузки перед передачей заказчику")
    parser.add_argument("--in", dest="source", default=str(REPORT_DIR / "recon_exceptions.csv"))
    parser.add_argument("--out", dest="target", default=str(REPORT_DIR / "recon_exceptions_masked.csv"))
    parser.add_argument("--salt", default=DEFAULT_SALT)
    parser.add_argument("--tokenize-ids", action="store_true",
                        help="псевдонимизировать RRN и auth_code (соединения по токену сохраняются)")
    args = parser.parse_args()
    count = anonymize_file(Path(args.source), Path(args.target), args.salt, args.tokenize_ids)
    print(f"обезличено строк: {count} -> {args.target}")


if __name__ == "__main__":
    main()
