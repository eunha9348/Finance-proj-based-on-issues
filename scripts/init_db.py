"""시드 DB(db/app.db) 생성 스크립트.

스키마(db/schema.sql)를 적용하고 데모 계정·데모 포트폴리오를 넣는다.
저장소에 커밋되는 DB 파일을 갱신할 때 실행한다:

    python scripts/init_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402

DB_PATH = ROOT / "db" / "app.db"
SCHEMA = ROOT / "db" / "schema.sql"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO users (email, name, password_hash, provider) VALUES (?, ?, ?, 'local')",
            ("demo@example.com", "데모 사용자", generate_password_hash("demo1234")),
        )
        conn.execute(
            """INSERT INTO risk_profiles (user_id, risk_type, score, answers_json)
               VALUES (1, 'balanced', 14, '[2,2,1,2,2,2]')""",
        )
        conn.executemany(
            """INSERT INTO holdings (user_id, ticker, name, market, quantity, avg_price, sector)
               VALUES (1, ?, ?, ?, ?, ?, ?)""",
            [
                ("005930.KS", "삼성전자", "KR", 50, 72000, "semiconductor"),
                ("NVDA", "NVIDIA", "US", 8, 120.0, "semiconductor"),
                ("TSLA", "Tesla", "US", 12, 230.0, "ev_battery"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    print(f"시드 DB 생성 완료: {DB_PATH}")


if __name__ == "__main__":
    main()
