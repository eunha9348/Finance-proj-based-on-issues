# 📊 Finance Proj Based on Issues — 이슈 기반 포트폴리오 리스크 분석·추천 시스템

사용자 포트폴리오(미국·한국 증시)를 입력하면 **5대 이슈 축**으로 뉴스를 수집·분류하고,
보유 종목과 연관 종목에 미치는 영향을 분석해 **단기/중기/장기** 리스크 관리·수익 극대화
전략과 **매수/매도/보유** 추천을 리포트로 생성합니다.

> ⚠️ 본 시스템의 출력은 참고 자료이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다.

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
| +0.45 이상 | 적극 매수 |
| +0.15 이상 | 매수 |
| -0.15 초과 | 보유 |
| -0.45 초과 | 비중 축소 |
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
