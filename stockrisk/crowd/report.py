"""군중심리지수 백테스트 마크다운 리포트 생성."""
from __future__ import annotations

from datetime import datetime

from stockrisk.crowd.backtest import BacktestResult, period_return
from stockrisk.crowd.charts import render_equity_curve_svg, render_index_history_svg
from stockrisk.crowd.data import MonthlyRecord
from stockrisk.crowd.index import CrowdIndexPoint

DISCLAIMER = (
    "> ⚠️ 본 리포트는 공개 데이터로 구성한 실험적 지수와 백테스트 결과이며 "
    "투자 권유가 아닙니다. 과거 성과가 미래 수익을 보장하지 않으며, 모든 투자 "
    "판단과 책임은 투자자 본인에게 있습니다."
)

# (레이블, 시작월, 종료월) — 사전에 널리 알려진 하락장 구간. 결과를 보고 고른 것이 아니라
# 구간을 먼저 정하고 그 안에서 전략/벤치마크 성과를 비교하는 방식(사후 최적화 방지).
STRESS_PERIODS = [
    ("닷컴 버블 붕괴", "2000-03", "2002-10"),
    ("글로벌 금융위기(GFC)", "2007-11", "2009-03"),
    ("코로나19 급락", "2020-02", "2020-04"),
    ("2022년 약세장", "2022-01", "2022-10"),
]


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def build_crowd_report(
    records: list[MonthlyRecord],
    index_points: list[CrowdIndexPoint],
    backtest: BacktestResult,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append("# 🌊 군중심리지수(Crowd Pulse Index) — S&P500 백테스트 리포트")
    lines.append("")
    lines.append(f"- 생성 시각: {now}")
    lines.append(
        f"- 데이터 구간: {records[0].month} ~ {records[-1].month} "
        f"(VIX 일별 + Shiller S&P500 월별 데이터, 실측 스냅샷)"
    )
    lines.append(
        f"- 백테스트 구간: {backtest.start_month} ~ {backtest.end_month} "
        f"({len(backtest.points)}개월, 준비 기간 {index_points[0].month} 이전 제외)"
    )
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")

    # ── 1. 개념 ──────────────────────────────────────────────────
    lines.append("## 1. 무엇을 만들었나")
    lines.append("")
    lines.append(
        "월가 기관 지표(공매도 잔고, 풋/콜 비율 등)는 무료로 구할 수 없어, "
        "**가격이 흘러온 자취 자체에 비친 '대중의 흐름'** 을 근사하는 지수를 만들었다. "
        "CNN Fear & Greed Index와 같은 철학(추세·변동성·밸류에이션 종합)을, 접근 가능한 "
        "실측 공개 데이터만으로 표준 라이브러리로 재구성했다."
    )
    lines.append("")
    lines.append("**하위 지표 4가지** (모두 과거 대비 백분위 0~100으로 환산 후 평균):")
    lines.append("")
    lines.append("| 지표 | 의미 | 방향 |")
    lines.append("|---|---|---|")
    lines.append("| 모멘텀 | 최근 3개월 수익률 | 높을수록 탐욕 |")
    lines.append("| 이격도 | 10개월 이동평균 대비 괴리율 | 높을수록 탐욕 |")
    lines.append("| 변동성(VIX) | VIX 월평균 | **낮을수록** 탐욕(반전) |")
    lines.append("| 밸류에이션(CAPE) | 실러 PE10 | 높을수록 탐욕 |")
    lines.append("")
    lines.append(
        "구간: 0~25 극단적 공포 · 25~45 공포 · 45~55 중립 · 55~75 탐욕 · 75~100 극단적 탐욕. "
        "각 시점의 백분위는 그 시점까지의 최근 10년(120개월) 데이터만 사용해 계산했다 — "
        "미래 데이터를 참조하지 않는다."
    )
    lines.append("")
    lines.append("### 지수 추이")
    lines.append("")
    lines.append(render_index_history_svg(index_points))
    lines.append("")

    latest = index_points[-1]
    lines.append(
        f"**최신값 ({latest.month})**: {latest.score:.1f} / 100 — **{latest.band_label_ko}**"
    )
    lines.append("")

    # ── 2. 전략 ──────────────────────────────────────────────────
    lines.append("## 2. 백테스트 전략")
    lines.append("")
    lines.append(
        "매월 말 관측된 지수 구간에 따라 다음 달 주식 비중을 정하는 **역발상(contrarian) "
        "배분 전략**이다. 공포일수록 비중을 늘리고 탐욕일수록 줄인다. 신호는 항상 그 달까지의 "
        "데이터로만 계산해 다음 달 수익에 적용한다(미래 참조 없음)."
    )
    lines.append("")
    lines.append("| 구간 | 주식 비중 | 현금성 비중 |")
    lines.append("|---|---|---|")
    lines.append("| 극단적 공포 | 100% | 0% |")
    lines.append("| 공포 | 75% | 25% |")
    lines.append("| 중립 | 50% | 50% |")
    lines.append("| 탐욕 | 25% | 75% |")
    lines.append("| 극단적 탐욕 | 0% | 100% |")
    lines.append("")
    lines.append(
        "벤치마크는 S&P500 배당 재투자 매수·보유. 현금성 비중의 수익률은 같은 데이터셋의 "
        "미 장기금리(연율)를 매월 단리로 근사해 사용했다."
    )
    lines.append("")

    # ── 3. 결과 ──────────────────────────────────────────────────
    lines.append("## 3. 성과 비교")
    lines.append("")
    s, b = backtest.strategy, backtest.benchmark
    lines.append("| 지표 | 군중심리 역발상 전략 | S&P500 매수·보유 |")
    lines.append("|---|---|---|")
    lines.append(f"| 총 수익률 | {_pct(s.total_return)} | {_pct(b.total_return)} |")
    lines.append(f"| 연복리수익률(CAGR) | {_pct(s.cagr)} | {_pct(b.cagr)} |")
    lines.append(f"| 연변동성 | {s.ann_volatility * 100:.1f}% | {b.ann_volatility * 100:.1f}% |")
    lines.append(f"| 샤프비율 | {s.sharpe:.2f} | {b.sharpe:.2f} |")
    lines.append(f"| 최대낙폭(MDD) | {s.max_drawdown * 100:.1f}% | {b.max_drawdown * 100:.1f}% |")
    lines.append(f"| 칼마비율 | {s.calmar:.2f} | {b.calmar:.2f} |")
    lines.append(f"| 월간 승률 | {s.win_rate * 100:.1f}% | {b.win_rate * 100:.1f}% |")
    lines.append(f"| $1 투자 시 최종 가치 | ${1 * (1 + s.total_return):.2f} | ${1 * (1 + b.total_return):.2f} |")
    lines.append("")
    lines.append("### 누적 성장 (로그 스케일)")
    lines.append("")
    lines.append(render_equity_curve_svg(backtest.points))
    lines.append("")

    verdict = (
        "이번 백테스트에서는 전략의 **총수익률·샤프비율 모두 매수·보유보다 낮았다**. "
        "장기 강세장에서 '탐욕' 신호가 뜰 때마다 비중을 줄인 것이 상승 국면 상당 부분을 "
        "놓치게 만든 결과로, 밸류에이션·변동성 기반 시장 타이밍이 장기적으로 매수·보유를 "
        "이기기 어렵다는 다수의 실증 연구와 같은 방향이다."
        if s.total_return < b.total_return
        else "이번 백테스트에서는 전략이 매수·보유 대비 총수익률에서도 앞섰다."
    )
    lines.append(f"**요약**: {verdict}")
    lines.append("")

    # ── 4. 하락장 구간 분석 ──────────────────────────────────────
    lines.append("## 4. 주요 하락장에서의 방어력")
    lines.append("")
    lines.append(
        "전체 기간 수익률과는 별개로, 전략이 원래 의도한 '하락장 방어'에서는 실제로 "
        "효과가 있었는지 대표적 하락장 4곳을 미리 정해두고 비교했다(결과를 보고 구간을 "
        "고른 것이 아니다)."
    )
    lines.append("")
    lines.append("| 구간 | 기간 | 전략 수익률 | 벤치마크 수익률 |")
    lines.append("|---|---|---|---|")
    for label, start, end in STRESS_PERIODS:
        res = period_return(backtest.points, start, end)
        if res is None:
            lines.append(f"| {label} | {start}~{end} | 데이터 없음 | 데이터 없음 |")
            continue
        strat_r, bench_r = res
        lines.append(f"| {label} | {start}~{end} | {_pct(strat_r)} | {_pct(bench_r)} |")
    lines.append("")

    # ── 5. 최근 12개월 지수 ──────────────────────────────────────
    lines.append("## 5. 최근 12개월 지수 상세")
    lines.append("")
    lines.append("| 월 | 지수 | 구간 | 모멘텀 | 이격도 | VIX(반전) | CAPE |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in index_points[-12:]:
        c = p.components

        def fmt(k: str) -> str:
            v = c.get(k)
            return f"{v:.0f}" if v is not None else "—"

        lines.append(
            f"| {p.month} | {p.score:.1f} | {p.band_label_ko} | "
            f"{fmt('momentum')} | {fmt('trend')} | {fmt('vix')} | {fmt('cape')} |"
        )
    lines.append("")

    # ── 6. 한계 ──────────────────────────────────────────────────
    lines.append("## 6. 데이터 출처와 한계")
    lines.append("")
    lines.append(
        "- **데이터 출처**: VIX 일별 종가(CBOE, 1990~) — "
        "`datasets/finance-vix` 공개 미러 / S&P500 월별 명목가격·배당·CAPE(PE10) — "
        "Robert Shiller 교수 데이터셋, `datasets/s-and-p-500` 공개 미러. "
        "두 데이터 모두 저장소에 스냅샷으로 커밋되어 있다(`data/market/`)."
    )
    lines.append(
        "- **월간 빈도**: 일별 VIX는 월평균으로 집계했고, S&P500·배당·CAPE는 원 데이터가 "
        "월 단위다. 일중 변동성이나 일별 리밸런싱 효과는 반영되지 않는다."
    )
    lines.append(
        "- **결측 이월**: 원 데이터의 배당·CAPE는 보고 지연으로 최근 구간이 0으로 찍혀 "
        "있어, 마지막 실측값을 이월했다(최근 CAPE는 실측 갱신 전까지 지수 계산에서 제외됨)."
    )
    lines.append("- **거래비용·세금·슬리피지 미반영**. 현금성 자산 수익률은 장기금리로 근사한 값이라 실제 단기금리와 차이가 있을 수 있다.")
    lines.append("- **배분 규칙은 사전에 고정**했다(결과를 보고 사후에 바꾸지 않음). 다른 임계값·가중치를 쓰면 결과가 달라질 수 있다.")
    lines.append("- 표본은 1993년 이후 미국 시장 한 경로(path)에 대한 결과이며, 다른 시장·기간에 일반화된다고 볼 수 없다.")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
