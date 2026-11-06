"""Сборка отчёта по SLA: HTML-дашборд и markdown-резюме из витрин."""

from __future__ import annotations

import argparse
import csv
import html
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


def load(name: str) -> list[dict]:
    path = PROCESSED / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/pipeline.py")
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def num(value) -> float:
    if value in (None, "", "None"):
        return 0.0
    return float(value)


def rub(kopecks) -> str:
    value = num(kopecks) / 100.0
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def pct(value) -> str:
    return f"{num(value):.1f}".replace(".", ",") + " %"


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def bar(share: float, tone: str = "accent") -> str:
    width = max(0.8, min(100.0, share))
    return (f'<div class="bar"><span class="bar-fill bar-{tone}" '
            f'style="width:{width:.1f}%"></span></div>')


STYLE = """
:root { --bg:#f5f7fb; --panel:#fff; --ink:#111f38; --muted:#6a7a92;
  --accent:#2563eb; --warn:#e08c1a; --bad:#d13c47; --ok:#1f9d63; --line:#e3e9f3; }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--bg); color:var(--ink);
  font:14px/1.55 "Segoe UI",Roboto,Arial,sans-serif; }
h1 { margin:0 0 6px; font-size:26px; letter-spacing:-0.3px; }
h2 { margin:0 0 12px; font-size:17px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:22px; }
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:12px; margin-bottom:22px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.kpi-label { color:var(--muted); font-size:12px; text-transform:uppercase;
  letter-spacing:.4px; margin-bottom:8px; }
.kpi-value { font-size:21px; font-weight:600; }
.kpi-value small { display:block; font-size:12px; font-weight:400; color:var(--muted); }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:20px 22px; margin-bottom:20px; overflow-x:auto; }
table { width:100%; border-collapse:collapse; }
th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }
th { color:var(--muted); font-size:12px; font-weight:600; text-transform:uppercase;
  letter-spacing:.3px; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
tbody tr:hover { background:#f8fafd; }
.mono { font-family:"Cascadia Mono",Consolas,monospace; font-size:13px; }
.bar { display:inline-block; vertical-align:middle; width:104px; height:8px; background:#edf1f7;
  border-radius:6px; overflow:hidden; margin-right:8px; }
.bar span { display:block; height:100%; }
.bar-accent { background:var(--accent); } .bar-warn { background:var(--warn); }
.bar-bad { background:var(--bad); } .bar-ok { background:var(--ok); }
.share { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px;
  font-weight:700; color:#fff; }
.tag-high { background:var(--bad); } .tag-mid { background:var(--warn); }
.tag-low { background:#8b9ab1; }
.hint { color:var(--muted); font-size:12.5px; margin:0 0 14px; max-width:900px; }
footer { color:var(--muted); font-size:12px; } 
"""

STYLE = STYLE + charts.CHART_CSS


def weekly_chart(rows: list[dict]) -> str:
    return charts.chart(
        "Динамика по неделям",
        "Инциденты и нарушения SLA по неделям. Расхождение между линиями показывает, "
        "растёт ли нагрузка быстрее, чем команда успевает закрывать заявки.",
        {
            "type": "line",
            "labels": [row["week_start"][5:] for row in rows],
            "series": [
                {"name": "Инциденты", "values": [num(r["incidents_cnt"]) for r in rows],
                 "color": "#2563eb"},
                {"name": "Нарушения SLA", "values": [num(r["sla_breach_cnt"]) for r in rows],
                 "color": "#d13c47"},
            ],
        },
        height=280,
    )


def penalty_donut(contracts: list[dict]) -> str:
    items = [
        {"name": row["partner_name"], "value": num(row["billed_penalty_kop"])}
        for row in sorted(contracts, key=lambda r: -num(r["billed_penalty_kop"]))
        if num(row["billed_penalty_kop"]) > 0
    ]
    return charts.chart(
        "Структура неустойки",
        "Как выставленная неустойка распределена между договорами за период.",
        {"type": "donut", "items": items, "center": "", "centerSub": "неустойка, ₽"},
        height=280,
    )


def availability_bars(contracts: list[dict]) -> str:
    rows = sorted(contracts, key=lambda r: num(r["avg_availability_pct"]))
    return charts.chart(
        "Доступность по договорам",
        "Средняя доступность парка партнёра за период. Красная линия на уровне 95 % — "
        "граница, ниже которой начинаются претензии по контракту.",
        {
            "type": "bars",
            "labels": [row["partner_name"] for row in rows],
            "values": [round(num(row["avg_availability_pct"]), 1) for row in rows],
            "color": "#0f766e",
        },
        height=280,
    )



def kpi_block(kpi: dict) -> str:
    cards = [
        ("Период", f"{esc(kpi['period_start'])} — {esc(kpi['period_end'])}", ""),
        ("Устройств в парке", f"{esc(kpi['devices_cnt'])}", f"активных {esc(kpi['active_devices_cnt'])}"),
        ("Инцидентов", f"{int(num(kpi['incidents_cnt'])):,}".replace(",", " "),
         f"критичных P1: {esc(kpi['p1_cnt'])}"),
        ("Нарушений SLA", f"{int(num(kpi['sla_breach_cnt'])):,}".replace(",", " "),
         f"{pct(kpi['breach_rate_pct'])} от всех"),
        ("Доступность парка", pct(kpi["avg_availability_pct"]), "по устройствам"),
        ("MTTR", f"{num(kpi['avg_mttr_hours']):.1f} ч", "среднее решение"),
        ("Реакция", f"{num(kpi['avg_response_hours']):.1f} ч", "среднее время"),
        ("Неустойка начислено", rub(kpi["billed_penalty_kop"]),
         f"до лимита: {rub(kpi['raw_penalty_kop'])}"),
        ("На замену (высокий)", esc(kpi["high_priority_replacements"]), "устройств"),
    ]
    html_parts = []
    for label, value, note in cards:
        note_html = f"<small>{note}</small>" if note else ""
        html_parts.append(
            f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value">{value}{note_html}</div></div>'
        )
    return '<section class="kpi-grid">' + "".join(html_parts) + "</section>"


def contract_block(rows: list[dict]) -> str:
    total_penalty = sum(num(r["billed_penalty_kop"]) for r in rows) or 1.0
    body = []
    for row in sorted(rows, key=lambda r: -num(r["billed_penalty_kop"])):
        share = 100.0 * num(row["billed_penalty_kop"]) / total_penalty
        breach = num(row["breach_rate_pct"])
        tone = "bad" if breach > 20 else ("warn" if breach > 10 else "ok")
        body.append(
            "<tr>"
            f'<td>{esc(row["partner_name"])}</td>'
            f'<td class="num">{esc(row["devices_cnt"])}</td>'
            f'<td class="num">{esc(row["incidents_cnt"])}</td>'
            f'<td>{bar(breach, tone)}<span class="share">{pct(breach)}</span></td>'
            f'<td class="num">{pct(row["avg_availability_pct"])}</td>'
            f'<td class="num">{num(row["avg_mttr_hours"]):.1f} ч</td>'
            f'<td class="num">{rub(row["billed_penalty_kop"])}</td>'
            f'<td>{bar(share, "muted")}<span class="share">{share:.0f}%</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Договоры и неустойки</h2>'
        '<p class="hint">Штраф = месячная плата × 1,5 % за каждый полный час просрочки решения, '
        'но не более 10 % платы в месяц. Лимит применяется на уровне договора и месяца.</p>'
        '<table><thead><tr><th>Партнёр</th><th class="num">Устройств</th>'
        '<th class="num">Инцидентов</th><th>Доля нарушений SLA</th>'
        '<th class="num">Доступность</th><th class="num">MTTR</th>'
        '<th class="num">Неустойка</th><th>Доля в сумме</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def weekly_block(rows: list[dict]) -> str:
    peak = max((num(r["incidents_cnt"]) for r in rows), default=1) or 1
    body = []
    for row in rows:
        count = num(row["incidents_cnt"])
        tone = "bad" if num(row["sla_breach_cnt"]) / (count or 1) > 0.18 else "accent"
        body.append(
            "<tr>"
            f'<td class="mono">{esc(row["week_start"])}</td>'
            f'<td class="num">{int(count)}</td>'
            f'<td>{bar(100.0 * count / peak, tone)}</td>'
            f'<td class="num">{esc(row["p1_cnt"])}</td>'
            f'<td class="num">{esc(row["sla_breach_cnt"])}</td>'
            f'<td class="num">{num(row["avg_response_hours"]):.1f} ч</td>'
            f'<td class="num">{num(row["avg_resolution_hours"]):.1f} ч</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Динамика по неделям</h2>'
        '<table><thead><tr><th>Неделя с</th><th class="num">Инцидентов</th><th></th>'
        '<th class="num">P1</th><th class="num">Нарушений SLA</th>'
        '<th class="num">Реакция</th><th class="num">Решение</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def replacement_block(rows: list[dict]) -> str:
    tags = {"ВЫСОКИЙ": ("tag-high", "Высокий"), "СРЕДНИЙ": ("tag-mid", "Средний"),
            "НАБЛЮДАТЬ": ("tag-low", "Наблюдать")}
    body = []
    for row in rows[:15]:
        css, label = tags.get(row["priority"], ("tag-low", row["priority"]))
        body.append(
            "<tr>"
            f'<td class="mono">{esc(row["device_id"])}</td>'
            f'<td>{esc(row["device_type"])}</td>'
            f'<td>{esc(row["partner_name"])}</td>'
            f'<td>{esc(row["city"])}</td>'
            f'<td class="num">{esc(row["incidents_cnt"])}</td>'
            f'<td class="num">{esc(row["p1_cnt"])}</td>'
            f'<td class="num">{pct(row["availability_pct"])}</td>'
            f'<td class="num">{rub(row["penalty_kop"])}</td>'
            f'<td>{esc(row["reason"])}</td>'
            f'<td><span class="tag {css}">{esc(label)}</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>План замены оборудования</h2>'
        '<p class="hint">Приоритет высокий: доступность ниже 90 % или 4+ критичных инцидента. '
        'Средний: доступность ниже 95 %, 3+ P1 или 8+ инцидентов.</p>'
        '<table><thead><tr><th>Устройство</th><th>Тип</th><th>Партнёр</th><th>Город</th>'
        '<th class="num">Инцидентов</th><th class="num">P1</th><th class="num">Доступность</th>'
        '<th class="num">Штраф</th><th>Причина</th><th>Приоритет</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def error_block(families: list[dict], codes: list[dict]) -> str:
    body = []
    for row in families:
        body.append(
            "<tr>"
            f'<td>{esc(row["family"])}</td>'
            f'<td class="num">{esc(row["incidents_cnt"])}</td>'
            f'<td>{bar(num(row["share_pct"]) * 2, "warn")}'
            f'<span class="share">{pct(row["share_pct"])}</span></td>'
            f'<td class="num">{esc(row["devices_cnt"])}</td>'
            f'<td class="num">{num(row["downtime_hours"]):.0f} ч</td>'
            f'<td class="num">{esc(row["sla_breach_cnt"])}</td>'
            f'<td class="num">{rub(row["penalty_kop"])}</td>'
            "</tr>"
        )
    codes_body = "".join(
        f'<tr><td class="mono">{esc(c["error_code"])}</td><td>{esc(c["error_text"])}</td>'
        f'<td class="num">{esc(c["incidents_cnt"])}</td>'
        f'<td class="num">{esc(c["sla_breach_cnt"])}</td>'
        f'<td class="num">{num(c["avg_resolution_hours"]):.1f} ч</td></tr>'
        for c in codes
    )
    return (
        '<section class="panel"><h2>Причины инцидентов</h2>'
        '<table><thead><tr><th>Семейство</th><th class="num">Инцидентов</th><th>Доля</th>'
        '<th class="num">Устройств</th><th class="num">Простой</th>'
        '<th class="num">Нарушений SLA</th><th class="num">Неустойка</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
        '<h2 style="margin-top:22px">Коды ошибок</h2>'
        '<table><thead><tr><th>Код</th><th>Описание</th><th class="num">Инцидентов</th>'
        '<th class="num">Нарушений</th><th class="num">Среднее решение</th></tr></thead><tbody>'
        + codes_body + "</tbody></table></section>"
    )


def channel_block(rows: list[dict]) -> str:
    body = "".join(
        f'<tr><td>{esc(r["channel"])}</td><td class="num">{esc(r["incidents_cnt"])}</td>'
        f'<td class="num">{num(r["avg_response_hours"]):.1f} ч</td>'
        f'<td class="num">{esc(r["critical_cnt"])}</td>'
        f'<td>{bar(num(r["breach_rate_pct"]), "bad" if num(r["breach_rate_pct"]) > 15 else "accent")}'
        f'<span class="share">{pct(r["breach_rate_pct"])}</span></td></tr>'
        for r in rows
    )
    return (
        '<section class="panel"><h2>Каналы обращений</h2>'
        '<table><thead><tr><th>Канал</th><th class="num">Инцидентов</th>'
        '<th class="num">Средняя реакция</th><th class="num">Критичных</th>'
        '<th>Нарушения SLA</th></tr></thead><tbody>' + body + "</tbody></table></section>"
    )


def render_html(kpi, contracts, weekly, replacements, families, codes, channels) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>SLA парка терминалов</title>
<style>{STYLE}</style></head>
<body>
<h1>SLA и доступность парка терминалов</h1>
<div class="sub">Контрактные нормативы, фактические сроки, неустойки и план замены оборудования.
Данные синтетические, суммы в копейках в источнике.</div>
{kpi_block(kpi[0])}
{weekly_chart(weekly)}
{penalty_donut(contracts)}
{availability_bars(contracts)}
{contract_block(contracts)}
{weekly_block(weekly)}
{replacement_block(replacements)}
{error_block(families, codes)}
{channel_block(channels)}
<footer>Доступность = 1 − простой / время наблюдения; пересекающиеся инциденты схлопнуты.
Штраф считается только по просрочке решения, просрочка реакции учитывается отдельно.</footer>
<script>{charts.CHART_JS}</script>
</body></html>
"""


def render_md(kpi, contracts, replacements, families) -> str:
    row = kpi[0]
    lines = [
        "# SLA парка терминалов — резюме",
        "",
        f"Период: **{row['period_start']} — {row['period_end']}**, "
        f"устройств **{row['devices_cnt']}** (активных {row['active_devices_cnt']}).",
        "",
        f"- Инцидентов **{row['incidents_cnt']}**, из них критичных P1 — {row['p1_cnt']}",
        f"- Нарушений SLA **{row['sla_breach_cnt']}** ({row['breach_rate_pct']} %)",
        f"- Доступность парка **{row['avg_availability_pct']} %**, MTTR **{row['avg_mttr_hours']} ч**",
        f"- Средняя реакция **{row['avg_response_hours']} ч**",
        f"- Неустойка: начислено **{rub(row['billed_penalty_kop'])}** "
        f"(без лимитов {rub(row['raw_penalty_kop'])})",
        f"- Устройств с высоким приоритетом замены — **{row['high_priority_replacements']}**",
        "",
        "## Договоры",
        "",
        "| Партнёр | Устройств | Инцидентов | Нарушений SLA | Доступность | Неустойка |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in sorted(contracts, key=lambda r: -num(r["billed_penalty_kop"])):
        lines.append(
            f"| {item['partner_name']} | {item['devices_cnt']} | {item['incidents_cnt']} | "
            f"{item['breach_rate_pct']} % | {item['avg_availability_pct']} % | "
            f"{rub(item['billed_penalty_kop'])} |"
        )
    lines += ["", "## Кандидаты на замену", "",
              "| Устройство | Тип | Партнёр | Доступность | P1 | Приоритет |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for item in replacements[:7]:
        lines.append(
            f"| {item['device_id']} | {item['device_type']} | {item['partner_name']} | "
            f"{item['availability_pct']} % | {item['p1_cnt']} | {item['priority']} |"
        )
    lines += ["", "## Причины", "", "| Семейство | Инцидентов | Доля | Неустойка |",
              "| --- | ---: | ---: | ---: |"]
    for item in families:
        lines.append(f"| {item['family']} | {item['incidents_cnt']} | {item['share_pct']} % | "
                     f"{rub(item['penalty_kop'])} |")
    return "\n".join(lines) + "\n"


def build() -> dict[str, Path]:
    kpi = load("mart_kpi")
    contracts = load("mart_contract")
    weekly = load("mart_weekly")
    replacements = load("mart_replacement")
    families = load("mart_error_family")
    codes = load("mart_error_code")
    channels = load("mart_channel")

    REPORTS.mkdir(parents=True, exist_ok=True)
    dashboard = REPORTS / "dashboard.html"
    dashboard.write_text(
        render_html(kpi, contracts, weekly, replacements, families, codes, channels),
        encoding="utf-8",
    )
    summary = REPORTS / "summary.md"
    summary.write_text(render_md(kpi, contracts, replacements, families), encoding="utf-8")
    return {"dashboard": dashboard, "summary": summary}


def main() -> None:
    argparse.ArgumentParser(description="Сборка отчёта SLA").parse_args()
    for name, path in build().items():
        print(f"{name:10s} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
