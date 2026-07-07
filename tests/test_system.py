"""핵심 파이프라인 단위 테스트 (네트워크 불필요)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import unittest

from stockrisk.analysis.classifier import IssueClassifier
from stockrisk.analysis.impact import ImpactAnalyzer
from stockrisk.main import load_portfolio
from stockrisk.models import Action, Horizon, IssueAxis, Market, NewsItem
from stockrisk.news.collector import load_news_from_file
from stockrisk.report import build_report
from stockrisk.strategy.recommender import StrategyRecommender, _score_to_action


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.clf = IssueClassifier()
        self.portfolio = load_portfolio(ROOT / "portfolio.example.json")

    def test_macro_rate_cut_is_positive(self):
        news = NewsItem(title="Fed signals rate cut as inflation cools", link="x", market=Market.US)
        issues = self.clf.classify(news, self.portfolio)
        macro = [i for i in issues if i.axis == IssueAxis.MACRO_FINANCE]
        self.assertTrue(macro)
        self.assertGreater(macro[0].sentiment, 0)

    def test_war_news_is_negative(self):
        news = NewsItem(title="중동 전쟁 공습 재개, 지정학 리스크 확대", link="x", market=Market.KR)
        issues = self.clf.classify(news, self.portfolio)
        war = [i for i in issues if i.axis == IssueAxis.WAR_GLOBAL]
        self.assertTrue(war)
        self.assertLess(war[0].sentiment, 0)

    def test_company_mention_detected(self):
        news = NewsItem(title="삼성전자 어닝쇼크, 매출 감소", link="x", market=Market.KR)
        issues = self.clf.classify(news, self.portfolio)
        self.assertTrue(any("005930.KS" in i.tickers_mentioned for i in issues))
        comp = [i for i in issues if i.axis == IssueAxis.COMPANY]
        self.assertTrue(comp)
        self.assertLess(comp[0].sentiment, 0)


class TestImpactAndStrategy(unittest.TestCase):
    def setUp(self):
        self.portfolio = load_portfolio(ROOT / "portfolio.example.json")
        news = load_news_from_file(ROOT / "samples" / "sample_news.json")
        self.issues = IssueClassifier().classify_all(news, self.portfolio)
        self.impacts = ImpactAnalyzer().analyze(self.portfolio, self.issues)

    def test_all_holdings_analyzed(self):
        self.assertEqual(len(self.impacts), len(self.portfolio.holdings))

    def test_direct_negative_news_hits_tesla(self):
        tesla = next(i for i in self.impacts if i.holding.ticker == "TSLA")
        self.assertLess(tesla.axis_scores[IssueAxis.COMPANY], 0)

    def test_direct_positive_news_lifts_nvidia_company_axis(self):
        nvda = next(i for i in self.impacts if i.holding.ticker == "NVDA")
        self.assertGreater(nvda.axis_scores[IssueAxis.COMPANY], 0)

    def test_horizon_scores_bounded(self):
        for imp in self.impacts:
            for h in Horizon:
                self.assertGreaterEqual(imp.horizon_scores[h], -1.0)
                self.assertLessEqual(imp.horizon_scores[h], 1.0)

    def test_recommendations_generated_for_all_horizons(self):
        recs = StrategyRecommender().recommend_all(self.impacts)
        for ticker, rec_list in recs.items():
            self.assertEqual(len(rec_list), 3)
            for rec in rec_list:
                self.assertIsInstance(rec.action, Action)
                self.assertTrue(rec.rationale)

    def test_report_builds(self):
        recs = StrategyRecommender().recommend_all(self.impacts)
        report = build_report(self.portfolio, self.issues, self.impacts, recs)
        self.assertIn("5대 이슈 축 요약", report)
        self.assertIn("삼성전자", report)
        self.assertIn("기간별 추천", report)


class TestActionMapping(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(_score_to_action(0.6), Action.STRONG_BUY)
        self.assertEqual(_score_to_action(0.2), Action.BUY)
        self.assertEqual(_score_to_action(0.0), Action.HOLD)
        self.assertEqual(_score_to_action(-0.2), Action.REDUCE)
        self.assertEqual(_score_to_action(-0.6), Action.SELL)

    def test_profile_shift_changes_action(self):
        # 경계 근처 점수는 성향에 따라 판정이 달라진다
        self.assertEqual(_score_to_action(0.08, shift=+0.08), Action.BUY)      # 공격형
        self.assertEqual(_score_to_action(0.08, shift=-0.08), Action.HOLD)     # 안정형
        self.assertEqual(_score_to_action(-0.08, shift=-0.08), Action.REDUCE)  # 안정형


class TestTacticsAreStockSpecific(unittest.TestCase):
    """전술이 종목·이슈에 따라 달라지고, 헤지 수단이 구체적으로 제시되는지 검증."""

    def setUp(self):
        self.portfolio = load_portfolio(ROOT / "portfolio.example.json")
        news = load_news_from_file(ROOT / "samples" / "sample_news.json")
        issues = IssueClassifier().classify_all(news, self.portfolio)
        self.impacts = ImpactAnalyzer().analyze(self.portfolio, issues)
        self.recs = StrategyRecommender().recommend_all(self.impacts)

    def _all_tactics(self, ticker: str) -> str:
        return " ".join(
            t for rec in self.recs[ticker]
            for t in rec.risk_management + rec.profit_strategy
        )

    def test_tactics_differ_between_stocks(self):
        lg = self._all_tactics("373220.KS")
        nvda = self._all_tactics("NVDA")
        self.assertNotEqual(lg, nvda)

    def test_negative_stock_gets_concrete_hedges(self):
        # LG에너지솔루션: 전 축 악재 → 손절 규율 + 헤지 수단이 구체적으로 제시
        lg = self._all_tactics("373220.KS")
        self.assertIn("손절 규율", lg)
        self.assertIn("410,000", lg)  # 평균단가 기반 계산 포함

    def test_stop_loss_uses_avg_price(self):
        # 손절 규율이 제시되는 종목은 평균단가가 문구에 인용된다
        samsung_tactics = self._all_tactics("005930.KS")
        if "손절 규율" in samsung_tactics:
            self.assertIn("72,000", samsung_tactics)

    def test_axis_evidence_populated(self):
        nvda = next(i for i in self.impacts if i.holding.ticker == "NVDA")
        company_ev = nvda.axis_evidence.get(IssueAxis.COMPANY, [])
        self.assertTrue(company_ev)
        self.assertIn("title", company_ev[0])
        self.assertIn("contribution", company_ev[0])


class TestPrices(unittest.TestCase):
    """가격 모듈: 합성 데이터로 지표·SVG 검증 (네트워크 불필요)."""

    def _hist(self):
        from stockrisk.prices import PriceHistory
        closes = [100 + i * 0.5 + (5 if i % 7 == 0 else 0) for i in range(120)]
        dates = [f"2026-0{1 + i // 30}-{1 + i % 30:02d}" for i in range(120)]
        return PriceHistory(symbol="TEST", dates=dates, closes=closes, currency="USD")

    def test_metrics(self):
        h = self._hist()
        self.assertGreater(h.return_over(20), 0)
        self.assertIsNotNone(h.annualized_volatility)
        self.assertLessEqual(h.max_drawdown, 0)
        self.assertGreater(h.period_high, h.period_low)

    def test_svg_renders(self):
        from stockrisk.prices import render_price_svg
        svg = render_price_svg(self._hist())
        self.assertIn("<svg", svg)
        self.assertIn("path", svg)

    def test_fetch_failure_returns_none(self):
        from stockrisk.prices import fetch_history
        # 존재하지 않는 호스트/차단 환경에서도 예외 없이 None
        self.assertIsNone(fetch_history("___INVALID___", timeout=2))


class TestRecency(unittest.TestCase):
    """최신성 가중: 최신 기사일수록 크게, 오래될수록 감쇠, 미상은 보수적."""

    def test_decay(self):
        from datetime import datetime, timedelta, timezone
        from stockrisk.analysis.impact import recency_weight
        now = datetime(2026, 7, 7, tzinfo=timezone.utc)
        self.assertEqual(recency_weight(now, now), 1.0)
        self.assertGreater(recency_weight(now - timedelta(days=3), now),
                           recency_weight(now - timedelta(days=10), now))
        self.assertEqual(recency_weight(None, now), 0.6)


class TestLLMClassifierSafety(unittest.TestCase):
    """LLM 분류기: 키 없으면 비활성, 응답 검증이 잘못된 값을 차단."""

    def test_disabled_without_key(self):
        import os
        from stockrisk.analysis import llm_classifier as L
        # 키가 없는 환경에서 비활성 (있으면 이 테스트는 스킵)
        if os.environ.get("GOOGLE_AI_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            self.skipTest("API key present")
        self.assertFalse(L.is_enabled())

    def test_validation_rejects_bad_axis_and_clamps(self):
        from stockrisk.analysis.llm_classifier import GeminiClassifier
        rows = [{"index": 0, "classifications": [
            {"axis": "NOT_AN_AXIS", "severity": 0.5, "sentiment": 0.1},
            {"axis": "company", "severity": 2.0, "sentiment": -3.0},
        ]}]
        out = GeminiClassifier._validate(rows, 1)
        self.assertEqual(len(out[0]), 1)                 # 잘못된 축 제거
        self.assertEqual(out[0][0]["axis"], "company")
        self.assertEqual(out[0][0]["severity"], 1.0)     # 범위 클램프
        self.assertEqual(out[0][0]["sentiment"], -1.0)

    def test_validation_rejects_out_of_range_index(self):
        from stockrisk.analysis.llm_classifier import GeminiClassifier
        out = GeminiClassifier._validate([{"index": 99, "classifications": []}], 1)
        self.assertNotIn(99, out)


class TestFullRegistry(unittest.TestCase):
    """전 종목 검색: 폴백(큐레이션)에서도 랭킹·시장 분리가 동작."""

    def test_search_ranks_exact_first(self):
        from webapp.analysis_service import search_registry
        results = search_registry("NVDA")
        self.assertTrue(results)
        self.assertEqual(results[0]["ticker"], "NVDA")

    def test_search_partial_korean(self):
        from webapp.analysis_service import search_registry
        tickers = [t["ticker"] for t in search_registry("삼성")]
        self.assertIn("005930.KS", tickers)


if __name__ == "__main__":
    unittest.main()
