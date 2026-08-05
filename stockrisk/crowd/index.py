"""군중심리지수(Crowd Pulse Index) 산출.

월가 기관용 지표(공매도 잔고, 옵션 풋/콜비 등)는 무료로 구할 수 없어 배제하고,
'가격이 흘러온 자취' 자체에서 대중 행동을 근사하는 4개 하위 지표를 각각
과거 대비 백분위(0~100)로 환산한 뒤 평균한다. CNN Fear & Greed Index와 같은
철학(추세·변동성·안전자산 선호를 종합)을 표준 라이브러리만으로 재구성한 것이다.

하위 지표:
  1. 모멘텀   — 최근 3개월 수익률 (추세 추종 심리)
  2. 이격도   — 10개월 이동평균 대비 현재가 괴리율 (과열/침체)
  3. 변동성   — VIX 월평균의 반전 백분위 (낮을수록 탐욕)
  4. 밸류에이션 — CAPE(PE10)의 백분위 (역사적 고평가일수록 탐욕)

모든 백분위는 시점 t까지의 데이터만 사용해 계산한다(미래 데이터 참조 없음).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from stockrisk.crowd.data import MonthlyRecord

WINDOW = 120       # 백분위 계산에 쓰는 롤링 윈도우(개월). 최근 10년
MIN_HISTORY = 36   # 지수 산출을 시작하기 전 최소 준비 기간(개월)

BAND_LABELS_KO = {
    "extreme_fear": "극단적 공포",
    "fear": "공포",
    "neutral": "중립",
    "greed": "탐욕",
    "extreme_greed": "극단적 탐욕",
}


def band_of(score: float) -> str:
    if score < 25:
        return "extreme_fear"
    if score < 45:
        return "fear"
    if score < 55:
        return "neutral"
    if score < 75:
        return "greed"
    return "extreme_greed"


@dataclass
class CrowdIndexPoint:
    month: str
    score: float
    band: str
    components: dict[str, float | None] = field(default_factory=dict)

    @property
    def band_label_ko(self) -> str:
        return BAND_LABELS_KO[self.band]


def _percentile_rank(value: float, window: list[float]) -> float:
    """window 내 value의 백분위(0~100). 동률은 0.5로 나눠 세어(중앙순위) 상수 구간에서
    50이 되도록 한다. window가 비면 중립값 50."""
    if not window:
        return 50.0
    less = sum(1 for w in window if w < value)
    equal = sum(1 for w in window if w == value)
    return 100.0 * (less + 0.5 * equal) / len(window)


def _raw_series(records: list[MonthlyRecord]) -> dict[str, list[float | None]]:
    n = len(records)
    momentum: list[float | None] = [None] * n
    trend: list[float | None] = [None] * n
    vix: list[float | None] = [None] * n
    cape: list[float | None] = [None] * n

    for i, rec in enumerate(records):
        vix[i] = rec.vix_avg
        cape[i] = rec.cape
        if i >= 3:
            base = records[i - 3].sp500
            if base > 0:
                momentum[i] = (rec.sp500 / base - 1.0) * 100
        if i >= 9:
            ma10 = sum(r.sp500 for r in records[i - 9 : i + 1]) / 10
            if ma10 > 0:
                trend[i] = (rec.sp500 / ma10 - 1.0) * 100

    return {"momentum": momentum, "trend": trend, "vix": vix, "cape": cape}


def compute_crowd_index(
    records: list[MonthlyRecord],
    window: int = WINDOW,
    min_history: int = MIN_HISTORY,
) -> list[CrowdIndexPoint]:
    """월별 레코드로부터 군중심리지수 시계열을 계산한다.

    각 시점 t의 하위 지표는 [max(0, t-window+1), t] 구간(과거~현재, 미래 제외)
    내 결측 제외 값들을 모집단으로 한 백분위다. 하위 지표 중 그 시점에 값이
    없으면(예: 초기 CAPE 결측) 나머지 지표만으로 평균한다.
    """
    series = _raw_series(records)
    points: list[CrowdIndexPoint] = []

    for i, rec in enumerate(records):
        if i < min_history:
            continue
        lo = max(0, i - window + 1)

        components: dict[str, float | None] = {}
        for name, invert in (("momentum", False), ("trend", False), ("vix", True), ("cape", False)):
            raw = series[name][i]
            if raw is None:
                components[name] = None
                continue
            hist = [v for v in series[name][lo : i + 1] if v is not None]
            pct = _percentile_rank(raw, hist)
            components[name] = (100.0 - pct) if invert else pct

        available = [v for v in components.values() if v is not None]
        score = sum(available) / len(available) if available else 50.0
        points.append(CrowdIndexPoint(month=rec.month, score=score, band=band_of(score), components=components))

    return points
