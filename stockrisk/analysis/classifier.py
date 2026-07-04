"""이슈 분류기.

수집된 뉴스를 5대 이슈 축으로 분류하고 심각도(severity)와 방향성(sentiment)을
산출한다. data/keywords.json의 한국어/영어 키워드 사전을 사용하는 규칙 기반
분류기로, 외부 API 없이 동작한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from stockrisk.models import ClassifiedIssue, IssueAxis, NewsItem, Portfolio

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class IssueClassifier:
    def __init__(self, keywords_path: str | Path | None = None):
        path = Path(keywords_path) if keywords_path else DATA_DIR / "keywords.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.axis_keywords: dict[IssueAxis, list[dict]] = {
            IssueAxis(axis): spec["keywords"]
            for axis, spec in config["axes"].items()
        }
        self.horizon_weights: dict = config["horizon_weights"]

    def classify(self, news: NewsItem, portfolio: Portfolio | None = None) -> list[ClassifiedIssue]:
        """뉴스 1건을 분류한다. 여러 축에 동시에 해당할 수 있어 리스트를 반환."""
        text = news.text.lower()
        results: list[ClassifiedIssue] = []
        tickers = self._mentioned_tickers(text, portfolio) if portfolio else []

        for axis, keywords in self.axis_keywords.items():
            matched = []
            weight_sum = 0.0
            sent_sum = 0.0
            for kw in keywords:
                if kw["term"].lower() in text:
                    matched.append(kw["term"])
                    weight_sum += kw["weight"]
                    sent_sum += kw["weight"] * kw["sentiment"]
            if not matched:
                continue
            # 심각도: 매칭 가중치 합을 1.5로 나눠 포화(2개 이상 강한 키워드면 1.0 근접)
            severity = min(1.0, weight_sum / 1.5)
            # 방향성: 가중 평균
            sentiment = max(-1.0, min(1.0, sent_sum / weight_sum))
            results.append(
                ClassifiedIssue(
                    news=news,
                    axis=axis,
                    severity=round(severity, 3),
                    sentiment=round(sentiment, 3),
                    matched_keywords=matched,
                    tickers_mentioned=tickers,
                )
            )
        return results

    def classify_all(self, news_list: list[NewsItem], portfolio: Portfolio | None = None) -> list[ClassifiedIssue]:
        issues: list[ClassifiedIssue] = []
        for n in news_list:
            issues.extend(self.classify(n, portfolio))
        return issues

    @staticmethod
    def _mentioned_tickers(text: str, portfolio: Portfolio) -> list[str]:
        """뉴스 본문에 직접 언급된 보유 종목의 티커 목록."""
        mentioned = []
        for h in portfolio.holdings:
            name = h.name.lower()
            # 미국 티커는 단어 경계로도 매칭 (예: 'AAPL')
            ticker_base = h.ticker.split(".")[0].lower()
            if name and name in text:
                mentioned.append(h.ticker)
            elif len(ticker_base) >= 3 and re.search(rf"\b{re.escape(ticker_base)}\b", text):
                mentioned.append(h.ticker)
        return mentioned
