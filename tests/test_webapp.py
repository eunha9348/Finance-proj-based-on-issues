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

    # ── 로그인 유지 (영구 세션) ────────────────────────────
    def test_remember_me_sets_persistent_cookie(self):
        self.register_and_login()
        self.client.get("/auth/logout")
        resp = self.client.post("/auth/login", data={
            "email": "tester@example.com", "password": "test12345", "remember": "on",
        })
        cookie = resp.headers.get("Set-Cookie", "")
        self.assertTrue("Max-Age=" in cookie or "Expires=" in cookie)

    def test_no_remember_is_session_cookie(self):
        self.register_and_login()
        self.client.get("/auth/logout")
        resp = self.client.post("/auth/login", data={
            "email": "tester@example.com", "password": "test12345",
        })
        cookie = resp.headers.get("Set-Cookie", "")
        self.assertNotIn("Max-Age=", cookie)
        self.assertNotIn("Expires=", cookie)

    # ── 분석 시 이력 DB 기록 ───────────────────────────────
    def _count_analyses(self):
        import sqlite3
        conn = sqlite3.connect(self.app.config["DATABASE"])
        try:
            return conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        finally:
            conn.close()

    def test_analysis_is_logged_to_db(self):
        self.register_and_login()
        self.complete_survey()
        self.assertEqual(self._count_analyses(), 0)
        self.client.post("/analyze", data={"query": "005930.KS"})
        self.assertEqual(self._count_analyses(), 1)
        self.client.post("/analyze", data={"query": "NVDA"})
        self.assertEqual(self._count_analyses(), 2)
        # 이력 페이지에 두 건 모두 노출
        html = self.client.get("/history").get_data(as_text=True)
        self.assertEqual(html.count("리포트 보기"), 2)

    def test_analysis_history_belongs_to_user(self):
        # 사용자 A가 분석 → A의 이력에만 남고 B에게는 안 보임
        self.register_and_login()
        self.complete_survey()
        self.client.post("/analyze", data={"query": "TSLA"})
        self.client.get("/auth/logout")
        self.client.post("/auth/register", data={
            "email": "b@example.com", "name": "비", "password": "test12345",
        })
        self.client.post("/survey/", data={f"q{i}": "2" for i in range(6)})
        html = self.client.get("/history").get_data(as_text=True)
        self.assertIn("분석 이력이 없습니다", html)

    # ── 소셜 로그인 전체 흐름 (HTTP 모킹) ──────────────────
    def test_social_login_full_flow_mocked(self):
        import os
        from webapp import auth
        os.environ["GOOGLE_CLIENT_ID"] = "test-id"
        os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
        orig_post, orig_get = auth._post_form, auth._get_json
        auth._post_form = lambda url, data: {"access_token": "tok"}
        auth._get_json = lambda url, bearer: {
            "sub": "google-123", "email": "social@example.com", "name": "소셜유저",
        }
        try:
            # 1) 시작: 구글 인가 URL로 리다이렉트
            r = self.client.get("/auth/social/google")
            self.assertEqual(r.status_code, 302)
            self.assertIn("accounts.google.com", r.headers["Location"])
            with self.client.session_transaction() as s:
                state = s["oauth_state"]
            # 2) 콜백: 신규 사용자 생성 + 로그인 + 설문으로 이동
            r = self.client.get(f"/auth/social/callback?code=abc&state={state}",
                                 follow_redirects=True)
            body = r.get_data(as_text=True)
            self.assertIn("투자 성향", body)  # 신규 → 설문
            with self.client.session_transaction() as s:
                self.assertIn("user_id", s)   # 로그인됨
            # 3) 재로그인 시 기존 계정 재사용 (중복 생성 안 함)
            self.client.get("/auth/logout")
            with self.client.session_transaction() as s:
                s["oauth_state"] = "st2"; s["oauth_provider"] = "google"
            self.client.get("/auth/social/callback?code=abc&state=st2",
                            follow_redirects=True)
            import sqlite3
            conn = sqlite3.connect(self.app.config["DATABASE"])
            n = conn.execute(
                "SELECT COUNT(*) FROM users WHERE email='social@example.com'"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(n, 1)
        finally:
            auth._post_form, auth._get_json = orig_post, orig_get
            os.environ.pop("GOOGLE_CLIENT_ID", None)
            os.environ.pop("GOOGLE_CLIENT_SECRET", None)

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
