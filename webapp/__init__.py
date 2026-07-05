"""이슈 기반 리스크 분석 웹서비스 (Flask).

앱 팩토리 패턴. 실행:
    python run.py                      # 개발 서버 (127.0.0.1:5000)
    FLASK_SECRET_KEY=... python run.py # 운영 시 시크릿 키 필수 지정
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

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
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

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
