-- 데모 계정 시드 데이터
-- 이메일: demo@example.com / 비밀번호: demo1234 (해시는 init_db.py에서 생성)
-- 이 파일은 구조 참고용이며 실제 시드는 scripts/init_db.py가 수행한다.

INSERT OR IGNORE INTO holdings (user_id, ticker, name, market, quantity, avg_price, sector) VALUES
  (1, '005930.KS', '삼성전자', 'KR', 50, 72000, 'semiconductor'),
  (1, 'NVDA', 'NVIDIA', 'US', 8, 120.0, 'semiconductor'),
  (1, 'TSLA', 'Tesla', 'US', 12, 230.0, 'ev_battery');
