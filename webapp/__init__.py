"""이슈 기반 리스크 분석 웹서비스 (Flask).

앱 팩토리 패턴. 실행:
    python run.py                      # 개발 서버 (127.0.0.1:5000)
    FLASK_SECRET_KEY=... python run.py # 운영 시 시크릿 키 필수 지정
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(__file__).resolve().parent.parent


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        instance_path=str(ROOT / "instance"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("WEBAPP_DB", str(ROOT / "instance" / "app.db")),
        SEED_DATABASE=str(ROOT / "db" / "app.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # 로그인 유지: '로그인 상태 유지' 선택 시 세션을 30일간 보존한다
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    # 운영 환경(HTTPS 프록시)에서만 활성화: Render/Railway는 TLS를 프록시에서
    # 종료하므로 X-Forwarded-* 헤더를 신뢰해야 소셜 로그인 redirect_uri가 https로
    # 생성된다. 로컬(http)에서는 TRUST_PROXY 미설정으로 꺼둔다.
    # Render는 RENDER=true를 자동 주입하므로 이를 폴백 신호로 사용한다.
    trust_proxy = os.environ.get("TRUST_PROXY")
    if trust_proxy is None:
        trust_proxy = "1" if os.environ.get("RENDER") else "0"
    if trust_proxy == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["PREFERRED_URL_SCHEME"] = "https"
        # HTTPS 운영 환경에서는 세션 쿠키를 Secure로 (HTTP로는 전송 안 함)
        app.config["SESSION_COOKIE_SECURE"] = True

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    from webapp import db
    db.init_app(app)

    # 템플릿 전역: 리포트 화면에서 5대 축을 순회할 때 사용
    from stockrisk.models import IssueAxis
    app.jinja_env.globals["axes"] = list(IssueAxis)

    from webapp.auth import bp as auth_bp
    from webapp.routes import bp as main_bp
    from webapp.survey import bp as survey_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(survey_bp)
    app.register_blueprint(main_bp)

    return app
