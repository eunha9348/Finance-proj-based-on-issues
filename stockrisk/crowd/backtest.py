"""군중심리지수 기반 역발상(contrarian) 배분 전략 백테스트.

전략: 매월 말 관측된 지수 구간(band)에 따라 다음 달의 주식 비중을 정한다
(공포일수록 비중 확대, 탐욕일수록 비중 축소 — 역발상). 신호는 항상 '그 달까지의
데이터'로만 계산되어 다음 달 수익에 적용되므로 미래 참조가 없다.

| 구간 | 주식 비중 | 현금성 비중 |
|---|---|---|
| 극단적 공포 | 100% | 0% |
| 공포 | 75% | 25% |
| 중립 | 50% | 50% |
| 탐욕 | 25% | 75% |
| 극단적 탐욕 | 0% | 100% |

비교 대상(벤치마크)은 S&P500 배당 재투자 매수·보유(buy & hold total return)다.
현금성 비중의 수익률은 미 장기금리(Shiller 데이터의 Long Interest Rate)를
매월 단리로 근사해 사용한다 — 별도 무위험금리 데이터를 새로 구할 필요 없이
같은 데이터셋 안에서 조달한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from stockrisk.crowd.data import MonthlyRecord
from stockrisk.crowd.index import CrowdIndexPoint

ALLOCATION_BY_BAND = {
    "extreme_fear": 1.00,
    "fear": 0.75,
    "neutral": 0.50,
    "greed": 0.25,
    "extreme_greed": 0.00,
}


@dataclass
class BacktestPoint:
    month: str
    equity_strategy: float
    equity_benchmark: float
    weight_equity: float
    strategy_return: float
    benchmark_return: float


@dataclass
class PerformanceStats:
    months: int
    total_return: float
    cagr: float
    ann_volatility: float
    sharpe: float
    max_drawdown: float
    calmar: float
    win_rate: float


@dataclass
class BacktestResult:
    points: list[BacktestPoint] = field(default_factory=list)
    strategy: PerformanceStats | None = None
    benchmark: PerformanceStats | None = None
    start_month: str = ""
    end_month: str = ""


def _monthly_total_return(prev: MonthlyRecord, cur: MonthlyRecord) -> float:
    if prev.sp500 <= 0:
        return 0.0
    return (cur.sp500 + cur.dividend_annual / 12.0) / prev.sp500 - 1.0


def _cash_return(prev: MonthlyRecord) -> float:
    return prev.long_rate_pct / 100.0 / 12.0


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def _stats(returns: list[float], equity: list[float], cash_returns: list[float]) -> PerformanceStats:
    n = len(returns)
    total_return = equity[-1] / equity[0] - 1.0
    cagr = (equity[-1] / equity[0]) ** (12.0 / n) - 1.0 if n > 0 else 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    ann_vol = math.sqrt(var) * math.sqrt(12)
    avg_rf_annual = (sum(cash_returns) / len(cash_returns)) * 12 if cash_returns else 0.0
    sharpe = (cagr - avg_rf_annual) / ann_vol if ann_vol > 0 else 0.0
    mdd = _max_drawdown(equity)
    calmar = (cagr / abs(mdd)) if mdd < 0 else float("inf")
    win_rate = sum(1 for r in returns if r > 0) / n
    return PerformanceStats(
        months=n,
        total_return=total_return,
        cagr=cagr,
        ann_volatility=ann_vol,
        sharpe=sharpe,
        max_drawdown=mdd,
        calmar=calmar,
        win_rate=win_rate,
    )


def period_return(points: list[BacktestPoint], start_month: str, end_month: str) -> tuple[float, float] | None:
    """[start_month, end_month] 구간(포함)의 전략·벤치마크 누적수익률. 데이터 없으면 None."""
    window = [p for p in points if start_month <= p.month <= end_month]
    if not window:
        return None
    strat = 1.0
    bench = 1.0
    for p in window:
        strat *= 1 + p.strategy_return
        bench *= 1 + p.benchmark_return
    return strat - 1.0, bench - 1.0


def run_backtest(records: list[MonthlyRecord], index_points: list[CrowdIndexPoint]) -> BacktestResult:
    """index_points[i]는 records[i]와 같은 달의 신호이며, records[i+1]의 수익에 적용한다."""
    by_month_record = {r.month: r for r in records}
    index_by_month = {p.month: p for p in index_points}
    months = [r.month for r in records]

    result = BacktestResult()
    eq_strategy = 1.0
    eq_benchmark = 1.0
    strat_returns: list[float] = []
    bench_returns: list[float] = []
    cash_returns: list[float] = []

    for i in range(1, len(months)):
        signal_month = months[i - 1]
        if signal_month not in index_by_month:
            continue  # 준비 기간(min_history) 이전은 백테스트에서 제외
        prev_rec = by_month_record[signal_month]
        cur_rec = by_month_record[months[i]]

        weight = ALLOCATION_BY_BAND[index_by_month[signal_month].band]
        sp_ret = _monthly_total_return(prev_rec, cur_rec)
        cash_ret = _cash_return(prev_rec)
        strat_ret = weight * sp_ret + (1 - weight) * cash_ret

        eq_strategy *= 1 + strat_ret
        eq_benchmark *= 1 + sp_ret

        strat_returns.append(strat_ret)
        bench_returns.append(sp_ret)
        cash_returns.append(cash_ret)

        result.points.append(
            BacktestPoint(
                month=months[i],
                equity_strategy=eq_strategy,
                equity_benchmark=eq_benchmark,
                weight_equity=weight,
                strategy_return=strat_ret,
                benchmark_return=sp_ret,
            )
        )

    if not result.points:
        return result

    strat_equity = [1.0] + [p.equity_strategy for p in result.points]
    bench_equity = [1.0] + [p.equity_benchmark for p in result.points]
    result.strategy = _stats(strat_returns, strat_equity, cash_returns)
    result.benchmark = _stats(bench_returns, bench_equity, cash_returns)
    result.start_month = result.points[0].month
    result.end_month = result.points[-1].month
    return result
