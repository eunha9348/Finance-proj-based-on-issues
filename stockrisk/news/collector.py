"""뉴스 수집기.

Google News RSS를 이용해 (1) 보유 종목별 뉴스, (2) 5대 이슈 축별 시장 뉴스를
한국(ko-KR)과 미국(en-US) 양쪽에서 수집한다. 외부 의존성 없이 표준 라이브러리
(urllib + xml.etree)만 사용하며, 네트워크가 막힌 환경을 위해 JSON 파일에서
뉴스를 읽어오는 오프라인 모드도 지원한다.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable

from stockrisk.models import Market, NewsItem, Portfolio

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

# 시장별 언어/지역 설정
LOCALE = {
    Market.KR: {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    Market.US: {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}

# 이슈 축별 시장 전반 뉴스 검색 질의 (시장별).
# 악재 편향을 막기 위해 긍정·부정 방향 질의를 축마다 균형 있게 포함한다.
AXIS_QUERIES = {
    Market.KR: [
        "증시 정치 규제 관세",
        "증시 정책 지원 보조금 호재",
        "전쟁 지정학 리스크 증시",
        "휴전 종전 협상 증시",
        "코스피 급락 투매 투자심리",
        "코스피 반등 랠리 외국인 순매수",
        "한국은행 기준금리 인하",
        "금리 인상 긴축 물가",
        "공매도 증시",
        "실적 호조 어닝 서프라이즈 코스피",
    ],
    Market.US: [
        "stock market tariff regulation",
        "stock market subsidy policy boost",
        "war geopolitical risk stocks",
        "ceasefire peace talks markets",
        "stock market selloff panic",
        "stock market rally record high",
        "Fed rate cut FOMC",
        "Fed rate hike inflation tightening",
        "short selling squeeze stocks",
        "earnings beat guidance raised stocks",
    ],
}

USER_AGENT = "Mozilla/5.0 (compatible; StockRiskBot/0.1)"


def _fetch_rss(url: str, timeout: int = 15) -> list[NewsItem]:
    """RSS URL 1건을 받아 NewsItem 리스트로 파싱한다. 실패 시 빈 리스트."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
    except Exception:
        return []
    return _parse_rss_bytes(raw)


def _parse_rss_bytes(raw: bytes) -> list[NewsItem]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        published = None
        pub = node.findtext("pubDate")
        if pub:
            try:
                published = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                published = None
        items.append(
            NewsItem(
                title=title,
                link=(node.findtext("link") or "").strip(),
                source=(node.findtext("source") or "").strip(),
                summary=(node.findtext("description") or "").strip(),
                published=published,
            )
        )
    return items


class NewsCollector:
    """포트폴리오 기준으로 종목별·축별 뉴스를 수집한다."""

    def __init__(self, per_query_limit: int = 10):
        self.per_query_limit = per_query_limit

    def _search(self, query: str, market: Market) -> list[NewsItem]:
        loc = LOCALE[market]
        url = GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(query), **loc)
        items = _fetch_rss(url)[: self.per_query_limit]
        for it in items:
            it.query = query
            it.market = market
        return items

    def collect(self, portfolio: Portfolio) -> list[NewsItem]:
        """보유 종목 이름별 + 축별 질의로 뉴스를 모아 중복 제거 후 반환.

        - 종목당 3개 질의: 일반 시세 + 호재 방향 + 악재 방향 (편향 없는 수집)
        - 모든 질의는 스레드 풀로 병렬 수집해 질의 수 확대에도 응답 시간 유지
        """
        from concurrent.futures import ThreadPoolExecutor

        jobs: list[tuple[str, Market]] = []
        for h in portfolio.holdings:
            if h.market == Market.KR:
                jobs += [
                    (f"{h.name} 주가", h.market),
                    (f"{h.name} 실적 OR 수주 OR 상향", h.market),
                    (f"{h.name} 하락 OR 소송 OR 공매도", h.market),
                ]
            else:
                jobs += [
                    (f"{h.name} stock", h.market),
                    (f"{h.name} earnings OR upgrade OR beats", h.market),
                    (f"{h.name} lawsuit OR short OR downgrade", h.market),
                ]
        for market in {h.market for h in portfolio.holdings}:
            jobs += [(q, market) for q in AXIS_QUERIES[market]]

        collected: list[NewsItem] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            for items in pool.map(lambda j: self._search(j[0], j[1]), jobs):
                collected.extend(items)
        return _dedupe(collected)


def load_news_from_file(path: str | Path) -> list[NewsItem]:
    """오프라인 모드: JSON 파일에서 뉴스 목록을 읽는다.

    형식: [{"title": ..., "link": ..., "source": ..., "summary": ...,
            "published": "2026-07-01T09:00:00", "query": ..., "market": "KR"|"US"}, ...]
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = []
    for row in data:
        published = None
        if row.get("published"):
            try:
                published = datetime.fromisoformat(row["published"])
            except ValueError:
                published = None
        items.append(
            NewsItem(
                title=row.get("title", ""),
                link=row.get("link", ""),
                source=row.get("source", ""),
                summary=row.get("summary", ""),
                published=published,
                query=row.get("query", ""),
                market=Market(row["market"]) if row.get("market") else None,
            )
        )
    return _dedupe(items)


def _dedupe(items: Iterable[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for it in items:
        key = it.link or it.title
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
