"""SQLite 연결·초기화 헬퍼.

- 스키마 단일 원천: db/schema.sql
- 런타임 DB: instance/app.db (없으면 저장소에 커밋된 시드 DB db/app.db를 복사)
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from flask import Flask, current_app, g

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "db" / "schema.sql"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_db(app: Flask):
    """런타임 DB가 없으면 시드 DB 복사, 그것도 없으면 스키마로 새로 생성."""
    db_path = Path(app.config["DATABASE"])
    if db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_conf = app.config.get("SEED_DATABASE") or ""
    if seed_conf and Path(seed_conf).is_file():
        shutil.copy(Path(seed_conf), db_path)
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def init_app(app: Flask):
    app.teardown_appcontext(close_db)
    with app.app_context():
        ensure_db(app)
