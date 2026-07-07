# 📊 IssueLens — 이슈 기반 포트폴리오 리스크 분석·추천 웹서비스

사용자 포트폴리오(미국·한국 증시)를 입력하면 **5대 이슈 축**으로 뉴스를 수집·분류하고,
보유 종목과 연관 종목에 미치는 영향을 분석해 **단기/중기/장기** 리스크 관리·수익 극대화
전략과 **매수/매도/보유** 추천을 리포트로 생성합니다.

분석 엔진(`stockrisk`, CLI)과 웹서비스(`webapp`, Flask) 두 층으로 구성됩니다.

> ⚠️ 본 시스템의 출력은 참고 자료이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다.

## 🌐 웹서비스 (IssueLens)

```bash
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:5000 (개발 서버)
# 운영 배포 예시
FLASK_SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))") \
  gunicorn -w 2 -b 0.0.0.0:8000 "webapp:create_app()"
```

- **데모 계정**: `demo@example.com` / `demo1234`
- **회원가입·로그인**: 이메일 가입(PBKDF2 해시) + 소셜 연동(Google/카카오/네이버 OAuth2).
  소셜 로그인은 환경변수 설정 시 자동 활성화:
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET`,
  `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
  (콜백 URL: `https://<도메인>/auth/social/callback` — 각 제공자 콘솔에 등록).
  운영 환경은 `RENDER`/`TRUST_PROXY=1` 감지 시 ProxyFix로 X-Forwarded 헤더를 신뢰해
  `redirect_uri`를 https로 생성하고 세션 쿠키에 Secure 플래그를 붙입니다.
- **로그인 유지**: '로그인 상태 유지' 선택 시 영구 세션(30일, `PERMANENT_SESSION_LIFETIME`).
  브라우저를 닫아도 유지되며, 해제 시 브라우저 종료로 만료됩니다. 소셜 로그인·가입은 유지가 기본.
- **분석 이력**: 로그인 사용자가 종목·포트폴리오를 분석하면 `analyses` 테이블에
  리포트 전문과 함께 자동 저장되어 `분석 이력`에서 다시 열람할 수 있습니다(사용자별 격리).
- **투자 성향 설문**: 가입 직후 6문항 진단 → 안정형/위험중립형/공격형.
  성향에 따라 매수·매도 임계값이 ±0.08 보정됩니다.
- **종목 분석**: 한·미 증시 **전 종목** 시장별 자동완성 검색(빌드 시 거래소 공식
  목록 생성) + 목록에 없는 종목도 이름·시장 입력으로 분석 가능. 실시간 뉴스 수집
  실패 시 샘플 뉴스로 자동 폴백해 항상 결과를 반환합니다.
- **최신성 우선 파이프라인**: 수집 기사를 발행 시각 최신순으로 정렬하고, 최신
  기사일수록 점수 기여를 크게(≤24h ×1.0 ~ 14일↑ ×0.25) 반영합니다. 리포트에는
  분석 기준 시각과 수집된 최신 뉴스 시각을 명시합니다.
- **포트폴리오 관리 / 분석 이력**: 종목 등록·수정·삭제, 전체 분석, 리포트 이력 저장.

### Google AI(Gemini) 뉴스 분류 — 선택

기본은 내장 키워드 분류기입니다. `GOOGLE_AI_API_KEY` 환경변수를 설정하면 Google
Gemini가 뉴스 분류(축·심각도·방향성)를 담당합니다.

```bash
# 로컬 실행 시 (셸 세션에만 존재, 파일로 저장하지 말 것)
export GOOGLE_AI_API_KEY="AIza...본인_키"
python run.py
```

- **키 발급**: [Google AI Studio](https://aistudio.google.com/apikey) → "Get API key"
- **⚠️ 보안**: API 키는 **절대 코드·저장소에 커밋하지 마세요.** 커밋 시 GitHub에
  노출되어 키가 도용될 수 있습니다. `.env`, `*.key`, `secrets.json`은 `.gitignore`로
  차단되어 있습니다. 운영 배포에서는 Render 대시보드의 환경변수(`GOOGLE_AI_API_KEY`,
  `sync: false`)로만 주입하세요.
- **할루시네이션 방지**: `temperature=0` + JSON 스키마 강제(축은 5개 열거값으로 제한)
  + "본문에 없는 사실을 만들지 말라" 프롬프트 제약. 응답 검증 실패 항목은 키워드
  분류기로 자동 폴백합니다. 종목명·수치·링크는 LLM이 생성하지 않고 원문/실측만 사용합니다.

### 전 종목 목록 생성

```bash
python scripts/build_ticker_db.py   # 거래소 공식 목록 → data/tickers_full.json
```

- 미국: Nasdaq Trader Symbol Directory / 한국: KRX KIND 상장법인목록
- 최소 종목 수 검증(미국 5,000 / 한국 2,000)을 통과해야 저장 — 불완전한 목록은 배포 안 함
- Render 빌드 명령에 포함되어 자동 실행되며, 실패해도 앱은 큐레이션 목록으로 폴백
- 생성 파일은 `.gitignore` 대상(빌드 산출물이라 커밋하지 않음)

### 데이터베이스

- 스키마: [`db/schema.sql`](db/schema.sql) (users, risk_profiles, holdings, analyses)
- 시드 DB: [`db/app.db`](db/app.db) — 데모 계정·포트폴리오 포함, 저장소에 커밋됨
- 런타임 DB: `instance/app.db` (첫 실행 시 시드 DB를 복사; `WEBAPP_DB` 환경변수로 변경 가능)
- 시드 재생성: `python scripts/init_db.py`

### 무료 호스팅 배포 (Render / Railway)

두 플랫폼 모두 이 저장소를 그대로 인식하도록 배포 설정 파일을 포함하고 있습니다.

**Render (무료 웹서비스)**

1. https://dashboard.render.com → **New +** → **Blueprint**
2. 이 GitHub 저장소(`eunha9348/Finance-proj-based-on-issues`) 연결 → `render.yaml`을 자동 인식
3. `FLASK_SECRET_KEY`는 자동 생성됩니다. 소셜 로그인을 쓰려면 대시보드에서
   `GOOGLE_CLIENT_ID` 등 값을 채워 넣으세요 (선택 사항, 비워두면 비활성화 상태로 정상 동작)
4. Deploy 클릭 → 빌드 완료 후 `https://issuelens.onrender.com` 형태의 URL 발급

**Railway**

1. https://railway.app → **New Project** → **Deploy from GitHub repo**
2. 이 저장소 선택 → `railway.json` + `Procfile`을 자동 인식(Nixpacks 빌더)
3. **Variables** 탭에서 `FLASK_SECRET_KEY` 추가 (필수), 소셜 로그인 키는 선택
4. Deploy 후 **Settings → Networking → Generate Domain**으로 공개 URL 발급

> ⚠️ **무료 티어 디스크는 영구 저장이 보장되지 않습니다.** 재배포·재시작 시
> `instance/app.db`가 초기화될 수 있어 신규 가입 계정·포트폴리오가 사라질 수 있습니다.
> 데모 이상의 용도로 데이터를 영구 보존하려면 Render Postgres, Railway Postgres
> 플러그인 등 외부 DB 연결을 권장합니다. (schema.sql은 표준 SQL이라 이식이 쉽습니다.)

## 5대 이슈 축

| 축 | 내용 | 예시 |
|---|---|---|
| ① 국가별 정치 이슈 | 선거·규제·관세·제재 등 | 관세 부과, 반독점 소송 |
| ② 전쟁·세계 이슈 | 전쟁·분쟁·팬데믹·재해 | 중동 공습, 휴전 협상 |
| ③ 기업 자체 이슈 | 오너리스크·매출하락·공매도 등 | 어닝쇼크, 횡령, 공매도 공격 |
| ④ 시장 모멘텀·투자심리 | 급등락·수급·공포지수 | 외국인 순매도, 패닉셀 |
| ⑤ 거시 금융 이슈 | 금리·인플레이션·환율 | 연준 금리인하, 경기침체 |

## 동작 구조

```
포트폴리오(JSON)
   │
   ▼
[1] 뉴스 수집 (stockrisk/news/collector.py)
    Google News RSS — 종목별 질의 + 축별 시장 질의, 한국어/영어
   │
   ▼
[2] 이슈 분류 (stockrisk/analysis/classifier.py)
    키워드 사전(data/keywords.json)으로 5대 축 분류
    심각도(0~1) × 방향성(-1 악재 ~ +1 호재) 산출
   │
   ▼
[3] 영향 분석 (stockrisk/analysis/impact.py)
    전이 경로: 직접 언급(100%) → 섹터 연관(상관계수) → 시장 전반(베타)
    연관 종목 매핑: data/related_stocks.json
    축별 점수를 기간 가중치로 합성 → 단기/중기/장기 점수
   │
   ▼
[4] 전략 추천 (stockrisk/strategy/recommender.py)
    점수 → 적극매수/매수/보유/비중축소/매도
    기간별 리스크 관리 · 수익 극대화 전술 제시
   │
   ▼
[5] 리포트 생성 (stockrisk/report.py) — 마크다운
```

## 사용법

Python 3.10+ 표준 라이브러리만 사용합니다 (외부 패키지 불필요).

```bash
# 1) 포트폴리오 작성 (portfolio.example.json 참고)
cp portfolio.example.json my_portfolio.json

# 2) 실시간 뉴스 수집 + 분석
python -m stockrisk analyze --portfolio my_portfolio.json --output report.md

# 3) 네트워크 없이 샘플 뉴스로 데모
python -m stockrisk analyze --portfolio portfolio.example.json \
    --news-file samples/sample_news.json --output report.md

# 4) 30분 간격 모니터링
python -m stockrisk monitor --portfolio my_portfolio.json --interval 1800
```

### 포트폴리오 형식

```json
{
  "owner": "홍길동",
  "holdings": [
    {"ticker": "005930.KS", "name": "삼성전자", "market": "KR",
     "quantity": 50, "avg_price": 72000, "sector": "semiconductor"},
    {"ticker": "AAPL", "name": "Apple", "market": "US",
     "quantity": 15, "avg_price": 185.5, "sector": "bigtech"}
  ]
}
```

- `market`: `KR` 또는 `US`
- `sector`: `data/related_stocks.json`의 섹터 키 (생략 시 티커로 자동 탐색)

## 점수 → 추천 매핑

| 기간 점수 | 추천 |
|---|---|
| +0.35 이상 | 적극 매수 |
| +0.12 이상 | 매수 |
| -0.12 초과 | 보유 |
| -0.35 초과 | 비중 축소 |
| 그 이하 | 매도 |

기간별 축 가중치(`data/keywords.json`의 `horizon_weights`): 예를 들어 **투자심리**는
단기에 가장 크게(1.0), 장기에는 거의(0.2) 반영되지 않고, **거시 금융**은 장기에
가장 크게(1.0) 반영됩니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 프로젝트 구조

```
stockrisk/
├── models.py               # 데이터 모델 (포트폴리오·뉴스·이슈·추천)
├── news/collector.py       # Google News RSS 수집기 (+오프라인 모드)
├── analysis/classifier.py  # 5대 축 키워드 분류기
├── analysis/impact.py      # 보유·연관 종목 영향 분석
├── strategy/recommender.py # 기간별 전략·매수/매도 추천
├── report.py               # 마크다운 리포트 생성
└── main.py                 # CLI (analyze / monitor)
data/
├── keywords.json           # 축별 분류 키워드 + 기간 가중치
└── related_stocks.json     # 섹터·연관 종목 매핑 + 시장 베타
```

## 한계와 확장 방향

- 키워드 규칙 기반 분류 → LLM 분류기로 교체 가능하도록 모듈 분리됨
- 가격 데이터 미사용 → 모멘텀 계산에 시세 API(yfinance 등) 연동 가능
- 연관 종목 매핑은 정적 JSON → 상관계수 실측 데이터로 대체 가능
