"""Отчёт по заявкам поддержки: HTML-дашборд и markdown-резюме."""

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

CATEGORY_TITLES = {
    "PAYMENT": "Оплата и проведение операций",
    "CONNECTIVITY": "Связь с процессингом",
    "HARDWARE": "Оборудование терминала",
    "CASH": "Наличные и инкассация",
    "SOFTWARE": "ПО и зависания",
    "CONSULT": "Консультации операторов",
    "ACCESS": "Доступ на объект",
    "OTHER": "Не распознано правилами",
}


def load(name: str) -> list[dict]:
    path = PROCESSED / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"нет файла {path}; сначала запустите src/analyze.py")
    with path.open(newline="", encoding=ENC) as fh:
        return list(csv.DictReader(fh, delimiter=SEP))


def num(value) -> float:
    if value in (None, "", "None"):
        return 0.0
    return float(value)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def pct(value) -> str:
    return f"{num(value):.1f}".replace(".", ",") + " %"


def bar(share: float, tone: str = "accent") -> str:
    width = max(1.0, min(100.0, share))
    return (f'<div class="bar"><span class="bar-fill bar-{tone}" '
            f'style="width:{width:.1f}%"></span></div>')


STYLE = """
:root { --bg:#f6f8fb; --panel:#fff; --ink:#101b2d; --muted:#68788f; --line:#e4e9f2;
  --accent:#4f46e5; --warn:#c07a10; --bad:#c23b4b; --ok:#16885a; }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--bg); color:var(--ink);
  font:14px/1.55 "Segoe UI",Roboto,Arial,sans-serif; }
h1 { margin:0 0 6px; font-size:26px; letter-spacing:-.3px; }
h2 { margin:0 0 12px; font-size:17px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:22px; }
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(175px,1fr));
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
.bar { display:inline-block; vertical-align:middle; width:110px; height:8px; background:#eef2f8;
  border-radius:6px; overflow:hidden; margin-right:8px; }
.bar span { display:block; height:100%; }
.bar-accent { background:var(--accent); } .bar-warn { background:var(--warn); }
.bar-bad { background:var(--bad); } .bar-ok { background:var(--ok); }
.share { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
.pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px;
  font-weight:700; color:#fff; }
.p1 { background:var(--bad); } .p2 { background:var(--warn); } .p3 { background:#8b9ab1; }
.hint { color:var(--muted); font-size:12.5px; margin:0 0 14px; max-width:920px; }
footer { color:var(--muted); font-size:12px; }
"""

STYLE = STYLE + charts.CHART_CSS


def weekly_chart(rows: list[dict]) -> str:
    return charts.chart(
        "Заявки и нарушения SLA по неделям",
        "Рост обращений сам по себе не проблема; проблема — когда нарушения SLA растут быстрее "
        "заявок: значит, мощность первой линии не успевает.",
        {
            "type": "line",
            "labels": [row["week_start"][5:] for row in rows],
            "series": [
                {"name": "Заявки", "values": [num(r["tickets_cnt"]) for r in rows],
                 "color": "#4f46e5"},
                {"name": "Нарушения SLA", "values": [num(r["breach_cnt"]) for r in rows],
                 "color": "#c23b4b"},
            ],
        },
        height=280,
    )


def category_donut(rows: list[dict]) -> str:
    items = [
        {"name": CATEGORY_TITLES.get(row["category"], row["category"]),
         "value": int(num(row["tickets_cnt"]))}
        for row in sorted(rows, key=lambda r: -num(r["tickets_cnt"]))
    ]
    return charts.chart(
        "Структура обращений",
        "Доли категорий за период. «Не распознано правилами» — очередь на доработку "
        "словаря, её видно, потому что она не спрятана в другие категории.",
        {"type": "donut", "items": items, "centerSub": "заявок"},
        height=280,
    )



def kpi_block(kpi: dict, metrics: dict) -> str:
    cards = [
        ("Заявок", f"{int(num(kpi['tickets_cnt'])):,}".replace(",", " "),
         f"открыто {int(num(kpi['open_cnt']))}"),
        ("Критичных P1", f"{int(num(kpi['p1_cnt'])):,}".replace(",", " "), "по приоритету"),
        ("Соблюдение SLA", pct(kpi["sla_compliance_pct"]), "реакция и решение"),
        ("Средняя реакция", f"{num(kpi['avg_response_h']):.1f} ч", "первый ответ"),
        ("Среднее решение", f"{num(kpi['avg_resolution_h']):.1f} ч", "закрытые заявки"),
        ("Повторные обращения", f"{int(num(kpi['repeat_cnt']))}",
         f"{pct(kpi['repeat_rate_pct'])} в окне 7 дней"),
        ("Точность категоризации", f"{metrics.get('accuracy', 0) * 100:.1f} %".replace(".", ","),
         "правила по тексту"),
    ]
    inner = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{value}<small>{esc(note)}</small></div></div>'
        for label, value, note in cards
    )
    return f'<section class="kpi-grid">{inner}</section>'


def category_block(rows: list[dict]) -> str:
    total = sum(num(r["tickets_cnt"]) for r in rows) or 1
    body = []
    for row in rows:
        share = 100.0 * num(row["tickets_cnt"]) / total
        breach = num(row["sla_breach_pct"])
        tone = "bad" if breach > 20 else ("warn" if breach > 12 else "ok")
        body.append(
            "<tr>"
            f'<td>{esc(CATEGORY_TITLES.get(row["category"], row["category"]))}</td>'
            f'<td class="num">{esc(row["tickets_cnt"])}</td>'
            f'<td>{bar(share)}<span class="share">{share:.0f}%</span></td>'
            f'<td class="num">{esc(row["p1_cnt"])}</td>'
            f'<td class="num">{num(row["avg_resolution_h"]):.1f} ч</td>'
            f'<td>{bar(breach, tone)}<span class="share">{pct(breach)}</span></td>'
            f'<td class="num">{pct(row["repeat_pct"])}</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Категории обращений</h2>'
        '<p class="hint">Категория определяется по тексту темы правилами по ключевым словам. '
        'Порядок правил важен: «как оформить возврат по чеку» — консультация, а не проблема принтера.</p>'
        '<table><thead><tr><th>Категория</th><th class="num">Заявок</th><th>Доля</th>'
        '<th class="num">P1</th><th class="num">Среднее решение</th>'
        '<th>Нарушения SLA</th><th class="num">Повторные</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def sla_block(rows: list[dict]) -> str:
    body = []
    for row in rows:
        compliance = num(row["compliance_pct"])
        tone = "bad" if compliance < 80 else ("warn" if compliance < 90 else "ok")
        body.append(
            "<tr>"
            f'<td><span class="pill {row["priority"].lower()}">{esc(row["priority"])}</span></td>'
            f'<td class="num">{esc(row["tickets_cnt"])}</td>'
            f'<td class="num">{esc(row["response_sla_h"])} ч / {esc(row["resolve_sla_h"])} ч</td>'
            f'<td class="num">{num(row["avg_response_h"]):.1f} ч</td>'
            f'<td class="num">{num(row["avg_resolution_h"]):.1f} ч</td>'
            f'<td class="num">{esc(row["response_breach_cnt"])}</td>'
            f'<td class="num">{esc(row["resolution_breach_cnt"])}</td>'
            f'<td>{bar(compliance, tone)}<span class="share">{pct(compliance)}</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>SLA по приоритетам</h2>'
        '<table><thead><tr><th>Приоритет</th><th class="num">Заявок</th><th class="num">Норматив</th>'
        '<th class="num">Реакция</th><th class="num">Решение</th>'
        '<th class="num">Просрочка реакции</th><th class="num">Просрочка решения</th>'
        '<th>Соблюдение</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></section>"
    )


def weekly_block(rows: list[dict]) -> str:
    peak = max((num(r["tickets_cnt"]) for r in rows), default=1) or 1
    body = []
    for row in rows:
        count = num(row["tickets_cnt"])
        breach_share = 100.0 * num(row["breach_cnt"]) / count if count else 0
        tone = "bad" if breach_share > 18 else "accent"
        body.append(
            "<tr>"
            f'<td class="mono">{esc(row["week_start"])}</td>'
            f'<td class="num">{int(count)}</td>'
            f'<td>{bar(100.0 * count / peak, tone)}</td>'
            f'<td class="num">{esc(row["p1_cnt"])}</td>'
            f'<td class="num">{esc(row["breach_cnt"])}</td>'
            f'<td class="num">{esc(row["repeat_cnt"])}</td>'
            f'<td class="num">{num(row["avg_response_h"]):.1f} ч</td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Динамика по неделям</h2>'
        '<table><thead><tr><th>Неделя</th><th class="num">Заявок</th><th></th>'
        '<th class="num">P1</th><th class="num">Нарушений SLA</th>'
        '<th class="num">Повторных</th><th class="num">Реакция</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></section>"
    )


def agent_block(rows: list[dict]) -> str:
    body = []
    for row in rows:
        breach = num(row["sla_breach_pct"])
        tone = "bad" if breach > 18 else ("warn" if breach > 10 else "ok")
        body.append(
            "<tr>"
            f'<td>{esc(row["agent"])}</td>'
            f'<td class="num">{esc(row["tickets_cnt"])}</td>'
            f'<td class="num">{esc(row["p1_cnt"])}</td>'
            f'<td class="num">{num(row["avg_response_h"]):.1f} ч</td>'
            f'<td class="num">{num(row["avg_resolution_h"]):.1f} ч</td>'
            f'<td>{bar(breach, tone)}<span class="share">{pct(breach)}</span></td>'
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Нагрузка операторов</h2>'
        '<p class="hint">Показатель нагрузки — не KPI сотрудника: он показывает, где '
        'распределение заявок неровное и кто работает без запаса по времени.</p>'
        '<table><thead><tr><th>Оператор</th><th class="num">Заявок</th><th class="num">P1</th>'
        '<th class="num">Реакция</th><th class="num">Решение</th>'
        '<th>Нарушения SLA</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></section>"
    )


def channel_block(channels: list[dict], partners: list[dict]) -> str:
    ch_body = "".join(
        f'<tr><td>{esc(r["channel"])}</td><td class="num">{esc(r["tickets_cnt"])}</td>'
        f'<td class="num">{pct(r["share_pct"])}</td>'
        f'<td class="num">{num(r["avg_response_h"]):.1f} ч</td>'
        f'<td>{bar(num(r["sla_breach_pct"]), "warn")}'
        f'<span class="share">{pct(r["sla_breach_pct"])}</span></td></tr>'
        for r in channels
    )
    pr_body = "".join(
        f'<tr><td>{esc(r["partner_name"])}</td><td class="num">{esc(r["tickets_cnt"])}</td>'
        f'<td class="num">{esc(r["p1_cnt"])}</td>'
        f'<td class="num">{pct(r["repeat_pct"])}</td>'
        f'<td class="num">{num(r["avg_resolution_h"]):.1f} ч</td></tr>'
        for r in partners
    )
    return (
        '<section class="panel"><h2>Каналы обращений</h2>'
        '<table><thead><tr><th>Канал</th><th class="num">Заявок</th><th class="num">Доля</th>'
        '<th class="num">Реакция</th><th>Нарушения SLA</th></tr></thead><tbody>'
        + ch_body + "</tbody></table>"
        '<h2 style="margin-top:22px">Партнёры</h2>'
        '<table><thead><tr><th>Партнёр</th><th class="num">Заявок</th><th class="num">P1</th>'
        '<th class="num">Повторные</th><th class="num">Среднее решение</th>'
        '</tr></thead><tbody>' + pr_body + "</tbody></table></section>"
    )


def repeat_block(rows: list[dict]) -> str:
    body = "".join(
        f'<tr><td class="mono">{esc(r["device_id"])}</td><td>{esc(r["device_type"])}</td>'
        f'<td>{esc(r["partner_name"])}</td><td class="num">{esc(r["repeat_cnt"])}</td>'
        f'<td>{esc(CATEGORY_TITLES.get(r["top_category"], r["top_category"]))}</td>'
        f'<td class="mono">{esc(r["last_repeat"])}</td></tr>'
        for r in rows[:12]
    )
    return (
        '<section class="panel"><h2>Устройства с повторными обращениями</h2>'
        '<p class="hint">Повторным считается обращение по тому же устройству в течение 7 дней '
        'после закрытия предыдущей заявки — признак того, что причина не устранена.</p>'
        '<table><thead><tr><th>Устройство</th><th>Тип</th><th>Партнёр</th>'
        '<th class="num">Повторных</th><th>Частая категория</th><th>Последнее</th>'
        '</tr></thead><tbody>' + body + "</tbody></table></section>"
    )


def render_html(kpi, metrics, categories, sla, weekly, agents, channels, partners, repeats) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Аналитика заявок поддержки</title>
<style>{STYLE}</style></head>
<body>
<h1>Заявки первой линии: SLA, категории, повторные обращения</h1>
<div class="sub">Разбор потока обращений по терминальному парку: сроки реакции и решения
против договорных нормативов, структура причин и устройства, по которым обращаются повторно.
Данные синтетические.</div>
{kpi_block(kpi[0], metrics)}
{weekly_chart(weekly)}
{category_donut(categories)}
{category_block(categories)}
{sla_block(sla)}
{weekly_block(weekly)}
{agent_block(agents)}
{channel_block(channels, partners)}
{repeat_block(repeats)}
<footer>Категория определяется правилами по тексту темы; «Не распознано правилами» —
обращения без ключевых слов, их стоит разбирать вручную и дополнять правила.</footer>
<script>{charts.CHART_JS}</script>
</body></html>
"""


def render_md(kpi, metrics, categories, sla, repeats) -> str:
    row = kpi[0]
    lines = [
        "# Заявки поддержки — резюме",
        "",
        f"Заявок **{row['tickets_cnt']}**, открытых {row['open_cnt']}, "
        f"критичных P1 — {row['p1_cnt']}.",
        f"Соблюдение SLA **{row['sla_compliance_pct']} %**, средняя реакция "
        f"{row['avg_response_h']} ч, среднее решение {row['avg_resolution_h']} ч.",
        f"Повторных обращений **{row['repeat_cnt']}** ({row['repeat_rate_pct']} %).",
        f"Точность категоризации правилами — **{metrics['accuracy'] * 100:.1f} %**.",
        "",
        "## Категории",
        "",
        "| Категория | Заявок | Доля | Нарушения SLA | Повторные |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in categories:
        lines.append(
            f"| {CATEGORY_TITLES.get(item['category'], item['category'])} | "
            f"{item['tickets_cnt']} | {item['share_pct']} % | "
            f"{item['sla_breach_pct']} % | {item['repeat_pct']} % |"
        )
    lines += ["", "## SLA по приоритетам", "",
              "| Приоритет | Заявок | Норматив | Реакция | Решение | Соблюдение |",
              "| --- | ---: | --- | ---: | ---: | ---: |"]
    for item in sla:
        lines.append(
            f"| {item['priority']} | {item['tickets_cnt']} | "
            f"{item['response_sla_h']} / {item['resolve_sla_h']} ч | "
            f"{item['avg_response_h']} ч | {item['avg_resolution_h']} ч | "
            f"{item['compliance_pct']} % |"
        )
    if repeats:
        lines += ["", "## Повторные обращения", "",
                  "| Устройство | Партнёр | Повторных | Частая категория |",
                  "| --- | --- | ---: | --- |"]
        for item in repeats[:6]:
            lines.append(
                f"| {item['device_id']} | {item['partner_name']} | {item['repeat_cnt']} | "
                f"{CATEGORY_TITLES.get(item['top_category'], item['top_category'])} |"
            )
    return "\n".join(lines) + "\n"


def build() -> dict[str, Path]:
    metrics = json.loads((PROCESSED / "classifier_metrics.json").read_text(encoding="utf-8"))
    kpi = load("mart_kpi")
    categories = load("mart_categories")
    sla = load("mart_sla")
    weekly = load("mart_weekly")
    agents = load("mart_agents")
    channels = load("mart_channels")
    partners = load("mart_partners")
    repeats = load("mart_repeat_devices")

    REPORTS.mkdir(parents=True, exist_ok=True)
    dashboard = REPORTS / "dashboard.html"
    dashboard.write_text(
        render_html(kpi, metrics, categories, sla, weekly, agents, channels, partners, repeats),
        encoding="utf-8",
    )
    summary = REPORTS / "summary.md"
    summary.write_text(render_md(kpi, metrics, categories, sla, repeats), encoding="utf-8")
    return {"dashboard": dashboard, "summary": summary}


def main() -> None:
    argparse.ArgumentParser(description="Сборка отчёта по заявкам").parse_args()
    for name, path in build().items():
        print(f"{name:10s} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
