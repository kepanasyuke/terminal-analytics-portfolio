"""Загрузка сырых CSV в SQLite: создаёт БД, применяет схему и наполняет staging-таблицы."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "warehouse.sqlite"

SEP = ";"
ENCODING = "utf-8-sig"

LOAD_PLAN = [
    ("dim_device", "devices.csv", set()),
    ("dim_merchant", "merchants.csv", set()),
    ("fact_incident", "incidents.csv", {"severity"}),
    ("stg_terminal", "terminal_journal.csv", {"amount_kop"}),
    ("stg_acquiring", "acquiring_settlement.csv", {"amount_kop"}),
]


def load_csv(conn: sqlite3.Connection, table: str, csv_name: str, int_columns: set[str],
             raw_dir: Path = RAW_DIR) -> int:
    path = raw_dir / csv_name
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/generate_data.py")
    with path.open(newline="", encoding=ENCODING) as fh:
        reader = csv.reader(fh, delimiter=SEP)
        header = next(reader)
        rows = [
            [
                None if value == "" else (int(value) if header[idx] in int_columns else value)
                for idx, value in enumerate(raw)
            ]
            for raw in reader
        ]
    placeholders = ", ".join("?" for _ in header)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(header)}) VALUES ({placeholders})", rows
    )
    return len(rows)


def build(db_path: Path = DB_PATH, raw_dir: Path = RAW_DIR,
          sql_dir: Path = SQL_DIR) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript((sql_dir / "01_schema.sql").read_text(encoding="utf-8"))
        counts = {
            table: load_csv(conn, table, csv_name, ints, raw_dir)
            for table, csv_name, ints in LOAD_PLAN
        }
        conn.commit()
        return counts
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка CSV в SQLite")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    counts = build(Path(args.db))
    for table, count in counts.items():
        print(f"{table:16s} {count:>10,d}".replace(",", " "))


if __name__ == "__main__":
    main()
