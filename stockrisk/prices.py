"""가격 데이터 모듈.

Yahoo Finance 공개 차트 API에서 일봉 이력을 받아 수익률·변동성 등 지표를
계산한다. API 키 불필요. 네트워크 실패 시 None을 반환하며, 호출측은
가격 섹션을 표시하지 않는다 — 가격 데이터를 추정하거나 지어내지 않는다.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1d"
USER_AGENT = "Mozilla/5.0 (compatible; StockRiskBot/0.2)"


@dataclass
class PriceHistory:
    symbol: str
    dates: list[str] = field(default_factory=list)      # "YYYY-MM-DD"
    closes: list[float] = field(default_factory=list)
    currency: str = ""

    # ── 파생 지표 (모두 실측 종가 기반 계산값) ──────────────────
    @property
    def last_close(self) -> float:
        return self.closes[-1]

    def return_over(self, days: int) -> float | None:
        """최근 n거래일 수익률(%). 데이터 부족 시 None."""
        if len(self.closes) <= days:
            return None
        base = self.closes[-days - 1]
        if base <= 0:
            return None
        return (self.closes[-1] / base - 1.0) * 100

    @property
    def annualized_volatility(self) -> float | None:
        """일간 수익률 표준편차 × √252 (%). 30일 미만 데이터면 None."""
        if len(self.closes) < 30:
            return None
        rets = [
            math.log(b / a)
            for a, b in zip(self.closes[:-1], self.closes[1:])
            if a > 0 and b > 0
        ]
        if len(rets) < 20:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var) * math.sqrt(252) * 100

    @property
    def max_drawdown(self) -> float | None:
        """기간 내 최대 낙폭(%, 음수)."""
        if len(self.closes) < 2:
            return None
        peak = self.closes[0]
        mdd = 0.0
        for c in self.closes:
            peak = max(peak, c)
            if peak > 0:
                mdd = min(mdd, c / peak - 1.0)
        return mdd * 100

    @property
    def period_high(self) -> float:
        return max(self.closes)

    @property
    def period_low(self) -> float:
        return min(self.closes)


def fetch_history(symbol: str, range_: str = "6mo", timeout: int = 8) -> PriceHistory | None:
    """일봉 이력 조회. 어떤 이유로든 실패하면 None (가격 섹션 비표시)."""
    url = YAHOO_CHART.format(symbol=urllib.parse.quote(symbol), range=range_)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        closes_raw = result["indicators"]["quote"][0]["close"]
        currency = result.get("meta", {}).get("currency", "") or ""
    except Exception:
        return None

    import datetime as _dt

    dates, closes = [], []
    for t, c in zip(ts, closes_raw):
        if c is None:
            continue
        dates.append(_dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"))
        closes.append(float(c))
    if len(closes) < 10:
        return None
    return PriceHistory(symbol=symbol, dates=dates, closes=closes, currency=currency)


# ── SVG 라인 차트 (서버 사이드 렌더링, 외부 라이브러리 불필요) ──────

def render_price_svg(
    history: PriceHistory,
    width: int = 720,
    height: int = 240,
    line_color: str = "#3987e5",
    grid_color: str = "#2c2c2a",
    text_color: str = "#898781",
) -> str:
    """종가 라인 차트 SVG. 단일 시리즈(범례 불필요), 2px 라인, 옅은 그리드."""
    pad_l, pad_r, pad_t, pad_b = 56, 12, 12, 24
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    closes = history.closes
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    lo -= span * 0.04
    hi += span * 0.04
    span = hi - lo

    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = pad_l + plot_w * (i / (n - 1))
        y = pad_t + plot_h * (1 - (c - lo) / span)
        pts.append((round(x, 1), round(y, 1)))
    path = "M" + " L".join(f"{x},{y}" for x, y in pts)
    area = f"{path} L{pts[-1][0]},{pad_t + plot_h} L{pts[0][0]},{pad_t + plot_h} Z"

    # 가로 그리드 4줄 + y라벨
    grid_lines, y_labels = [], []
    for k in range(5):
        val = lo + span * k / 4
        y = pad_t + plot_h * (1 - k / 4)
        grid_lines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="{grid_color}" stroke-width="1"/>'
        )
        label = f"{val:,.0f}" if val >= 100 else f"{val:,.2f}"
        y_labels.append(
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{text_color}">{label}</text>'
        )
    # x라벨: 처음/중간/끝 날짜
    xi = [0, n // 2, n - 1]
    x_labels = [
        f'<text x="{pts[i][0]}" y="{height - 6}" text-anchor="middle" '
        f'font-size="11" fill="{text_color}">{history.dates[i]}</text>'
        for i in xi
    ]

    circles = (
        f'<circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="4" fill="{line_color}" '
        f'stroke="#161618" stroke-width="2"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{history.symbol} 최근 종가 추이" '
        f'style="width:100%;height:auto;display:block">'
        + "".join(grid_lines) + "".join(y_labels) + "".join(x_labels)
        + f'<path d="{area}" fill="{line_color}" opacity="0.08"/>'
        + f'<path d="{path}" fill="none" stroke="{line_color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        + circles
        + "</svg>"
    )
