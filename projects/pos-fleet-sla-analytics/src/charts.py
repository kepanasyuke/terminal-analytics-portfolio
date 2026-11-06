"""Лёгкие SVG-графики для HTML-отчётов: без зависимостей, работают офлайн.

Python-часть только упаковывает данные в data-chart; рисование и анимация — в CHART_JS.
Анимация отключается системной настройкой prefers-reduced-motion.
"""

from __future__ import annotations

import html
import json

CHART_CSS = """
.chart { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 20px 22px; margin-bottom: 20px; }
.chart h2 { margin: 0 0 4px; font-size: 17px; }
.chart-hint { color: var(--muted); font-size: 12.5px; margin: 0 0 14px; max-width: 900px; }
.chart-host { position: relative; width: 100%; }
.chart svg { width: 100%; height: 100%; display: block; overflow: visible; }
.chart .grid line { stroke: var(--line); stroke-width: 1; }
.chart .axis text { fill: var(--muted); font-size: 11px; font-family: "Segoe UI", Roboto, Arial, sans-serif; }
.chart .value-label { fill: var(--muted); font-size: 11px; font-family: "Segoe UI", Roboto, Arial, sans-serif; }
.chart .series-line { fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 2000; stroke-dashoffset: 2000; animation: chart-draw 1.5s ease-out forwards; }
.chart .series-area { opacity: 0; animation: chart-fade .9s .55s ease-out forwards; }
.chart .dot { opacity: 0; animation: chart-fade .35s ease-out forwards; }
.chart .bar { transform-box: fill-box; transform-origin: bottom; animation: chart-grow .85s cubic-bezier(.2,.9,.2,1) forwards; }
.chart .donut-seg { animation: chart-donut 1.2s cubic-bezier(.3,.9,.3,1) forwards; }
.chart .chart-legend { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 12px;
  font-size: 12.5px; color: var(--muted); }
.chart .chart-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px;
  margin-right: 7px; vertical-align: -1px; }
.chart .donut-center { fill: var(--ink); font-size: 22px; font-weight: 600; text-anchor: middle;
  font-family: "Segoe UI", Roboto, Arial, sans-serif; }
.chart .donut-sub { fill: var(--muted); font-size: 11px; text-anchor: middle;
  font-family: "Segoe UI", Roboto, Arial, sans-serif; }
@keyframes chart-draw { to { stroke-dashoffset: 0; } }
@keyframes chart-fade { to { opacity: 1; } }
@keyframes chart-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes chart-donut { from { stroke-dasharray: 0 100; } }
@media (prefers-reduced-motion: reduce) {
  .chart .series-line, .chart .series-area, .chart .dot, .chart .bar, .chart .donut-seg {
    animation: none !important; opacity: 1 !important; stroke-dashoffset: 0 !important;
    stroke-dasharray: var(--dash, none) !important; transform: none !important;
  }
  .countup { animation: none !important; }
}
"""

CHART_JS = r"""
(function () {
  var NS = "http://www.w3.org/2000/svg";
  var PALETTE = ["#2563eb", "#0f766e", "#c2760b", "#c23b4b", "#6d28d9", "#7c8aa0", "#1f9d63"];
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function node(name, attrs) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) { n.setAttribute(k, attrs[k]); } }
    return n;
  }
  function fmt(v) {
    var rounded = Math.round(v * 10) / 10;
    return String(rounded).replace(".", ",").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  function niceMax(max) {
    if (!(max > 0)) { return 1; }
    var pow = Math.pow(10, Math.floor(Math.log(max) / Math.LN10));
    var n = max / pow;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * pow;
  }
  function host(container) {
    var w = 760, h = container.clientHeight || 260;
    var pad = {l: 48, r: 14, t: 14, b: 30};
    var svg = node("svg", {viewBox: "0 0 " + w + " " + h, role: "img"});
    container.appendChild(svg);
    return {svg: svg, w: w, h: h, pad: pad, iw: w - pad.l - pad.r, ih: h - pad.t - pad.b};
  }
  function gridAndAxis(f, max, labels, showEvery) {
    var g = node("g", {"class": "grid"});
    for (var i = 0; i <= 4; i++) {
      var y = f.pad.t + f.ih * i / 4;
      g.appendChild(node("line", {x1: f.pad.l, x2: f.pad.l + f.iw, y1: y, y2: y}));
      var t = node("text", {x: f.pad.l - 8, y: y + 4, "text-anchor": "end", "class": "value-label"});
      t.textContent = fmt(max * (4 - i) / 4);
      g.appendChild(t);
    }
    f.svg.appendChild(g);
    var ax = node("g", {"class": "axis"});
    var step = showEvery || Math.ceil(labels.length / 8);
    labels.forEach(function (label, idx) {
      if (idx % step !== 0 && idx !== labels.length - 1) { return; }
      var x = f.pad.l + (labels.length === 1 ? f.iw / 2 : f.iw * idx / (labels.length - 1));
      var t = node("text", {x: x, y: f.pad.t + f.ih + 18, "text-anchor": "middle"});
      t.textContent = label;
      ax.appendChild(t);
    });
    f.svg.appendChild(ax);
  }
  function lineChart(container, cfg) {
    var f = host(container);
    var series = cfg.series || [];
    var labels = cfg.labels || [];
    var max = 0;
    series.forEach(function (s) { s.values.forEach(function (v) { max = Math.max(max, v); }); });
    max = niceMax(max);
    gridAndAxis(f, max, labels);
    var count = labels.length;
    series.forEach(function (s, si) {
      var color = s.color || PALETTE[si % PALETTE.length];
      var pts = s.values.map(function (v, i) {
        var x = f.pad.l + (count === 1 ? f.iw / 2 : f.iw * i / (count - 1));
        var y = f.pad.t + f.ih - (v / max) * f.ih;
        return [x, y];
      });
      if (cfg.area) {
        var area = "M" + pts[0][0] + "," + (f.pad.t + f.ih) +
          pts.map(function (p) { return "L" + p[0] + "," + p[1]; }).join("") +
          "L" + pts[pts.length - 1][0] + "," + (f.pad.t + f.ih) + "Z";
        f.svg.appendChild(node("path", {d: area, fill: color, "fill-opacity": "0.10",
          "class": "series-area"}));
      }
      var d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0] + "," + p[1]; }).join("");
      var path = node("path", {d: d, stroke: color, "class": "series-line"});
      f.svg.appendChild(path);
      if (reduce) {
        path.style.strokeDashoffset = "0";
      } else {
        var len = 0;
        try { len = path.getTotalLength(); } catch (e) { len = 2000; }
        path.style.strokeDasharray = len;
        path.style.strokeDashoffset = len;
        path.style.animation = "chart-draw 1.5s ease-out forwards";
      }
      pts.forEach(function (p, i) {
        var dot = node("circle", {cx: p[0], cy: p[1], r: 3.2, fill: color, "class": "dot"});
        dot.style.animationDelay = (reduce ? 0 : 0.25 + i * 0.02) + "s";
        f.svg.appendChild(dot);
      });
    });
    legend(container, series.map(function (s, i) {
      return {name: s.name, color: s.color || PALETTE[i % PALETTE.length]};
    }));
  }
  function barChart(container, cfg) {
    var f = host(container);
    var values = cfg.values || [];
    var labels = cfg.labels || [];
    var max = niceMax(Math.max.apply(null, values.concat([0])));
    gridAndAxis(f, max, [], 1);
    var ax = node("g", {"class": "axis"});
    var slot = f.iw / Math.max(1, values.length);
    var bw = Math.min(46, slot * 0.58);
    values.forEach(function (v, i) {
      var h = max ? (v / max) * f.ih : 0;
      var x = f.pad.l + slot * i + (slot - bw) / 2;
      var y = f.pad.t + f.ih - h;
      var rect = node("rect", {x: x, y: y, width: bw, height: Math.max(h, 0.6), rx: 4,
        fill: cfg.color || PALETTE[i % PALETTE.length], "class": "bar"});
      rect.style.animationDelay = (reduce ? 0 : i * 0.06) + "s";
      f.svg.appendChild(rect);
      var t = node("text", {x: x + bw / 2, y: y - 6, "text-anchor": "middle",
        "class": "value-label"});
      t.textContent = fmt(v);
      f.svg.appendChild(t);
      var lt = node("text", {x: x + bw / 2, y: f.pad.t + f.ih + 18, "text-anchor": "middle"});
      lt.textContent = labels[i] || "";
      ax.appendChild(lt);
    });
    f.svg.appendChild(ax);
  }
  function donutChart(container, cfg) {
    var w = 760, h = container.clientHeight || 260;
    var svg = node("svg", {viewBox: "0 0 " + w + " " + h, role: "img"});
    container.appendChild(svg);
    var items = cfg.items || [];
    var total = items.reduce(function (a, b) { return a + b.value; }, 0) || 1;
    var cx = 150, cy = h / 2, r = Math.min(h / 2 - 12, 96);
    var offset = 0;
    items.forEach(function (item, i) {
      var share = item.value / total;
      var color = item.color || PALETTE[i % PALETTE.length];
      var circle = node("circle", {cx: cx, cy: cy, r: r, fill: "none", stroke: color,
        "stroke-width": 22, pathLength: 100, "class": "donut-seg",
        transform: "rotate(-90 " + cx + " " + cy + ")"});
      circle.style.strokeDasharray = reduce ? share * 100 + " 100" : "0 100";
      circle.style.setProperty("--dash", share * 100 + " 100");
      circle.style.strokeDashoffset = -offset * 100;
      if (!reduce) {
        circle.style.animationDelay = (i * 0.09) + "s";
        circle.setAttribute("data-target", share * 100);
      }
      svg.appendChild(circle);
      offset += share;
    });
    if (!reduce) {
      svg.querySelectorAll(".donut-seg").forEach(function (seg) {
        var target = seg.getAttribute("data-target");
        seg.style.animation = "none";
        void seg.getBoundingClientRect();
        seg.style.strokeDasharray = "0 100";
        seg.animate(
          [{strokeDasharray: "0 100"}, {strokeDasharray: target + " 100"}],
          {duration: 1100, delay: Number(seg.style.animationDelay.replace("s", "")) * 1000,
           easing: "cubic-bezier(.3,.9,.3,1)", fill: "forwards"}
        );
      });
    }
    var center = node("text", {x: cx, y: cy - 2, "class": "donut-center"});
    center.textContent = cfg.center || fmt(total);
    svg.appendChild(center);
    var sub = node("text", {x: cx, y: cy + 18, "class": "donut-sub"});
    sub.textContent = cfg.centerSub || "всего";
    svg.appendChild(sub);

    var legendBox = document.createElement("div");
    legendBox.className = "chart-legend";
    items.forEach(function (item, i) {
      var span = document.createElement("span");
      span.innerHTML = '<i style="background:' + (item.color || PALETTE[i % PALETTE.length]) +
        '"></i>' + item.name + " — " + fmt(item.value) +
        " (" + (100 * item.value / total).toFixed(1).replace(".", ",") + " %)";
      legendBox.appendChild(span);
    });
    container.appendChild(legendBox);
  }
  function legend(container, items) {
    var box = document.createElement("div");
    box.className = "chart-legend";
    items.forEach(function (item) {
      var span = document.createElement("span");
      span.innerHTML = '<i style="background:' + item.color + '"></i>' + item.name;
      box.appendChild(span);
    });
    container.appendChild(box);
  }
  function parse(value) {
    return value.replace(/\s/g, "").replace(",", ".");
  }
  function countUp(el) {
    var match = /^(\s*)([\d\s\u00a0]+(?:[.,]\d+)?)(.*)$/.exec(el.textContent);
    if (!match) { return; }
    var target = parseFloat(parse(match[2]));
    if (!isFinite(target) || target === 0) { return; }
    var decimals = match[2].indexOf(",") >= 0 ? 1 : 0;
    var prefix = match[1], suffix = match[3];
    var started = null;
    function frame(ts) {
      if (!started) { started = ts; }
      var progress = Math.min(1, (ts - started) / 900);
      var eased = 1 - Math.pow(1 - progress, 3);
      var value = target * eased;
      var text = decimals
        ? value.toFixed(1).replace(".", ",")
        : String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
      el.textContent = prefix + text + suffix;
      if (progress < 1) { window.requestAnimationFrame(frame); }
    }
    el.textContent = prefix + (decimals ? "0,0" : "0") + suffix;
    window.requestAnimationFrame(frame);
  }
  function init() {
    document.querySelectorAll(".chart-host").forEach(function (container) {
      var raw = container.getAttribute("data-chart");
      if (!raw) { return; }
      var cfg;
      try { cfg = JSON.parse(raw); } catch (e) { return; }
      if (cfg.type === "line") { lineChart(container, cfg); }
      else if (cfg.type === "bars") { barChart(container, cfg); }
      else if (cfg.type === "donut") { donutChart(container, cfg); }
    });
    if (!reduce && "IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            countUp(entry.target);
            io.unobserve(entry.target);
          }
        });
      }, {threshold: 0.4});
      document.querySelectorAll(".kpi-value").forEach(function (el) {
        if (el.querySelector("small")) { return; }
        io.observe(el);
      });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""


def chart(title: str, hint: str, config: dict, height: int = 260) -> str:
    """Возвращает HTML-блок с графиком; данные уходят в data-chart как JSON."""
    payload = html.escape(json.dumps(config, ensure_ascii=False), quote=True)
    return (
        f'<section class="chart"><h2>{html.escape(title)}</h2>'
        f'<p class="chart-hint">{html.escape(hint)}</p>'
        f'<div class="chart-host" data-chart="{payload}" style="height:{height}px"></div>'
        "</section>"
    )


def assets() -> str:
    """CSS и JS для вставки в <head> и перед </body>."""
    return CHART_CSS, CHART_JS
