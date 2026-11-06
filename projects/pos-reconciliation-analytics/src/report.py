"""Отчётный слой: собирает HTML-дашборд и текстовое резюме из витрин SQL.

Никаких внешних зависимостей — только стандартная библиотека, чтобы отчёт
можно было пересобрать на любой машине без установки пакетов.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import defaultdict
from pathlib import Path

try:
    from . import charts
except ImportError:  # запуск как скрипта: python src/report.py
    import charts

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
REPORT_DIR = ROOT / "reports"

SEP = ";"
ENCODING = "utf-8-sig"

EXCEPTION_TITLES = {
    "MISSING_IN_ACQUIRING": "Операция не дошла до процессинга",
    "MISSING_IN_TERMINAL": "Операция есть в процессинге, но нет на терминале",
    "AMOUNT_MISMATCH": "Расходится сумма",
    "STATUS_MISMATCH": "Расходится статус операции",
    "TIMESTAMP_DRIFT": "Расходится время операции (> 10 мин)",
    "DUPLICATE_IN_ACQUIRING": "Дубликат операции в процессинге",
}


def load(name: str, folder: Path = PROCESSED_DIR) -> list[dict]:
    path = folder / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/run_sql.py")
    with path.open(newline="", encoding=ENCODING) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def num(value, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    return float(value)


def rub(kopecks) -> str:
    value = num(kopecks) / 100.0
    sign = "-" if value < 0 else ""
    body = f"{abs(value):,.0f}".replace(",", " ")
    return f"{sign}{body} ₽"


def pct(value) -> str:
    return f"{num(value):.2f}".replace(".", ",") + " %"


def bar(share: float, tone: str = "accent") -> str:
    width = max(0.6, min(100.0, share))
    return (
        f'<div class="bar"><span class="bar-fill bar-{tone}" '
        f'style="width:{width:.1f}%"></span></div>'
    )


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


KPI_CARDS = [
    ("Период", "period", None),
    ("Устройств в парке", "devices_cnt", None),
    ("Операций сверено", "txns_cnt", None),
    ("Оборот по журналу", "amount_kop", rub),
    ("Доля одобренных", "approval_rate_pct", pct),
    ("Доступность парка", "avg_availability_pct", pct),
    ("MTTR", "avg_mttr_hours", lambda v: f"{num(v):.1f} ч"),
    ("Расхождений", "exceptions_cnt", None),
    ("Сумма под риском", "amount_at_risk_kop", rub),
    ("Доля расхождений", "exception_rate_pct", pct),
]


def render_kpi(kpi: dict) -> str:
    cards = []
    for label, key, formatter in KPI_CARDS:
        if key == "period":
            value = f"{esc(kpi.get('period_start'))} — {esc(kpi.get('period_end'))}"
        elif key == "devices_cnt":
            value = f"{esc(kpi.get('devices_cnt'))} <small>из них активных {esc(kpi.get('active_devices_cnt'))}</small>"
        elif key == "txns_cnt":
            value = f"{int(num(kpi.get('txns_cnt'))):,}".replace(",", " ")
        elif key == "exceptions_cnt":
            value = f"{int(num(kpi.get('exceptions_cnt'))):,}".replace(",", " ")
        elif formatter:
            value = formatter(kpi.get(key))
        else:
            value = esc(kpi.get(key))
        cards.append(
            f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value">{value}</div></div>'
        )
    return '<section class="kpi-grid">' + "".join(cards) + "</section>"


def render_recon(recon: list[dict]) -> str:
    total = sum(num(row["exceptions_cnt"]) for row in recon)
    rows = []
    for row in sorted(recon, key=lambda r: -num(r["exceptions_cnt"])):
        share = 100.0 * num(row["exceptions_cnt"]) / total if total else 0
        rows.append(
            "<tr>"
            f'<td><span class="pill sev-{esc(row["severity"])}">P{esc(row["severity"])}</span> '
            f'{esc(EXCEPTION_TITLES.get(row["exception_type"], row["exception_type"]))}</td>'
            f'<td class="num">{int(num(row["exceptions_cnt"])):,}</td>'.replace(",", " ")
            + f'<td>{bar(share)}<span class="share">{share:.1f}%</span></td>'
            f'<td class="num">{rub(row["amount_at_risk_kop"])}</td>'
            f'<td class="num">{esc(row["devices_cnt"])}</td>'
            f'<td class="num">{esc(row["partners_cnt"])}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Сверка терминалы ↔ процессинг</h2>'
        '<p class="hint">Ключ сопоставления — RRN. Одна операция попадает ровно в один класс '
        'расхождений по приоритету: дубликат → пропажа → сумма → статус → время.</p>'
        '<table><thead><tr><th>Класс расхождения</th><th class="num">Случаев</th>'
        '<th>Доля</th><th class="num">Сумма под риском</th><th class="num">Устройств</th>'
        '<th class="num">Партнёров</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></section>"
    )


def render_partners(devices: list[dict], partner_daily: list[dict]) -> str:
    by_partner: dict[str, dict] = defaultdict(lambda: {
        "devices": 0, "availability": [], "txns": 0, "amount": 0.0,
        "exceptions": 0, "at_risk": 0.0,
    })
    for row in devices:
        entry = by_partner[row["partner_name"]]
        entry["devices"] += 1
        entry["availability"].append(num(row["availability_pct"]))
    partner_names = {r["partner_id"]: r["partner_name"] for r in devices}
    for row in partner_daily:
        name = partner_names.get(row["partner_id"], row["partner_id"])
        entry = by_partner[name]
        entry["txns"] += int(num(row["txns_cnt"]))
        entry["amount"] += num(row["amount_kop"])
        entry["exceptions"] += int(num(row["exceptions_cnt"]))
        entry["at_risk"] += num(row["amount_at_risk_kop"])

    total_amount = sum(e["amount"] for e in by_partner.values()) or 1.0
    rows = []
    for name, entry in sorted(by_partner.items(), key=lambda kv: -kv[1]["amount"]):
        availability = (
            sum(entry["availability"]) / len(entry["availability"])
            if entry["availability"] else 0.0
        )
        tone = "bad" if availability < 97 else "accent"
        rows.append(
            "<tr>"
            f"<td>{esc(name)}</td>"
            f'<td class="num">{entry["devices"]}</td>'
            f'<td class="num">{entry["txns"]:,}</td>'.replace(",", " ")
            + f'<td class="num">{rub(entry["amount"])}</td>'
            f'<td>{bar(100.0 * entry["amount"] / total_amount, "muted")}'
            f'<span class="share">{100.0 * entry["amount"] / total_amount:.1f}%</span></td>'
            f'<td class="num">{entry["exceptions"]:,}</td>'.replace(",", " ")
            + f'<td class="num">{rub(entry["at_risk"])}</td>'
            f'<td>{bar(availability, tone)}<span class="share">{availability:.2f}%</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Партнёры</h2>'
        '<table><thead><tr><th>Партнёр</th><th class="num">Устройств</th>'
        '<th class="num">Операций</th><th class="num">Оборот</th><th>Доля оборота</th>'
        '<th class="num">Расхождений</th><th class="num">Под риском</th>'
        '<th>Доступность</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></section>"
    )


def render_devices(devices: list[dict], exceptions: list[dict], limit: int = 12) -> str:
    risk: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in exceptions:
        risk[row["device_id"]] += num(row["amount_at_risk_kop"])
        counts[row["device_id"]] += 1
    worst = sorted(devices, key=lambda r: num(r["availability_pct"]))[:limit]
    rows = []
    for row in worst:
        availability = num(row["availability_pct"])
        tone = "bad" if availability < 95 else ("warn" if availability < 98 else "accent")
        rows.append(
            "<tr>"
            f'<td class="mono">{esc(row["device_id"])}</td>'
            f'<td>{esc(row["device_type"])}</td>'
            f'<td>{esc(row["partner_name"])}</td>'
            f'<td>{esc(row["city"])}</td>'
            f'<td class="num">{int(num(row["incidents_cnt"]))}</td>'
            f'<td>{bar(availability, tone)}<span class="share">{availability:.2f}%</span></td>'
            f'<td class="num">{num(row["downtime_hours"]):.1f} ч</td>'
            f'<td class="num">{counts.get(row["device_id"], 0)}</td>'
            f'<td class="num">{rub(risk.get(row["device_id"], 0))}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Худшие устройства по доступности</h2>'
        '<table><thead><tr><th>Устройство</th><th>Тип</th><th>Партнёр</th><th>Город</th>'
        '<th class="num">Инцидентов</th><th>Доступность</th><th class="num">Простой</th>'
        '<th class="num">Расхождений</th><th class="num">Под риском</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></section>"
    )


def render_errors(errors: list[dict]) -> str:
    rows = []
    for row in errors:
        share = num(row["share_pct"])
        rows.append(
            "<tr>"
            f'<td class="mono">{esc(row["error_code"])}</td>'
            f"<td>{esc(row['error_text'])}</td>"
            f'<td class="num">{int(num(row["incidents_cnt"]))}</td>'
            f'<td>{bar(share * 4, "warn")}<span class="share">{share:.1f}%</span></td>'
            f'<td class="num">{num(row["downtime_hours"]):.1f} ч</td>'
            f'<td class="num">{int(num(row["sla_breach_cnt"]))}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Инциденты по кодам ошибок</h2>'
        '<table><thead><tr><th>Код</th><th>Описание</th><th class="num">Инцидентов</th>'
        '<th>Доля</th><th class="num">Простой</th><th class="num">Нарушений SLA</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
    )


STYLE = """
:root {
  --bg: #f4f6fa; --panel: #ffffff; --ink: #12203a; --muted: #6b7a90;
  --accent: #1f6feb; --warn: #d9821b; --bad: #cf3b45; --line: #e2e8f2;
}
* { box-sizing: border-box; }
body { margin: 0; padding: 32px; background: var(--bg); color: var(--ink);
  font: 14px/1.5 "Segoe UI", Roboto, Arial, sans-serif; }
header { margin-bottom: 24px; }
h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -0.3px; }
h2 { margin: 0 0 12px; font-size: 17px; }
.sub { color: var(--muted); font-size: 13px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 12px; margin-bottom: 22px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; }
.kpi-label { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.4px; margin-bottom: 8px; }
.kpi-value { font-size: 21px; font-weight: 600; }
.kpi-value small { display: block; font-size: 12px; font-weight: 400; color: var(--muted); }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 20px 22px; margin-bottom: 20px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left;
  white-space: nowrap; }
th { color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.3px; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:hover { background: #f8fafd; }
.mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: 13px; }
.bar { display: inline-block; vertical-align: middle; width: 110px; height: 8px;
  background: #edf1f7; border-radius: 6px; overflow: hidden; margin-right: 8px; }
.bar span { display: block; height: 100%; }
.bar-accent { background: var(--accent); }
.bar-warn { background: var(--warn); }
.bar-bad { background: var(--bad); }
.bar-muted { background: #9fb0c8; }
.share { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.pill { display: inline-block; min-width: 26px; text-align: center; padding: 1px 6px;
  border-radius: 999px; font-size: 11px; font-weight: 700; color: #fff; margin-right: 6px; }
.sev-1 { background: var(--bad); } .sev-2 { background: var(--warn); }
.sev-3 { background: var(--accent); } .sev-4 { background: #7c8aa0; }
.hint { color: var(--muted); font-size: 12.5px; margin: 0 0 14px; max-width: 900px; }
footer { color: var(--muted); font-size: 12px; margin-top: 8px; }
"""

STYLE = STYLE + charts.CHART_CSS


def daily_chart(exceptions: list[dict]) -> str:
    by_date: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in exceptions:
        bucket = by_date[row["txn_date"]]
        bucket[0] += 1
        if str(row.get("severity", "")) == "1":
            bucket[1] += 1
    dates = sorted(by_date)
    return charts.chart(
        "Расхождения по дням",
        "Каждый день — сколько операций не сошлось между журналом терминалов и процессингом. "
        "P1 — расхождения, где на кону деньги: пропажи, суммы, дубликаты.",
        {
            "type": "line",
            "labels": [d[5:] for d in dates],
            "area": True,
            "series": [
                {"name": "Все расхождения", "values": [by_date[d][0] for d in dates],
                 "color": "#2563eb"},
                {"name": "Приоритет P1", "values": [by_date[d][1] for d in dates],
                 "color": "#cf3b45"},
            ],
        },
        height=280,
    )


def recon_donut(recon: list[dict]) -> str:
    items = [
        {"name": EXCEPTION_TITLES.get(row["exception_type"], row["exception_type"]),
         "value": int(num(row["exceptions_cnt"]))}
        for row in sorted(recon, key=lambda r: -num(r["exceptions_cnt"]))
    ]
    return charts.chart(
        "Структура расхождений",
        "Доля классов в общем числе расхождений за период.",
        {"type": "donut", "items": items, "centerSub": "расхождений"},
        height=280,
    )



def render_dashboard(kpi, recon, fleet, devices, errors, partner_daily, exceptions) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Терминальная сеть: сверка и доступность</title>
<style>{STYLE}</style>
</head>
<body>
<header>
  <h1>Терминальная сеть: сверка систем и доступность парка</h1>
  <div class="sub">Портфельный проект: два независимых источника (журнал терминалов и процессинг),
  полная сверка по RRN, метрики SLA и отчёт для заказчика. Данные синтетические.</div>
</header>
{render_kpi(kpi[0])}
{daily_chart(exceptions)}
{recon_donut(recon)}
{render_recon(recon)}
{render_partners(devices, partner_daily)}
{render_devices(devices, exceptions)}
{render_errors(errors)}
<footer>Все суммы — в рублях, в источнике суммы хранятся в копейках (INTEGER).
Доступность = 1 − суммарный простой / время наблюдения; пересекающиеся инциденты схлопнуты.</footer>
<script>{charts.CHART_JS}</script>
</body>
</html>
"""


def render_summary(kpi, recon, devices, errors) -> str:
    row = kpi[0]
    lines = [
        "# Резюме по терминальной сети",
        "",
        f"Период: **{row['period_start']} — {row['period_end']}** ({row['period_days']} дней)",
        "",
        "## Ключевые показатели",
        "",
        f"- Устройств в парке: **{row['devices_cnt']}** (активных {row['active_devices_cnt']})",
        f"- Операций сверено: **{int(num(row['txns_cnt'])):,}**".replace(",", " "),
        f"- Оборот по журналу терминалов: **{rub(row['amount_kop'])}**",
        f"- Доля одобренных операций: **{pct(row['approval_rate_pct'])}**",
        f"- Доступность парка: **{pct(row['avg_availability_pct'])}**, MTTR **{num(row['avg_mttr_hours']):.1f} ч**",
        f"- Расхождений между системами: **{int(num(row['exceptions_cnt'])):,}**"
        .replace(",", " ") + f" (доля {pct(row['exception_rate_pct'])}), сумма под риском **{rub(row['amount_at_risk_kop'])}**",
        "",
        "## Расхождения по классам",
        "",
        "| Класс | Случаев | Сумма под риском | Устройств |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in sorted(recon, key=lambda r: -num(r["exceptions_cnt"])):
        title = EXCEPTION_TITLES.get(item["exception_type"], item["exception_type"])
        lines.append(
            f"| {title} | {int(num(item['exceptions_cnt']))} | "
            f"{rub(item['amount_at_risk_kop'])} | {item['devices_cnt']} |"
        )

    lines += ["", "## Устройства с худшей доступностью", "",
              "| Устройство | Тип | Город | Инцидентов | Доступность | Простой, ч |",
              "| --- | --- | --- | ---: | ---: | ---: |"]
    for item in sorted(devices, key=lambda r: num(r["availability_pct"]))[:5]:
        lines.append(
            f"| {item['device_id']} | {item['device_type']} | {item['city']} | "
            f"{item['incidents_cnt']} | {pct(item['availability_pct'])} | "
            f"{num(item['downtime_hours']):.1f} |"
        )

    lines += ["", "## Топ кодов ошибок", "",
              "| Код | Описание | Инцидентов | Простой, ч | Нарушений SLA |",
              "| --- | --- | ---: | ---: | ---: |"]
    for item in sorted(errors, key=lambda r: -num(r["incidents_cnt"]))[:5]:
        lines.append(
            f"| {item['error_code']} | {item['error_text']} | {item['incidents_cnt']} | "
            f"{num(item['downtime_hours']):.1f} | {item['sla_breach_cnt']} |"
        )
    return "\n".join(lines) + "\n"


def build() -> dict[str, Path]:
    kpi = load("mart_kpi")
    recon = load("mart_recon_summary")
    fleet = load("mart_fleet_summary")
    devices = load("mart_device_sla")
    errors = load("mart_error_codes")
    partner_daily = load("mart_partner_daily")
    exceptions = load("recon_exceptions", REPORT_DIR)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard = REPORT_DIR / "dashboard.html"
    dashboard.write_text(
        render_dashboard(kpi, recon, fleet, devices, errors, partner_daily, exceptions),
        encoding="utf-8",
    )
    summary = REPORT_DIR / "summary.md"
    summary.write_text(render_summary(kpi, recon, devices, errors), encoding="utf-8")
    return {"dashboard": dashboard, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка HTML-дашборда и резюме")
    parser.parse_args()
    paths = build()
    for name, path in paths.items():
        print(f"{name:10s} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
