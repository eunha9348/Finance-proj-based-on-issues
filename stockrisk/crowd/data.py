"""실측 시장 데이터 로더.

두 개의 공개·무료 데이터셋을 사용한다 (API 키 불필요, 둘 다 저장소에 스냅샷으로
커밋되어 있어 네트워크 없이도 동작):

- ``data/market/vix_daily.csv``: CBOE VIX 일별 종가 (1990-01-02~).
  출처: https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv
- ``data/market/sp500_monthly.csv``: Robert Shiller 교수의 S&P500 월별 명목가격·
  배당·CAPE(PE10) 데이터 (1871-01~).
  출처: https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv

두 파일 모두 실제 공개 데이터의 스냅샷이며, 임의로 생성·추정한 값이 아니다.
최신 몇 개월 구간은 원 데이터 자체의 보고 지연으로 배당·CAPE가 0.0(결측)으로
찍혀 있을 수 있어, 이 모듈에서 마지막 실측값을 이월(carry-forward)한다.
"""
from __future__ import annotations

import csv
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VIX_URL = "https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv"
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
USER_AGENT = "Mozilla/5.0 (compatible; StockRiskBot/0.2)"

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "market"


@dataclass
class MonthlyRecord:
    """한 달치 정합된 시장 데이터 (모두 실측값 또는 실측값 이월)."""

    month: str                  # "YYYY-MM"
    sp500: float                 # S&P500 월말 명목가격
    dividend_annual: float       # 연환산 배당(이월 포함)
    long_rate_pct: float         # 미 장기금리 연율 %(이월 포함, 현금성 자산 대용)
    cape: float | None           # CAPE(PE10). 산출 불가/결측 구간은 None
    vix_avg: float                # 해당 월 VIX 일평균
    vix_end: float                # 해당 월 마지막 VIX 종가


def _download(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def refresh_snapshots(data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
    """원 출처에서 최신 데이터를 받아 로컬 스냅샷을 갱신한다.

    네트워크가 없는 환경(샌드박스 등)에서는 실패하며, 그 경우 커밋된 스냅샷을
    그대로 사용하면 된다 — 값을 추정하거나 지어내지 않는다.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "vix_daily.csv").write_text(_download(VIX_URL), encoding="utf-8")
    (data_dir / "sp500_monthly.csv").write_text(_download(SP500_URL), encoding="utf-8")


def _load_vix_monthly(path: Path) -> dict[str, tuple[float, float]]:
    """일별 VIX 종가를 월별 (평균, 월말값)으로 집계."""
    by_month: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date = row["DATE"]
            close = row.get("CLOSE", "").strip()
            if not date or not close:
                continue
            try:
                close_v = float(close)
            except ValueError:
                continue
            month = date[:7]
            by_month.setdefault(month, []).append(close_v)
    out: dict[str, tuple[float, float]] = {}
    for month, closes in by_month.items():
        out[month] = (sum(closes) / len(closes), closes[-1])
    return out


def load_monthly_records(data_dir: Path | str = DEFAULT_DATA_DIR) -> list[MonthlyRecord]:
    """두 스냅샷을 합쳐 VIX 데이터가 존재하는 구간(1990-01~)의 월별 레코드를 만든다."""
    data_dir = Path(data_dir)
    vix_by_month = _load_vix_monthly(data_dir / "vix_daily.csv")

    records: list[MonthlyRecord] = []
    last_dividend = 0.0
    last_rate = 0.0
    with (data_dir / "sp500_monthly.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            month = row["Date"][:7]
            if month not in vix_by_month:
                continue
            sp500 = float(row["SP500"])
            dividend = float(row["Dividend"])
            rate = float(row["Long Interest Rate"])
            pe10_raw = float(row["PE10"])

            # 0.0은 실측 0이 아니라 '보고 지연으로 아직 갱신 안 됨'을 뜻하므로 이월
            if dividend > 0:
                last_dividend = dividend
            if rate > 0:
                last_rate = rate
            cape = pe10_raw if pe10_raw > 0 else None

            vix_avg, vix_end = vix_by_month[month]
            records.append(
                MonthlyRecord(
                    month=month,
                    sp500=sp500,
                    dividend_annual=last_dividend,
                    long_rate_pct=last_rate,
                    cape=cape,
                    vix_avg=vix_avg,
                    vix_end=vix_end,
                )
            )
    records.sort(key=lambda r: r.month)
    return records
