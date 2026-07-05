"""웹서비스 통합 테스트: 가입 → 설문 → 분석 → 포트폴리오 → 이력."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp import create_app  # noqa: E402


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(Path(self.tmp.name) / "test.db"),
            "SEED_DATABASE": "",  # 시드 복사 없이 스키마로 새로 생성
            "SECRET_KEY": "test",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # ── 헬퍼 ──────────────────────────────────────────────
    def register_and_login(self):
        return self.client.post("/auth/register", data={
            "email": "tester@example.com", "name": "테스터", "password": "test12345",
        }, follow_redirects=True)

    def complete_survey(self, level=2):
        data = {f"q{i}": str(level) for i in range(6)}
        return self.client.post("/survey/", data=data, follow_redirects=True)

    # ── 테스트 ────────────────────────────────────────────
    def test_public_pages(self):
        for path in ("/", "/about", "/auth/login", "/auth/register"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

    def test_register_validates_input(self):
        resp = self.client.post("/auth/register", data={
            "email": "bad", "name": "x", "password": "short",
        })
        self.assertIn("올바른 이메일", resp.get_data(as_text=True))

    def test_register_then_redirected_to_survey(self):
        resp = self.register_and_login()
        self.assertIn("투자 성향 진단", resp.get_data(as_text=True))

    def test_duplicate_email_rejected(self):
        self.register_and_login()
        self.client.get("/auth/logout")
        resp = self.client.post("/auth/register", data={
            "email": "tester@example.com", "name": "다른사람", "password": "test12345",
        })
        self.assertIn("이미 가입된 이메일", resp.get_data(as_text=True))

    def test_survey_classifies_profile(self):
        self.register_and_login()
        resp = self.complete_survey(level=3)  # 모든 문항 최고점 → 공격형
        self.assertIn("공격형", resp.get_data(as_text=True))

    def test_login_logout(self):
        self.register_and_login()
        self.client.get("/auth/logout")
        resp = self.client.post("/auth/login", data={
            "email": "tester@example.com", "password": "test12345",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post("/auth/login", data={
            "email": "tester@example.com", "password": "wrongpass",
        })
        self.assertIn("올바르지 않습니다", resp.get_data(as_text=True))

    def test_protected_pages_require_login(self):
        for path in ("/dashboard", "/analyze", "/portfolio", "/history"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)

    def test_search_api(self):
        resp = self.client.get("/api/search?q=삼성")
        rows = resp.get_json()
        self.assertTrue(any(r["ticker"] == "005930.KS" for r in rows))

    def test_analyze_known_ticker_offline(self):
        self.register_and_login()
        self.complete_survey()
        resp = self.client.post("/analyze", data={"query": "삼성전자"})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("삼성전자", html)
        self.assertIn("기간별 추천", html)

    def test_analyze_unknown_ticker_with_market(self):
        self.register_and_login()
        self.complete_survey()
        resp = self.client.post("/analyze", data={
            "query": "듄앤컴퍼니", "market": "KR",
        })
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("듄앤컴퍼니", html)

    def test_portfolio_add_analyze_delete(self):
        self.register_and_login()
        self.complete_survey()
        # 추가
        resp = self.client.post("/portfolio", data={
            "query": "NVDA", "quantity": "5", "avg_price": "120",
        }, follow_redirects=True)
        self.assertIn("NVIDIA", resp.get_data(as_text=True))
        # 전체 분석
        resp = self.client.post("/analyze/portfolio")
        self.assertIn("포트폴리오 종합 리포트", resp.get_data(as_text=True))
        # 이력 확인
        resp = self.client.get("/history")
        self.assertIn("리포트 보기", resp.get_data(as_text=True))

    def test_social_login_unconfigured_shows_notice(self):
        resp = self.client.get("/auth/social/google", follow_redirects=True)
        self.assertIn("설정되지 않았습니다", resp.get_data(as_text=True))

    def test_analysis_history_detail_access_control(self):
        self.register_and_login()
        self.complete_survey()
        self.client.post("/analyze", data={"query": "NVDA"})
        # 본인 이력 접근 OK
        resp = self.client.get("/history/1")
        self.assertEqual(resp.status_code, 200)
        # 타인 이력 접근 차단
        self.client.get("/auth/logout")
        self.client.post("/auth/register", data={
            "email": "other@example.com", "name": "타인", "password": "test12345",
        })
        resp = self.client.get("/history/1", follow_redirects=True)
        self.assertIn("찾을 수 없습니다", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
