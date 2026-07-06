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
        # LG에너지솔루션: 전 축 악재 → 손절 기준 + 헤지 수단이 구체적으로 제시
        lg = self._all_tactics("373220.KS")
        self.assertIn("손절 기준", lg)
        self.assertIn("410,000", lg.replace(",", ","))  # 평균단가 기반 계산 포함

    def test_stop_loss_uses_avg_price(self):
        # 삼성전자 avg 72000 → -8% = 66,240 이 문구에 등장
        samsung_tactics = self._all_tactics("005930.KS")
        if "손절 기준" in samsung_tactics:
            self.assertIn("66,240", samsung_tactics)

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


if __name__ == "__main__":
    unittest.main()
