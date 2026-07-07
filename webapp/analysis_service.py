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
from stockrisk.analysis import llm_classifier
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
_full_cache: list[dict] | None = None
_investors_cache: dict | None = None

FULL_TICKERS_PATH = ROOT / "data" / "tickers_full.json"


def ticker_registry() -> list[dict]:
    """큐레이션 레지스트리 (섹터 정보 포함, 인기 종목 칩에 사용)."""
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = json.loads(TICKERS_PATH.read_text(encoding="utf-8"))["tickers"]
    return _registry_cache


def full_registry() -> list[dict]:
    """전 종목 레지스트리 (scripts/build_ticker_db.py가 거래소 공식 목록에서 생성).

    파일이 없으면(생성 전) 큐레이션 목록만 반환 — 종목을 추정하지 않는다.
    큐레이션 항목의 섹터 정보가 우선한다.
    """
    global _full_cache
    if _full_cache is not None:
        return _full_cache
    curated = {t["ticker"]: t for t in ticker_registry()}
    merged: list[dict] = list(ticker_registry())
    if FULL_TICKERS_PATH.exists():
        try:
            data = json.loads(FULL_TICKERS_PATH.read_text(encoding="utf-8"))
            for market_key, market in (("kr", "KR"), ("us", "US")):
                for row in data.get(market_key, []):
                    if row["ticker"] in curated:
                        continue
                    merged.append({
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "market": market,
                        "sector": "",
                    })
        except Exception:
            pass  # 손상된 파일이면 큐레이션 목록만 사용
    _full_cache = merged
    return _full_cache


def investor_views(tickers: list[str]) -> dict:
    """티커별 유명 투자자 견해 (큐레이션 데이터에 있는 종목만).

    반환: {"disclaimer": str, "by_ticker": {ticker: [entry, ...]}}
    데이터가 없는 종목은 포함되지 않는다 — 추정·생성하지 않는다.
    """
    global _investors_cache
    if _investors_cache is None:
        _investors_cache = json.loads(
            (ROOT / "data" / "investors.json").read_text(encoding="utf-8")
        )
    stocks = _investors_cache.get("stocks", {})
    return {
        "disclaimer": _investors_cache.get("disclaimer", ""),
        "by_ticker": {t: stocks[t] for t in tickers if t in stocks},
    }


def search_registry(query: str) -> list[dict]:
    """전 종목 대상 검색. 정확 티커 > 접두 일치 > 부분 일치 순으로 랭킹,
    시장별 최대 8건씩 반환한다."""
    q = query.strip().lower()
    if not q:
        return []

    def rank(t: dict) -> int:
        tk, nm = t["ticker"].lower(), t["name"].lower()
        if tk == q or nm == q:
            return 0
        if tk.startswith(q) or nm.startswith(q):
            return 1
        if q in tk or q in nm:
            return 2
        return 9

    scored = [(rank(t), t) for t in full_registry()]
    scored = [(r, t) for r, t in scored if r < 9]
    scored.sort(key=lambda x: (x[0], len(x[1]["name"])))
    out, per_market = [], {"KR": 0, "US": 0}
    for _r, t in scored:
        m = t["market"]
        if per_market.get(m, 0) >= 8:
            continue
        per_market[m] = per_market.get(m, 0) + 1
        out.append(t)
        if len(out) >= 16:
            break
    return out


def resolve_stock(query: str) -> dict | None:
    """정확히 일치하는 종목 1건 (전 종목 대상: 티커 우선, 다음 이름)."""
    q = query.strip().lower()
    registry = full_registry()
    for t in registry:
        if t["ticker"].lower() == q:
            return t
    exact_names = [t for t in registry if t["name"].lower() == q]
    if len(exact_names) == 1:
        return exact_names[0]
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
    analyzed_at: str = ""                       # 분석 기준 시각 (UTC ISO)
    latest_news_at: str = ""                    # 수집 뉴스 중 최신 기사 시각
    classifier_name: str = "keyword"            # keyword | gemini


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
    per_query_limit: int = 25,
    fetch_prices: bool = True,
) -> AnalysisResult:
    from datetime import datetime, timezone

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

    # 최신 기사 우선 정렬 (발행 시각 미상은 뒤로) — 주가는 뉴스 직후 급변하므로
    # 리포트 근거·기여 가중 모두 최신 기사가 우선한다
    def _pub_key(n):
        if n.published is None:
            return 0.0
        p = n.published
        return p.timestamp() if p.tzinfo else p.replace(tzinfo=timezone.utc).timestamp()
    news.sort(key=_pub_key, reverse=True)

    # 분류기 선택: GOOGLE_AI_API_KEY 설정 시 Gemini, 아니면 키워드 사전
    if llm_classifier.is_enabled():
        classifier = llm_classifier.GeminiClassifier()
        classifier_name = "gemini"
    else:
        classifier = IssueClassifier()
        classifier_name = "keyword"
    issues = classifier.classify_all(news, portfolio)
    impacts = ImpactAnalyzer().analyze(portfolio, issues)

    # 가격 패널을 먼저 만들고, 실측 20일 수익률을 모멘텀으로 주입한 뒤 추천
    # (가격 데이터가 없으면 momentum=None → 추천에 반영되지 않음)
    prices = _build_price_panels(holdings, fetch_prices)
    for imp in impacts:
        panel = prices.get(imp.holding.ticker)
        if panel and panel.ret_20d is not None:
            imp.momentum = round(panel.ret_20d, 2)

    recommendations = StrategyRecommender(risk_profile=risk_profile).recommend_all(impacts)
    report_md = build_report(portfolio, issues, impacts, recommendations)

    latest = ""
    for n in news:
        if n.published is not None:
            latest = n.published.isoformat()
            break  # 이미 최신순 정렬됨

    return AnalysisResult(
        portfolio=portfolio,
        issues=issues,
        impacts=impacts,
        recommendations=recommendations,
        report_md=report_md,
        news_count=len({n.link or n.title for n in news}),
        offline=offline,
        prices=prices,
        analyzed_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        latest_news_at=latest,
        classifier_name=classifier_name,
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
