"""전략 추천기 v3 — 수익 극대화·헤지 능력 극대화 지향.

설계 원칙 (모두 결정론적 규칙, 생성·추정 없음):

1. **비대칭 임계값** — 뉴스 코퍼스는 구조적으로 악재(전쟁·관세·소송) 기사가
   많아 대칭 임계값에서는 매수 신호가 과소 생산된다. 매수 문턱(+0.08)을
   축소 문턱(-0.12)보다 낮게 잡아 편향을 보정한다.
2. **실측 모멘텀 반영** — 가격 데이터가 실제로 수집된 경우에만 20일 수익률을
   기간별 계수(단기 0.5 / 중기 0.25 / 장기 0.1)로 점수에 가산한다.
   모멘텀은 실증적으로 검증된 수익 팩터이며, 데이터가 없으면 반영하지 않는다.
3. **전술 다변화** — (지배 축, 방향, 기간, 점수 강도, 종목)의 함수로 전술을
   구성하고, 동급 전술 풀에서는 티커 해시로 결정론적으로 변형을 선택해
   종목마다 다른 각도의 대응이 제시되게 한다.
4. **헤지 구체화** — data/hedges.json의 큐레이션된 실존 상품만 인용한다.
"""
from __future__ import annotations

import hashlib
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

# 비대칭 임계값: 매수 신호 생산을 늘리고, 명확한 악재에만 축소/매도
THRESHOLDS = [
    (0.30, Action.STRONG_BUY),
    (0.08, Action.BUY),
    (-0.12, Action.HOLD),
    (-0.32, Action.REDUCE),
]

PROFILE_SHIFTS = {
    "conservative": -0.08,
    "balanced": 0.0,
    "aggressive": +0.08,
}

# 기간별 모멘텀 반영 계수 (실측 20일 수익률 % → 점수 가산)
MOMENTUM_FACTOR = {Horizon.SHORT: 0.5, Horizon.MID: 0.25, Horizon.LONG: 0.1}
MOMENTUM_CAP = 0.15  # 모멘텀 가산 상한 (점수 단위)


def _score_to_action(score: float, shift: float = 0.0) -> Action:
    effective = score + shift
    for threshold, action in THRESHOLDS:
        if effective >= threshold:
            return action
    return Action.SELL


def _momentum_tilt(momentum: float | None, horizon: Horizon) -> float:
    """실측 20일 수익률(%)의 기간별 점수 가산. 데이터 없으면 0."""
    if momentum is None:
        return 0.0
    tilt = (momentum / 100.0) * MOMENTUM_FACTOR[horizon]
    return max(-MOMENTUM_CAP, min(MOMENTUM_CAP, tilt))


def _dominant_axes(impact: HoldingImpact, k: int = 3) -> list[tuple[IssueAxis, float]]:
    ranked = sorted(
        ((a, s) for a, s in impact.axis_scores.items() if s != 0.0),
        key=lambda t: abs(t[1]),
        reverse=True,
    )
    return ranked[:k]


def _pick(pool: list[str], ticker: str, horizon: Horizon, salt: str = "") -> str:
    """동급 전술 풀에서 결정론적으로 1개 선택 (종목·기간마다 다른 변형)."""
    key = f"{ticker}:{horizon.value}:{salt}".encode()
    idx = int(hashlib.sha256(key).hexdigest(), 16) % len(pool)
    return pool[idx]


class StrategyRecommender:
    def __init__(self, risk_profile: str = "balanced"):
        self.risk_profile = risk_profile
        self.shift = PROFILE_SHIFTS.get(risk_profile, 0.0)
        hedge_data = json.loads((DATA_DIR / "hedges.json").read_text(encoding="utf-8"))
        self.axis_hedges: dict = hedge_data["axis_hedges"]
        self.sector_hedges: dict = hedge_data["sector_hedges"]

    # ------------------------------------------------------------------
    def recommend(self, impact: HoldingImpact) -> list[Recommendation]:
        recs = []
        for horizon in Horizon:
            base = impact.horizon_scores.get(horizon, 0.0)
            tilt = _momentum_tilt(impact.momentum, horizon)
            score = round(max(-1.0, min(1.0, base + tilt)), 3)
            action = _score_to_action(score, self.shift)
            rationale = self._build_rationale(impact, horizon, base, tilt, score, action)
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

    # ── 판단 근거 서술 ───────────────────────────────────────────
    @staticmethod
    def _build_rationale(
        impact: HoldingImpact,
        horizon: Horizon,
        base: float,
        tilt: float,
        score: float,
        action: Action,
    ) -> str:
        dom = _dominant_axes(impact, k=2)
        if not dom and tilt == 0.0:
            return "수집된 뉴스에서 이 종목에 유의미한 이슈가 감지되지 않았습니다."
        parts = [
            f"{axis.label_ko} {'호재' if s > 0 else '악재'}({s:+.2f})" for axis, s in dom
        ]
        text = f"{horizon.label_ko} 뉴스 점수 {base:+.2f}"
        if tilt != 0.0:
            text += f" + 실측 20일 모멘텀 반영 {tilt:+.2f}"
        text += f" = {score:+.2f} → {action.label_ko}."
        if parts:
            text += f" 주요 동인: {', '.join(parts)}."
        if impact.momentum is not None:
            text += f" (최근 20거래일 수익률 {impact.momentum:+.1f}%)"
        return text

    # ── 리스크 관리 전술 ─────────────────────────────────────────
    def _risk_tactics(self, impact: HoldingImpact, horizon: Horizon, score: float) -> list[str]:
        if score >= 0:
            return []
        h = impact.holding
        t = h.ticker
        market = h.market.value
        severe = score <= -0.25          # 강한 악재와 약한 악재는 다른 대응
        tactics: list[str] = []
        negative_axes = [(a, s) for a, s in _dominant_axes(impact) if s < 0]

        if horizon == Horizon.SHORT:
            if h.avg_price > 0:
                stop = h.avg_price * (0.90 if severe else 0.93)
                pct = "-10%" if severe else "-7%"
                tactics.append(
                    f"손절 규율: 평균단가 {h.avg_price:,.0f} 기준 {pct}인 {stop:,.0f} "
                    f"이탈 시 기계적 축소 — 악재 강도({score:+.2f})에 맞춘 기준선"
                )
            else:
                tactics.append(
                    f"손절 규율: 진입가 대비 {'-10%' if severe else '-7%'} 기준선을 "
                    "미리 정해 감정 개입 차단"
                )
            tactics.append(_pick([
                "시간 분산 매도: 당일 전량 정리 대신 2~3거래일에 걸쳐 나눠 정리해 체결 충격 완화",
                "반등 매도: 낙폭 과대 구간에서는 기술적 반등 시 분할 정리로 평균 매도가 개선",
                "부분 청산 후 관찰: 절반만 정리하고 나머지는 후속 뉴스 확인 후 결정하는 2단계 대응",
            ], t, horizon, "sell"))
        elif horizon == Horizon.MID:
            tactics.append(_pick([
                f"목표 비중 회귀: {h.name} 비중이 계획을 초과했다면 초과분만 기계적으로 정리 (리밸런싱)",
                f"상대강도 점검: {h.name}이 같은 섹터 대비 계속 약하면 섹터 내 강한 종목으로 교체 검토",
                "이벤트 전 축소: 실적 발표·금리 결정 등 예정 이벤트 직전에는 포지션을 줄이고 결과 확인 후 재진입",
            ], t, horizon, "mid"))
            if severe:
                tactics.append(
                    "현금 완충: 추가 하락에 대비해 포트폴리오 현금 비중 10~20% 확보를 우선"
                )
        else:
            tactics.append(_pick([
                "구조 검증: 이 악재가 분기 실적 2회 이상에서 매출·이익 추세를 실제로 꺾는지 확인 후 장기 보유 여부 재판단",
                "분할 손절 상한: 장기 관점에서도 최대 손실 한도(-20% 등)를 정해 두고 이탈 시 예외 없이 축소",
                "대체 후보 비교: 같은 투자 논리를 더 싸게 살 수 있는 동종 종목이 있는지 정기 비교",
            ], t, horizon, "long"))

        # 지배 악재 축별 구체적 헤지 (상위 2개 축)
        for axis, s in negative_axes[:2]:
            key = self._axis_hedge_key(axis, s)
            if key and key in self.axis_hedges:
                spec = self.axis_hedges[key]
                inst = spec["instruments"].get(market, [])
                if inst:
                    names = ", ".join(f"{i['ticker']} ({i['name']})" for i in inst[:2])
                    why = inst[0]["why"]
                    tactics.append(f"{spec['label']}: {names} — {why} (예시)")

        # 섹터 분산
        if h.sector and h.sector in self.sector_hedges:
            sh = self.sector_hedges[h.sector]
            div = sh["diversify"].get(market, "")
            if div and div != "—":
                tactics.append(f"종목→섹터 전환: {div}로 일부 대체해 개별 리스크 축소. {sh['note']}")

        # 변동성이 실측된 경우: 변동성 기반 포지션 조절
        if impact.momentum is not None and impact.momentum < -8:
            tactics.append(
                f"추세 확인: 최근 20거래일 실측 수익률 {impact.momentum:+.1f}%로 "
                "가격도 뉴스와 같은 방향 — 물타기보다 규칙 기반 축소가 우선"
            )
        return tactics

    # ── 수익 극대화 전술 ─────────────────────────────────────────
    def _profit_tactics(self, impact: HoldingImpact, horizon: Horizon, score: float) -> list[str]:
        if score <= 0:
            return []
        h = impact.holding
        t = h.ticker
        market = h.market.value
        strong = score >= 0.25
        tactics: list[str] = []
        positive_axes = [(a, s) for a, s in _dominant_axes(impact) if s > 0]

        if horizon == Horizon.SHORT:
            tactics.append(_pick([
                "3분할 진입: 목표 수량을 1/3씩 나눠 매수 — 첫 진입 후 되돌림(-3%)과 돌파 확인 시 추가",
                "돌파 추종: 호재 뉴스 이후 직전 고점 돌파를 확인하고 진입해 가짜 반등을 걸러냄",
                "갭 주의 진입: 급등 출발일은 피하고 첫 눌림 구간에서 진입해 평균 단가 관리",
            ], t, horizon, "entry"))
            if h.avg_price > 0:
                target = h.avg_price * (1.15 if strong else 1.10)
                tactics.append(
                    f"이익 보호: {target:,.0f}({'+15%' if strong else '+10%'}) 도달 시 "
                    "일부 익절, 잔여분은 고점 대비 -5% 트레일링 스탑"
                )
        elif horizon == Horizon.MID:
            tactics.append(_pick([
                "눌림목 적립: 조정 -5% 구간마다 예정 수량을 나눠 매수해 평균 단가 개선",
                "피라미딩: 추세가 유지될 때만 이익 위에 추가 매수 — 손실 포지션에는 추가하지 않음",
                "손익비 규칙: 목표 수익(+20%)과 허용 손실(-8%)의 2.5:1 손익비를 유지하는 규모로만 확대",
            ], t, horizon, "scale"))
        else:
            tactics.append(_pick([
                "정액 적립: 월 단위 일정 금액 매수로 시점 위험을 분산하고 배당·분배금은 재투자",
                "코어-새틀라이트: 이 종목을 장기 코어로 두고 단기 아이디어는 별도 소액으로 분리 운용",
                "리밸런싱 상한: 상승으로 비중이 목표+5%p를 넘으면 초과분만 익절해 수익을 확정하며 유지",
            ], t, horizon, "core"))

        # 지배 호재 축별 수혜 확장
        for axis, s in positive_axes[:2]:
            if axis == IssueAxis.MACRO_FINANCE:
                spec = self.axis_hedges["macro_finance_rate_cut"]
                inst = spec["instruments"].get(market, [])
                if inst:
                    names = ", ".join(f"{i['ticker']} ({i['name']})" for i in inst[:2])
                    tactics.append(f"{spec['label']}: {names} — 같은 금리 사이클 수혜를 채권·지수로 확장 (예시)")
            elif axis == IssueAxis.COMPANY and h.sector and h.sector in self.sector_hedges:
                div = self.sector_hedges[h.sector]["diversify"].get(market, "")
                if div and div != "—":
                    tactics.append(
                        f"테마 확장: 이 호재가 섹터 공통 추세라면 {div}로 수혜 폭을 넓히는 선택지 (예시)"
                    )
            elif axis == IssueAxis.WAR_GLOBAL and s > 0:
                tactics.append("긴장 완화 국면: 낙폭이 컸던 경기민감·소비 섹터의 회복 탄력이 큰 경향 — 리오프닝형 종목 점검")

        if impact.momentum is not None and impact.momentum > 8:
            tactics.append(
                f"추세 순풍: 최근 20거래일 실측 수익률 {impact.momentum:+.1f}%로 "
                "가격이 뉴스와 같은 방향 — 추세 추종 전략의 성공 확률이 높은 구간"
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
        return None
