"""투자 성향 설문.

가입 직후(또는 마이페이지에서 재응답) 6문항 설문으로 안정형/위험중립형/공격형을
판정하고, 판정 결과는 추천 임계값 보정(stockrisk.strategy.PROFILE_SHIFTS)에 쓰인다.
"""
from __future__ import annotations

import json

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from webapp.auth import login_required
from webapp.db import get_db

bp = Blueprint("survey", __name__, url_prefix="/survey")

# (질문, [(보기, 점수), ...]) — 점수가 높을수록 공격적
QUESTIONS = [
    ("투자 경험이 얼마나 되시나요?", [
        ("처음이거나 1년 미만", 1),
        ("1~3년 (예적금·펀드 위주)", 2),
        ("3~10년 (주식 직접투자 경험)", 3),
        ("10년 이상 또는 파생상품 경험", 4),
    ]),
    ("투자금이 1개월 만에 20% 하락한다면 어떻게 하시겠습니까?", [
        ("전부 매도하고 당분간 투자를 쉰다", 1),
        ("일부를 매도해 손실을 줄인다", 2),
        ("그대로 보유하며 회복을 기다린다", 3),
        ("오히려 저가 매수 기회로 삼는다", 4),
    ]),
    ("주로 기대하는 연 수익률은 어느 정도인가요?", [
        ("예금 금리 수준 (~4%)이면 충분", 1),
        ("5~10% 정도의 안정적 수익", 2),
        ("10~20%, 어느 정도 변동은 감수", 3),
        ("20% 이상, 큰 변동도 감수", 4),
    ]),
    ("전체 자산 중 주식 등 위험자산 비중은?", [
        ("10% 미만", 1),
        ("10~30%", 2),
        ("30~60%", 3),
        ("60% 이상", 4),
    ]),
    ("투자 자금은 언제까지 사용할 계획이 없는 돈인가요?", [
        ("1년 이내 사용 예정", 1),
        ("1~3년", 2),
        ("3~7년", 3),
        ("7년 이상 여유 자금", 4),
    ]),
    ("악재 뉴스가 나오면 보통 어떻게 반응하시나요?", [
        ("불안해서 바로 매도부터 생각한다", 1),
        ("일단 지켜보지만 스트레스를 받는다", 2),
        ("사실 관계를 확인한 뒤 판단한다", 3),
        ("과잉반응한 시장의 기회를 찾는다", 4),
    ]),
]

# 총점 6~24 → 3단계 성향
def classify(score: int) -> tuple[str, str]:
    if score <= 11:
        return "conservative", "안정형"
    if score <= 17:
        return "balanced", "위험중립형"
    return "aggressive", "공격형"


RISK_TYPE_LABELS = {"conservative": "안정형", "balanced": "위험중립형", "aggressive": "공격형"}

RISK_TYPE_DESC = {
    "conservative": "원금 보전을 중시하는 성향입니다. 추천 엔진이 매수 판정에 더 엄격한 기준을, 위험 축소 판정에 더 민감한 기준을 적용합니다.",
    "balanced": "위험과 수익의 균형을 추구하는 성향입니다. 추천 엔진이 표준 임계값을 적용합니다.",
    "aggressive": "높은 수익을 위해 변동성을 감수하는 성향입니다. 추천 엔진이 매수 판정에 더 완화된 기준을 적용합니다.",
}


@bp.route("/", methods=("GET", "POST"))
@login_required
def survey():
    if request.method == "POST":
        answers = []
        total = 0
        for idx, (_q, options) in enumerate(QUESTIONS):
            raw = request.form.get(f"q{idx}")
            if raw is None or not raw.isdigit() or not (0 <= int(raw) < len(options)):
                flash("모든 문항에 응답해 주세요.")
                return render_template("survey.html", questions=QUESTIONS)
            choice = int(raw)
            answers.append(choice)
            total += options[choice][1]
        risk_type, label = classify(total)
        db = get_db()
        db.execute(
            """INSERT INTO risk_profiles (user_id, risk_type, score, answers_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                 risk_type=excluded.risk_type, score=excluded.score,
                 answers_json=excluded.answers_json, updated_at=excluded.updated_at""",
            (g.user["id"], risk_type, total, json.dumps(answers)),
        )
        db.commit()
        flash(f"투자 성향 진단 완료: {label}")
        return redirect(url_for("main.dashboard"))
    return render_template("survey.html", questions=QUESTIONS)


def get_profile(user_id: int):
    return get_db().execute(
        "SELECT * FROM risk_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
