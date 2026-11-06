"""Генератор анимированных SVG-превью для README.

GitHub не исполняет скрипты, но отрисовывает декларативную анимацию SMIL в SVG,
подключённом через <img>. Поэтому превью рисуются из тех же витрин, что и отчёты,
и анимируются средствами самого SVG: линия прорисовывается, столбцы растут,
донат раскрывается, точки на схеме пайплайна бегут по стрелкам.

Запуск (данные должны быть посчитаны пайплайнами проектов):

    python tools/make_readme_animations.py
"""

from __future__ import annotations

import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"

BG = "#f6f8fb"
PANEL = "#ffffff"
LINE = "#e3e9f3"
INK = "#111f38"
MUTED = "#6a7a92"
BLUE = "#2563eb"
RED = "#cf3b45"
TEAL = "#0f766e"
VIOLET = "#4f46e5"
AMBER = "#d9821b"

FONT = "'Segoe UI',Roboto,Arial,sans-serif"


def read(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"нет файла {path}: сначала прогоните пайплайн проекта")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def num(value, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    return float(value)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def nice_max(max_value: float) -> float:
    if max_value <= 0:
        return 1
    exponent = 10 ** int(_log10(max_value))
    scaled = max_value / exponent
    step = 1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10
    return step * exponent


def _log10(value: float) -> float:
    import math

    return math.log10(value)


def header(width: int, height: int, title: str, subtitle: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        f"<title>{esc(title)}</title>"
        f'<rect width="{width}" height="{height}" rx="16" fill="{BG}"/>'
        f'<text x="24" y="34" font-family="{FONT}" font-size="17" font-weight="600" '
        f'fill="{INK}">{esc(title)}</text>'
        f'<text x="24" y="55" font-family="{FONT}" font-size="12" fill="{MUTED}">'
        f"{esc(subtitle)}</text>"
    )


def footer() -> str:
    return "</svg>"


def grid_layer(width: int, height: int, left: int, right: int, top: int, bottom: int,
               max_value: float) -> str:
    parts = []
    inner_h = bottom - top
    for index in range(5):
        y = top + inner_h * index / 4
        parts.append(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" '
                     f'stroke="{LINE}" stroke-width="1"/>')
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="{FONT}" '
            f'font-size="11" fill="{MUTED}">{fmt_int(max_value * (4 - index) / 4)}</text>'
        )
    return "".join(parts)


def path_length(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return total


def line_chart(title: str, subtitle: str, labels: list[str],
               series: list[tuple[str, list[float], str]], width: int = 760,
               height: int = 300) -> str:
    left, right, top, bottom = 56, width - 24, 74, height - 44
    inner_w, inner_h = right - left, bottom - top
    values = [value for _, points, _ in series for value in points]
    max_value = nice_max(max(values))
    body = [header(width, height, title, subtitle),
            grid_layer(width, height, left, right, top, bottom, max_value)]

    count = len(labels)
    step = max(1, count // 8)
    for index, label in enumerate(labels):
        if index % step and index != count - 1:
            continue
        x = left + inner_w * index / (count - 1 if count > 1 else 1)
        body.append(f'<text x="{x:.1f}" y="{bottom + 20}" text-anchor="middle" '
                    f'font-family="{FONT}" font-size="11" fill="{MUTED}">{esc(label)}</text>')

    for order, (name, points, color) in enumerate(series):
        coords = [
            (left + inner_w * index / (count - 1 if count > 1 else 1),
             bottom - inner_h * (value / max_value if max_value else 0))
            for index, value in enumerate(points)
        ]
        path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        length = max(path_length(coords), 1.0)
        begin = 0.25 + order * 0.35
        body.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.6" '
            f'stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="{length:.0f}" '
            f'stroke-dashoffset="{length:.0f}">'
            f'<animate attributeName="stroke-dashoffset" from="{length:.0f}" to="0" '
            f'dur="2.3s" begin="{begin:.2f}s" fill="freeze"/></path>'
        )
        for index, (x, y) in enumerate(coords):
            delay = begin + 0.35 + index * min(0.06, 1.6 / max(1, len(coords)))
            body.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="0" fill="{color}">'
                f'<animate attributeName="r" from="0" to="3.4" dur="0.35s" '
                f'begin="{delay:.2f}s" fill="freeze"/></circle>'
            )

    legend_x = left
    for name, _, color in series:
        body.append(f'<rect x="{legend_x}" y="{height - 18}" width="10" height="10" rx="3" '
                    f'fill="{color}"/>')
        body.append(f'<text x="{legend_x + 16}" y="{height - 9}" font-family="{FONT}" '
                    f'font-size="12" fill="{MUTED}">{esc(name)}</text>')
        legend_x += 16 + len(name) * 7.2 + 26
    body.append(footer())
    return "".join(body)


def bar_chart(title: str, subtitle: str, labels: list[str], values: list[float],
              suffix: str = "", color: str = TEAL, width: int = 760, height: int = 300,
              threshold: float | None = None) -> str:
    left, right, top, bottom = 56, width - 24, 74, height - 52
    inner_w, inner_h = right - left, bottom - top
    max_value = nice_max(max(values))
    body = [header(width, height, title, subtitle),
            grid_layer(width, height, left, right, top, bottom, max_value)]

    slot = inner_w / max(1, len(values))
    bar_w = min(56, slot * 0.55)
    for index, value in enumerate(values):
        target_h = inner_h * (value / max_value if max_value else 0)
        x = left + slot * index + (slot - bar_w) / 2
        y = bottom - target_h
        delay = 0.2 + index * 0.12
        body.append(
            f'<rect x="{x:.1f}" y="{bottom}" width="{bar_w:.1f}" height="0" rx="5" fill="{color}">'
            f'<animate attributeName="height" from="0" to="{target_h:.1f}" dur="0.9s" '
            f'begin="{delay:.2f}s" fill="freeze"/>'
            f'<animate attributeName="y" from="{bottom}" to="{y:.1f}" dur="0.9s" '
            f'begin="{delay:.2f}s" fill="freeze"/></rect>'
        )
        body.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="12" font-weight="600" fill="{INK}" opacity="0">'
            f'{value:.1f}{esc(suffix)}'
            f'<animate attributeName="opacity" from="0" to="1" dur="0.4s" '
            f'begin="{delay + 0.7:.2f}s" fill="freeze"/></text>'
        )
        body.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{bottom + 20}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{MUTED}">{esc(labels[index])}</text>'
        )

    if threshold is not None and max_value:
        y = bottom - inner_h * (threshold / max_value)
        body.append(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{RED}" '
                    f'stroke-width="1.5" stroke-dasharray="6 5">'
                    f'<animate attributeName="opacity" from="0" to="1" dur="0.6s" '
                    f'begin="0.4s" fill="freeze"/></line>')
        body.append(f'<text x="{right - 4}" y="{y - 8:.1f}" text-anchor="end" '
                    f'font-family="{FONT}" font-size="11" fill="{RED}">порог {threshold:g}%</text>')
    body.append(footer())
    return "".join(body)


def donut_chart(title: str, subtitle: str, items: list[tuple[str, float]],
                width: int = 760, height: int = 300) -> str:
    body = [header(width, height, title, subtitle)]
    total = sum(value for _, value in items) or 1
    cx, cy, radius = 150, height / 2 + 18, 86
    palette = [BLUE, TEAL, AMBER, RED, VIOLET, "#7c8aa0", "#1f9d63", "#b45309"]
    offset = 0.0
    body.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{LINE}" '
                f'stroke-width="24"/>')
    for index, (name, value) in enumerate(items):
        share = 100.0 * value / total
        color = palette[index % len(palette)]
        body.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" '
            f'stroke-width="24" pathLength="100" stroke-dasharray="0 100" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'<animate attributeName="stroke-dasharray" from="0 100" '
            f'to="{share:.2f} 100" dur="0.85s" begin="{0.2 + index * 0.14:.2f}s" '
            f'fill="freeze"/></circle>'
        )
        offset += share

    body.append(f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-family="{FONT}" '
                f'font-size="24" font-weight="600" fill="{INK}">{fmt_int(total)}</text>')
    body.append(f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" font-family="{FONT}" '
                f'font-size="11" fill="{MUTED}">всего</text>')

    legend_x, legend_y = 310, 96
    for index, (name, value) in enumerate(items):
        color = palette[index % len(palette)]
        y = legend_y + index * 26
        delay = 0.5 + index * 0.12
        body.append(
            f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" dur="0.4s" '
            f'begin="{delay:.2f}s" fill="freeze"/>'
            f'<rect x="{legend_x}" y="{y - 9}" width="10" height="10" rx="3" fill="{color}"/>'
            f'<text x="{legend_x + 18}" y="{y}" font-family="{FONT}" font-size="12" fill="{INK}">'
            f'{esc(name)}</text>'
            f'<text x="{width - 24}" y="{y}" text-anchor="end" font-family="{FONT}" '
            f'font-size="12" fill="{MUTED}">{100 * value / total:.1f}%'.replace(".", ",")
            + "</text></g>"
        )
    body.append(footer())
    return "".join(body)


def pipeline_hero() -> str:
    width, height = 900, 220
    body = [header(width, height, "Как устроен каждый проект",
                   "синтетические данные с эталоном → расчёты на SQL или Python → "
                   "метрики → отчёт и тесты")]
    nodes = [
        ("Данные", "генератор с эталоном", 40),
        ("Расчёт", "SQL · Python", 262),
        ("Метрики", "витрины и пороги", 484),
        ("Отчёт", "HTML · CSV · тесты", 706),
    ]
    node_w, node_y, node_h = 172, 96, 74
    body.append(f'<path id="flow" d="M {nodes[0][2] + node_w / 2} {node_y + node_h / 2} '
                f'L {nodes[-1][2] + node_w - 20} {node_y + node_h / 2}" fill="none" '
                f'stroke="none"/>')
    for title, note, x in nodes:
        body.append(
            f'<rect x="{x}" y="{node_y}" width="{node_w}" height="{node_h}" rx="12" '
            f'fill="{PANEL}" stroke="{LINE}"/>'
            f'<text x="{x + node_w / 2}" y="{node_y + 32}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" font-weight="600" fill="{INK}">'
            f"{esc(title)}</text>"
            f'<text x="{x + node_w / 2}" y="{node_y + 52}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{MUTED}">{esc(note)}</text>'
        )
    for index in range(3):
        x = nodes[index][2] + node_w + 6
        body.append(f'<path d="M {x} {node_y + node_h / 2} l 30 0" stroke="{MUTED}" '
                    f'stroke-width="1.6" marker-end="url(#arrow)"/>')
    body.append(
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#6a7a92"/>'
        "</marker></defs>"
    )
    for index in range(3):
        body.append(
            f'<circle r="5" fill="{BLUE}" opacity="0.85">'
            f'<animateMotion dur="3.6s" begin="{index * 1.2:.1f}s" repeatCount="indefinite" '
            f'fill="freeze"><mpath href="#flow"/></animateMotion></circle>'
        )
    body.append(f'<text x="{width / 2}" y="{height - 26}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="12" fill="{MUTED}">'
                "четыре проекта — 46 тестов на эталонных данных</text>")
    body.append(footer())
    return "".join(body)


def build() -> list[Path]:
    written: list[Path] = []

    recon = PROJECTS / "pos-reconciliation-analytics"
    exceptions = read(recon / "reports" / "recon_exceptions.csv")
    by_date: dict[str, int] = {}
    p1_by_date: dict[str, int] = {}
    for row in exceptions:
        by_date[row["txn_date"]] = by_date.get(row["txn_date"], 0) + 1
        if str(row.get("severity")) == "1":
            p1_by_date[row["txn_date"]] = p1_by_date.get(row["txn_date"], 0) + 1
    dates = sorted(by_date)
    svg = line_chart(
        "Сверка терминалов и процессинга",
        f"{fmt_int(sum(by_date.values()))} расхождений на 186 718 операций · по дням",
        [d[5:] for d in dates],
        [("Все расхождения", [by_date[d] for d in dates], BLUE),
         ("Приоритет P1", [p1_by_date.get(d, 0) for d in dates], RED)],
    )
    (recon / "assets").mkdir(parents=True, exist_ok=True)
    (recon / "assets" / "preview.svg").write_text(svg, encoding="utf-8")
    written.append(recon / "assets" / "preview.svg")

    sla = PROJECTS / "pos-fleet-sla-analytics"
    contracts = read(sla / "data" / "processed" / "mart_contract.csv")
    contracts.sort(key=lambda r: num(r["avg_availability_pct"]))
    svg = bar_chart(
        "SLA и доступность парка",
        "средняя доступность по договорам за период · красная линия — граница 95 %",
        [row["partner_name"] for row in contracts],
        [round(num(row["avg_availability_pct"]), 1) for row in contracts],
        suffix=" %",
        threshold=95,
    )
    (sla / "assets").mkdir(parents=True, exist_ok=True)
    (sla / "assets" / "preview.svg").write_text(svg, encoding="utf-8")
    written.append(sla / "assets" / "preview.svg")

    anomaly = PROJECTS / "pos-transaction-anomaly-monitor"
    alerts = read(anomaly / "data" / "processed" / "alerts.csv")
    by_alert_date: dict[str, int] = {}
    high_by_date: dict[str, int] = {}
    for row in alerts:
        by_alert_date[row["txn_date"]] = by_alert_date.get(row["txn_date"], 0) + 1
        if row["severity"] == "HIGH":
            high_by_date[row["txn_date"]] = high_by_date.get(row["txn_date"], 0) + 1
    alert_dates = sorted(by_alert_date)
    svg = line_chart(
        "Мониторинг аномалий",
        f"{len(alerts)} алертов на 7 200 наблюдений · полнота 100 %, точность 81 %",
        [d[5:] for d in alert_dates],
        [("Все алерты", [by_alert_date[d] for d in alert_dates], TEAL),
         ("Высокий приоритет", [high_by_date.get(d, 0) for d in alert_dates], RED)],
    )
    (anomaly / "assets").mkdir(parents=True, exist_ok=True)
    (anomaly / "assets" / "preview.svg").write_text(svg, encoding="utf-8")
    written.append(anomaly / "assets" / "preview.svg")

    tickets = PROJECTS / "servicedesk-ticket-analytics"
    categories = read(tickets / "data" / "processed" / "mart_categories.csv")
    titles = {
        "PAYMENT": "Оплата", "CONNECTIVITY": "Связь", "HARDWARE": "Оборудование",
        "CASH": "Наличные", "SOFTWARE": "ПО", "CONSULT": "Консультации",
        "ACCESS": "Доступ", "OTHER": "Не распознано",
    }
    items = [
        (titles.get(row["category"], row["category"]), num(row["tickets_cnt"]))
        for row in sorted(categories, key=lambda r: -num(r["tickets_cnt"]))
    ]
    svg = donut_chart(
        "Заявки поддержки",
        "структура обращений за период · точность категоризации правилами 86 %",
        items,
    )
    (tickets / "assets").mkdir(parents=True, exist_ok=True)
    (tickets / "assets" / "preview.svg").write_text(svg, encoding="utf-8")
    written.append(tickets / "assets" / "preview.svg")

    (ROOT / "assets").mkdir(parents=True, exist_ok=True)
    hero = ROOT / "assets" / "pipeline.svg"
    hero.write_text(pipeline_hero(), encoding="utf-8")
    written.append(hero)
    return written


if __name__ == "__main__":
    for path in build():
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} КБ")
