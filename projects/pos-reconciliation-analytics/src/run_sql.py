"""Прогон SQL-слоя: применяет скрипты из sql/ по порядку и выгружает витрины в CSV."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "warehouse.sqlite"
BI_DIR = ROOT / "data" / "processed"
REPORT_DIR = ROOT / "reports"

SEP = ";"
ENCODING = "utf-8-sig"

SQL_FILES = [
    "02_staging_clean.sql",
    "03_reconciliation.sql",
    "04_control_totals.sql",
    "05_marts.sql",
]

EXPORT_TABLES = {
    "warehouse": [
        "mart_kpi",
        "mart_recon_summary",
        "mart_partner_daily",
        "mart_device_sla",
        "mart_fleet_summary",
        "mart_error_codes",
        "control_totals",
    ],
    "reports": [
        "recon_exceptions",
    ],
}


def run_scripts(conn: sqlite3.Connection, sql_dir: Path = SQL_DIR, verbose: bool = True) -> None:
    for name in SQL_FILES:
        path = sql_dir / name
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.commit()
        if verbose:
            print(f"  применён {name}")


def export_table(conn: sqlite3.Connection, table: str, target: Path) -> int:
    cursor = conn.execute(f"SELECT * FROM {table}")
    header = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding=ENCODING) as fh:
        writer = csv.writer(fh, delimiter=SEP)
        writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def export_all(conn: sqlite3.Connection, db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for folder, tables in EXPORT_TABLES.items():
        target_dir = BI_DIR if folder == "warehouse" else REPORT_DIR
        for table in tables:
            counts[table] = export_table(conn, table, target_dir / f"{table}.csv")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Применение SQL и выгрузка витрин")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"нет БД {db_path}; сначала запустите src/build_db.py")
    conn = sqlite3.connect(db_path)
    try:
        run_scripts(conn)
        counts = export_all(conn, db_path)
    finally:
        conn.close()
    for table, count in counts.items():
        print(f"{table:22s} {count:>8,d}".replace(",", " "))


if __name__ == "__main__":
    main()
