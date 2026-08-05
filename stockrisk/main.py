"""CLI 진입점.

사용법:
    # 실시간 뉴스 수집 + 분석
    python -m stockrisk analyze --portfolio portfolio.json

    # 오프라인 샘플 뉴스로 분석 (네트워크 불필요)
    python -m stockrisk analyze --portfolio portfolio.example.json \
        --news-file samples/sample_news.json --output report.md

    # 주기적 모니터링 (기본 30분 간격)
    python -m stockrisk monitor --portfolio portfolio.json --interval 1800
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from stockrisk.analysis.classifier import IssueClassifier
from stockrisk.analysis.impact import ImpactAnalyzer
from stockrisk.crowd.backtest import run_backtest
from stockrisk.crowd.data import load_monthly_records, refresh_snapshots
from stockrisk.crowd.index import compute_crowd_index
from stockrisk.crowd.report import build_crowd_report
from stockrisk.models import Holding, Market, Portfolio
from stockrisk.news.collector import NewsCollector, load_news_from_file
from stockrisk.report import build_report
from stockrisk.strategy.recommender import StrategyRecommender


def load_portfolio(path: str | Path) -> Portfolio:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    holdings = [
        Holding(
            ticker=h["ticker"],
            name=h["name"],
            market=Market(h["market"]),
            quantity=h.get("quantity", 0),
            avg_price=h.get("avg_price", 0),
            sector=h.get("sector", ""),
        )
        for h in data["holdings"]
    ]
    return Portfolio(owner=data.get("owner", "user"), holdings=holdings)


def run_analysis(args: argparse.Namespace) -> str:
    portfolio = load_portfolio(args.portfolio)

    if args.news_file:
        news = load_news_from_file(args.news_file)
        print(f"[뉴스] 오프라인 파일에서 {len(news)}건 로드", file=sys.stderr)
    else:
        collector = NewsCollector(per_query_limit=args.per_query_limit)
        news = collector.collect(portfolio)
        print(f"[뉴스] 실시간 수집 {len(news)}건", file=sys.stderr)
        if not news:
            print(
                "[경고] 뉴스를 수집하지 못했습니다. 네트워크 상태를 확인하거나 "
                "--news-file 로 오프라인 뉴스를 지정하세요.",
                file=sys.stderr,
            )

    classifier = IssueClassifier()
    issues = classifier.classify_all(news, portfolio)
    print(f"[분류] 5대 축 이슈 {len(issues)}건 감지", file=sys.stderr)

    analyzer = ImpactAnalyzer()
    impacts = analyzer.analyze(portfolio, issues)

    recommender = StrategyRecommender()
    recommendations = recommender.recommend_all(impacts)

    report = build_report(portfolio, issues, impacts, recommendations)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[완료] 리포트 저장: {args.output}", file=sys.stderr)
    else:
        print(report)
    return report


def run_crowd_backtest(args: argparse.Namespace) -> str:
    if args.refresh:
        print("[군중심리] 원 출처에서 최신 데이터 다운로드 중...", file=sys.stderr)
        refresh_snapshots()

    records = load_monthly_records()
    index_points = compute_crowd_index(records)
    backtest = run_backtest(records, index_points)
    report = build_crowd_report(records, index_points, backtest)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[완료] 리포트 저장: {args.output}", file=sys.stderr)
    else:
        print(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stockrisk",
        description="5대 이슈 축 기반 포트폴리오 리스크 분석·추천 시스템 (미국·한국 증시)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="뉴스 수집 후 1회 분석 리포트 생성")
    p_analyze.add_argument("--portfolio", required=True, help="포트폴리오 JSON 파일 경로")
    p_analyze.add_argument("--news-file", help="오프라인 뉴스 JSON 파일 (지정 시 수집 생략)")
    p_analyze.add_argument("--output", help="리포트 저장 경로 (미지정 시 표준 출력)")
    p_analyze.add_argument("--per-query-limit", type=int, default=10, help="질의당 뉴스 수집 상한")

    p_monitor = sub.add_parser("monitor", help="주기적으로 분석을 반복 실행")
    p_monitor.add_argument("--portfolio", required=True)
    p_monitor.add_argument("--interval", type=int, default=1800, help="반복 간격(초), 기본 30분")
    p_monitor.add_argument("--output", default="report.md", help="매 회차 리포트 저장 경로")
    p_monitor.add_argument("--per-query-limit", type=int, default=10)
    p_monitor.add_argument("--news-file", default=None, help=argparse.SUPPRESS)

    p_crowd = sub.add_parser(
        "crowd-backtest", help="군중심리지수 산출 + S&P500 매수·보유 대비 백테스트 리포트 생성"
    )
    p_crowd.add_argument("--output", help="리포트 저장 경로 (미지정 시 표준 출력)")
    p_crowd.add_argument(
        "--refresh", action="store_true", help="data/market/ 스냅샷을 원 출처에서 갱신 후 실행"
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        run_analysis(args)
        return 0

    if args.command == "crowd-backtest":
        run_crowd_backtest(args)
        return 0

    if args.command == "monitor":
        print(f"[모니터] {args.interval}초 간격으로 분석을 반복합니다. Ctrl+C로 종료.", file=sys.stderr)
        while True:
            try:
                run_analysis(args)
            except Exception as exc:  # 모니터링 루프는 개별 실패에도 계속 돈다
                print(f"[오류] 분석 실패: {exc}", file=sys.stderr)
            time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
