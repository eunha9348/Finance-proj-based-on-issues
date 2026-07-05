-- 이슈 기반 포트폴리오 리스크 분석 웹서비스 DB 스키마 (SQLite)
-- 이 파일이 스키마의 단일 진실 원천(single source of truth)이다.

PRAGMA foreign_keys = ON;

-- 회원
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT,                      -- 소셜 가입자는 NULL
    provider      TEXT NOT NULL DEFAULT 'local',  -- local | google | kakao | naver
    provider_id   TEXT,                      -- 소셜 제공자 측 사용자 ID
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 투자 성향 설문 결과 (사용자당 최신 1건 유지)
CREATE TABLE IF NOT EXISTS risk_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    risk_type    TEXT NOT NULL,              -- conservative | balanced | aggressive
    score        INTEGER NOT NULL,           -- 설문 총점
    answers_json TEXT NOT NULL,              -- 문항별 응답 원본
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 보유 종목 (사용자 포트폴리오)
CREATE TABLE IF NOT EXISTS holdings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker    TEXT NOT NULL,
    name      TEXT NOT NULL,
    market    TEXT NOT NULL CHECK (market IN ('KR', 'US')),
    quantity  REAL NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    sector    TEXT NOT NULL DEFAULT '',
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, ticker)
);

-- 분석 이력
CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,               -- single(단일 종목) | portfolio(전체)
    target      TEXT NOT NULL,               -- 티커 또는 'portfolio'
    news_count  INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    offline     INTEGER NOT NULL DEFAULT 0,  -- 1이면 샘플 뉴스 기반
    report_md   TEXT NOT NULL,               -- 마크다운 리포트 전문
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id);
CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id, created_at DESC);
