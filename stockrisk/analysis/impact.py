"""영향 분석기.

분류된 이슈(ClassifiedIssue)들이 보유 종목과 연관 종목에 미치는 영향을
점수화한다.

전이 경로 3단계:
  1. 직접 언급  — 뉴스에 종목명/티커가 등장하면 영향 100% 반영
  2. 섹터 전이  — 같은 섹터 키워드/연관 종목이 등장하면 correlation 비율 반영
  3. 시장 전이  — 시장 전반 이슈는 axis_market_beta 비율만큼 반영

축별 점수를 기간(단기/중기/장기) 가중치로 합성해 horizon_scores를 만든다.
"""
from __future__ import annotations

import json
from pathlib import Path

from stockrisk.models import (
    ClassifiedIssue,
    Holding,
    HoldingImpact,
    Horizon,
    IssueAxis,
    Portfolio,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class ImpactAnalyzer:
    def __init__(
        self,
        related_path: str | Path | None = None,
        keywords_path: str | Path | None = None,
    ):
        rpath = Path(related_path) if related_path else DATA_DIR / "related_stocks.json"
        related = json.loads(rpath.read_text(encoding="utf-8"))
        self.sectors: dict = related["sectors"]
        self.axis_market_beta: dict = related["axis_market_beta"]

        kpath = Path(keywords_path) if keywords_path else DATA_DIR / "keywords.json"
        self.horizon_weights: dict = json.loads(kpath.read_text(encoding="utf-8"))[
            "horizon_weights"
        ]

    # ------------------------------------------------------------------
    def analyze(self, portfolio: Portfolio, issues: list[ClassifiedIssue]) -> list[HoldingImpact]:
        return [self._analyze_holding(h, issues) for h in portfolio.holdings]

    # ------------------------------------------------------------------
    def _sector_of(self, holding: Holding) -> str | None:
        if holding.sector and holding.sector in self.sectors:
            return holding.sector
        for name, spec in self.sectors.items():
            if holding.ticker in spec["tickers"]:
                return name
        return None

    def _relevance(self, holding: Holding, issue: ClassifiedIssue) -> tuple[float, str]:
        """이슈가 이 종목에 얼마나 관련 있는지(0~1)와 전이 경로 설명을 반환."""
        # 1) 직접 언급
        if holding.ticker in issue.tickers_mentioned:
            return 1.0, "직접 언급"

        text = issue.news.text.lower()
        sector = self._sector_of(holding)

        # 2) 섹터 전이: 섹터 키워드 또는 같은 섹터의 다른 종목명이 등장
        if sector:
            spec = self.sectors[sector]
            for kw in spec["keywords"]:
                if kw.lower() in text:
                    return spec["correlation"], f"섹터({spec['label_ko']}) 키워드 '{kw}'"
            for other in issue.tickers_mentioned:
                if other != holding.ticker and other in spec["tickers"]:
                    return spec["correlation"], f"연관 종목({other}) 경유 전이"

        # 3) 시장 전이: 같은 시장의 시장 전반 이슈
        if issue.news.market is None or issue.news.market == holding.market:
            beta = self.axis_market_beta.get(issue.axis.value, 0.3)
            # 다른 종목 개별 이슈(company)인데 이 종목과 무관하면 전이 거의 없음
            if issue.axis == IssueAxis.COMPANY and issue.tickers_mentioned:
                return 0.0, ""
            return beta, "시장 전반 이슈"

        return 0.0, ""

    def _analyze_holding(self, holding: Holding, issues: list[ClassifiedIssue]) -> HoldingImpact:
        axis_acc: dict[IssueAxis, list[float]] = {a: [] for a in IssueAxis}
        scored: list[tuple[float, ClassifiedIssue, str]] = []

        for issue in issues:
            relevance, path = self._relevance(holding, issue)
            if relevance <= 0.0:
                continue
            # 이슈 1건의 기여 = 방향성 × 심각도 × 관련도
            contribution = issue.sentiment * issue.severity * relevance
            axis_acc[issue.axis].append(contribution)
            scored.append((abs(contribution), issue, path))

        # 축별 점수: 기여 평균에 이슈 수 보정(같은 방향 뉴스가 많을수록 신뢰도↑)
        axis_scores: dict[IssueAxis, float] = {}
        for axis, vals in axis_acc.items():
            if not vals:
                axis_scores[axis] = 0.0
                continue
            mean = sum(vals) / len(vals)
            volume_boost = min(1.0, 0.6 + 0.1 * len(vals))  # 1건 0.7배 ~ 4건 이상 1.0배
            axis_scores[axis] = round(max(-1.0, min(1.0, mean * volume_boost)), 3)

        # 기간별 합성 점수
        horizon_scores: dict[Horizon, float] = {}
        for horizon in Horizon:
            num, den = 0.0, 0.0
            for axis in IssueAxis:
                w = self.horizon_weights[axis.value][horizon.value]
                num += axis_scores[axis] * w
                den += w if axis_scores[axis] != 0.0 else 0.0
            horizon_scores[horizon] = round(num / den, 3) if den > 0 else 0.0

        # 근거 이슈 상위 5건
        scored.sort(key=lambda t: t[0], reverse=True)
        top_issues = [iss for _, iss, _ in scored[:5]]
        related_notes = [
            f"[{iss.axis.label_ko}] {iss.news.title} ({path}, 기여 {'+' if iss.sentiment >= 0 else ''}{iss.sentiment * iss.severity:.2f})"
            for _, iss, path in scored[:5]
        ]

        return HoldingImpact(
            holding=holding,
            axis_scores=axis_scores,
            horizon_scores=horizon_scores,
            top_issues=top_issues,
            related_notes=related_notes,
        )
