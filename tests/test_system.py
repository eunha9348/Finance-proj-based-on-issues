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
        self.assertEqual(_score_to_action(-0.3), Action.REDUCE)
        self.assertEqual(_score_to_action(-0.6), Action.SELL)


if __name__ == "__main__":
    unittest.main()
