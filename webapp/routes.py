"""메인 라우트: 홈, 대시보드, 종목 분석, 포트폴리오 관리, 분석 이력."""
from __future__ import annotations

from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template,
    request, url_for,
)

from stockrisk.models import Holding, Market
from webapp.analysis_service import (
    holding_from_input, run_analysis, search_registry, ticker_registry,
)
from webapp.auth import login_required
from webapp.db import get_db
from webapp.survey import RISK_TYPE_DESC, RISK_TYPE_LABELS, get_profile

bp = Blueprint("main", __name__)


def _user_risk_profile() -> str:
    if g.user is None:
        return "balanced"
    row = get_profile(g.user["id"])
    return row["risk_type"] if row else "balanced"


def _user_holdings() -> list[Holding]:
    rows = get_db().execute(
        "SELECT * FROM holdings WHERE user_id = ? ORDER BY added_at", (g.user["id"],)
    ).fetchall()
    return [
        Holding(
            ticker=r["ticker"], name=r["name"], market=Market(r["market"]),
            quantity=r["quantity"], avg_price=r["avg_price"], sector=r["sector"],
        )
        for r in rows
    ]


def _save_analysis(kind: str, target: str, result) -> int:
    db = get_db()
    cur = db.execute(
        """INSERT INTO analyses (user_id, kind, target, news_count, issue_count, offline, report_md)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (g.user["id"], kind, target, result.news_count, len(result.issues),
         1 if result.offline else 0, result.report_md),
    )
    db.commit()
    return cur.lastrowid


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    profile = get_profile(g.user["id"])
    holdings = get_db().execute(
        "SELECT * FROM holdings WHERE user_id = ? ORDER BY added_at", (g.user["id"],)
    ).fetchall()
    recent = get_db().execute(
        "SELECT id, kind, target, news_count, issue_count, offline, created_at "
        "FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 8",
        (g.user["id"],),
    ).fetchall()
    return render_template(
        "dashboard.html",
        profile=profile,
        risk_labels=RISK_TYPE_LABELS,
        risk_desc=RISK_TYPE_DESC,
        holdings=holdings,
        recent=recent,
    )


# ── 종목 검색 API (자동완성) ─────────────────────────────────────

@bp.route("/api/search")
def api_search():
    return jsonify(search_registry(request.args.get("q", "")))


# ── 단일 종목 분석 ───────────────────────────────────────────────

@bp.route("/analyze", methods=("GET", "POST"))
@login_required
def analyze():
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        market = request.form.get("market") or None
        name = request.form.get("name") or None
        if not query:
            flash("종목명 또는 티커를 입력해 주세요.")
            return render_template("analyze.html", registry=ticker_registry())
        holding = holding_from_input(query, market=market, name=name)
        if holding is None:
            # 레지스트리에 없는 종목: 시장을 지정해 재시도하도록 안내
            return render_template(
                "analyze.html", registry=ticker_registry(),
                unresolved=query,
            )
        result = run_analysis(
            [holding],
            risk_profile=_user_risk_profile(),
            fetch_prices=not current_app.config.get("TESTING", False),
        )
        analysis_id = _save_analysis("single", holding.ticker, result)
        return render_template(
            "report.html",
            result=result,
            analysis_id=analysis_id,
            title=f"{holding.name} ({holding.ticker}) 분석 리포트",
        )
    return render_template("analyze.html", registry=ticker_registry())


# ── 포트폴리오 전체 분석 ─────────────────────────────────────────

@bp.route("/analyze/portfolio", methods=("POST",))
@login_required
def analyze_portfolio():
    holdings = _user_holdings()
    if not holdings:
        flash("먼저 포트폴리오에 종목을 추가해 주세요.")
        return redirect(url_for("main.portfolio"))
    result = run_analysis(
        holdings,
        risk_profile=_user_risk_profile(),
        fetch_prices=not current_app.config.get("TESTING", False),
    )
    analysis_id = _save_analysis("portfolio", "portfolio", result)
    return render_template(
        "report.html", result=result, analysis_id=analysis_id,
        title="내 포트폴리오 종합 리포트",
    )


# ── 포트폴리오 관리 ──────────────────────────────────────────────

@bp.route("/portfolio", methods=("GET", "POST"))
@login_required
def portfolio():
    db = get_db()
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        market = request.form.get("market") or None
        name = request.form.get("name") or None
        holding = holding_from_input(query, market=market, name=name) if query else None
        if holding is None:
            flash("종목을 찾지 못했습니다. 목록에서 선택하거나 시장(KR/US)과 이름을 함께 입력해 주세요.")
        else:
            try:
                quantity = float(request.form.get("quantity") or 0)
                avg_price = float(request.form.get("avg_price") or 0)
            except ValueError:
                quantity, avg_price = 0.0, 0.0
            db.execute(
                """INSERT INTO holdings (user_id, ticker, name, market, quantity, avg_price, sector)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, ticker) DO UPDATE SET
                     quantity=excluded.quantity, avg_price=excluded.avg_price""",
                (g.user["id"], holding.ticker, holding.name, holding.market.value,
                 quantity, avg_price, holding.sector),
            )
            db.commit()
            flash(f"{holding.name} 종목을 저장했습니다.")
        return redirect(url_for("main.portfolio"))
    rows = db.execute(
        "SELECT * FROM holdings WHERE user_id = ? ORDER BY added_at", (g.user["id"],)
    ).fetchall()
    return render_template("portfolio.html", holdings=rows, registry=ticker_registry())


@bp.route("/portfolio/delete/<int:holding_id>", methods=("POST",))
@login_required
def portfolio_delete(holding_id: int):
    db = get_db()
    db.execute("DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, g.user["id"]))
    db.commit()
    return redirect(url_for("main.portfolio"))


# ── 분석 이력 ────────────────────────────────────────────────────

@bp.route("/history")
@login_required
def history():
    rows = get_db().execute(
        "SELECT id, kind, target, news_count, issue_count, offline, created_at "
        "FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (g.user["id"],),
    ).fetchall()
    return render_template("history.html", analyses=rows)


@bp.route("/history/<int:analysis_id>")
@login_required
def history_detail(analysis_id: int):
    row = get_db().execute(
        "SELECT * FROM analyses WHERE id = ? AND user_id = ?",
        (analysis_id, g.user["id"]),
    ).fetchone()
    if row is None:
        flash("분석 이력을 찾을 수 없습니다.")
        return redirect(url_for("main.history"))
    return render_template("history_detail.html", analysis=row)


@bp.route("/about")
def about():
    return render_template("about.html")
