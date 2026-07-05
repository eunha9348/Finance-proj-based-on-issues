"""회원가입 · 로그인 · 소셜 연동(OAuth2).

- 이메일 가입: PBKDF2 해시(werkzeug) 저장
- 소셜 로그인: Google / Kakao / Naver OAuth2 인가 코드 방식.
  환경변수(<PROVIDER>_CLIENT_ID / _CLIENT_SECRET)가 설정된 제공자만 활성화되며,
  미설정 시 버튼에 '설정 필요' 안내가 뜬다.
"""
from __future__ import annotations

import functools
import json
import os
import re
import secrets
import urllib.parse
import urllib.request

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from webapp.db import get_db

bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 소셜 제공자 OAuth2 엔드포인트 정의
OAUTH_PROVIDERS = {
    "google": {
        "label": "Google",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "email_key": "email",
        "name_key": "name",
        "id_key": "sub",
    },
    "kakao": {
        "label": "카카오",
        "auth_url": "https://kauth.kakao.com/oauth/authorize",
        "token_url": "https://kauth.kakao.com/oauth/token",
        "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        "scope": "account_email profile_nickname",
        "email_key": "kakao_account.email",
        "name_key": "kakao_account.profile.nickname",
        "id_key": "id",
    },
    "naver": {
        "label": "네이버",
        "auth_url": "https://nid.naver.com/oauth2.0/authorize",
        "token_url": "https://nid.naver.com/oauth2.0/token",
        "userinfo_url": "https://openapi.naver.com/v1/nid/me",
        "scope": "",
        "email_key": "response.email",
        "name_key": "response.name",
        "id_key": "response.id",
    },
}


def provider_config(name: str) -> dict | None:
    """환경변수에 키가 있으면 제공자 설정 반환, 없으면 None."""
    cid = os.environ.get(f"{name.upper()}_CLIENT_ID")
    secret = os.environ.get(f"{name.upper()}_CLIENT_SECRET")
    if not cid or not secret:
        return None
    return {**OAUTH_PROVIDERS[name], "client_id": cid, "client_secret": secret}


def enabled_providers() -> dict[str, bool]:
    return {name: provider_config(name) is not None for name in OAUTH_PROVIDERS}


# ── 세션 훅 ──────────────────────────────────────────────────────

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def _login_user(user_row):
    session.clear()
    session["user_id"] = user_row["id"]


def _has_profile(user_id: int) -> bool:
    return get_db().execute(
        "SELECT 1 FROM risk_profiles WHERE user_id = ?", (user_id,)
    ).fetchone() is not None


def _after_login_redirect(user_id: int):
    """첫 로그인(설문 미완료)이면 투자 성향 설문으로 보낸다."""
    if not _has_profile(user_id):
        return redirect(url_for("survey.survey"))
    return redirect(url_for("main.dashboard"))


# ── 이메일 가입/로그인 ────────────────────────────────────────────

@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        error = None
        if not EMAIL_RE.match(email):
            error = "올바른 이메일 주소를 입력해 주세요."
        elif not name:
            error = "이름(닉네임)을 입력해 주세요."
        elif len(password) < 8:
            error = "비밀번호는 8자 이상이어야 합니다."
        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (email, name, password_hash, provider) VALUES (?, ?, ?, 'local')",
                    (email, name, generate_password_hash(password)),
                )
                db.commit()
            except Exception:
                error = "이미 가입된 이메일입니다."
            else:
                _login_user(db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())
                flash("가입을 환영합니다! 먼저 투자 성향을 알려주세요.")
                return redirect(url_for("survey.survey"))
        flash(error)
    return render_template("auth/register.html", providers=enabled_providers())


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or user["password_hash"] is None or not check_password_hash(user["password_hash"], password):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.")
        else:
            _login_user(user)
            return _after_login_redirect(user["id"])
    return render_template("auth/login.html", providers=enabled_providers())


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.index"))


# ── 소셜 로그인 ──────────────────────────────────────────────────

@bp.route("/social/<provider>")
def social_start(provider: str):
    if provider not in OAUTH_PROVIDERS:
        flash("지원하지 않는 로그인 방식입니다.")
        return redirect(url_for("auth.login"))
    cfg = provider_config(provider)
    if cfg is None:
        flash(
            f"{OAUTH_PROVIDERS[provider]['label']} 로그인은 아직 설정되지 않았습니다. "
            f"관리자가 {provider.upper()}_CLIENT_ID / {provider.upper()}_CLIENT_SECRET "
            "환경변수를 설정하면 활성화됩니다."
        )
        return redirect(url_for("auth.login"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    session["oauth_provider"] = provider
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": url_for("auth.social_callback", _external=True),
        "response_type": "code",
        "state": state,
    }
    if cfg["scope"]:
        params["scope"] = cfg["scope"]
    return redirect(f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}")


@bp.route("/social/callback")
def social_callback():
    provider = session.get("oauth_provider")
    state = session.get("oauth_state")
    if not provider or request.args.get("state") != state:
        flash("로그인 상태 검증에 실패했습니다. 다시 시도해 주세요.")
        return redirect(url_for("auth.login"))
    cfg = provider_config(provider)
    code = request.args.get("code")
    if cfg is None or not code:
        flash("소셜 로그인에 실패했습니다.")
        return redirect(url_for("auth.login"))
    try:
        token = _post_form(cfg["token_url"], {
            "grant_type": "authorization_code",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": url_for("auth.social_callback", _external=True),
            "code": code,
        })
        userinfo = _get_json(cfg["userinfo_url"], token["access_token"])
    except Exception:
        flash("소셜 제공자와 통신에 실패했습니다. 잠시 후 다시 시도해 주세요.")
        return redirect(url_for("auth.login"))

    email = _dig(userinfo, cfg["email_key"])
    name = _dig(userinfo, cfg["name_key"]) or (email.split("@")[0] if email else provider)
    pid = str(_dig(userinfo, cfg["id_key"]))
    if not email:
        flash("소셜 계정에서 이메일을 가져올 수 없습니다. 이메일 제공에 동의해 주세요.")
        return redirect(url_for("auth.login"))

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE provider = ? AND provider_id = ?", (provider, pid)
    ).fetchone() or db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        cur = db.execute(
            "INSERT INTO users (email, name, provider, provider_id) VALUES (?, ?, ?, ?)",
            (email.lower(), name, provider, pid),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    _login_user(user)
    return _after_login_redirect(user["id"])


# ── HTTP 헬퍼 ────────────────────────────────────────────────────

def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_json(url: str, bearer: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _dig(data: dict, dotted: str):
    cur = data
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur
