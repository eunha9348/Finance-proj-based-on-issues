"""리포트용 SVG 차트 (외부 라이브러리 불필요, stockrisk/prices.py와 같은 방식)."""
from __future__ import annotations

import math

from stockrisk.crowd.backtest import BacktestPoint
from stockrisk.crowd.index import CrowdIndexPoint

_BAND_COLOR = {
    "extreme_fear": "#d64545",
    "fear": "#e08a3c",
    "neutral": "#8a8a86",
    "greed": "#5a9e5a",
    "extreme_greed": "#2f8f4e",
}


def _x_labels(dates: list[str], width: int, pad_l: int, pad_r: int, y: float, text_color: str) -> str:
    plot_w = width - pad_l - pad_r
    n = len(dates)
    idxs = [0, n // 2, n - 1]
    out = []
    for i in idxs:
        x = pad_l + plot_w * (i / (n - 1))
        out.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{text_color}">{dates[i]}</text>'
        )
    return "".join(out)


def render_equity_curve_svg(
    points: list[BacktestPoint],
    width: int = 760,
    height: int = 300,
    strategy_color: str = "#3987e5",
    benchmark_color: str = "#e0a83c",
    grid_color: str = "#2c2c2a",
    text_color: str = "#898781",
) -> str:
    """전략 vs 벤치마크 누적 성장(로그 스케일) 라인 차트."""
    pad_l, pad_r, pad_t, pad_b = 60, 12, 16, 26
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    dates = [p.month for p in points]
    strat_log = [math.log10(p.equity_strategy) for p in points]
    bench_log = [math.log10(p.equity_benchmark) for p in points]
    lo = min(min(strat_log), min(bench_log), 0.0)
    hi = max(max(strat_log), max(bench_log), 0.0)
    span = (hi - lo) or 1.0
    lo -= span * 0.05
    hi += span * 0.05
    span = hi - lo

    n = len(points)

    def path_for(values: list[float]) -> str:
        pts = []
        for i, v in enumerate(values):
            x = pad_l + plot_w * (i / (n - 1))
            y = pad_t + plot_h * (1 - (v - lo) / span)
            pts.append(f"{x:.1f},{y:.1f}")
        return "M" + " L".join(pts)

    grid_lines, y_labels = [], []
    for k in range(5):
        val = lo + span * k / 4
        y = pad_t + plot_h * (1 - k / 4)
        grid_lines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="{grid_color}" stroke-width="1"/>'
        )
        multiple = 10 ** val
        y_labels.append(
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{text_color}">{multiple:,.1f}x</text>'
        )

    legend = (
        f'<circle cx="{width - 190}" cy="{pad_t + 2}" r="4" fill="{strategy_color}"/>'
        f'<text x="{width - 180}" y="{pad_t + 6}" font-size="11" fill="{text_color}">군중심리 역발상 전략</text>'
        f'<circle cx="{width - 190}" cy="{pad_t + 18}" r="4" fill="{benchmark_color}"/>'
        f'<text x="{width - 180}" y="{pad_t + 22}" font-size="11" fill="{text_color}">S&amp;P500 매수·보유</text>'
    )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="군중심리지수 전략 vs S&amp;P500 매수·보유 누적성장(로그)" '
        f'style="width:100%;height:auto;display:block">'
        + "".join(grid_lines) + "".join(y_labels)
        + _x_labels(dates, width, pad_l, pad_r, height - 6, text_color)
        + f'<path d="{path_for(bench_log)}" fill="none" stroke="{benchmark_color}" stroke-width="2" stroke-linejoin="round"/>'
        + f'<path d="{path_for(strat_log)}" fill="none" stroke="{strategy_color}" stroke-width="2" stroke-linejoin="round"/>'
        + legend
        + "</svg>"
    )


def render_index_history_svg(
    index_points: list[CrowdIndexPoint],
    width: int = 760,
    height: int = 220,
    line_color: str = "#3987e5",
    grid_color: str = "#2c2c2a",
    text_color: str = "#898781",
) -> str:
    """군중심리지수 0~100 시계열 + 공포/탐욕 기준선."""
    pad_l, pad_r, pad_t, pad_b = 40, 12, 12, 26
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(index_points)
    dates = [p.month for p in index_points]

    def y_of(v: float) -> float:
        return pad_t + plot_h * (1 - v / 100.0)

    pts = []
    for i, p in enumerate(index_points):
        x = pad_l + plot_w * (i / (n - 1))
        pts.append(f"{x:.1f},{y_of(p.score):.1f}")
    path = "M" + " L".join(pts)

    thresholds = [25, 45, 55, 75]
    lines = []
    for t in thresholds:
        y = y_of(t)
        lines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="{grid_color}" stroke-width="1" stroke-dasharray="3,3"/>'
        )

    last = index_points[-1]
    last_x = pad_l + plot_w
    last_y = y_of(last.score)
    marker = (
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" '
        f'fill="{_BAND_COLOR[last.band]}" stroke="#161618" stroke-width="1.5"/>'
    )

    y_labels = "".join(
        f'<text x="{pad_l - 6}" y="{y_of(v) + 4:.1f}" text-anchor="end" '
        f'font-size="10" fill="{text_color}">{v}</text>'
        for v in (0, 25, 45, 55, 75, 100)
    )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="군중심리지수 추이(0~100)" '
        f'style="width:100%;height:auto;display:block">'
        + "".join(lines) + y_labels
        + _x_labels(dates, width, pad_l, pad_r, height - 6, text_color)
        + f'<path d="{path}" fill="none" stroke="{line_color}" stroke-width="1.6"/>'
        + marker
        + "</svg>"
    )
