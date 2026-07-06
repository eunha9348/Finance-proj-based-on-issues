"""전략 추천기.

HoldingImpact의 기간별 점수를 매수·매도 행동으로 매핑하고, 종목·섹터·지배
이슈 축에 따라 달라지는 구체적 전술을 생성한다.

- 임계값은 뉴스 기반 점수의 실제 분포에 맞춰 보정: ±0.12 (매수/축소), ±0.35 (적극)
- 전술은 고정 문구가 아니라 (지배 축, 섹터, 시장, 보유단가, 기간)의 함수로 생성
- 헤지 수단은 data/hedges.json의 큐레이션된 실존 상품 목록에서만 인용 (추정 금지)
"""
from __future__ import annotations

import json
from pathlib import Path

from stockrisk.models import (
    Action,
    HoldingImpact,
    Horizon,
    IssueAxis,
    Recommendation,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

THRESHOLDS = [
    (0.35, Action.STRONG_BUY),
    (0.12, Action.BUY),
    (-0.12, Action.HOLD),
    (-0.35, Action.REDUCE),
]

# 투자 성향별 임계값 보정: 보수적일수록 매수는 어렵고 매도는 빨라진다
PROFILE_SHIFTS = {
    "conservative": -0.08,   # 안정형: 점수를 낮춰 판정 (매수 문턱↑, 매도 문턱↓)
    "balanced": 0.0,         # 위험중립형
    "aggressive": +0.08,     # 공격형: 점수를 높여 판정
}


def _score_to_action(score: float, shift: float = 0.0) -> Action:
    effective = score + shift
    for threshold, action in THRESHOLDS:
        if effective >= threshold:
            return action
    return Action.SELL


def _dominant_axes(impact: HoldingImpact, k: int = 3) -> list[tuple[IssueAxis, float]]:
    """영향이 큰 순서로 상위 k개 축 반환 (0점 축 제외)."""
    ranked = sorted(
        ((a, s) for a, s in impact.axis_scores.items() if s != 0.0),
        key=lambda t: abs(t[1]),
        reverse=True,
    )
    return ranked[:k]


class StrategyRecommender:
    def __init__(self, risk_profile: str = "balanced"):
        """risk_profile: conservative(안정형) / balanced(위험중립형) / aggressive(공격형)"""
        self.risk_profile = risk_profile
        self.shift = PROFILE_SHIFTS.get(risk_profile, 0.0)
        hedge_data = json.loads((DATA_DIR / "hedges.json").read_text(encoding="utf-8"))
        self.axis_hedges: dict = hedge_data["axis_hedges"]
        self.sector_hedges: dict = hedge_data["sector_hedges"]

    # ------------------------------------------------------------------
    def recommend(self, impact: HoldingImpact) -> list[Recommendation]:
        recs = []
        for horizon in Horizon:
            score = impact.horizon_scores.get(horizon, 0.0)
            action = _score_to_action(score, self.shift)
            rationale = self._build_rationale(impact, horizon, score, action)
            risk = self._risk_tactics(impact, horizon, score)
            profit = self._profit_tactics(impact, horizon, score)
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

    # ── 근거 서술 ────────────────────────────────────────────────
    @staticmethod
    def _build_rationale(
        impact: HoldingImpact, horizon: Horizon, score: float, action: Action
    ) -> str:
        dom = _dominant_axes(impact, k=2)
        if not dom:
            return "수집된 뉴스에서 이 종목에 유의미한 이슈가 감지되지 않았습니다."
        parts = []
        for axis, s in dom:
            direction = "호재" if s > 0 else "악재"
            parts.append(f"{axis.label_ko} {direction}({s:+.2f})")
        return (
            f"{horizon.label_ko} 종합 점수 {score:+.2f} → {action.label_ko}. "
            f"주요 동인: {', '.join(parts)}."
        )

    # ── 리스크 관리 전술 (악재 국면, 종목별 생성) ─────────────────
    def _risk_tactics(self, impact: HoldingImpact, horizon: Horizon, score: float) -> list[str]:
        if score >= 0:
            return []
        h = impact.holding
        market = h.market.value
        tactics: list[str] = []
        negative_axes = [(a, s) for a, s in _dominant_axes(impact) if s < 0]

        # 1) 구체적 손절/축소 기준 — 보유 단가가 있으면 가격으로 환산
        if horizon == Horizon.SHORT:
            if h.avg_price > 0:
                stop = h.avg_price * 0.92
                tactics.append(
                    f"손절 기준: 평균단가 {h.avg_price:,.0f} 대비 -8%인 "
                    f"{stop:,.0f} 이탈 시 기계적으로 비중 축소 (처분효과 차단)"
                )
            else:
                tactics.append("손절 기준: 진입가 대비 -8% 이탈 시 기계적 비중 축소 기준선 설정")
            tactics.append("분할 매도: 2~3회로 나눠 정리해 단일 시점 판단 오류 위험 분산")
        elif horizon == Horizon.MID:
            tactics.append(
                f"리밸런싱: {h.name} 비중이 포트폴리오 목표치를 넘었는지 점검하고 "
                "초과분만 우선 정리 (전량 매도보다 규칙 기반 축소)"
            )
        else:
            tactics.append(
                "구조 점검: 현재 악재가 일회성 뉴스인지, 매출·이익 추세를 바꾸는 "
                "구조적 변화인지 분기 실적 2회 이상으로 확인 후 장기 보유 여부 재판단"
            )

        # 2) 지배 악재 축별 구체적 헤지 수단 (큐레이션 데이터에서 인용)
        for axis, s in negative_axes[:2]:
            hedge_key = self._axis_hedge_key(axis, s)
            if hedge_key and hedge_key in self.axis_hedges:
                spec = self.axis_hedges[hedge_key]
                names = ", ".join(
                    f"{i['ticker']} ({i['name']})" for i in spec["instruments"].get(market, [])[:2]
                )
                if names:
                    tactics.append(f"{spec['label']}: {names} 등으로 상쇄 포지션 검토 (예시)")

        # 3) 섹터 분산 수단
        if h.sector and h.sector in self.sector_hedges:
            sh = self.sector_hedges[h.sector]
            div = sh["diversify"].get(market, "")
            if div and div != "—":
                tactics.append(f"개별 종목 리스크 분산: {div}로 일부 대체 검토. {sh['note']}")

        # 4) 금리 국면 파생 힌트
        macro = impact.axis_scores.get(IssueAxis.MACRO_FINANCE, 0.0)
        if macro < -0.1 and horizon != Horizon.SHORT:
            key = "macro_finance_rate_hike"
            spec = self.axis_hedges[key]
            names = ", ".join(f"{i['ticker']}" for i in spec["instruments"].get(market, [])[:2])
            if names:
                tactics.append(f"긴축 국면 방어: 현금성 자산은 {names} 등 단기채로 이자 수취 (예시)")
        return tactics

    # ── 수익 극대화 전술 (호재 국면, 종목별 생성) ─────────────────
    def _profit_tactics(self, impact: HoldingImpact, horizon: Horizon, score: float) -> list[str]:
        if score <= 0:
            return []
        h = impact.holding
        market = h.market.value
        tactics: list[str] = []
        positive_axes = [(a, s) for a, s in _dominant_axes(impact) if s > 0]

        if horizon == Horizon.SHORT:
            tactics.append(
                "분할 진입: 호재 확산 초기에는 목표 수량의 1/3씩 나눠 매수해 "
                "뉴스 되돌림(소문에 사서 뉴스에 파는 되돌림) 위험을 낮춤"
            )
            if h.avg_price > 0:
                target = h.avg_price * 1.12
                tactics.append(
                    f"이익 보호: {target:,.0f}(+12%) 도달 시 일부 익절 후 "
                    "나머지는 고점 대비 -5% 트레일링 스탑으로 추세 추종"
                )
        elif horizon == Horizon.MID:
            tactics.append("눌림목 활용: 단기 조정(-5% 내외) 구간을 분할 매수 기회로 활용")
        else:
            tactics.append("장기 적립: 월 단위 분할 매수로 시점 위험을 분산하고 배당은 재투자")

        # 지배 호재 축별 수혜 포지션
        for axis, s in positive_axes[:2]:
            if axis == IssueAxis.MACRO_FINANCE:
                spec = self.axis_hedges["macro_finance_rate_cut"]
                names = ", ".join(
                    f"{i['ticker']} ({i['name']})" for i in spec["instruments"].get(market, [])[:2]
                )
                if names:
                    tactics.append(f"{spec['label']}: {names} 등으로 수혜 확장 검토 (예시)")
            elif axis == IssueAxis.COMPANY and h.sector and h.sector in self.sector_hedges:
                div = self.sector_hedges[h.sector]["diversify"].get(market, "")
                if div and div != "—":
                    tactics.append(
                        f"동일 테마 확장: 개별 호재가 섹터 전반 추세라면 {div}로 "
                        "폭넓게 노출을 가져가는 것도 대안"
                    )
        return tactics

    # ------------------------------------------------------------------
    @staticmethod
    def _axis_hedge_key(axis: IssueAxis, score: float) -> str | None:
        if axis == IssueAxis.WAR_GLOBAL:
            return "war_global"
        if axis == IssueAxis.SENTIMENT:
            return "sentiment"
        if axis == IssueAxis.GEOPOLITICS:
            return "geopolitics"
        if axis == IssueAxis.MACRO_FINANCE:
            return "macro_finance_rate_hike" if score < 0 else "macro_finance_rate_cut"
        return None  # COMPANY 악재는 섹터 분산으로 대응 (별도 처리)
