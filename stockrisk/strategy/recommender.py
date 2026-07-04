"""전략 추천기.

HoldingImpact의 기간별 점수를 바탕으로 단기/중기/장기 각각에 대해
매수·매도·보유 추천과 리스크 관리·수익 극대화 전술을 생성한다.

점수 → 행동 매핑 (행동경제학적 편향 완화를 위해 기계적 기준 적용):
  +0.45 이상  적극 매수 | +0.15 이상 매수 | -0.15 초과 보유
  -0.45 초과  비중 축소 | 그 이하   매도
"""
from __future__ import annotations

from stockrisk.models import (
    Action,
    HoldingImpact,
    Horizon,
    IssueAxis,
    Recommendation,
)

THRESHOLDS = [
    (0.45, Action.STRONG_BUY),
    (0.15, Action.BUY),
    (-0.15, Action.HOLD),
    (-0.45, Action.REDUCE),
]

# 기간별 리스크 관리 전술 (악재 국면)
RISK_TACTICS = {
    Horizon.SHORT: [
        "손절 기준선 설정: 평균 매수가 대비 -7~-10% 이탈 시 기계적 손절",
        "분할 매도: 한 번에 정리하지 말고 2~3회로 나누어 비중 축소",
        "변동성 확대 구간에서는 신규 진입 보류, 현금 비중 확보",
    ],
    Horizon.MID: [
        "포트폴리오 리밸런싱: 악재 축 노출이 큰 종목 비중을 줄이고 방어주/현금 확대",
        "헤지 수단 검토: 인버스 ETF, 달러 자산 등으로 하방 위험 완충",
        "실적 발표·금리 결정 등 이벤트 일정 전후로 포지션 축소",
    ],
    Horizon.LONG: [
        "펀더멘털 점검: 이슈가 일시적 노이즈인지 구조적 악화인지 구분",
        "섹터 분산: 단일 섹터 집중도를 낮춰 특정 이슈 축 노출 축소",
        "달러·원화 등 통화 분산으로 환율 리스크 관리",
    ],
}

# 기간별 수익 극대화 전술 (호재 국면)
PROFIT_TACTICS = {
    Horizon.SHORT: [
        "모멘텀 추종: 호재 뉴스 확산 초기 구간에서 분할 매수로 진입",
        "목표가 도달 시 일부 익절로 수익 확정 (트레일링 스탑 활용)",
    ],
    Horizon.MID: [
        "눌림목 분할 매수: 단기 조정 시 저가 매수로 평균 단가 개선",
        "호재 축(예: 금리인하 수혜)에 정렬된 연관 종목으로 비중 확대",
    ],
    Horizon.LONG: [
        "적립식 분할 매수로 시점 분산 (분할 매수, cost averaging)",
        "구조적 성장 축(AI·금리 사이클 등)에 맞춘 장기 보유 및 배당 재투자",
    ],
}


def _score_to_action(score: float) -> Action:
    for threshold, action in THRESHOLDS:
        if score >= threshold:
            return action
    return Action.SELL


def _dominant_axes(impact: HoldingImpact, k: int = 2) -> list[tuple[IssueAxis, float]]:
    """영향이 큰 순서로 상위 k개 축 반환 (0점 축 제외)."""
    ranked = sorted(
        ((a, s) for a, s in impact.axis_scores.items() if s != 0.0),
        key=lambda t: abs(t[1]),
        reverse=True,
    )
    return ranked[:k]


class StrategyRecommender:
    def recommend(self, impact: HoldingImpact) -> list[Recommendation]:
        recs = []
        for horizon in Horizon:
            score = impact.horizon_scores.get(horizon, 0.0)
            action = _score_to_action(score)
            rationale = self._build_rationale(impact, horizon, score, action)

            risk = list(RISK_TACTICS[horizon]) if score < 0 else []
            profit = list(PROFIT_TACTICS[horizon]) if score > 0 else []
            if not risk and not profit:
                risk = ["뚜렷한 이슈 신호 없음: 기존 포지션 유지, 이벤트 일정만 모니터링"]

            recs.append(
                Recommendation(
                    holding=impact.holding,
                    horizon=horizon,
                    action=action,
                    score=score,
                    rationale=rationale,
                    risk_management=risk,
                    profit_strategy=profit,
                )
            )
        return recs

    def recommend_all(self, impacts: list[HoldingImpact]) -> dict[str, list[Recommendation]]:
        return {imp.holding.ticker: self.recommend(imp) for imp in impacts}

    @staticmethod
    def _build_rationale(
        impact: HoldingImpact, horizon: Horizon, score: float, action: Action
    ) -> str:
        dom = _dominant_axes(impact)
        if not dom:
            return "수집된 뉴스에서 이 종목에 유의미한 이슈가 감지되지 않았습니다."
        axis_desc = ", ".join(
            f"{a.label_ko} {'호재' if s > 0 else '악재'}({s:+.2f})" for a, s in dom
        )
        return (
            f"{horizon.label_ko} 종합 점수 {score:+.2f} → {action.label_ko}. "
            f"주요 동인: {axis_desc}."
        )
