"""한·미 증시 전 종목 목록 생성 스크립트.

공식 출처에서만 내려받는다 (종목을 생성·추정하지 않는다):
  - 미국: Nasdaq Trader Symbol Directory (nasdaqlisted.txt, otherlisted.txt)
          — 나스닥·NYSE·AMEX 전 상장 심볼 공식 파일
  - 한국: KRX KIND 상장법인목록 (corpList.do, 유가증권/코스닥 각각)

결과: data/tickers_full.json
  {"generated_at": ..., "kr": [{"ticker","name"}...], "us": [{"ticker","name"}...]}

검증 게이트: 시장별 최소 종목 수(미국 5,000 / 한국 2,000)를 넘지 못하면
기존 파일을 덮어쓰지 않고 실패로 종료한다 — 불완전한 목록 배포 방지.

사용:
  python scripts/build_ticker_db.py            # 다운로드 + 생성
Render 배포 시 빌드 명령에 포함되어 자동 실행된다 (실패해도 빌드는 계속,
앱은 큐레이션 기본 목록으로 폴백).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tickers_full.json"

NASDAQ_URLS = [
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]
KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
UA = "Mozilla/5.0 (compatible; IssueLensTickerBot/1.0)"

MIN_US = 5000
MIN_KR = 2000


def _get(url: str, data: dict | None = None, timeout: int = 30) -> bytes:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_us() -> list[dict]:
    """Nasdaq Trader 심볼 디렉터리 파싱 (파이프 구분 텍스트)."""
    out: list[dict] = []
    for url in NASDAQ_URLS:
        raw = _get(url).decode("utf-8", errors="replace")
        lines = [l for l in raw.splitlines() if l and "|" in l]
        header = lines[0].split("|")
        sym_idx = 0
        name_idx = 1
        try:
            test_idx = header.index("Test Issue")
        except ValueError:
            test_idx = None
        etf_idx = header.index("ETF") if "ETF" in header else None
        for line in lines[1:]:
            if line.startswith("File Creation Time"):
                continue
            cols = line.split("|")
            if len(cols) <= max(sym_idx, name_idx):
                continue
            sym = cols[sym_idx].strip()
            name = cols[name_idx].strip()
            if not sym or not name:
                continue
            if test_idx is not None and len(cols) > test_idx and cols[test_idx].strip() == "Y":
                continue  # 테스트 심볼 제외
            is_etf = etf_idx is not None and len(cols) > etf_idx and cols[etf_idx].strip() == "Y"
            out.append({"ticker": sym, "name": name, "etf": is_etf})
    # 심볼 기준 중복 제거
    seen: set[str] = set()
    dedup = []
    for row in out:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        dedup.append(row)
    return dedup


def fetch_kr() -> list[dict]:
    """KRX KIND 상장법인목록 파싱 (EUC-KR HTML 테이블).

    유가증권(stockMkt → .KS)과 코스닥(kosdaqMkt → .KQ)을 각각 받는다.
    """
    out: list[dict] = []
    for market_type, suffix in (("stockMkt", ".KS"), ("kosdaqMkt", ".KQ")):
        raw = _get(KIND_URL, data={
            "method": "download",
            "searchType": "13",
            "marketType": market_type,
        })
        html = raw.decode("euc-kr", errors="replace")
        # 행 단위 파싱: <tr><td>회사명</td><td>종목코드</td>...
        for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_match.group(1), re.S)
            if len(cells) < 2:
                continue
            name = re.sub(r"<[^>]+>", "", cells[0]).strip()
            code = re.sub(r"<[^>]+>", "", cells[1]).strip()
            if not re.fullmatch(r"\d{6}", code):
                continue  # 헤더 행 등 제외
            out.append({"ticker": f"{code}{suffix}", "name": name, "etf": False})
    return out


def main() -> int:
    print("[1/3] 미국 심볼 디렉터리 다운로드 (Nasdaq Trader)...")
    try:
        us = fetch_us()
    except Exception as exc:
        print(f"  실패: {exc}", file=sys.stderr)
        us = []
    print(f"  미국 {len(us):,}종목")

    print("[2/3] 한국 상장법인목록 다운로드 (KRX KIND)...")
    try:
        kr = fetch_kr()
    except Exception as exc:
        print(f"  실패: {exc}", file=sys.stderr)
        kr = []
    print(f"  한국 {len(kr):,}종목")

    print("[3/3] 검증 및 저장...")
    if len(us) < MIN_US or len(kr) < MIN_KR:
        print(
            f"  검증 실패 (미국 {len(us)} < {MIN_US} 또는 한국 {len(kr)} < {MIN_KR}). "
            "기존 파일을 유지하고 종료합니다 — 불완전한 목록은 배포하지 않습니다.",
            file=sys.stderr,
        )
        return 1

    OUT.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": {
                    "us": "Nasdaq Trader Symbol Directory",
                    "kr": "KRX KIND 상장법인목록",
                },
                "us": us,
                "kr": kr,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"  저장 완료: {OUT} (한국 {len(kr):,} + 미국 {len(us):,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
