"""Отчёт по аномалиям: HTML-дашборд и markdown-резюме."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

try:
    from . import charts
except ImportError:  # запуск как скрипта: python src/report.py
    import charts

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
SEP = ";"
ENC = "utf-8-sig"

KIND_TITLES = {
    "VOLUME_DROP": "Падение объёма операций",
    "VOLUME_SPIKE": "Рост объёма операций",
    "SILENT": "Устройство не проводит операции",
    "DECLINE_SPIKE": "Рост доли отказов",
}


def load(name: str) -> list[dict]:
    path = PROCESSED / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/detect.py")
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def num(value) -> float:
    if value in (None, "", "None"):
        return 0.0
    return float(value)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def pct(value) -> str:
    return f"{num(value):+.1f}".replace(".", ",") + " %"


def bar(share: float, tone: str = "accent") -> str:
    width = max(1.0, min(100.0, share))
    return (f'<div class="bar"><span class="bar-fill bar-{tone}" '
            f'style="width:{width:.1f}%"></span></div>')


STYLE = """
:root { --bg:#f6f7f9; --panel:#fff; --ink:#0f1c2e; --muted:#68788f; --line:#e4e9f1;
  --accent:#0f766e; --warn:#c2760b; --bad:#c0392b; --ok:#1c8a52; }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--bg); color:var(--ink);
  font:14px/1.55 "Segoe UI",Roboto,Arial,sans-serif; }
h1 { margin:0 0 6px; font-size:26px; letter-spacing:-.3px; }
h2 { margin:0 0 12px; font-size:17px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:22px; }
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px; margin-bottom:22px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.kpi-label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.4px;
  margin-bottom:8px; }
.kpi-value { font-size:21px; font-weight:600; }
.kpi-value small { display:block; font-size:12px; font-weight:400; color:var(--muted); }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:20px 22px; margin-bottom:20px; overflow-x:auto; }
table { width:100%; border-collapse:collapse; }
th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }
th { color:var(--muted); font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.3px; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
tbody tr:hover { background:#f9fbfd; }
.mono { font-family:"Cascadia Mono",Consolas,monospace; font-size:13px; }
.bar { display:inline-block; vertical-align:middle; width:110px; height:8px; background:#eef2f7;
  border-radius:6px; overflow:hidden; margin-right:8px; }
.bar span { display:block; height:100%; }
.bar-accent { background:var(--accent); } .bar-warn { background:var(--warn); }
.bar-bad { background:var(--bad); } .bar-ok { background:var(--ok); }
.share { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px;
  font-weight:700; color:#fff; }
.tag-high { background:var(--bad); } .tag-mid { background:var(--warn); }
.hint { color:var(--muted); font-size:12.5px; margin:0 0 14px; max-width:920px; }
footer { color:var(--muted); font-size:12px; }
"""

STYLE = STYLE + charts.CHART_CSS


def daily_chart(alerts: list[dict]) -> str:
    by_date: dict[str, list[int]] = {}
    for alert in alerts:
        bucket = by_date.setdefault(alert["txn_date"], [0, 0])
        bucket[0] += 1
        if alert["severity"] == "HIGH":
            bucket[1] += 1
    dates = sorted(by_date)
    return charts.chart(
        "Алерты по дням",
        "Сколько отклонений детектор нашёл в каждый день периода. Высокий приоритет — "
        "простои и резкие падения объёма, их проверяют в первую очередь.",
        {
            "type": "line",
            "labels": [d[5:] for d in dates],
            "area": True,
            "series": [
                {"name": "Все алерты", "values": [by_date[d][0] for d in dates], "color": "#0f766e"},
                {"name": "Высокий приоритет", "values": [by_date[d][1] for d in dates],
                 "color": "#c0392b"},
            ],
        },
        height=280,
    )


def kind_donut(rows: list[dict]) -> str:
    items = [
        {"name": KIND_TITLES.get(row["kind"], row["kind"]),
         "value": int(num(row["alerts_cnt"]))}
        for row in rows
    ]
    return charts.chart(
        "Классы аномалий",
        "Что именно ломалось: простой, падение или всплеск объёма, рост доли отказов.",
        {"type": "donut", "items": items, "centerSub": "алертов"},
        height=280,
    )



def kpi_block(metrics: dict, by_kind: list[dict], by_device: list[dict]) -> str:
    high = sum(int(num(r["high_cnt"])) for r in by_kind)
    cards = [
        ("Заложено аномалий", str(metrics.get("planted", "—")), "эталон генератора"),
        ("Найдено алертов", str(metrics.get("alerts", "—")), "все классы"),
        ("Полнота", f"{metrics.get('recall', 0) * 100:.0f} %", "доля найденных аномалий"),
        ("Точность", f"{metrics.get('precision', 0) * 100:.0f} %", "доля верных среди алертов"),
        ("Высокий приоритет", str(high), "требует реакции сегодня"),
        ("Устройств с алертами", str(len(by_device)), "уникальных терминалов"),
    ]
    inner = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{esc(value)}<small>{esc(note)}</small></div></div>'
        for label, value, note in cards
    )
    return f'<section class="kpi-grid">{inner}</section>'


def kind_block(rows: list[dict], total: int) -> str:
    body = []
    for row in rows:
        share = 100.0 * num(row["alerts_cnt"]) / total if total else 0
        tone = "bad" if row["kind"] in {"SILENT", "VOLUME_DROP"} else "warn"
        body.append(
            "<tr>"
            f'<td>{esc(KIND_TITLES.get(row["kind"], row["kind"]))}</td>'
            f'<td class="mono">{esc(row["kind"])}</td>'
            f'<td class="num">{esc(row["alerts_cnt"])}</td>'
            f'<td>{bar(share, tone)}<span class="share">{share:.0f}%</span></td>'
            f'<td class="num">{esc(row["devices_cnt"])}</td>'
            f'<td class="num">{esc(row["partners_cnt"])}</td>'
            f'<td class="num">{esc(row["high_cnt"])}</td>'
            f'<td class="mono">{esc(row["first_date"])}</td>'
            f'<td class="mono">{esc(row["last_date"])}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Алерты по классам</h2>'
        '<p class="hint">Порог срабатывания: отклонение от нормы того же дня недели больше 40–55 % '
        'и z-оценка выше 3,5 — статистическая заметность без операционного смысла не считается аномалией.</p>'
        '<table><thead><tr><th>Класс</th><th>Код</th><th class="num">Алертов</th><th>Доля</th>'
        '<th class="num">Устройств</th><th class="num">Партнёров</th>'
        '<th class="num">Высокий</th><th>Первый</th><th>Последний</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def device_block(rows: list[dict]) -> str:
    body = []
    for row in rows[:15]:
        tone = "bad" if int(num(row["high_cnt"])) > 0 else "warn"
        body.append(
            "<tr>"
            f'<td class="mono">{esc(row["device_id"])}</td>'
            f'<td>{esc(row["device_type"])}</td>'
            f'<td>{esc(row["partner_name"])}</td>'
            f'<td>{esc(row["city"])}</td>'
            f'<td class="num">{esc(row["alerts_cnt"])}</td>'
            f'<td>{bar(min(100.0, num(row["alerts_cnt"]) * 25), tone)}</td>'
            f'<td class="num">{esc(row["high_cnt"])}</td>'
            f'<td>{esc(row["kinds"])}</td>'
            f'<td class="mono">{esc(row["last_alert_date"])}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Проблемные устройства</h2>'
        '<table><thead><tr><th>Устройство</th><th>Тип</th><th>Партнёр</th><th>Город</th>'
        '<th class="num">Алертов</th><th></th><th class="num">Высокий</th><th>Классы</th>'
        '<th>Последний</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def alert_block(rows: list[dict]) -> str:
    body = []
    for row in rows[:20]:
        css = "tag-high" if row["severity"] == "HIGH" else "tag-mid"
        deviation = num(row["deviation_pct"])
        tone = "bad" if deviation < 0 else "warn"
        body.append(
            "<tr>"
            f'<td class="mono">{esc(row["alert_id"])}</td>'
            f'<td class="mono">{esc(row["txn_date"])}</td>'
            f'<td class="mono">{esc(row["device_id"])}</td>'
            f'<td>{esc(row["device_type"])}</td>'
            f'<td>{esc(row["partner_name"])}</td>'
            f'<td>{esc(KIND_TITLES.get(row["kind"], row["kind"]))}</td>'
            f'<td><span class="tag {css}">{esc(row["severity"])}</span></td>'
            f'<td class="num">{num(row["observed"]):.0f}</td>'
            f'<td class="num">{num(row["baseline"]):.0f}</td>'
            f'<td>{bar(min(100.0, abs(deviation)), tone)}<span class="share">{pct(deviation)}</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Последние алерты высокого приоритета</h2>'
        '<table><thead><tr><th>ID</th><th>Дата</th><th>Устройство</th><th>Тип</th>'
        '<th>Партнёр</th><th>Класс</th><th>Приоритет</th><th class="num">Факт</th>'
        '<th class="num">Норма</th><th>Отклонение</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def render_html(metrics, by_kind, by_device, alerts) -> str:
    total = sum(int(num(r["alerts_cnt"])) for r in by_kind)
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Аномалии в работе терминалов</title>
<style>{STYLE}</style></head>
<body>
<h1>Аномалии в суточных показателях терминалов</h1>
<div class="sub">Контроль объёма операций и доли отказов по каждому устройству.
База — медиана того же дня недели за 4 недели, устойчивая оценка разброса — MAD.
Данные синтетические, эталон аномалий известен заранее.</div>
{kpi_block(metrics, by_kind, by_device)}
{daily_chart(alerts)}
{kind_donut(by_kind)}
{kind_block(by_kind, total)}
{device_block(by_device)}
{alert_block([a for a in alerts if a["severity"] == "HIGH"] or alerts)}
<footer>Алерт — сигнал к проверке, а не диагноз: рост объёма часто объясняется акцией,
падение — работами на канале связи. Проверка занимает минуты, простой киоска — часы.</footer>
<script>{charts.CHART_JS}</script>
</body></html>
"""


def render_md(metrics, by_kind, by_device) -> str:
    lines = [
        "# Аномалии в работе терминалов — резюме",
        "",
        f"Алертов: **{metrics.get('alerts')}**, заложено аномалий **{metrics.get('planted')}**.",
        f"Полнота **{metrics.get('recall', 0) * 100:.0f} %**, "
        f"точность **{metrics.get('precision', 0) * 100:.0f} %**.",
        "",
        "## По классам",
        "",
        "| Класс | Алертов | Устройств | Высокий приоритет |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in by_kind:
        lines.append(
            f"| {KIND_TITLES.get(row['kind'], row['kind'])} | {row['alerts_cnt']} | "
            f"{row['devices_cnt']} | {row['high_cnt']} |"
        )
    lines += ["", "## Устройства", "", "| Устройство | Партнёр | Алертов | Классы |",
              "| --- | --- | ---: | --- |"]
    for row in by_device[:8]:
        lines.append(f"| {row['device_id']} | {row['partner_name']} | {row['alerts_cnt']} | "
                     f"{row['kinds']} |")
    lines += ["", "## Как читать", "",
              "1. SILENT и VOLUME_DROP — сначала проверить связь и питание, потом железо.",
              "2. VOLUME_SPIKE — сверить с календарём акций и работами на кассе.",
              "3. DECLINE_SPIKE — смотреть коды отказов: связь, карт-ридер или процессинг."]
    return "\n".join(lines) + "\n"


def build() -> dict[str, Path]:
    metrics = json.loads((PROCESSED / "detection_metrics.json").read_text(encoding="utf-8"))
    by_kind = load("alerts_by_kind")
    by_device = load("alerts_by_device")
    alerts = load("alerts")

    REPORTS.mkdir(parents=True, exist_ok=True)
    dashboard = REPORTS / "dashboard.html"
    dashboard.write_text(render_html(metrics, by_kind, by_device, alerts), encoding="utf-8")
    summary = REPORTS / "summary.md"
    summary.write_text(render_md(metrics, by_kind, by_device), encoding="utf-8")
    return {"dashboard": dashboard, "summary": summary}


def main() -> None:
    argparse.ArgumentParser(description="Сборка отчёта по аномалиям").parse_args()
    for name, path in build().items():
        print(f"{name:10s} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
