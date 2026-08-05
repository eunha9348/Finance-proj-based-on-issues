"""군중심리지수·백테스트 단위 테스트 (네트워크 불필요, 커밋된 스냅샷만 사용)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockrisk.crowd.backtest import ALLOCATION_BY_BAND, period_return, run_backtest
from stockrisk.crowd.data import MonthlyRecord, load_monthly_records
from stockrisk.crowd.index import CrowdIndexPoint, band_of, compute_crowd_index


def _flat_records(n: int, price_fn, vix_fn, cape=20.0) -> list[MonthlyRecord]:
    records = []
    for i in range(n):
        y, m = divmod(i, 12)
        records.append(
            MonthlyRecord(
                month=f"{1990 + y:04d}-{m + 1:02d}",
                sp500=price_fn(i),
                dividend_annual=20.0,
                long_rate_pct=3.0,
                cape=cape,
                vix_avg=vix_fn(i),
                vix_end=vix_fn(i),
            )
        )
    return records


class TestBand(unittest.TestCase):
    def test_band_boundaries(self):
        self.assertEqual(band_of(0), "extreme_fear")
        self.assertEqual(band_of(24.9), "extreme_fear")
        self.assertEqual(band_of(25), "fear")
        self.assertEqual(band_of(44.9), "fear")
        self.assertEqual(band_of(45), "neutral")
        self.assertEqual(band_of(54.9), "neutral")
        self.assertEqual(band_of(55), "greed")
        self.assertEqual(band_of(74.9), "greed")
        self.assertEqual(band_of(75), "extreme_greed")
        self.assertEqual(band_of(100), "extreme_greed")


class TestIndex(unittest.TestCase):
    def test_flat_market_is_neutral(self):
        """가격도 VIX도 변화가 없으면(백분위 모집단이 전부 동일값) 지수는 중립 근처."""
        records = _flat_records(48, price_fn=lambda i: 100.0, vix_fn=lambda i: 15.0)
        points = compute_crowd_index(records, min_history=36)
        self.assertTrue(points)
        for p in points:
            self.assertAlmostEqual(p.score, 50.0, delta=1e-9)
            self.assertEqual(p.band, "neutral")

    def test_no_lookahead(self):
        """뒤쪽에 극단적인 값을 추가해도 이전 시점의 지수 값은 바뀌지 않아야 한다."""
        records_a = _flat_records(40, price_fn=lambda i: 100.0 * (1.01 ** i), vix_fn=lambda i: 15.0)
        points_a = compute_crowd_index(records_a, min_history=36)

        records_b = records_a + _flat_records(5, price_fn=lambda i: 1000.0, vix_fn=lambda i: 80.0)
        # 뒤에 이어붙인 5개월도 month 라벨이 겹치지 않도록 조정
        for i, r in enumerate(records_b[len(records_a):]):
            r.month = f"1999-{i + 1:02d}"
        points_b = compute_crowd_index(records_b, min_history=36)

        shared = {p.month: p.score for p in points_a}
        for p in points_b:
            if p.month in shared:
                self.assertAlmostEqual(p.score, shared[p.month], places=6)

    def test_sharp_rally_scores_higher_than_flat_baseline(self):
        """긴 횡보 뒤 마지막 3개월 급등+VIX 급락이 오면 그 시점 지수는 중립보다 뚜렷이 높아야 한다."""

        def price(i: int) -> float:
            if i < 45:
                return 100.0
            return {45: 110.0, 46: 122.0, 47: 140.0}[i]

        def vix(i: int) -> float:
            return 10.0 if i < 45 else {45: 8.0, 46: 6.0, 47: 5.0}[i]

        records = _flat_records(48, price_fn=price, vix_fn=vix)
        points = compute_crowd_index(records, min_history=36)
        by_month = {p.month: p for p in points}
        baseline = by_month[records[40].month].score
        rally = by_month[records[47].month].score
        self.assertGreater(rally, baseline)
        self.assertGreater(rally, 55.0)


class TestBacktest(unittest.TestCase):
    def test_allocation_weights_are_monotonic(self):
        order = ["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
        weights = [ALLOCATION_BY_BAND[b] for b in order]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_all_extreme_fear_matches_pure_equity(self):
        """항상 극단적 공포(100% 주식 비중)로 강제하면 전략 수익률은 벤치마크와 완전히 같아야 한다."""
        records = _flat_records(60, price_fn=lambda i: 100.0 * (1.01 ** i), vix_fn=lambda i: 90.0)
        points = [
            CrowdIndexPoint(month=r.month, score=10.0, band="extreme_fear", components={})
            for r in records
        ]
        result = run_backtest(records, points)
        self.assertAlmostEqual(result.strategy.total_return, result.benchmark.total_return, places=9)
        self.assertAlmostEqual(result.strategy.cagr, result.benchmark.cagr, places=9)

    def test_all_extreme_greed_gives_zero_equity_exposure(self):
        """항상 극단적 탐욕(현금 100%)이면 전략 수익률은 벤치마크와 무관하게 현금금리와 같아야 한다."""
        records = _flat_records(36, price_fn=lambda i: 100.0 * (1.05 ** i), vix_fn=lambda i: 15.0)
        points = [
            CrowdIndexPoint(month=r.month, score=90.0, band="extreme_greed", components={})
            for r in records
        ]
        result = run_backtest(records, points)
        for p in result.points:
            expected_cash = records[0].long_rate_pct / 100.0 / 12.0
            self.assertAlmostEqual(p.strategy_return, expected_cash, places=9)
            self.assertEqual(p.weight_equity, 0.0)

    def test_period_return_matches_manual_compounding(self):
        records = _flat_records(48, price_fn=lambda i: 100.0 * (1.01 ** i), vix_fn=lambda i: 15.0)
        points = compute_crowd_index(records, min_history=36)
        result = run_backtest(records, points)
        window = [p for p in result.points if result.points[0].month <= p.month <= result.points[2].month]
        expected_bench = 1.0
        for p in window:
            expected_bench *= 1 + p.benchmark_return
        got = period_return(result.points, result.points[0].month, result.points[2].month)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got[1], expected_bench - 1.0, places=9)


class TestRealSnapshot(unittest.TestCase):
    """커밋된 실측 데이터 스냅샷이 여전히 파싱 가능한지 확인 (네트워크 불필요)."""

    def test_loads_and_covers_expected_range(self):
        records = load_monthly_records()
        self.assertGreater(len(records), 400)
        self.assertEqual(records[0].month, "1990-01")
        for r in records:
            self.assertGreater(r.sp500, 0)
            self.assertGreaterEqual(r.vix_avg, 0)

    def test_full_pipeline_runs(self):
        records = load_monthly_records()
        points = compute_crowd_index(records)
        result = run_backtest(records, points)
        self.assertTrue(points)
        self.assertTrue(result.points)
        for p in points:
            self.assertGreaterEqual(p.score, 0.0)
            self.assertLessEqual(p.score, 100.0)


if __name__ == "__main__":
    unittest.main()
