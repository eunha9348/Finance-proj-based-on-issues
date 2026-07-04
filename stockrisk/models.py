"""핵심 데이터 모델 정의.

포트폴리오, 보유 종목, 뉴스, 이슈 분류, 영향 분석, 추천 결과를 표현하는
데이터클래스들을 모아둔 모듈.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Market(str, Enum):
    """대상 시장. 현재 미국(US)과 한국(KR)을 지원한다."""

    US = "US"
    KR = "KR"


class IssueAxis(str, Enum):
    """리스크 분석의 5대 이슈 축."""

    GEOPOLITICS = "geopolitics"        # 국가별 정치 이슈
    WAR_GLOBAL = "war_global"          # 전쟁 등 세계 이슈
    COMPANY = "company"                # 오너리스크·매출하락·공매도 등 기업 자체 이슈
    SENTIMENT = "sentiment"            # 모멘텀에 따른 시장 전체 투자심리
    MACRO_FINANCE = "macro_finance"    # 금리인하 등 전세계 금융 이슈

    @property
    def label_ko(self) -> str:
        return {
            IssueAxis.GEOPOLITICS: "국가별 정치 이슈",
            IssueAxis.WAR_GLOBAL: "전쟁·세계 이슈",
            IssueAxis.COMPANY: "기업 자체 이슈",
            IssueAxis.SENTIMENT: "시장 모멘텀·투자심리",
            IssueAxis.MACRO_FINANCE: "거시 금융 이슈",
        }[self]


class Horizon(str, Enum):
    """투자 전략 기간 구분."""

    SHORT = "short"    # 단기: ~1개월
    MID = "mid"        # 중기: 1~6개월
    LONG = "long"      # 장기: 6개월 이상

    @property
    def label_ko(self) -> str:
        return {
            Horizon.SHORT: "단기 (~1개월)",
            Horizon.MID: "중기 (1~6개월)",
            Horizon.LONG: "장기 (6개월+)",
        }[self]


class Action(str, Enum):
    """추천 행동."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"

    @property
    def label_ko(self) -> str:
        return {
            Action.STRONG_BUY: "적극 매수",
            Action.BUY: "매수",
            Action.HOLD: "보유",
            Action.REDUCE: "비중 축소",
            Action.SELL: "매도",
        }[self]


@dataclass
class Holding:
    """보유 종목 1건."""

    ticker: str                # 예: "AAPL", "005930.KS"
    name: str                  # 예: "애플", "삼성전자"
    market: Market
    quantity: float = 0.0
    avg_price: float = 0.0     # 평균 매수 단가 (시장 통화 기준)
    sector: str = ""           # 예: "semiconductor", "ev"

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_price


@dataclass
class Portfolio:
    """사용자 포트폴리오."""

    owner: str
    holdings: list[Holding] = field(default_factory=list)

    def by_market(self, market: Market) -> list[Holding]:
        return [h for h in self.holdings if h.market == market]


@dataclass
class NewsItem:
    """수집한 뉴스 기사 1건."""

    title: str
    link: str
    source: str = ""
    summary: str = ""
    published: Optional[datetime] = None
    query: str = ""            # 이 기사를 가져온 검색 질의
    market: Optional[Market] = None

    @property
    def text(self) -> str:
        """분류에 사용하는 전체 텍스트."""
        return f"{self.title} {self.summary}"


@dataclass
class ClassifiedIssue:
    """뉴스 1건을 5대 축으로 분류한 결과."""

    news: NewsItem
    axis: IssueAxis
    severity: float            # 0.0 ~ 1.0 (사안의 심각도/중요도)
    sentiment: float           # -1.0(악재) ~ +1.0(호재)
    matched_keywords: list[str] = field(default_factory=list)
    tickers_mentioned: list[str] = field(default_factory=list)  # 직접 언급된 보유 종목 티커


@dataclass
class HoldingImpact:
    """특정 보유 종목에 대한 이슈들의 종합 영향 평가."""

    holding: Holding
    # 축별 영향 점수: -1.0(강한 악재) ~ +1.0(강한 호재)
    axis_scores: dict[IssueAxis, float] = field(default_factory=dict)
    # 기간별 종합 점수
    horizon_scores: dict[Horizon, float] = field(default_factory=dict)
    # 이 종목에 영향을 준 주요 이슈 (근거 제시용)
    top_issues: list[ClassifiedIssue] = field(default_factory=list)
    # 연관 종목 경로로 전이된 영향 설명
    related_notes: list[str] = field(default_factory=list)
    momentum: Optional[float] = None   # 최근 가격 모멘텀 (예: 20일 수익률)

    @property
    def overall_score(self) -> float:
        if not self.horizon_scores:
            return 0.0
        return sum(self.horizon_scores.values()) / len(self.horizon_scores)


@dataclass
class Recommendation:
    """종목별 기간별 추천."""

    holding: Holding
    horizon: Horizon
    action: Action
    score: float               # 판단 근거가 된 점수
    rationale: str             # 추천 사유 (한국어 설명)
    risk_management: list[str] = field(default_factory=list)   # 리스크 관리 전술
    profit_strategy: list[str] = field(default_factory=list)   # 수익 극대화 전술
