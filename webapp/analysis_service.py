"""웹 요청 → 분석 엔진(stockrisk) 연결 서비스 계층.

- 임의 종목 분석: 레지스트리(data/tickers.json)에서 검색하거나,
  사용자가 이름·시장을 직접 입력한 종목도 즉석 Holding으로 분석한다.
- 실시간 뉴스 수집을 먼저 시도하고, 0건이면 샘플 뉴스로 자동 폴백해
  네트워크가 막힌 환경에서도 서비스가 항상 결과를 반환한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stockrisk.analysis.classifier import IssueClassifier
from stockrisk.analysis.impact import ImpactAnalyzer
from stockrisk.models import (
    ClassifiedIssue, Holding, HoldingImpact, Market, Portfolio, Recommendation,
)
from stockrisk.news.collector import NewsCollector, load_news_from_file
from stockrisk.prices import PriceHistory, fetch_history, render_price_svg
from stockrisk.report import build_report
from stockrisk.strategy.recommender import StrategyRecommender

ROOT = Path(__file__).resolve().parent.parent
TICKERS_PATH = ROOT / "data" / "tickers.json"
SAMPLE_NEWS = ROOT / "samples" / "sample_news.json"

_registry_cache: list[dict] | None = None


def ticker_registry() -> list[dict]:
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = json.loads(TICKERS_PATH.read_text(encoding="utf-8"))["tickers"]
    return _registry_cache


def search_registry(query: str) -> list[dict]:
    """이름 또는 티커 부분 일치 검색 (대소문자 무시)."""
    q = query.strip().lower()
    if not q:
        return []
    return [
        t for t in ticker_registry()
        if q in t["ticker"].lower() or q in t["name"].lower()
    ][:10]


def resolve_stock(query: str) -> dict | None:
    """정확히 일치하는 종목 1건을 찾는다 (티커 우선, 다음 이름)."""
    q = query.strip().lower()
    for t in ticker_registry():
        if t["ticker"].lower() == q:
            return t
    for t in ticker_registry():
        if t["name"].lower() == q:
            return t
    matches = search_registry(query)
    return matches[0] if len(matches) == 1 else None


@dataclass
class PricePanel:
    """리포트에 표시할 가격 섹션. history가 실측 데이터일 때만 생성된다."""
    history: PriceHistory
    svg: str
    ret_20d: float | None
    ret_60d: float | None
    volatility: float | None
    max_drawdown: float | None


@dataclass
class AnalysisResult:
    portfolio: Portfolio
    issues: list[ClassifiedIssue]
    impacts: list[HoldingImpact]
    recommendations: dict[str, list[Recommendation]]
    report_md: str
    news_count: int
    offline: bool                               # True면 샘플 뉴스 기반
    prices: dict[str, PricePanel] = None        # ticker → 가격 패널 (실패 시 항목 없음)


def _build_price_panels(holdings: list[Holding], fetch_prices: bool) -> dict[str, PricePanel]:
    """종목별 가격 패널. 조회 실패 종목은 제외 — 가격을 추정하지 않는다."""
    panels: dict[str, PricePanel] = {}
    if not fetch_prices:
        return panels
    for h in holdings:
        hist = fetch_history(h.ticker)
        if hist is None:
            continue
        panels[h.ticker] = PricePanel(
            history=hist,
            svg=render_price_svg(hist),
            ret_20d=hist.return_over(20),
            ret_60d=hist.return_over(60),
            volatility=hist.annualized_volatility,
            max_drawdown=hist.max_drawdown,
        )
    return panels


def run_analysis(
    holdings: list[Holding],
    risk_profile: str = "balanced",
    live_news: bool = True,
    per_query_limit: int = 15,
    fetch_prices: bool = True,
) -> AnalysisResult:
    portfolio = Portfolio(owner="web", holdings=holdings)

    news, offline = [], False
    if live_news:
        try:
            news = NewsCollector(per_query_limit=per_query_limit).collect(portfolio)
        except Exception:
            news = []
    if not news:
        news = load_news_from_file(SAMPLE_NEWS)
        offline = True

    classifier = IssueClassifier()
    issues = classifier.classify_all(news, portfolio)
    impacts = ImpactAnalyzer().analyze(portfolio, issues)
    recommendations = StrategyRecommender(risk_profile=risk_profile).recommend_all(impacts)
    report_md = build_report(portfolio, issues, impacts, recommendations)
    return AnalysisResult(
        portfolio=portfolio,
        issues=issues,
        impacts=impacts,
        recommendations=recommendations,
        report_md=report_md,
        news_count=len({n.link or n.title for n in news}),
        offline=offline,
        prices=_build_price_panels(holdings, fetch_prices),
    )


def holding_from_input(
    query: str,
    market: str | None = None,
    name: str | None = None,
    sector: str = "",
) -> Holding | None:
    """사용자 입력을 Holding으로 변환.

    1) 레지스트리에서 해석 시도
    2) 실패 시 name+market이 주어졌으면 즉석 종목 생성 (어떤 종목이든 분석 가능)
    """
    found = resolve_stock(query)
    if found:
        return Holding(
            ticker=found["ticker"], name=found["name"],
            market=Market(found["market"]), sector=found.get("sector", ""),
        )
    if market in ("KR", "US"):
        display = (name or query).strip()
        if display:
            return Holding(
                ticker=query.strip().upper() or display,
                name=display, market=Market(market), sector=sector,
            )
    return None
