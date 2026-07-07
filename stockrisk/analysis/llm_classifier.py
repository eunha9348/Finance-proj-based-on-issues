"""Google AI (Gemini) 기반 LLM 뉴스 분류기 — 선택 기능.

- 환경변수 GOOGLE_AI_API_KEY(또는 GEMINI_API_KEY)가 설정된 경우에만 활성화.
  키가 없으면 서비스는 기존 키워드 분류기로 동작한다.
- API 키는 절대 코드·저장소에 넣지 않는다. Render 환경변수로만 주입.

할루시네이션 방지 설계:
  1. temperature=0 — 같은 입력에 최대한 같은 출력
  2. responseSchema로 JSON 구조 강제 — 축 이름은 5개 열거값으로 제한
  3. 프롬프트에 '본문에 없는 사실·수치·종목명을 만들지 말 것' 명시
  4. LLM은 (축, 심각도, 방향성) 판정만 담당 — 뉴스 제목·링크·종목 언급 감지는
     원문 그대로/기존 정규식 로직을 사용하므로 텍스트가 생성될 여지가 없음
  5. 응답 검증 실패(축 이름 오류, 범위 밖 수치) 시 해당 뉴스는 키워드 분류기로 폴백
"""
from __future__ import annotations

import json
import os
import urllib.request

from stockrisk.analysis.classifier import IssueClassifier
from stockrisk.models import ClassifiedIssue, IssueAxis, NewsItem, Portfolio

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)
DEFAULT_MODEL = "gemini-2.0-flash"
BATCH_SIZE = 20          # 한 번의 호출로 분류할 뉴스 수 (비용·속도 최적화)
VALID_AXES = {a.value for a in IssueAxis}

SYSTEM_PROMPT = """당신은 금융 뉴스 분류기입니다. 각 뉴스를 다음 5개 축으로 분류하세요.
- geopolitics: 국가별 정치 이슈 (선거, 규제, 관세, 제재)
- war_global: 전쟁·세계 이슈 (분쟁, 팬데믹, 재해, 휴전)
- company: 기업 자체 이슈 (실적, 오너리스크, 공매도, 수주, 소송)
- sentiment: 시장 투자심리 (급등락, 수급, 공포지수, 랠리)
- macro_finance: 거시 금융 (금리, 물가, 환율, 경기)

규칙:
1. 뉴스 본문에 실제로 있는 내용만 근거로 판단하세요. 본문에 없는 사실·수치·종목명을 절대 만들지 마세요.
2. 하나의 뉴스가 여러 축에 해당하면 각각 출력하세요. 해당 없으면 빈 배열.
3. severity: 사안의 중대성 0.0~1.0 / sentiment: 주가 방향성 -1.0(악재)~+1.0(호재)
4. 지정된 JSON 형식으로만 응답하세요."""

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "index": {"type": "INTEGER"},
            "classifications": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "axis": {"type": "STRING", "enum": sorted(VALID_AXES)},
                        "severity": {"type": "NUMBER"},
                        "sentiment": {"type": "NUMBER"},
                    },
                    "required": ["axis", "severity", "sentiment"],
                },
            },
        },
        "required": ["index", "classifications"],
    },
}


def api_key() -> str | None:
    return os.environ.get("GOOGLE_AI_API_KEY") or os.environ.get("GEMINI_API_KEY")


def is_enabled() -> bool:
    return api_key() is not None


class GeminiClassifier:
    """Gemini로 (축, 심각도, 방향성)을 판정하고, 실패 시 키워드 분류기로 폴백.

    IssueClassifier와 동일한 인터페이스(classify_all)를 제공한다.
    """

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 25):
        self.model = model
        self.timeout = timeout
        self.fallback = IssueClassifier()   # 폴백 + 종목 언급 감지 재사용

    # ------------------------------------------------------------------
    def classify_all(
        self, news_list: list[NewsItem], portfolio: Portfolio | None = None
    ) -> list[ClassifiedIssue]:
        issues: list[ClassifiedIssue] = []
        for start in range(0, len(news_list), BATCH_SIZE):
            batch = news_list[start:start + BATCH_SIZE]
            batch_results = self._classify_batch(batch)
            if batch_results is None:
                # 호출 실패 → 이 배치는 키워드 분류기로
                for n in batch:
                    issues.extend(self.fallback.classify(n, portfolio))
                continue
            for i, news in enumerate(batch):
                rows = batch_results.get(i)
                if rows is None:
                    issues.extend(self.fallback.classify(news, portfolio))
                    continue
                tickers = (
                    self.fallback._mentioned_tickers(news.text.lower(), portfolio)
                    if portfolio else []
                )
                for row in rows:
                    issues.append(ClassifiedIssue(
                        news=news,
                        axis=IssueAxis(row["axis"]),
                        severity=row["severity"],
                        sentiment=row["sentiment"],
                        matched_keywords=["llm"],
                        tickers_mentioned=tickers,
                    ))
        return issues

    # ------------------------------------------------------------------
    def _classify_batch(self, batch: list[NewsItem]) -> dict[int, list[dict]] | None:
        """배치 1회 호출. 실패하면 None (호출측에서 폴백)."""
        key = api_key()
        if not key:
            return None
        numbered = "\n".join(
            f"[{i}] {n.title} — {n.summary[:200]}" for i, n in enumerate(batch)
        )
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": numbered}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
        url = GEMINI_URL.format(model=self.model, key=key)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            rows = json.loads(text)
        except Exception:
            return None
        return self._validate(rows, len(batch))

    @staticmethod
    def _validate(rows, batch_len: int) -> dict[int, list[dict]] | None:
        """응답 검증: 축 이름·수치 범위를 벗어나면 해당 항목 폐기."""
        if not isinstance(rows, list):
            return None
        out: dict[int, list[dict]] = {}
        for row in rows:
            try:
                idx = int(row["index"])
                if not (0 <= idx < batch_len):
                    continue
                cleaned = []
                for c in row.get("classifications", []):
                    axis = c.get("axis")
                    sev = float(c.get("severity"))
                    sent = float(c.get("sentiment"))
                    if axis not in VALID_AXES:
                        continue
                    cleaned.append({
                        "axis": axis,
                        "severity": max(0.0, min(1.0, round(sev, 3))),
                        "sentiment": max(-1.0, min(1.0, round(sent, 3))),
                    })
                out[idx] = cleaned
            except (KeyError, TypeError, ValueError):
                continue
        return out
