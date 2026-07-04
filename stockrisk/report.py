"""마크다운 리포트 생성기."""
from __future__ import annotations

from datetime import datetime

from stockrisk.models import (
    ClassifiedIssue,
    HoldingImpact,
    Horizon,
    IssueAxis,
    Portfolio,
    Recommendation,
)

DISCLAIMER = (
    "> ⚠️ 본 리포트는 뉴스 기반 규칙 분석의 참고 자료이며 투자 권유가 아닙니다. "
    "모든 투자 판단과 책임은 투자자 본인에게 있습니다."
)


def _bar(score: float, width: int = 10) -> str:
    """-1~+1 점수를 텍스트 게이지로 표현."""
    filled = round(abs(score) * width)
    sign = "🟢" if score > 0 else ("🔴" if score < 0 else "⚪")
    return f"{sign} {'█' * filled}{'░' * (width - filled)} {score:+.2f}"


def build_report(
    portfolio: Portfolio,
    issues: list[ClassifiedIssue],
    impacts: list[HoldingImpact],
    recommendations: dict[str, list[Recommendation]],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append(f"# 📊 이슈 기반 포트폴리오 리스크 리포트")
    lines.append("")
    lines.append(f"- 생성 시각: {now}")
    lines.append(f"- 대상: {portfolio.owner} / 보유 종목 {len(portfolio.holdings)}개 (미국·한국 증시)")
    lines.append(f"- 분석 뉴스: {len({i.news.link or i.news.title for i in issues})}건, 감지 이슈: {len(issues)}건")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")

    # ── 1. 5대 축 요약 ────────────────────────────────────────────
    lines.append("## 1. 5대 이슈 축 요약")
    lines.append("")
    lines.append("| 이슈 축 | 감지 건수 | 평균 방향성 | 대표 뉴스 |")
    lines.append("|---|---|---|---|")
    for axis in IssueAxis:
        axis_issues = [i for i in issues if i.axis == axis]
        if axis_issues:
            avg = sum(i.sentiment * i.severity for i in axis_issues) / len(axis_issues)
            top = max(axis_issues, key=lambda i: i.severity)
            title = top.news.title[:60]
            lines.append(
                f"| {axis.label_ko} | {len(axis_issues)} | {avg:+.2f} | {title} |"
            )
        else:
            lines.append(f"| {axis.label_ko} | 0 | — | — |")
    lines.append("")

    # ── 2. 종목별 분석 ────────────────────────────────────────────
    lines.append("## 2. 종목별 영향 분석 및 추천")
    lines.append("")
    for impact in impacts:
        h = impact.holding
        lines.append(f"### {h.name} ({h.ticker}, {h.market.value})")
        lines.append("")
        if h.quantity:
            lines.append(f"- 보유: {h.quantity:g}주 @ {h.avg_price:,.2f}")
        lines.append("")
        lines.append("**축별 영향 점수**")
        lines.append("")
        for axis in IssueAxis:
            score = impact.axis_scores.get(axis, 0.0)
            lines.append(f"- {axis.label_ko}: {_bar(score)}")
        lines.append("")

        if impact.related_notes:
            lines.append("**주요 근거 뉴스**")
            lines.append("")
            for note in impact.related_notes:
                lines.append(f"- {note}")
            lines.append("")

        lines.append("**기간별 추천**")
        lines.append("")
        lines.append("| 기간 | 점수 | 추천 | 근거 |")
        lines.append("|---|---|---|---|")
        for rec in recommendations.get(h.ticker, []):
            lines.append(
                f"| {rec.horizon.label_ko} | {rec.score:+.2f} | **{rec.action.label_ko}** | {rec.rationale} |"
            )
        lines.append("")

        for rec in recommendations.get(h.ticker, []):
            tactics = rec.risk_management + rec.profit_strategy
            if tactics:
                kind = "리스크 관리" if rec.risk_management else "수익 극대화"
                lines.append(f"<details><summary>{rec.horizon.label_ko} — {kind} 전술</summary>")
                lines.append("")
                for t in tactics:
                    lines.append(f"- {t}")
                lines.append("")
                lines.append("</details>")
                lines.append("")

    # ── 3. 포트폴리오 총평 ────────────────────────────────────────
    lines.append("## 3. 포트폴리오 총평")
    lines.append("")
    for horizon in Horizon:
        scores = [imp.horizon_scores.get(horizon, 0.0) for imp in impacts]
        avg = sum(scores) / len(scores) if scores else 0.0
        stance = "위험 관리 우선" if avg < -0.1 else ("기회 활용 국면" if avg > 0.1 else "중립 유지")
        lines.append(f"- **{horizon.label_ko}**: 평균 점수 {avg:+.2f} → {stance}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
