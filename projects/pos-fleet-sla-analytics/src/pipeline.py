"""Загрузка выгрузок в SQLite, расчёт витрин SLA и выгрузка в CSV."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "sla.sqlite"
OUT_DIR = ROOT / "data" / "processed"

SEP = ";"
ENC = "utf-8-sig"

LOAD_PLAN = [
    ("dim_contract", "contracts.csv", {"monthly_fee_kop", "p1_hours", "p2_hours", "p3_hours",
                                       "penalty_per_hour_pct", "penalty_cap_pct"}),
    ("dim_device", "devices.csv", set()),
    ("fact_incident", "incidents.csv", {"severity", "sla_hours"}),
    ("dim_period", "period.csv", {"period_days"}),
]

SQL_FILES = ["02_marts.sql"]

EXPORT = [
    "mart_kpi", "mart_contract", "mart_penalty_month", "mart_weekly",
    "mart_error_family", "mart_error_code", "mart_channel", "mart_device", "mart_replacement",
]


def load_csv(conn: sqlite3.Connection, table: str, name: str, numerics: set[str],
             raw_dir: Path = RAW) -> int:
    path = raw_dir / name
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/generate_fleet.py")
    with path.open(newline="", encoding=ENC) as fh:
        reader = csv.reader(fh, delimiter=SEP)
        header = next(reader)
        rows = []
        for raw in reader:
            row = []
            for idx, value in enumerate(raw):
                if value == "":
                    row.append(None)
                elif header[idx] in numerics:
                    row.append(float(value) if "." in value else int(value))
                else:
                    row.append(value)
            rows.append(row)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(header)}) VALUES ({', '.join('?' for _ in header)})",
        rows,
    )
    return len(rows)


def run(db_path: Path = DB_PATH, raw_dir: Path = RAW, sql_dir: Path = SQL_DIR,
        out_dir: Path = OUT_DIR, verbose: bool = True) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    counts: dict[str, int] = {}
    try:
        conn.executescript((sql_dir / "01_schema.sql").read_text(encoding="utf-8"))
        for table, name, numerics in LOAD_PLAN:
            counts[table] = load_csv(conn, table, name, numerics, raw_dir)
        for name in SQL_FILES:
            conn.executescript((sql_dir / name).read_text(encoding="utf-8"))
        conn.commit()

        out_dir.mkdir(parents=True, exist_ok=True)
        for table in EXPORT:
            cursor = conn.execute(f"SELECT * FROM {table}")
            header = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            with (out_dir / f"{table}.csv").open("w", newline="", encoding=ENC) as fh:
                writer = csv.writer(fh, delimiter=SEP)
                writer.writerow(header)
                writer.writerows(rows)
            counts[table] = len(rows)
    finally:
        conn.close()
    if verbose:
        for table, count in counts.items():
            print(f"{table:22s} {count:>8,d}".replace(",", " "))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка витрин SLA")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    run(Path(args.db))


if __name__ == "__main__":
    main()
