# -*- coding: utf-8 -*-
"""Application Flask — Suivi des congés 2027.

API JSON + service du frontend SPA (frontend/public/, développement seulement).
"""
import datetime as dt
import json
import os
import re
import unicodedata
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import (
    SQL_DAYS_SINCE_SUBMIT, SQL_NOW_MINUS, get_db, init_db, public_user, row_to_dict,
    set_setting,
)
from mailer import notify_validator
from reminders import start_reminder_scheduler
from rules import add_months
from rules import agent_summary
from rules import ca_prev_code
from rules import ca_prev_code
from rules import compute as rule_compute
from rules import matrix_rows

import act_as
import apm
import audit_logs
import config
import ratelimit
from config import BASE_DIR, SECRET_FILE, UPLOAD_DIR
MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif",
    ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods", ".txt",
}

app = Flask(__name__, static_folder=config.FRONTEND_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

# Paramètres par défaut (avant tout import Excel)
DEFAULT_SETTINGS = {
    "general": {"year": 2027, "year_start": "2027-01-01", "year_end": "2027-12-31"},
    "codes": [], "penibilites": [], "penibilites_durees": {}, "durees": [],
    "quotites": [], "jours_hebdo": [], "temps_travail": [], "durees_rtt": [],
    "matrix": [], "jours_feries": [], "vacances_scolaires": [],
}


def load_settings() -> dict:
    """Charge tous les paramètres depuis la base (avec repli sur les défauts)."""
    db = get_db()
    rows = db.execute("SELECT cle, valeur FROM settings").fetchall()
    db.close()
    out = dict(DEFAULT_SETTINGS)
    for r in rows:
        try:
            out[r["cle"]] = json.loads(r["valeur"])
        except (ValueError, TypeError):
            out[r["cle"]] = r["valeur"]
    return out


def json_loads(value):
    return json.loads(value)


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False)


def cells_to_list(cells: dict) -> list:
    """{'1050': 'CA'} -> [{'month': 1, 'code': 'CA'}] (une entrée par demi-journée)."""
    out = []
    for key, code in (cells or {}).items():
        if not code:
            continue
        try:
            k = int(key)
        except (TypeError, ValueError):
            continue
        out.append({
            "month": k // 1000,
            "day": (k % 1000) // 10,
            "half": k % 10,
            "key": k,
            "code": code,
        })
    return out


def _secret_key():
    if config.SECRET_KEY:
        return config.SECRET_KEY.encode("utf-8")
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as fh:
            return fh.read()
    key = os.urandom(32)
    try:
        with open(SECRET_KEY_FILE := SECRET_FILE, "wb") as fh:
            fh.write(key)
    except OSError as exc:
        raise RuntimeError(
            "Impossible d'écrire %s : définir CONGES_SECRET_KEY dans l'environnement (.env)" % SECRET_FILE
        ) from exc
    try:
        os.chmod(SECRET_KEY_FILE, 0o600)
    except OSError:
        pass
    return key


app.secret_key = _secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=config.SESSION_HOURS),
)


if config.PROXY_HOPS:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=config.PROXY_HOPS, x_proto=config.PROXY_HOPS)


@app.after_request
def _cors(resp):
    """CORS limité aux origines listées dans CONGES_CORS_ORIGINS (aucune par défaut)."""
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin in config.CORS_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Vary"] = "Origin"
    return resp


@app.after_request
def _no_cache_assets(resp):
    """Empêche le navigateur de servir une ancienne version du JS/CSS/HTML.

    Indispensable pour que les correctifs soient pris en compte sans avoir à
    demander à l'utilisateur un rechargement forcé (Ctrl+F5).
    """
    path = request.path or ""
    if path == "/" or path.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# --------------------------------------------------------------------------- #
#  Session / authentification
# --------------------------------------------------------------------------- #
def current_user():
    # L'identité provient uniquement de la session signée côté serveur :
    # aucun en-tête ni cookie fourni par le client n'est cru sur parole.
    uid = session.get("uid")
    if not uid:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND actif=1", (int(uid),)).fetchone()
    real = None
    if session.get("real_uid"):
        # « Se connecter en tant que » : l'identité réelle doit rester un administrateur actif.
        real = db.execute(
            "SELECT * FROM users WHERE id=? AND actif=1 AND admin=1", (int(session["real_uid"]),)
        ).fetchone()
    db.close()
    if session.get("real_uid") and not real:
        session.clear()
        return None
    request.real_user = row_to_dict(real) if real else None
    return row_to_dict(user) if user else None


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Authentification requise"}), 401
        request.user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Authentification requise"}), 401
        if not user["admin"]:
            return jsonify({"error": "Accès réservé à l'administrateur"}), 403
        request.user = user
        return fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
#  Rôles et périmètre de visibilité
# --------------------------------------------------------------------------- #
ROLE_LEVELS = {
    "administrateur": 8,
    "dgs": 7,
    "dga": 6,
    "direction": 5,
    "service": 4,
    "secteur": 3,
    "unite": 2,
    "equipe": 1,
    "agent": 0,
}
ROLE_LABELS = {
    "administrateur": "Administrateur",
    "dgs": "Valideur DGS",
    "dga": "Valideur DGA",
    "direction": "Valideur Direction",
    "service": "Valideur Service",
    "secteur": "Valideur Secteur",
    "unite": "Valideur Unité",
    "equipe": "Valideur Équipe",
    "agent": "Agent",
}
# Rôles autorisés pour le responsable direct de chaque niveau.
# Les niveaux existants conservent leurs possibilités de rattachement ;
# la chaîne DGS > DGA > Direction > Service > Secteur > Unité > Équipe > Agent
# est prise en charge, avec possibilité de sauter un niveau intermédiaire.
PARENT_ROLES = {
    "dgs": ("administrateur",),
    "dga": ("dgs",),
    "direction": ("dga", "dgs", "administrateur"),
    "service": ("direction",),
    "secteur": ("service", "direction"),
    "unite": ("secteur", "service"),
    "equipe": ("unite", "secteur"),
    "agent": ("administrateur", "dgs", "dga", "direction", "service",
              "secteur", "unite", "equipe"),
}
VALIDATOR_ROLES = ("administrateur", "dgs", "dga", "direction", "service",
                   "secteur", "unite", "equipe")
# Codes retenus pour le taux d'absence du tableau de bord RH.
# RC a été retiré ; TT (télétravail) n'est pas une absence.
ABSENCE_CODES = (
    "AI", "AS", "CA", "CA26", "CAH", "CET", "CM", "CP", "CT", "ET",
    "GEM", "GR", "JB", "JS", "MD", "RTT", "RTTH", "SF", "SX", "TP", "RCH",
)


def _user_role(user):
    role = (user or {}).get("role")
    if role in ROLE_LEVELS:
        return role
    return "administrateur" if (user or {}).get("admin") else "secteur"


def _subtree_ids(db, root_id):
    """Identifiants de l'utilisateur et de tous ses descendants (parent_id)."""
    rows = db.execute("SELECT id, parent_id FROM users").fetchall()
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])
    out, seen, stack = [], set(), [root_id]
    while stack:
        uid = stack.pop()
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
        stack.extend(children.get(uid, []))
    return out


def _org_ancestor_name(db, user_id, role):
    """Nom du premier ancêtre (ou de l'utilisateur) ayant le rôle demandé."""
    seen = set()
    uid = user_id
    while uid and uid not in seen:
        seen.add(uid)
        row = db.execute(
            "SELECT id, login, nom, role, parent_id FROM users WHERE id=?", (uid,)
        ).fetchone()
        if not row:
            break
        if _user_role(row_to_dict(row)) == role:
            return row["nom"] or row["login"] or ""
        uid = row["parent_id"]
    return ""


def _scope_ids(db, user):
    """Utilisateurs visibles : tous pour l'admin, le sous-arbre sinon."""
    if user.get("admin") or _user_role(user) == "administrateur":
        return [r["id"] for r in db.execute("SELECT id FROM users").fetchall()]
    return _subtree_ids(db, user["id"])


def _scope_agents(db, user, year=None):
    if _user_role(user) == "agent":
        where = "a.agent_user_id=?"
        params = [user["id"]]
        if year is not None:
            where += " AND a.year=?"
            params.append(int(year))
        return db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE %s ORDER BY a.nom" % where,
            params,
        ).fetchall()
    ids = _scope_ids(db, user)
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    params = list(ids)
    where = "a.user_id IN (%s)" % marks
    if year is not None:
        where += " AND a.year=?"
        params.append(int(year))
    return db.execute(
        "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
        "WHERE %s ORDER BY u.login, a.nom" % where,
        params,
    ).fetchall()


def _planning_scope_user(db, user):
    """Pour un agent : le service auquel il est rattaché, sinon son unité directe.

    Le planning d'un agent couvre son service, et non seulement son secteur.
    """
    if _user_role(user) != "agent":
        return user
    seen = set()
    uid = user.get("parent_id")
    first_parent = None
    while uid and uid not in seen:
        seen.add(uid)
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            break
        candidate = row_to_dict(row)
        if first_parent is None:
            first_parent = candidate
        if _user_role(candidate) == "service":
            return candidate
        uid = candidate.get("parent_id")
    if first_parent:
        return first_parent
    return user


def _request_year(default=None):
    raw = request.args.get("year")
    try:
        y = int(raw)
        if 2000 <= y <= 2100:
            return y
    except (TypeError, ValueError):
        pass
    if default is not None:
        return default
    return int(load_settings().get("general", {}).get("year", 2027))


def _settings_for_year(settings, year):
    import copy

    s = copy.deepcopy(settings)
    s.setdefault("general", {})
    y = int(year)
    s["general"]["year"] = y
    s["general"]["year_start"] = "%d-01-01" % y
    s["general"]["year_end"] = "%d-12-31" % y
    return s


def _agent_by_id(db, aid):
    return db.execute(
        "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id WHERE a.id=?",
        (aid,),
    ).fetchone()


def _can_view_agent(db, user, agent):
    if not agent:
        return False
    if user.get("admin"):
        return True
    if agent["agent_user_id"] == user["id"]:
        return True
    return agent["user_id"] in set(_scope_ids(db, user))


def _can_edit_agent(db, user, agent, scope_ids=None):
    """Un utilisateur peut modifier les fiches de son périmètre.

    Le périmètre est le sous-arbre dont il est la racine : ses propres fiches
    et celles de tous ses subordonnés (direction -> service -> secteur, ou
    secteur directement rattaché à une direction).
    """
    if not agent:
        return False
    if user.get("admin"):
        return True
    if _user_role(user) == "agent":
        return False
    if scope_ids is None:
        scope_ids = set(_scope_ids(db, user))
    return agent["user_id"] in scope_ids


def _can_create_fiche(user):
    return bool(user) and (user.get("admin") or _user_role(user) in VALIDATOR_ROLES)


def _can_manage_users(user):
    return bool(user) and (user.get("admin") or _user_role(user) in VALIDATOR_ROLES)


def _can_edit_cells(db, user, agent):
    """Saisie directe des absences : admin ou responsable, jamais le titulaire."""
    if not agent:
        return False
    if user.get("admin"):
        return True
    if _user_role(user) == "agent":
        return False
    if agent["agent_user_id"] == user["id"]:
        return False
    return agent["user_id"] in set(_scope_ids(db, user))


def _validator_chain(db, owner_id):
    """Compte proprietaire + valideurs hierarchiquement superieurs (actifs).

    Le premier element est le proprietaire de la fiche (le createur), puis
    remonte la chaine des responsables. Seuls les roles valideurs sont retenus.
    """
    out = []
    seen = set()
    uid = owner_id
    while uid and uid not in seen:
        seen.add(uid)
        row = db.execute(
            "SELECT id, login, nom, email, role, parent_id, actif FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        if not row:
            break
        user = row_to_dict(row)
        if user.get("actif") and _user_role(user) in VALIDATOR_ROLES:
            out.append(user)
        uid = user.get("parent_id")
    return out


def _validate_user_parent(db, role, parent_id, uid=None):
    """Vérifie la cohérence du responsable selon le rôle."""
    if role == "administrateur":
        return None if not parent_id else "Un administrateur ne peut pas avoir de responsable"
    if role == "agent" and parent_id in (None, "", 0):
        return "Un agent doit être rattaché à un valideur"
    if parent_id in (None, "", 0):
        return None
    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        return "Responsable invalide"
    if uid is not None and parent_id == uid:
        return "Un utilisateur ne peut pas être son propre responsable"
    parent = db.execute("SELECT * FROM users WHERE id=?", (parent_id,)).fetchone()
    if not parent:
        return "Responsable introuvable"
    # Un secteur peut être rattaché à un service ou directement à une direction.
    parent_role = _user_role(row_to_dict(parent))
    if parent_role not in PARENT_ROLES.get(role, ()):
        labels = " ou ".join(ROLE_LABELS[r] for r in PARENT_ROLES.get(role, ()))
        return "Le responsable doit être de niveau %s" % (labels or "supérieur")
    return None


def _reparent_children(db, deleted):
    """Rattache les subordonnés au premier ancêtre dont le rôle est valide."""
    ancestors, seen, pid = [], set(), deleted["parent_id"]
    while pid and pid not in seen:
        seen.add(pid)
        row = db.execute(
            "SELECT id, parent_id, role, admin FROM users WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            break
        ancestors.append(row)
        pid = row["parent_id"]
    children = db.execute(
        "SELECT id, role, admin FROM users WHERE parent_id=?", (deleted["id"],)
    ).fetchall()
    for child in children:
        child_role = _user_role(row_to_dict(child))
        allowed = PARENT_ROLES.get(child_role, ())
        new_parent = next(
            (a["id"] for a in ancestors if _user_role(row_to_dict(a)) in allowed),
            None,
        )
        db.execute("UPDATE users SET parent_id=? WHERE id=?", (new_parent, child["id"]))


def _check_credentials(user, password):
    """Vérifie le mot de passe selon CONGES_AUTH_MODE ; lève ApmError si l'AD est indisponible.

    Mode « ad » : l'Active Directory (via l'APM) valide le mot de passe. Les comptes
    administrateurs conservent leur mot de passe local, compte de secours si l'AD est en panne.
    """
    local_ok = check_password_hash(user["mot_de_passe"], password)
    if config.AUTH_MODE != "ad":
        return local_ok, "local"
    if user["admin"] and local_ok:
        return True, "secours"
    return apm.ad_authenticate((user["ad_login"] or user["login"]).strip(), password), "ad"


def _clean_matricule(value):
    """(matricule normalisé, erreur) : lettres, chiffres, . _ - ; 20 caractères au maximum."""
    value = (value or "").strip()
    if value and not re.fullmatch(r"[A-Za-z0-9._-]{1,20}", value):
        return value, "Matricule invalide (lettres, chiffres, . _ - ; 20 caractères au maximum)"
    return value, None


def _matricule_holder(db, matricule, exclude_user_id=None):
    """Identifiant du compte qui porte déjà ce matricule (autre que exclude_user_id), sinon None."""
    if not matricule:
        return None
    row = db.execute(
        "SELECT login FROM users WHERE matricule=? AND id<>?", (matricule, exclude_user_id or 0)
    ).fetchone()
    return row["login"] if row else None


def _password_managed_by_ad(user):
    return config.AUTH_MODE == "ad" and not user["admin"]


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    login_name = (data.get("login") or "").strip()
    password = data.get("password") or ""
    bucket = "login:" + (request.remote_addr or "?")
    if ratelimit.blocked(bucket, config.LOGIN_MAX_FAILURES, 900):
        audit_logs.log_login("echec", login_name, None, False, "limite")
        return jsonify({"error": "Trop de tentatives de connexion, réessayez dans quelques minutes"}), 429
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE login=?", (login_name,)).fetchone()
    db.close()
    if not user:
        ratelimit.record(bucket)
        audit_logs.log_login("echec", login_name, None, False, "inconnu")
        return jsonify({"error": "Identifiant/mot de passe incorrect"}), 401
    try:
        valid, method = _check_credentials(user, password)
    except apm.ApmError as exc:
        app.logger.error("Authentification AD indisponible : %s", exc)
        audit_logs.log_login("echec", login_name, user["id"], False, "service_ad", "ad")
        return jsonify({"error": "Service d'authentification indisponible, réessayez plus tard"}), 503
    if not valid:
        ratelimit.record(bucket)
        audit_logs.log_login("echec", login_name, user["id"], False, "mot_de_passe", method)
        return jsonify({"error": "Identifiant/mot de passe incorrect"}), 401
    if not user["actif"]:
        audit_logs.log_login("echec", login_name, user["id"], False, "desactive", method)
        return jsonify({"error": "Ce compte est désactivé"}), 403
    session.clear()
    session["uid"] = user["id"]
    session.permanent = True
    audit_logs.log_login("connexion", login_name, user["id"], True, "", method)
    out = public_user(user)
    out["password_by_ad"] = _password_managed_by_ad(user)
    out["auth_mode"] = config.AUTH_MODE
    return jsonify({"user": out})


@app.route("/api/me", methods=["GET"])
@login_required
def me():
    user = dict(request.user)
    user.pop("mot_de_passe", None)
    user["password_by_ad"] = _password_managed_by_ad(request.user)
    user["auth_mode"] = config.AUTH_MODE
    real = getattr(request, "real_user", None)
    if real:
        user["impersonation"] = {"by": {"id": real["id"], "login": real["login"], "nom": real["nom"]}}
    return jsonify({"user": user})


@app.route("/api/me/password", methods=["POST"])
@login_required
def me_password():
    if getattr(request, "real_user", None):
        return jsonify({"error": "Changement de mot de passe impossible en mode « se connecter en tant que »"}), 403
    if _password_managed_by_ad(request.user):
        return jsonify({"error": "Votre mot de passe est celui de votre compte Ville (Active Directory) : "
                                 "il se change depuis votre poste, pas dans cette application"}), 400
    data = request.get_json(force=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    confirm_password = data.get("confirm_password") or ""
    if not current_password or not new_password:
        return jsonify({"error": "Mot de passe actuel et nouveau mot de passe obligatoires"}), 400
    if new_password != confirm_password:
        return jsonify({"error": "Les deux nouveaux mots de passe ne correspondent pas"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "Le nouveau mot de passe doit contenir au moins 8 caractères"}), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (request.user["id"],)).fetchone()
    if not user or not check_password_hash(user["mot_de_passe"], current_password):
        db.close()
        return jsonify({"error": "Mot de passe actuel incorrect"}), 400
    if check_password_hash(user["mot_de_passe"], new_password):
        db.close()
        return jsonify({"error": "Le nouveau mot de passe doit être différent de l'actuel"}), 400
    db.execute(
        "UPDATE users SET mot_de_passe=? WHERE id=?",
        (generate_password_hash(new_password), user["id"]),
    )
    _audit_user(db, user["id"], user["login"], request.user, "modification",
                "mot_de_passe", "***", "modifié", "Changement par l'utilisateur")
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    act_as.end_impersonation(_audit_user)
    if session.get("uid"):
        audit_logs.log_login("deconnexion", "", session.get("uid"), True)
    session.clear()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Paramètres
# --------------------------------------------------------------------------- #
@app.route("/api/settings", methods=["GET"])
@login_required
def settings_get():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["PUT"])
@admin_required
def settings_put():
    data = request.get_json(force=True) or {}
    db = get_db()
    for key, value in data.items():
        if key in ("seeded",):
            continue
        set_setting(db, key, value)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/settings/reimport", methods=["POST"])
@admin_required
def settings_reimport():
    """Réimporte les paramètres depuis le classeur Excel copié dans ./source/."""
    from seed import extract

    source = os.path.join(BASE_DIR, "source")
    xlsx = None
    if os.path.isdir(source):
        for name in os.listdir(source):
            if name.lower().endswith(".xlsx"):
                xlsx = os.path.join(source, name)
                break
    if not xlsx:
        return jsonify({"error": "Aucun classeur trouvé dans le dossier source/"}), 404
    try:
        ok = extract(xlsx)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "Import impossible : %s" % exc}), 500
    if not ok:
        return jsonify({"error": "Import impossible"}), 500
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Utilisateurs (admin)
# --------------------------------------------------------------------------- #
@app.route("/api/users", methods=["GET"])
@login_required
def users_list():
    if not _can_manage_users(request.user):
        return jsonify({"error": "Accès réservé aux administrateurs et valideurs"}), 403
    db = get_db()
    select = (
        "SELECT u.id, u.login, u.ad_login, u.matricule, u.nom, u.email, u.admin, u.role, u.parent_id, "
        "u.actif, u.cree_le, p.nom AS parent_nom, p.login AS parent_login "
        "FROM users u LEFT JOIN users p ON p.id = u.parent_id "
    )
    if request.user.get("admin"):
        rows = db.execute(select).fetchall()
    else:
        ids = [i for i in _scope_ids(db, request.user) if i != request.user["id"]]
        if not ids:
            db.close()
            return jsonify([])
        marks = ",".join("?" for _ in ids)
        rows = db.execute(select + "WHERE u.id IN (%s)" % marks, ids).fetchall()
    db.close()
    users = [row_to_dict(r) for r in rows]

    def norm(value):
        return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()

    # Niveau de validation (administrateur -> agent), puis identifiant.
    users.sort(key=lambda u: (
        -ROLE_LEVELS.get(_user_role(u), 0),
        norm(u.get("login")),
    ))
    return jsonify(users)


@app.route("/api/users/audit", methods=["GET"])
@admin_required
def users_audit():
    try:
        limit = int(request.args.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 500))
    db = get_db()
    rows = db.execute(
        "SELECT id, user_id, target_login, actor_id, actor_login, action, "
        "field, old_value, new_value, comment, created_at "
        "FROM user_audit ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/users", methods=["POST"])
@login_required
def users_create():
    if not _can_manage_users(request.user):
        return jsonify({"error": "Accès réservé aux administrateurs et valideurs"}), 403
    data = request.get_json(force=True) or {}
    login_name = (data.get("login") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip()
    role = (data.get("role") or ("administrateur" if data.get("admin") else "secteur")).strip()
    if not login_name:
        return jsonify({"error": "Identifiant obligatoire"}), 400
    if not password:
        # Mode AD : le mot de passe est celui du compte Ville ; un mot de passe local aléatoire (jamais communiqué)
        # remplit la colonne. Les administrateurs gardent un mot de passe local (compte de secours).
        if config.AUTH_MODE != "ad" or role == "administrateur":
            return jsonify({"error": "Identifiant et mot de passe obligatoires"}), 400
        password = uuid.uuid4().hex + "Aa1!"
    matricule, merr = _clean_matricule(data.get("matricule"))
    if merr:
        return jsonify({"error": merr}), 400
    if role not in ROLE_LEVELS:
        return jsonify({"error": "Rôle invalide"}), 400
    creator_role = _user_role(request.user)
    creatable = {
        "administrateur": set(ROLE_LEVELS),
        "dgs": {"dga", "direction", "service", "secteur", "unite", "equipe", "agent"},
        "dga": {"direction", "service", "secteur", "unite", "equipe", "agent"},
        "direction": {"service", "secteur", "unite", "equipe", "agent"},
        "service": {"secteur", "unite", "equipe", "agent"},
        "secteur": {"unite", "equipe", "agent"},
        "unite": {"equipe", "agent"},
        "equipe": {"agent"},
    }
    if not request.user.get("admin") and role not in creatable.get(creator_role, set()):
        return jsonify({"error": "Vous ne pouvez pas créer ce niveau de compte"}), 403
    db = get_db()
    exists = db.execute("SELECT id FROM users WHERE login=?", (login_name,)).fetchone()
    if exists:
        db.close()
        return jsonify({"error": "Cet identifiant existe déjà"}), 400
    parent_id = data.get("parent_id")
    if parent_id in ("", 0):
        parent_id = None
    if not request.user.get("admin") and parent_id is None:
        db.close()
        return jsonify({"error": "Le responsable est obligatoire"}), 400
    err = _validate_user_parent(db, role, parent_id)
    if err:
        db.close()
        return jsonify({"error": err}), 400
    if not request.user.get("admin"):
        try:
            parent_int = int(parent_id)
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "Responsable invalide"}), 400
        if parent_int not in set(_scope_ids(db, request.user)):
            db.close()
            return jsonify({"error": "Le responsable doit être dans votre périmètre"}), 403
    if role == "administrateur":
        parent_id = None
    holder = _matricule_holder(db, matricule)
    if holder:
        db.close()
        return jsonify({"error": "Ce matricule est déjà attribué au compte %s" % holder}), 400
    cur = db.execute(
        "INSERT INTO users (login, ad_login, matricule, nom, email, mot_de_passe, admin, role, parent_id, actif) "
        "VALUES (?,?,?,?,?,?,?,?,?,1)",
        (login_name, (data.get("ad_login") or "").strip(), matricule, (data.get("nom") or login_name).strip(), email,
         generate_password_hash(password), 1 if role == "administrateur" else 0,
         role, parent_id),
    )
    _audit_user(
        db, cur.lastrowid, login_name, request.user, "creation", "compte", "",
        "role=%s; responsable=%s; actif=Oui" % (
            role, _login_for_user(db, parent_id) or "—"),
    )
    _audit_user(db, cur.lastrowid, login_name, request.user, "creation",
                "mot_de_passe", "", "défini")
    db.commit()
    user = db.execute(
        "SELECT id, login, ad_login, matricule, nom, email, admin, role, parent_id, actif, cree_le "
        "FROM users WHERE id=?",
        (cur.lastrowid,),
    ).fetchone()
    db.close()
    return jsonify(row_to_dict(user))


@app.route("/api/users/<int:uid>", methods=["PUT"])
@login_required
def users_update(uid):
    if not _can_manage_users(request.user):
        return jsonify({"error": "Accès réservé aux administrateurs et valideurs"}), 403
    data = request.get_json(force=True) or {}
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "Utilisateur introuvable"}), 404
    is_admin = bool(request.user.get("admin"))
    if "login" in data and not is_admin:
        db.close()
        return jsonify({"error": "Seul l'administrateur peut modifier un identifiant"}), 403
    if not is_admin:
        if uid == request.user["id"] or uid not in set(_scope_ids(db, request.user)):
            db.close()
            return jsonify({"error": "Ce compte n'est pas dans votre périmètre"}), 403
        # Un valideur gère les paramètres des comptes liés, pas leur rôle ni leur rattachement.
        role = _user_role(row_to_dict(user))
        parent_id = user["parent_id"]
        admin_flag = user["admin"]
    else:
        role = (data.get("role") or _user_role(row_to_dict(user))).strip()
        if role not in ROLE_LEVELS:
            db.close()
            return jsonify({"error": "Rôle invalide"}), 400
        parent_id = data.get("parent_id", user["parent_id"])
        if parent_id in ("", 0):
            parent_id = None
        if uid == request.user["id"]:
            if role != "administrateur":
                db.close()
                return jsonify({"error": "Impossible de retirer vos propres droits administrateur"}), 400
            if not data.get("actif", user["actif"]):
                db.close()
                return jsonify({"error": "Impossible de désactiver votre propre compte"}), 400
            parent_id = None
        else:
            err = _validate_user_parent(db, role, parent_id, uid)
            if err:
                db.close()
                return jsonify({"error": err}), 400
        if role == "administrateur":
            parent_id = None
        admin_flag = 1 if role == "administrateur" else 0
    login_name = user["login"]
    if is_admin and "login" in data:
        login_name = (data.get("login") or "").strip()
        if not login_name:
            db.close()
            return jsonify({"error": "L'identifiant est obligatoire"}), 400
        if login_name != user["login"]:
            exists = db.execute(
                "SELECT id FROM users WHERE login=? AND id<>?", (login_name, uid)
            ).fetchone()
            if exists:
                db.close()
                return jsonify({"error": "Cet identifiant existe déjà"}), 400
    email = (data.get("email") if "email" in data else (user["email"] or "")).strip()
    actif = 1 if data.get("actif", user["actif"]) else 0
    ad_login = (data.get("ad_login") if "ad_login" in data else (user["ad_login"] or "")).strip()
    matricule, merr = _clean_matricule(data["matricule"] if "matricule" in data else user["matricule"])
    holder = _matricule_holder(db, matricule, uid)
    if merr or holder:
        db.close()
        return jsonify({"error": merr or "Ce matricule est déjà attribué au compte %s" % holder}), 400
    db.execute(
        "UPDATE users SET login=?, ad_login=?, matricule=?, nom=?, email=?, admin=?, role=?, parent_id=?, actif=? WHERE id=?",
        (login_name, ad_login, matricule, (data.get("nom") or user["nom"]).strip(), email,
         admin_flag, role, parent_id, actif, uid),
    )
    password = data.get("password")
    if password:
        db.execute("UPDATE users SET mot_de_passe=? WHERE id=?", (generate_password_hash(password), uid))
    changes = []
    if login_name != user["login"]:
        changes.append(("login", user["login"], login_name))
    if role != user["role"]:
        changes.append(("rôle", user["role"], role))
    if parent_id != user["parent_id"]:
        changes.append(("responsable", _login_for_user(db, user["parent_id"]),
                        _login_for_user(db, parent_id)))
    if actif != user["actif"]:
        changes.append(("activation", "Oui" if user["actif"] else "Non",
                        "Oui" if actif else "Non"))
    if admin_flag != user["admin"]:
        changes.append(("administrateur", "Oui" if user["admin"] else "Non",
                        "Oui" if admin_flag else "Non"))
    if email != (user["email"] or ""):
        changes.append(("e-mail", user["email"] or "", email))
    if ad_login != (user["ad_login"] or ""):
        changes.append(("identifiant AD", user["ad_login"] or "", ad_login))
    if matricule != (user["matricule"] or ""):
        changes.append(("matricule", user["matricule"] or "", matricule))
    new_nom = (data.get("nom") or user["nom"]).strip()
    if new_nom != user["nom"]:
        changes.append(("nom", user["nom"], new_nom))
    if password:
        changes.append(("mot_de_passe", "***", "modifié"))
    for field, old_value, new_value in changes:
        _audit_user(db, uid, login_name, request.user, "modification",
                    field, old_value, new_value)
    db.commit()
    user = db.execute(
        "SELECT id, login, ad_login, matricule, nom, email, admin, role, parent_id, actif, cree_le "
        "FROM users WHERE id=?",
        (uid,),
    ).fetchone()
    db.close()
    return jsonify(row_to_dict(user))


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@login_required
def users_delete(uid):
    if not _can_manage_users(request.user):
        return jsonify({"error": "Accès réservé aux administrateurs et valideurs"}), 403
    if uid == request.user["id"]:
        return jsonify({"error": "Impossible de supprimer votre propre compte"}), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "Utilisateur introuvable"}), 404
    if not request.user.get("admin") and uid not in set(_scope_ids(db, request.user)):
        db.close()
        return jsonify({"error": "Ce compte n'est pas dans votre périmètre"}), 403
    _audit_user(db, uid, user["login"], request.user, "suppression", "compte",
                "%s / %s" % (user["role"], user["login"]), "",
                "Suppression du compte")
    # Les subordonnés remontent au premier ancêtre dont le rôle reste valide.
    _reparent_children(db, user)
    db.execute("DELETE FROM agents WHERE user_id=? OR agent_user_id=?", (uid, uid))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Agents (fiches)
# --------------------------------------------------------------------------- #
def _agent_payload(db, agent_id, user_id=None, with_cells=True):
    if user_id is None:
        agent = _agent_by_id(db, agent_id)
    else:
        agent = db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE a.id=? AND a.user_id=?",
            (agent_id, user_id),
        ).fetchone()
    if not agent:
        return None
    out = row_to_dict(agent)
    out["params"] = json_loads(agent["params"])
    out["periods"] = json_loads(agent["periods"]) if agent["periods"] else []
    out["cells"] = []
    if with_cells:
        cells = db.execute("SELECT jour, code FROM cells WHERE agent_id=?", (agent_id,)).fetchall()
        out["cells"] = {str(c["jour"]): c["code"] for c in cells}
    out["cassages"] = _agent_cassages(db, agent_id)
    out["hourly"] = _agent_hourly(db, agent_id)
    out["recoveries"] = _agent_recoveries(db, agent_id)
    return out


@app.route("/api/agents", methods=["GET"])
@login_required
def agents_list():
    db = get_db()
    rows = _scope_agents(db, request.user, _request_year())
    scope_ids = set(_scope_ids(db, request.user))
    out = []
    for r in rows:
        item = row_to_dict(r)
        item["params"] = json_loads(r["params"])
        item["periods"] = json_loads(r["periods"]) if r["periods"] else []
        item["can_edit"] = _can_edit_agent(db, request.user, r, scope_ids)
        item["pending_count"] = _pending_count(db, r["id"])
        out.append(item)
    db.close()
    return jsonify(out)


def _default_params():
    return {
        "penibilite": "", "duree_hebdo": "38 heures", "quotite": "", "jours_hebdo": "",
        "date_arrivee": "", "date_depart": "",
        "reliquat": "", "solde_cet": "",
    }


def _normalize_params(params):
    """Garantit la présence de toutes les clés attendues par rules.compute."""
    base = _default_params()
    for key, value in (params or {}).items():
        base[key] = value
    # coercition des types numériques attendus tels quels
    if base.get("jours_hebdo") in ("", None):
        base["jours_hebdo"] = None
    return base


def _valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value or ""))


def _parse_iso_date(value):
    try:
        return dt.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _normalize_periods(raw, params, year):
    """Valide les périodes de paramètres d'une fiche.

    Retourne [] si aucune période, None si la structure est invalide.
    Les périodes doivent être contiguës et couvrir toute la présence.
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        return None
    if not raw:
        return []
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    year_start = dt.date(year, 1, 1)
    year_end = dt.date(year, 12, 31)
    arr = _parse_iso_date((params or {}).get("date_arrivee")) or year_start
    dep = _parse_iso_date((params or {}).get("date_depart")) or year_end
    if arr < year_start:
        arr = year_start
    if dep > year_end:
        dep = year_end
    if arr > dep:
        return None

    out = []
    previous_end = None
    for item in raw:
        if not isinstance(item, dict):
            return None
        start = _parse_iso_date(item.get("start"))
        end = _parse_iso_date(item.get("end"))
        if not start or not end or start > end:
            return None
        if start < arr or end > dep:
            return None
        if previous_end is not None and start != previous_end + dt.timedelta(days=1):
            return None
        jours = item.get("jours_hebdo")
        if jours in ("", None):
            jours = None
        else:
            try:
                jours = int(jours)
            except (TypeError, ValueError):
                return None
        out.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "penibilite": (item.get("penibilite") or "").strip(),
            "duree_hebdo": (item.get("duree_hebdo") or "").strip(),
            "quotite": (item.get("quotite") or "").strip(),
            "jours_hebdo": jours,
        })
        previous_end = end

    if out[0]["start"] != arr.isoformat() or out[-1]["end"] != dep.isoformat():
        return None
    return out


def _agent_login(db, prenom, nom):
    """Identifiant : première lettre du prénom + nom, en majuscules."""
    base = (prenom.strip()[:1] + nom.strip()).upper()
    base = re.sub(r"[^A-Z0-9]", "", base) or "AGENT"
    login = base
    suffix = 2
    while db.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
        login = "%s%d" % (base, suffix)
        suffix += 1
    return login


def _agent_password():
    return "Conges" + uuid.uuid4().hex[:4].upper() + "!"


@app.route("/api/agents", methods=["POST"])
@login_required
def agents_create():
    if not _can_create_fiche(request.user):
        return jsonify({"error": "Seuls les administrateurs et valideurs peuvent créer une fiche"}), 403
    data = request.get_json(force=True) or {}
    nom = (data.get("nom") or "").strip().upper()
    prenom = (data.get("prenom") or "").strip().upper()
    email = (data.get("email") or "").strip()
    if not nom or not prenom:
        return jsonify({"error": "Nom et prénom obligatoires"}), 400
    if not _valid_email(email):
        return jsonify({"error": "Adresse e-mail invalide"}), 400
    try:
        year = int(data.get("year") or _request_year())
    except (TypeError, ValueError):
        year = _request_year()
    if not (2000 <= year <= 2100):
        year = _request_year()
    db = get_db()
    raw_owner = data.get("owner_id") or request.user["id"]
    try:
        owner_id = int(raw_owner)
    except (TypeError, ValueError):
        db.close()
        return jsonify({"error": "Propriétaire invalide"}), 400
    owner = db.execute(
        "SELECT * FROM users WHERE id=? AND actif=1", (owner_id,)
    ).fetchone()
    if not owner or _user_role(row_to_dict(owner)) not in VALIDATOR_ROLES:
        db.close()
        return jsonify({"error": "Le propriétaire doit être un valideur actif"}), 400
    if not request.user.get("admin") and owner_id not in set(_scope_ids(db, request.user)):
        db.close()
        return jsonify({"error": "Ce valideur n'est pas dans votre périmètre"}), 403
    raw_validator = data.get("validator_id")
    if raw_validator in (None, "", 0, "0"):
        db.close()
        return jsonify({"error": "Compte valideur obligatoire"}), 400
    try:
        validator_id = int(raw_validator)
    except (TypeError, ValueError):
        db.close()
        return jsonify({"error": "Compte valideur invalide"}), 400
    validator = db.execute(
        "SELECT * FROM users WHERE id=? AND actif=1", (validator_id,)
    ).fetchone()
    if not validator or _user_role(row_to_dict(validator)) not in VALIDATOR_ROLES:
        db.close()
        return jsonify({"error": "Le compte valideur doit être un compte valideur actif"}), 400
    allowed_validators = {u["id"] for u in _validator_chain(db, owner_id)}
    if validator_id not in allowed_validators:
        db.close()
        return jsonify({"error": "Compte valideur non autorisé pour ce propriétaire"}), 400
    matricule, merr = _clean_matricule(data.get("matricule"))
    holder = _matricule_holder(db, matricule)
    if merr or holder:
        db.close()
        return jsonify({"error": merr or "Ce matricule est déjà attribué au compte %s" % holder}), 400
    params = _normalize_params(data.get("params"))
    is_manager = 1 if data.get("is_manager") else 0
    login = _agent_login(db, prenom, nom)
    password = _agent_password()
    full_name = ("%s %s" % (nom, prenom)).strip()
    try:
        cur_user = db.execute(
            "INSERT INTO users (login, nom, email, matricule, mot_de_passe, admin, role, parent_id, actif) "
            "VALUES (?,?,?,?,?,0,'agent',?,1)",
            (login, full_name, email, matricule, generate_password_hash(password), owner_id),
        )
        agent_user_id = cur_user.lastrowid
        cur = db.execute(
            "INSERT INTO agents (user_id, agent_user_id, nom, prenom, email, matricule, validator_id, year, params, is_manager) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (owner_id, agent_user_id, nom, prenom, email, matricule, validator_id, year, json_dumps(params), is_manager),
        )
        agent_row_id = cur.lastrowid
        if is_manager:
            db.execute(
                "UPDATE agents SET is_manager=0 WHERE user_id=? AND year=? AND id<>?",
                (owner_id, year, agent_row_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        return jsonify({"error": "Création de la fiche impossible"}), 500
    payload = _agent_payload(db, agent_row_id, owner_id)
    payload["can_edit"] = True
    payload.update(_agent_flags(db, request.user, _agent_by_id(db, agent_row_id)))
    payload["agent_id"] = agent_user_id
    payload["agent_login"] = login
    payload["agent_password"] = password
    db.close()
    return jsonify(payload)


@app.route("/api/agents/<int:aid>", methods=["GET"])
@login_required
def agents_get(aid):
    db = get_db()
    agent = _agent_by_id(db, aid)
    if not agent or not _can_view_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    payload = _agent_payload(db, aid)
    payload["can_edit"] = _can_edit_agent(db, request.user, agent)
    payload.update(_agent_flags(db, request.user, agent))
    payload["can_change_owner"] = _can_change_owner(db, request.user, agent)
    payload["owner_options"] = _owner_options(db, request.user, agent)
    db.close()
    return jsonify(payload)


@app.route("/api/hourly/<int:hid>", methods=["PUT", "DELETE"])
@login_required
def hourly_update(hid):
    """Modification ou suppression d'heures déjà posées par un valideur."""
    db = get_db()
    row = db.execute("SELECT * FROM hourly_absences WHERE id=?", (hid,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Heures introuvables"}), 404
    agent = _agent_by_id(db, row["agent_id"])
    if not agent or not _can_edit_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Vous n'êtes pas responsable de cette fiche"}), 403

    if request.method == "DELETE":
        request_id = row["request_id"]
        db.execute("DELETE FROM hourly_absences WHERE id=?", (hid,))
        if request_id:
            db.execute(
                "UPDATE leave_requests SET status='annulee', "
                "cancel_decided_at=CURRENT_TIMESTAMP, cancel_decided_by=?, "
                "cancel_decision_comment=? WHERE id=?",
                (request.user["id"], "Suppression par le valideur", request_id),
            )
            _audit_request(db, request_id, "supprimee_valideur",
                           request.user["id"], "Heures supprimées par le valideur")
        db.commit()
        db.close()
        return jsonify({"ok": True})

    data = request.get_json(force=True) or {}
    code = (data.get("code") or "").strip().upper()
    if code not in HOUR_CODES:
        db.close()
        return jsonify({"error": "Code d'heures non autorisé"}), 400
    absence_date = str(data.get("absence_date") or "").strip()
    try:
        ad = dt.date.fromisoformat(absence_date[:10])
    except (TypeError, ValueError):
        db.close()
        return jsonify({"error": "Date d'absence invalide"}), 400
    if ad.year != int(agent["year"]):
        db.close()
        return jsonify({"error": "La date doit être dans l'année de la fiche"}), 400
    start_time = str(data.get("start_time") or "").strip()
    end_time = str(data.get("end_time") or "").strip()
    computed = _hours_between(start_time, end_time)
    if computed is None:
        db.close()
        return jsonify({"error": "Horaires invalides : l'heure de fin doit suivre l'heure de début"}), 400
    try:
        hours = float(data.get("hours") or computed)
    except (TypeError, ValueError):
        hours = computed
    if abs(hours - computed) > 0.02:
        db.close()
        return jsonify({"error": "La durée ne correspond pas aux horaires saisis"}), 400
    if hours <= 0:
        db.close()
        return jsonify({"error": "La durée doit être supérieure à zéro"}), 400
    if _hourly_overlaps(
        db, agent["id"], absence_date, start_time, end_time,
        exclude_request_id=row["request_id"], exclude_hourly_id=hid,
    ):
        db.close()
        return jsonify({"error": "Ces horaires chevauchent une absence existante"}), 400
    ok, result = _request_hourly_balance(
        db, agent, code, absence_date, start_time, end_time, hours,
        exclude_id=row["request_id"], exclude_hourly_id=hid,
    )
    if not ok:
        key = {"CAH": "cah", "RTTH": "rth", "RCH": "rch"}.get(code, "cah")
        restant = ((result.get("solde") or {}).get(key) or {}).get("restant")
        db.close()
        return jsonify({"error": "Solde d'heures insuffisant : il resterait %s h" % restant}), 400
    db.execute(
        "UPDATE hourly_absences SET code=?, absence_date=?, start_time=?, "
        "end_time=?, hours=?, year=? WHERE id=?",
        (code, absence_date, start_time, end_time, hours, ad.year, hid),
    )
    if row["request_id"]:
        db.execute(
            "UPDATE leave_requests SET code=?, absence_date=?, start_time=?, "
            "end_time=?, hours=?, days=? WHERE id=?",
            (code, absence_date, start_time, end_time, hours,
             round(hours / 7.0, 6), row["request_id"]),
        )
        _audit_request(db, row["request_id"], "modifiee_valideur",
                       request.user["id"], "Heures modifiées par le valideur")
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/agents/<int:aid>", methods=["PUT"])
@login_required
def agents_update(aid):
    data = request.get_json(force=True) or {}
    db = get_db()
    agent = _agent_by_id(db, aid)
    if not agent or not _can_view_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    if not _can_edit_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Lecture seule : vous ne pouvez pas modifier cette fiche"}), 403
    if "cells" in data and not _can_edit_cells(db, request.user, agent):
        old_cells = _agent_cells(db, aid)
        new_cells = {str(k): v for k, v in (data.get("cells") or {}).items() if v}
        if new_cells != old_cells:
            db.close()
            return jsonify({"error": "Saisie directe désactivée : utilisez une demande de congé"}), 403
    old_owner_id = int(agent["user_id"])
    owner_id = data.get("owner_id", old_owner_id)
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        db.close()
        return jsonify({"error": "Propriétaire invalide"}), 400
    if owner_id != old_owner_id:
        if not _can_change_owner(db, request.user, agent):
            db.close()
            return jsonify({"error": "Vous ne pouvez pas modifier le propriétaire de cette fiche"}), 403
        owner = db.execute(
            "SELECT * FROM users WHERE id=? AND actif=1", (owner_id,)
        ).fetchone()
        if not owner or _user_role(row_to_dict(owner)) not in VALIDATOR_ROLES:
            db.close()
            return jsonify({"error": "Le propriétaire doit être un valideur actif"}), 400
        if not request.user.get("admin") and owner_id not in set(_scope_ids(db, request.user)):
            db.close()
            return jsonify({"error": "Ce valideur n'est pas dans votre périmètre"}), 403
    nom = (data.get("nom") if "nom" in data else agent["nom"] or "").strip().upper()
    prenom = (data.get("prenom") if "prenom" in data else agent["prenom"] or "").strip().upper()
    email = (data.get("email") if "email" in data else agent["email"] or "").strip()
    if not nom or not prenom:
        db.close()
        return jsonify({"error": "Nom et prénom obligatoires"}), 400
    if not _valid_email(email):
        db.close()
        return jsonify({"error": "Adresse e-mail invalide"}), 400
    validator_id = data.get("validator_id", agent["validator_id"])
    if validator_id in ("", 0):
        validator_id = None
    if validator_id is not None:
        try:
            validator_id = int(validator_id)
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "Compte valideur invalide"}), 400
        validator = db.execute(
            "SELECT * FROM users WHERE id=? AND actif=1", (validator_id,)
        ).fetchone()
        if not validator or _user_role(row_to_dict(validator)) not in VALIDATOR_ROLES:
            db.close()
            return jsonify({"error": "Le compte valideur doit être un compte valideur actif"}), 400
    if validator_id is None:
        db.close()
        return jsonify({"error": "Compte valideur obligatoire"}), 400
    allowed_validators = {u["id"] for u in _validator_chain(db, owner_id)}
    if validator_id not in allowed_validators:
        if "validator_id" not in data and owner_id != old_owner_id:
            validator_id = owner_id
        else:
            db.close()
            return jsonify({"error": "Compte valideur non autorisé pour ce propriétaire"}), 400
    params_obj = data["params"] if "params" in data else json_loads(agent["params"])
    params_obj = _normalize_params(params_obj)
    periods = json_loads(agent["periods"]) if agent["periods"] else []
    if "periods" in data:
        periods = data.get("periods") or []
    if periods:
        normalized = _normalize_periods(periods, params_obj, agent["year"])
        if normalized is None:
            db.close()
            return jsonify({"error": "Périodes invalides : elles doivent être contiguës et couvrir toute la présence de l'agent."}), 400
        periods = normalized
        last = periods[-1]
        for key in ("penibilite", "duree_hebdo", "quotite", "jours_hebdo"):
            params_obj[key] = last.get(key)
    params = json_dumps(params_obj)
    periods_json = json_dumps(periods)
    if "is_manager" in data:
        is_manager = 1 if data.get("is_manager") else 0
    else:
        is_manager = int(agent["is_manager"] or 0)
    matricule, merr = _clean_matricule(data["matricule"] if "matricule" in data else agent["matricule"])
    holder = _matricule_holder(db, matricule, agent["agent_user_id"])
    if merr or holder:
        db.close()
        return jsonify({"error": merr or "Ce matricule est déjà attribué au compte %s" % holder}), 400
    db.execute(
        "UPDATE agents SET user_id=?, nom=?, prenom=?, email=?, matricule=?, validator_id=?, params=?, periods=?, is_manager=?, "
        "modifie_le=CURRENT_TIMESTAMP WHERE id=?",
        (owner_id, nom, prenom, email, matricule, validator_id, params, periods_json, is_manager, aid),
    )
    if is_manager:
        db.execute(
            "UPDATE agents SET is_manager=0 WHERE user_id=? AND year=? AND id<>?",
            (owner_id, agent["year"], aid),
        )
    linked_id = agent["agent_user_id"]
    if linked_id:
        linked = db.execute("SELECT * FROM users WHERE id=?", (linked_id,)).fetchone()
        if linked and _user_role(row_to_dict(linked)) == "agent":
            db.execute(
                "UPDATE users SET nom=?, email=?, matricule=?, parent_id=? WHERE id=?",
                (("%s %s" % (nom, prenom)).strip(), email, matricule, owner_id, linked_id),
            )
    if "cells" in data:
        db.execute("DELETE FROM cells WHERE agent_id=?", (aid,))
        cells = data.get("cells") or {}
        db.executemany(
            "INSERT INTO cells (agent_id, jour, code) VALUES (?,?,?)",
            [(aid, int(jour), code) for jour, code in cells.items() if code],
        )
    db.commit()
    updated_agent = _agent_by_id(db, aid)
    payload = _agent_payload(db, aid)
    payload["can_edit"] = True
    payload.update(_agent_flags(db, request.user, updated_agent))
    payload["can_change_owner"] = _can_change_owner(db, request.user, updated_agent)
    payload["owner_options"] = _owner_options(db, request.user, updated_agent)
    db.close()
    return jsonify(payload)


@app.route("/api/agents/<int:aid>", methods=["DELETE"])
@login_required
def agents_delete(aid):
    db = get_db()
    agent = _agent_by_id(db, aid)
    if not agent or not _can_view_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    if not _can_edit_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Lecture seule : vous ne pouvez pas supprimer cette fiche"}), 403
    db.execute("DELETE FROM cells WHERE agent_id=?", (aid,))
    db.execute("DELETE FROM agents WHERE id=?", (aid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/agents/<int:aid>/clone", methods=["POST"])
@login_required
def agents_clone(aid):
    db = get_db()
    source = _agent_by_id(db, aid)
    if not source or not _can_view_agent(db, request.user, source):
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    data = request.get_json(force=True) or {}
    cur = db.execute(
        "INSERT INTO agents (user_id, nom, year, params) VALUES (?,?,?,?)",
        (request.user["id"], (data.get("nom") or source["nom"] + " (copie)").strip(),
         source["year"], source["params"]),
    )
    cells = db.execute("SELECT jour, code FROM cells WHERE agent_id=?", (aid,)).fetchall()
    db.executemany(
        "INSERT INTO cells (agent_id, jour, code) VALUES (?,?,?)",
        [(cur.lastrowid, c["jour"], c["code"]) for c in cells],
    )
    db.commit()
    payload = _agent_payload(db, cur.lastrowid, request.user["id"])
    payload["can_edit"] = True
    payload.update(_agent_flags(db, request.user, _agent_by_id(db, cur.lastrowid)))
    db.close()
    return jsonify(payload)


@app.route("/api/agents/duplicate", methods=["POST"])
@login_required
def agents_duplicate():
    """Duplique une ou plusieurs fiches vers une année.

    Les paramètres sont conservés (hors dates d'arrivée/départ, propres à
    l'année source) ; les congés saisis (cases du calendrier) ne sont pas copiés.
    """
    data = request.get_json(force=True) or {}
    raw_ids = data.get("ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"error": "Aucune fiche sélectionnée"}), 400
    target = data.get("year")
    db = get_db()
    created, errors = [], []
    for raw in raw_ids:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        source = _agent_by_id(db, aid)
        if not source or not _can_view_agent(db, request.user, source):
            errors.append({"id": raw, "error": "Fiche introuvable"})
            continue
        if not _can_edit_agent(db, request.user, source):
            errors.append({"id": raw, "error": "Lecture seule"})
            continue
        try:
            year = int(target) if target not in (None, "") else int(source["year"]) + 1
        except (TypeError, ValueError):
            year = int(source["year"]) + 1
        if not (2000 <= year <= 2100):
            year = int(source["year"]) + 1
        params = json_loads(source["params"])
        source_periods = json_loads(source["periods"]) if source["periods"] else []
        if source_periods:
            last = source_periods[-1]
            for key in ("penibilite", "duree_hebdo", "quotite", "jours_hebdo"):
                params[key] = last.get(key)
        params["date_arrivee"] = ""
        params["date_depart"] = ""
        params = _normalize_params(params)
        cur = db.execute(
            "INSERT INTO agents (user_id, agent_user_id, nom, prenom, email, matricule, validator_id, year, params, is_manager) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (source["user_id"], source["agent_user_id"], source["nom"], source["prenom"],
             source["email"], source["matricule"], source["validator_id"], year, json_dumps(params),
             int(source["is_manager"] or 0)),
        )
        if source["is_manager"]:
            db.execute(
                "UPDATE agents SET is_manager=0 WHERE user_id=? AND year=? AND id<>?",
                (source["user_id"], year, cur.lastrowid),
            )
        created.append({
            "id": cur.lastrowid, "nom": source["nom"], "prenom": source["prenom"],
            "year": year, "can_edit": True,
        })
    db.commit()
    db.close()
    return jsonify({"created": created, "errors": errors})


# --------------------------------------------------------------------------- #
#  Demandes de congés (circuit N+1)
# --------------------------------------------------------------------------- #
REQUEST_STATUSES = ("en_attente", "validee", "refusee", "annulee")
BALANCE_CODES = {
    "CA": "ca", "CA26": "ca",
    "RTT": "rtt", "RTTF": "rtt",
    "JS": "js", "JB": "jb", "CET": "cet",
}
HOUR_CODES = ("CAH", "RTTH", "RCH")
CASSAGE_CODES = ("CA", "RTT")


def _requestable_codes(year=None):
    """Codes qu'un agent peut demander, dans l'ordre métier.

    CA n-1 est le code dynamique de l'année précédente (CA25, CA26, ...).
    Il est autorisé côté serveur ; le frontend ne l'affiche que si un
    reliquat est encore disponible.
    """
    settings = _settings_for_year(load_settings(), int(year)) if year else load_settings()
    configured = {c.get("code") for c in (settings.get("codes") or []) if c.get("code")}
    ca_prev = ca_prev_code(settings)
    ordered = ["CA", ca_prev, "RTT", "JB", "JS", "MD", "AS", "CET"]
    return [code for code in ordered if code == ca_prev or code in configured]


def _parse_request_cells(raw):
    if not isinstance(raw, list):
        return None
    out = []
    for value in raw:
        try:
            key = int(value)
        except (TypeError, ValueError):
            return None
        if key not in out:
            out.append(key)
    return sorted(out)


def _cell_valid(key, year):
    month = key // 1000
    day = (key % 1000) // 10
    half = key % 10
    if not (1 <= month <= 12 and 1 <= day <= 31 and half in (0, 1)):
        return False
    try:
        dt.date(int(year), month, day)
    except ValueError:
        return False
    return True


def _agent_cells(db, agent_id):
    return {
        str(r["jour"]): r["code"]
        for r in db.execute("SELECT jour, code FROM cells WHERE agent_id=?", (agent_id,)).fetchall()
    }


def _agent_cassages(db, agent_id, include_pending=False, exclude_id=None):
    """Cassages validés (et éventuellement en attente) d'une fiche."""
    statuses = ["validee", "annulation_demandee"]
    if include_pending:
        statuses.append("en_attente")
    placeholders = ",".join("?" for _ in statuses)
    sql = (
        "SELECT id, code, days, hours, valid_until, decide_le, cree_le, year, status "
        "FROM leave_requests WHERE agent_id=? AND request_type='cassage' "
        "AND status IN (%s)" % placeholders
    )
    params = [agent_id] + statuses
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    out = []
    for row in db.execute(sql, params).fetchall():
        item = dict(row)
        item["pending"] = row["status"] == "en_attente"
        out.append(item)
    return out


def _agent_hourly(db, agent_id, include_pending=False, exclude_id=None,
                  exclude_hourly_id=None):
    """Absences horaires validées (et éventuellement en attente)."""
    out = []
    for row in db.execute(
        "SELECT id, code, absence_date, start_time, end_time, hours, request_id, year "
        "FROM hourly_absences WHERE agent_id=? ORDER BY absence_date, start_time",
        (agent_id,),
    ).fetchall():
        if exclude_hourly_id is not None and int(row["id"]) == int(exclude_hourly_id):
            continue
        item = dict(row)
        item["pending"] = False
        out.append(item)
    if include_pending:
        sql = (
            "SELECT id, code, absence_date, start_time, end_time, hours, year "
            "FROM leave_requests WHERE agent_id=? AND request_type='heures' "
            "AND status='en_attente'"
        )
        params = [agent_id]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        for row in db.execute(sql, params).fetchall():
            item = dict(row)
            item["pending"] = True
            item["request_id"] = row["id"]
            out.append(item)
    return out


def _agent_recoveries(db, agent_id):
    """Déclarations d'heures de récupération validées."""
    return [
        dict(row)
        for row in db.execute(
            "SELECT id, code, hours, absence_date, valid_until, decide_le, year, status "
            "FROM leave_requests WHERE agent_id=? AND request_type='recuperation' "
            "AND status IN ('validee','annulation_demandee') "
            "ORDER BY absence_date, id",
            (agent_id,),
        ).fetchall()
    ]


def _parse_time_minutes(value):
    if not value:
        return None
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def _hours_between(start_time, end_time):
    start = _parse_time_minutes(start_time)
    end = _parse_time_minutes(end_time)
    if start is None or end is None or end <= start:
        return None
    return round((end - start) / 60.0, 4)


def _hourly_half_parts(absence_date, start_time, end_time):
    """Répartition des heures entre le matin et l'après-midi (coupure 12h00)."""
    try:
        d = dt.date.fromisoformat(str(absence_date)[:10])
    except (TypeError, ValueError):
        return {}
    start = _parse_time_minutes(start_time)
    end = _parse_time_minutes(end_time)
    if start is None or end is None or end <= start:
        return {}
    noon = 12 * 60
    base = d.month * 1000 + d.day * 10
    parts = {}
    if start < noon and min(end, noon) > start:
        parts[base] = round((min(end, noon) - start) / 60.0, 4)
    if end > noon and end > max(start, noon):
        parts[base + 1] = round((end - max(start, noon)) / 60.0, 4)
    return parts


def _hourly_half_keys(absence_date, start_time, end_time):
    """Clés des demi-journées couvertes par une absence horaire.

    La coupure matin/après-midi est fixée à 12h00 ; aucun horaire de
    référence n'est imposé par ailleurs.
    """
    return list(_hourly_half_parts(absence_date, start_time, end_time).keys())


def _hourly_overlaps(db, agent_id, absence_date, start_time, end_time,
                     exclude_request_id=None, exclude_hourly_id=None):
    """Vérifie chevauchement horaire + occupation des demi-journées."""
    start = _parse_time_minutes(start_time)
    end = _parse_time_minutes(end_time)
    if start is None or end is None or end <= start:
        return True
    for item in _agent_hourly(db, agent_id, include_pending=True,
                              exclude_id=exclude_request_id,
                              exclude_hourly_id=exclude_hourly_id):
        if str(item.get("absence_date") or "")[:10] != str(absence_date)[:10]:
            continue
        s2 = _parse_time_minutes(item.get("start_time"))
        e2 = _parse_time_minutes(item.get("end_time"))
        if s2 is None or e2 is None:
            continue
        if start < e2 and s2 < end:
            return True
    keys = {str(k) for k in _hourly_half_keys(absence_date, start_time, end_time)}
    occupied = set(_agent_cells(db, agent_id).keys()) | set(_pending_cells(db, agent_id).keys())
    return bool(keys & occupied)


def _hourly_occupied_half(db, agent_id, exclude_request_id=None):
    """Demi-journées déjà occupées par une absence horaire."""
    out = set()
    for item in _agent_hourly(db, agent_id, include_pending=True, exclude_id=exclude_request_id):
        out.update(str(k) for k in _hourly_half_keys(
            item.get("absence_date"), item.get("start_time"), item.get("end_time")
        ))
    return out


def _pending_requests(db, agent_id, exclude_id=None):
    sql = "SELECT * FROM leave_requests WHERE agent_id=? AND status='en_attente'"
    params = [agent_id]
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    return db.execute(sql, params).fetchall()


def _pending_cells(db, agent_id, exclude_id=None):
    out = {}
    for row in _pending_requests(db, agent_id, exclude_id):
        try:
            keys = json_loads(row["cells"])
        except (ValueError, TypeError):
            keys = []
        for key in keys:
            try:
                out[str(int(key))] = row["code"]
            except (TypeError, ValueError):
                continue
    return out


def _pending_count(db, agent_id):
    row = db.execute(
        "SELECT COUNT(*) AS c FROM leave_requests WHERE agent_id=? AND status='en_attente'",
        (agent_id,),
    ).fetchone()
    return row["c"] if row else 0


def _can_change_owner(db, user, agent):
    return bool(
        user.get("admin")
        or (_user_role(user) in VALIDATOR_ROLES and _can_edit_agent(db, user, agent))
    )


def _owner_options(db, user, agent):
    if not agent or not _can_change_owner(db, user, agent):
        return []
    roles = list(VALIDATOR_ROLES)
    role_marks = ",".join("?" for _ in roles)
    if user.get("admin"):
        rows = db.execute(
            "SELECT id, login, nom, role FROM users "
            "WHERE actif=1 AND role IN (%s) ORDER BY nom, login" % role_marks,
            roles,
        ).fetchall()
    else:
        ids = _scope_ids(db, user)
        id_marks = ",".join("?" for _ in ids)
        rows = db.execute(
            "SELECT id, login, nom, role FROM users "
            "WHERE actif=1 AND role IN (%s) AND id IN (%s) ORDER BY nom, login"
            % (role_marks, id_marks),
            roles + ids,
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def _agent_flags(db, user, agent):
    return {
        "can_edit_cells": _can_edit_cells(db, user, agent),
        "can_request": agent["agent_user_id"] == user["id"],
        "can_special_request": bool(
            user.get("admin")
            or agent["agent_user_id"] == user["id"]
            or (_user_role(user) in VALIDATOR_ROLES and _can_edit_agent(db, user, agent))
        ),
        "pending_cells": _pending_cells(db, agent["id"]),
        "pending_count": _pending_count(db, agent["id"]),
    }


def _request_validator(db, user):
    """Responsable N+1 actif ; remonte la hiérarchie, puis l'admin."""
    if user.get("admin"):
        return None
    seen = set()
    pid = user.get("parent_id")
    while pid and pid not in seen:
        seen.add(pid)
        row = db.execute("SELECT id, parent_id, actif FROM users WHERE id=?", (pid,)).fetchone()
        if not row:
            break
        if row["actif"]:
            return row["id"]
        pid = row["parent_id"]
    admin = db.execute(
        "SELECT id FROM users WHERE admin=1 AND actif=1 AND id<>? LIMIT 1",
        (user["id"],),
    ).fetchone()
    return admin["id"] if admin else None


def _can_cancel_request(db, user, row):
    if user.get("admin") or row["user_id"] == user["id"]:
        return True
    agent = _agent_by_id(db, row["agent_id"])
    return bool(agent and agent["agent_user_id"] == user["id"])


def _can_validate_request(db, user, row):
    """Le valideur assigné et ses valideurs descendants (jamais un supérieur)."""
    if user.get("admin"):
        return True
    ids = set(_scope_ids(db, user))
    if row["validator_id"]:
        return int(row["validator_id"]) in ids
    agent = _agent_by_id(db, row["agent_id"])
    if not agent:
        return False
    responsible_id = agent["validator_id"] or agent["user_id"]
    return responsible_id in ids


def _can_approve_cancel(db, user, row):
    if user.get("admin"):
        return True
    ids = set(_scope_ids(db, user))
    if row["validator_id"]:
        return int(row["validator_id"]) in ids
    agent = _agent_by_id(db, row["agent_id"])
    if not agent:
        return False
    responsible_id = agent["validator_id"] or agent["user_id"]
    return responsible_id in ids


def _resolve_request_validator(db, agent, user):
    validator_id = agent["validator_id"] or _request_validator(db, user)
    auto = validator_id is None
    status = "validee" if auto else "en_attente"
    validator_email = ""
    validator_label = ""
    if validator_id is not None:
        validator = db.execute(
            "SELECT login, nom, email FROM users WHERE id=?", (validator_id,)
        ).fetchone()
        if validator:
            validator_email = validator["email"] or ""
            validator_label = validator["nom"] or validator["login"] or ""
    return validator_id, auto, status, validator_email, validator_label


def _balance_restant(result, code):
    key = BALANCE_CODES.get(code)
    if not key and re.match(r"^CA\d{2}$", code or ""):
        key = "ca"
    if not key:
        return None
    return ((result.get("solde") or {}).get(key) or {}).get("restant")


def _request_balance(db, agent, cells, code, exclude_id=None):
    """Recalcule le solde avec les absences validées + les demandes en attente."""
    params = json_loads(agent["params"])
    periods = json_loads(agent["periods"]) if agent["periods"] else []
    merged = _agent_cells(db, agent["id"])
    merged.update(_pending_cells(db, agent["id"], exclude_id))
    for key in cells:
        merged[str(key)] = code
    settings = _settings_for_year(load_settings(), int(agent["year"]))
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = periods
    cassages = _agent_cassages(db, agent["id"], include_pending=True, exclude_id=exclude_id)
    hourly = _agent_hourly(db, agent["id"], include_pending=True, exclude_id=exclude_id)
    result = rule_compute(agent_for_rules, cells_to_list(merged), settings,
                          cassages=cassages, hourly=hourly)
    restant = _balance_restant(result, code)
    if restant is not None and restant < -1e-9:
        return False, result
    return True, result


def _request_cassage_balance(db, agent, code, days=1, exclude_id=None):
    """Solde CA/RTT après réservation des cassages validés et en attente."""
    params = json_loads(agent["params"])
    periods = json_loads(agent["periods"]) if agent["periods"] else []
    settings = _settings_for_year(load_settings(), int(agent["year"]))
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = periods
    cassages = _agent_cassages(db, agent["id"], include_pending=True, exclude_id=exclude_id)
    hourly = _agent_hourly(db, agent["id"], include_pending=True, exclude_id=exclude_id)
    merged = _agent_cells(db, agent["id"])
    merged.update(_pending_cells(db, agent["id"], exclude_id))
    result = rule_compute(agent_for_rules, cells_to_list(merged),
                          settings, cassages=cassages, hourly=hourly)
    dispo = result.get("ca_current_dispo" if code == "CA" else "rtt_current_dispo")
    if dispo is None:
        key = "ca" if code == "CA" else "rtt"
        dispo = ((result.get("solde") or {}).get(key) or {}).get("current_dispo")
    return (dispo is not None and dispo >= float(days) - 1e-9), result


def _request_hourly_balance(db, agent, code, absence_date, start_time, end_time,
                            hours, exclude_id=None, exclude_hourly_id=None):
    """Solde d'heures CAH/RTTH à la date de l'absence."""
    params = json_loads(agent["params"])
    periods = json_loads(agent["periods"]) if agent["periods"] else []
    settings = _settings_for_year(load_settings(), int(agent["year"]))
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = periods
    cassages = _agent_cassages(db, agent["id"], include_pending=True, exclude_id=exclude_id)
    hourly = _agent_hourly(db, agent["id"], include_pending=True, exclude_id=exclude_id,
                           exclude_hourly_id=exclude_hourly_id)
    recoveries = _agent_recoveries(db, agent["id"])
    result = rule_compute(agent_for_rules, cells_to_list(_agent_cells(db, agent["id"])),
                          settings, cassages=cassages, hourly=hourly,
                          hours_as_of=absence_date, recoveries=recoveries)
    key = {"CAH": "cah", "RTTH": "rth", "RCH": "rch"}.get(code, "cah")
    restant = ((result.get("solde") or {}).get(key) or {}).get("restant")
    return (restant is not None and restant >= float(hours) - 1e-9), result


def _create_special_request(db, agent, data, request_type, user):
    """Crée une demande de cassage ou une demande d'absence en heures."""
    code = (data.get("code") or "").strip().upper()
    comment = (data.get("comment") or "").strip()
    is_responsible = bool(
        user.get("admin")
        or (_user_role(user) in VALIDATOR_ROLES and _can_edit_agent(db, user, agent))
    )
    if is_responsible:
        validator_id, auto, status = None, True, "validee"
    else:
        validator_id, auto, status, _validator_email, _validator_label = _resolve_request_validator(
            db, agent, user
        )
    now = dt.datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    if is_responsible:
        effective_validator = user["id"]
    elif validator_id:
        effective_validator = validator_id
    else:
        effective_validator = agent["validator_id"] or agent["user_id"]
    account_name, manager_name = _validator_snapshot(
        db, effective_validator, agent["year"]
    )

    if request_type == "cassage":
        if code not in CASSAGE_CODES:
            return {"error": "Seuls un CA ou un RTT peuvent être cassés en heures"}, 400
        try:
            days = float(data.get("days") or 1)
        except (TypeError, ValueError):
            days = 1
        if abs(days - 1) > 1e-9:
            return {"error": "Le cassage se fait uniquement sur une journée entière"}, 400
        ok, result = _request_cassage_balance(db, agent, code, days)
        if not ok:
            restant = result.get("ca_current_dispo" if code == "CA" else "rtt_current_dispo")
            return {"error": "Droits insuffisants pour casser un jour : il resterait %s j" % restant}, 400
        valid_until = add_months(now.date(), 6).isoformat() if auto else ""
        cur = db.execute(
            "INSERT INTO leave_requests "
            "(agent_id, user_id, year, request_type, code, cells, days, hours, "
            "absence_date, start_time, end_time, valid_until, status, validator_id, "
            "validator_account_name, validator_manager_name, comment, soumis_le, decide_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent["id"], user["id"], int(agent["year"]), "cassage", code, "[]",
             days, 7.0 * days, "", "", "", valid_until, status, validator_id,
             account_name, manager_name, comment, now_str,
             now_str if auto else None),
        )
        request_id = cur.lastrowid
        _audit_request(db, request_id, "auto_validee" if auto else "soumise", user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        out["auto"] = auto
        return out, 200

    if request_type == "heures":
        if code not in HOUR_CODES:
            return {"error": "Code d'heures non autorisé"}, 400
        absence_date = str(data.get("absence_date") or data.get("date") or "").strip()
        try:
            ad = dt.date.fromisoformat(absence_date[:10])
        except (TypeError, ValueError):
            return {"error": "Date d'absence invalide"}, 400
        if ad.year != int(agent["year"]):
            return {"error": "La date doit être dans l'année de la fiche"}, 400
        start_time = str(data.get("start_time") or "").strip()
        end_time = str(data.get("end_time") or "").strip()
        computed = _hours_between(start_time, end_time)
        if computed is None:
            return {"error": "Horaires invalides : l'heure de fin doit suivre l'heure de début"}, 400
        try:
            hours = float(data.get("hours") or computed)
        except (TypeError, ValueError):
            hours = computed
        if abs(hours - computed) > 0.02:
            return {"error": "La durée ne correspond pas aux horaires saisis"}, 400
        if hours <= 0:
            return {"error": "La durée doit être supérieure à zéro"}, 400
        if _hourly_overlaps(db, agent["id"], absence_date, start_time, end_time):
            return {"error": "Cette plage horaire chevauche une absence existante ou une demande en attente"}, 400
        ok, result = _request_hourly_balance(
            db, agent, code, absence_date, start_time, end_time, hours
        )
        if not ok:
            restant = ((result.get("solde") or {}).get("cah" if code == "CAH" else "rth") or {}).get("restant")
            return {"error": "Solde d'heures insuffisant : il resterait %s h" % restant}, 400
        cur = db.execute(
            "INSERT INTO leave_requests "
            "(agent_id, user_id, year, request_type, code, cells, days, hours, "
            "absence_date, start_time, end_time, valid_until, status, validator_id, "
            "validator_account_name, validator_manager_name, comment, soumis_le, decide_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent["id"], user["id"], int(agent["year"]), "heures", code, "[]",
             round(hours / 7.0, 6), hours, absence_date, start_time, end_time,
             "", status, validator_id, account_name, manager_name, comment,
             now_str, now_str if auto else None),
        )
        request_id = cur.lastrowid
        if auto:
            row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
            _write_hourly_absence(db, row, user["id"])
        _audit_request(db, request_id, "auto_validee" if auto else "soumise", user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        out["auto"] = auto
        return out, 200

    if request_type == "recuperation":
        if code != "RCH":
            return {"error": "Code d'heures de récupération invalide"}, 400
        absence_date = str(data.get("absence_date") or data.get("date") or "").strip()
        try:
            ad = dt.date.fromisoformat(absence_date[:10])
        except (TypeError, ValueError):
            return {"error": "Date de réalisation invalide"}, 400
        if ad.year != int(agent["year"]):
            return {"error": "La date doit être dans l'année de la fiche"}, 400
        try:
            hours = float(data.get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0
        if hours <= 0:
            return {"error": "Le nombre d'heures doit être supérieur à zéro"}, 400
        valid_until = add_months(ad, 6).isoformat() if auto else ""
        cur = db.execute(
            "INSERT INTO leave_requests "
            "(agent_id, user_id, year, request_type, code, cells, days, hours, "
            "absence_date, start_time, end_time, valid_until, status, validator_id, "
            "validator_account_name, validator_manager_name, comment, soumis_le, decide_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent["id"], user["id"], int(agent["year"]), "recuperation", "RCH", "[]",
             round(hours / 7.0, 6), hours, absence_date, "", "", valid_until,
             status, validator_id, account_name, manager_name, comment,
             now_str, now_str if auto else None),
        )
        request_id = cur.lastrowid
        _audit_request(db, request_id, "auto_validee" if auto else "soumise", user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        out["auto"] = auto
        return out, 200

    return {"error": "Type de demande inconnu"}, 400


def _request_allocated_hours(db, agent, request_id):
    """Heures déjà consommées sur un cassage donné (FIFO)."""
    params = json_loads(agent["params"])
    periods = json_loads(agent["periods"]) if agent["periods"] else []
    settings = _settings_for_year(load_settings(), int(agent["year"]))
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = periods
    cassages = _agent_cassages(db, agent["id"])
    hourly = _agent_hourly(db, agent["id"])
    recoveries = _agent_recoveries(db, agent["id"])
    result = rule_compute(agent_for_rules, cells_to_list(_agent_cells(db, agent["id"])),
                          settings, cassages=cassages, hourly=hourly,
                          recoveries=recoveries)
    row = db.execute(
        "SELECT code, request_type FROM leave_requests WHERE id=?", (request_id,)
    ).fetchone()
    if not row:
        return 0.0
    if row["request_type"] == "recuperation":
        key = "rch"
    else:
        key = "cah" if row["code"] == "CA" else "rth"
    allocated = ((result.get("solde") or {}).get(key) or {}).get("allocated") or {}
    return float(allocated.get(request_id) or 0)


def _write_request_cells(db, agent_id, cells, code):
    db.executemany(
        "INSERT INTO cells (agent_id, jour, code) VALUES (?,?,?) "
        "ON CONFLICT(agent_id, jour) DO UPDATE SET code=excluded.code",
        [(agent_id, int(key), code) for key in cells],
    )
    db.execute("UPDATE agents SET modifie_le=CURRENT_TIMESTAMP WHERE id=?", (agent_id,))


def _write_hourly_absence(db, row, actor_id=None):
    """Enregistre l'absence horaire d'une demande validée (idempotent)."""
    exists = db.execute(
        "SELECT id FROM hourly_absences WHERE request_id=?", (row["id"],)
    ).fetchone()
    if exists:
        return
    db.execute(
        "INSERT INTO hourly_absences "
        "(agent_id, year, absence_date, code, start_time, end_time, hours, request_id, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (row["agent_id"], row["year"], row["absence_date"], row["code"],
         row["start_time"], row["end_time"], row["hours"], row["id"], actor_id),
    )
    db.execute("UPDATE agents SET modifie_le=CURRENT_TIMESTAMP WHERE id=?", (row["agent_id"],))


def _delete_hourly_absence(db, request_id):
    db.execute("DELETE FROM hourly_absences WHERE request_id=?", (request_id,))


def _audit_request(db, request_id, action, actor_id, comment=""):
    real = getattr(request, "real_user", None)
    if real and actor_id != real["id"]:
        comment = ((comment or "") + " [par %s, en tant que]" % real["login"]).strip()
    db.execute(
        "INSERT INTO leave_request_events (request_id, action, actor_id, comment) VALUES (?,?,?,?)",
        (request_id, action, actor_id, comment or ""),
    )


def _login_for_user(db, user_id):
    if not user_id:
        return ""
    row = db.execute("SELECT login FROM users WHERE id=?", (int(user_id),)).fetchone()
    return row["login"] if row else str(user_id)


def _audit_user(db, target_id, target_login, actor, action, field="",
                old_value="", new_value="", comment=""):
    """Trace une modification de compte sans jamais stocker de mot de passe."""
    actor = actor or {}
    real = getattr(request, "real_user", None)
    if real and actor.get("id") != real["id"]:
        comment = ((comment or "") + " [en tant que %s]" % (actor.get("login") or "?")).strip()
        actor = real
    db.execute(
        "INSERT INTO user_audit "
        "(user_id, target_login, actor_id, actor_login, action, field, old_value, new_value, comment) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            target_id,
            target_login or "",
            actor.get("id"),
            actor.get("login") or "",
            action,
            field or "",
            "" if old_value is None else str(old_value),
            "" if new_value is None else str(new_value),
            comment or "",
        ),
    )


def _manager_name_for_user(db, user_id, year):
    """Nom de l'agent marqué « responsable de l'unité » pour ce compte valideur."""
    if not user_id:
        return ""
    try:
        year = int(year)
    except (TypeError, ValueError):
        return ""
    row = db.execute(
        "SELECT nom, prenom FROM agents "
        "WHERE user_id=? AND year=? AND is_manager=1 ORDER BY id LIMIT 1",
        (int(user_id), year),
    ).fetchone()
    if not row:
        return ""
    return ("%s %s" % (row["nom"], row["prenom"] or "")).strip()


def _validator_snapshot(db, validator_id, year):
    """Nom du compte valideur + nom du responsable d'unité, au moment T."""
    if not validator_id:
        return "", ""
    user = db.execute(
        "SELECT nom, login FROM users WHERE id=?", (int(validator_id),)
    ).fetchone()
    account = ((user["nom"] or user["login"] or "") if user else "")
    manager = _manager_name_for_user(db, validator_id, year)
    return account, manager


def _validator_group_label(account, manager):
    # Le groupe est le compte valideur ; le responsable d'unité est affiché
    # dans sa propre colonne, avec son nom historisé pour chaque demande.
    account = (account or "").strip()
    manager = (manager or "").strip()
    return account or manager


def _request_row(db, request_id):
    row = db.execute(
        "SELECT r.*, TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, "
        "u.login AS proprietaire, u.nom AS proprietaire_nom, "
        "v.login AS validator_login, v.nom AS validator_nom "
        "FROM leave_requests r "
        "JOIN agents a ON a.id=r.agent_id "
        "JOIN users u ON u.id=r.user_id "
        "LEFT JOIN users v ON v.id=r.validator_id "
        "WHERE r.id=?",
        (request_id,),
    ).fetchone()
    if not row:
        return None
    out = row_to_dict(row)
    try:
        out["cells"] = json_loads(row["cells"])
    except (ValueError, TypeError):
        out["cells"] = []
    out["validator_account_name"] = row["validator_account_name"] or ""
    out["validator_manager_name"] = row["validator_manager_name"] or ""
    if (row["validator_id"] and not out["validator_account_name"]
            and not out["validator_manager_name"]):
        account, manager = _validator_snapshot(db, row["validator_id"], row["year"])
        out["validator_account_name"] = (
            account or row["validator_nom"] or row["validator_login"] or ""
        )
        out["validator_manager_name"] = manager
    out["validator_display_name"] = (
        out["validator_manager_name"] or out["validator_account_name"]
    )
    return out


@app.route("/api/requests", methods=["GET"])
@login_required
def requests_list():
    scope = (request.args.get("scope") or "mine").strip()
    year = _request_year()
    status = request.args.get("status")
    db = get_db()
    sql = "SELECT r.id FROM leave_requests r JOIN agents a ON a.id=r.agent_id WHERE r.year=?"
    params = [year]
    if scope == "mine":
        sql += " AND (r.user_id=? OR a.agent_user_id=?)"
        params.extend([request.user["id"], request.user["id"]])
    elif scope == "to_validate":
        if request.user.get("admin"):
            sql += " AND r.status IN ('en_attente','annulation_demandee')"
        else:
            ids = _scope_ids(db, request.user)
            marks = ",".join("?" for _ in ids)
            sql += (
                " AND (r.validator_id IN (%s) OR "
                "(r.validator_id IS NULL AND COALESCE(a.validator_id, a.user_id) IN (%s))) "
                "AND r.status IN ('en_attente','annulation_demandee')"
                % (marks, marks)
            )
            params.extend(ids * 2)
    elif scope == "perimeter":
        if request.user.get("admin"):
            pass
        elif _user_role(request.user) in VALIDATOR_ROLES:
            ids = _scope_ids(db, request.user)
            marks = ",".join("?" for _ in ids)
            sql += (
                " AND (r.validator_id IN (%s) OR "
                "(r.validator_id IS NULL AND COALESCE(a.validator_id, a.user_id) IN (%s)))"
                % (marks, marks)
            )
            params.extend(ids * 2)
        else:
            db.close()
            return jsonify({"error": "Accès réservé aux valideurs"}), 403
    elif scope == "all":
        if not request.user.get("admin"):
            db.close()
            return jsonify({"error": "Accès réservé à l'administrateur"}), 403
    else:
        db.close()
        return jsonify({"error": "Périmètre inconnu"}), 400
    if status and scope != "to_validate":
        sql += " AND r.status=?"
        params.append(status)
    sql += " ORDER BY r.cree_le DESC, r.id DESC"
    ids = [r["id"] for r in db.execute(sql, params).fetchall()]
    out = [x for x in (_request_row(db, rid) for rid in ids) if x]
    scope_ids = set(_scope_ids(db, request.user))
    for item in out:
        vid = item.get("validator_id")
        if vid is not None:
            vid = int(vid)
            if vid == request.user["id"]:
                item["validator_scope"] = "direct"
            elif vid in scope_ids:
                item["validator_scope"] = "subordinate"
            else:
                item["validator_scope"] = "other"
            account = (
                item.get("validator_account_name") or item.get("validator_nom")
                or item.get("validator_login") or ""
            )
            manager = item.get("validator_manager_name") or ""
            item["validator_account_name"] = account
            item["validator_manager_name"] = manager
            item["validator_group_id"] = vid
            item["validator_group_label"] = (
                _validator_group_label(account, manager) or ("Valideur #%s" % vid)
            )
        else:
            agent = _agent_by_id(db, item["agent_id"])
            responsible_id = (
                (agent["validator_id"] or agent["user_id"]) if agent else item.get("user_id")
            )
            if responsible_id == request.user["id"]:
                item["validator_scope"] = "direct"
            elif responsible_id in scope_ids:
                item["validator_scope"] = "subordinate"
            else:
                item["validator_scope"] = "other"
            item["validator_group_id"] = responsible_id
            account = item.get("validator_account_name") or ""
            manager = item.get("validator_manager_name") or ""
            if not account and not manager:
                account, manager = _validator_snapshot(
                    db, responsible_id, item.get("year")
                )
            if not account and agent:
                ref_id = agent["validator_id"] or agent["user_id"]
                ref = db.execute("SELECT nom, login FROM users WHERE id=?", (ref_id,)).fetchone()
                if ref:
                    account = ref["nom"] or ref["login"] or ""
            if not account:
                account = item.get("proprietaire_nom") or item.get("proprietaire") or ""
            item["validator_account_name"] = account
            item["validator_manager_name"] = manager
            item["validator_display_name"] = manager or account
            item["validator_group_label"] = (
                _validator_group_label(account, manager) or account
            )
    db.close()
    return jsonify(out)


@app.route("/api/requests/counts", methods=["GET"])
@login_required
def requests_counts():
    db = get_db()
    mine = db.execute(
        "SELECT COUNT(*) AS c FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
        "WHERE (r.user_id=? OR a.agent_user_id=?) "
        "AND r.status IN ('en_attente','annulation_demandee')",
        (request.user["id"], request.user["id"]),
    ).fetchone()["c"]
    if request.user.get("admin"):
        to_validate = db.execute(
            "SELECT COUNT(*) AS c FROM leave_requests "
            "WHERE status IN ('en_attente','annulation_demandee')"
        ).fetchone()["c"]
    else:
        ids = _scope_ids(db, request.user)
        marks = ",".join("?" for _ in ids)
        to_validate = db.execute(
            "SELECT COUNT(*) AS c FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
            "WHERE (r.validator_id IN (%s) OR "
            "(r.validator_id IS NULL AND COALESCE(a.validator_id, a.user_id) IN (%s))) "
            "AND r.status IN ('en_attente','annulation_demandee')"
            % (marks, marks),
            ids * 2,
        ).fetchone()["c"]
    db.close()
    return jsonify({"mine_pending": mine, "to_validate": to_validate})


@app.route("/api/reminders", methods=["GET"])
@login_required
def reminders_list():
    """Demandes en attente depuis plus de N jours, dans le périmètre courant."""
    try:
        days = int(request.args.get("days") or 3)
    except (TypeError, ValueError):
        days = 3
    days = max(1, min(days, 60))
    db = get_db()
    sql = (
        "SELECT r.id, r.code, r.status, r.soumis_le, r.cree_le, "
        "TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, "
        "v.login AS validator_login, v.nom AS validator_nom, " + SQL_DAYS_SINCE_SUBMIT + " AS jours "
        "FROM leave_requests r "
        "JOIN agents a ON a.id=r.agent_id "
        "LEFT JOIN users v ON v.id=r.validator_id "
        "WHERE r.status IN ('en_attente','annulation_demandee') "
        "AND COALESCE(r.soumis_le, r.cree_le) < " + SQL_NOW_MINUS
    )
    params = ["-%d days" % days]
    role = _user_role(request.user)
    if request.user.get("admin"):
        pass
    elif role == "agent":
        sql += " AND (r.user_id=? OR a.agent_user_id=?)"
        params.extend([request.user["id"], request.user["id"]])
    else:
        ids = _scope_ids(db, request.user)
        if not ids:
            db.close()
            return jsonify({"count": 0, "items": []})
        marks = ",".join("?" for _ in ids)
        sql += (
            " AND (r.validator_id IN (%s) OR "
            "(r.validator_id IS NULL AND COALESCE(a.validator_id, a.user_id) IN (%s)))"
            % (marks, marks)
        )
        params.extend(ids * 2)
    sql += " ORDER BY r.soumis_le ASC, r.id ASC LIMIT 100"
    rows = db.execute(sql, params).fetchall()
    db.close()
    items = [row_to_dict(r) for r in rows]
    return jsonify({"count": len(items), "items": items})


@app.route("/api/requests", methods=["POST"])
@login_required
def requests_create():
    is_multipart = (request.content_type or "").startswith("multipart/form-data")
    if is_multipart:
        data = request.form
        raw_cells = data.get("cells")
        try:
            cells_raw = json.loads(raw_cells) if raw_cells else None
        except (ValueError, TypeError):
            cells_raw = None
        upload = request.files.get("attachment")
    else:
        data = request.get_json(force=True) or {}
        cells_raw = data.get("cells")
        upload = None
    try:
        agent_id = int(data.get("agent_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Fiche invalide"}), 400
    request_type = (data.get("request_type") or "absence").strip().lower()
    if request_type not in ("absence", "cassage", "heures", "recuperation"):
        return jsonify({"error": "Type de demande inconnu"}), 400
    code = (data.get("code") or "").strip()
    cells = _parse_request_cells(cells_raw)
    comment = (data.get("comment") or "").strip()

    attachment_name = ""
    attachment_stored = ""
    attachment_size = 0
    attachment_mime = ""
    attachment_blob = None
    if upload and upload.filename:
        attachment_name = secure_filename(upload.filename) or "piece-jointe"
        ext = os.path.splitext(attachment_name)[1].lower()
        if ext not in ALLOWED_ATTACHMENT_EXT:
            return jsonify({"error": "Format de pièce jointe non autorisé"}), 400
        attachment_blob = upload.read()
        attachment_size = len(attachment_blob)
        if attachment_size > MAX_ATTACHMENT_SIZE:
            return jsonify({"error": "Pièce jointe trop volumineuse (5 Mo maximum)"}), 400
        attachment_mime = upload.mimetype or ""
        attachment_stored = uuid.uuid4().hex + ext

    db = get_db()
    agent = _agent_by_id(db, agent_id)
    if not agent or not _can_view_agent(db, request.user, agent):
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    is_agent_user = agent["agent_user_id"] == request.user["id"]
    is_responsible = bool(
        request.user.get("admin")
        or (_user_role(request.user) in VALIDATOR_ROLES
            and _can_edit_agent(db, request.user, agent))
    )
    if request_type in ("cassage", "heures", "recuperation"):
        if not (is_agent_user or is_responsible):
            db.close()
            return jsonify({"error": "Vous n'êtes pas responsable de cette fiche"}), 403
    elif not (is_agent_user or request.user.get("admin")):
        db.close()
        return jsonify({"error": "Vous ne pouvez demander que pour votre propre fiche"}), 403
    if request_type in ("cassage", "heures", "recuperation"):
        result, status = _create_special_request(db, agent, data, request_type, request.user)
        db.close()
        return jsonify(result), status
    if code not in _requestable_codes(int(agent["year"])):
        db.close()
        return jsonify({"error": "Code d'absence non autorisé"}), 400
    if cells is None or not cells:
        db.close()
        return jsonify({"error": "Sélectionnez au moins une demi-journée"}), 400
    if any(not _cell_valid(key, agent["year"]) for key in cells):
        db.close()
        return jsonify({"error": "Sélection invalide pour l'année de la fiche"}), 400
    existing = _agent_cells(db, agent_id)
    if any(str(key) in existing for key in cells):
        db.close()
        return jsonify({"error": "Une absence est déjà saisie sur une des cases sélectionnées"}), 400
    pending = _pending_cells(db, agent_id)
    if any(str(key) in pending for key in cells):
        db.close()
        return jsonify({"error": "Une demande est déjà en attente sur une des cases sélectionnées"}), 400
    hourly_occupied = _hourly_occupied_half(db, agent_id)
    if any(str(key) in hourly_occupied for key in cells):
        db.close()
        return jsonify({"error": "Une absence en heures existe déjà sur une des demi-journées sélectionnées"}), 400
    ok, result = _request_balance(db, agent, cells, code)
    if not ok:
        restant = _balance_restant(result, code)
        db.close()
        return jsonify({"error": "Solde insuffisant : il resterait %s j" % restant}), 400
    ca_prev = ca_prev_code(_settings_for_year(load_settings(), int(agent["year"])))
    if code == ca_prev:
        rel_initial = result.get("reliquat_initial") or 0
        ca_prev_used = (result.get("counts") or {}).get("ca26") or 0
        if rel_initial <= 0 or ca_prev_used > rel_initial:
            db.close()
            return jsonify({"error": "Aucun reliquat CA n-1 disponible"}), 400
    validator_id = agent["validator_id"] or _request_validator(db, request.user)
    auto = validator_id is None
    status = "validee" if auto else "en_attente"
    validator_email = ""
    validator_label = ""
    if validator_id is not None:
        validator = db.execute(
            "SELECT login, nom, email FROM users WHERE id=?", (validator_id,)
        ).fetchone()
        if validator:
            validator_email = validator["email"] or ""
            validator_label = validator["nom"] or validator["login"] or ""
    agent_name = ("%s %s" % (agent["nom"], agent["prenom"] or "")).strip()
    agent_year = int(agent["year"])
    effective_validator = validator_id or agent["validator_id"] or agent["user_id"]
    account_name, manager_name = _validator_snapshot(db, effective_validator, agent_year)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        "INSERT INTO leave_requests "
        "(agent_id, user_id, year, code, cells, days, status, validator_id, "
        "validator_account_name, validator_manager_name, comment, soumis_le, decide_le) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (agent_id, request.user["id"], int(agent["year"]), code, json_dumps(cells),
         len(cells) / 2.0, status, validator_id, account_name, manager_name,
         comment, now, now if auto else None),
    )
    request_id = cur.lastrowid
    if auto:
        _write_request_cells(db, agent_id, cells, code)
        _audit_request(db, request_id, "auto_validee", request.user["id"], comment)
    else:
        _audit_request(db, request_id, "soumise", request.user["id"], comment)
    if attachment_blob is not None:
        path = os.path.join(UPLOAD_DIR, attachment_stored)
        try:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(attachment_blob)
        except OSError:
            try:
                os.remove(path)
            except OSError:
                pass
            db.rollback()
            db.close()
            return jsonify({"error": "Enregistrement de la pièce jointe impossible"}), 500
        db.execute(
            "UPDATE leave_requests SET attachment_name=?, attachment_file=?, "
            "attachment_size=?, attachment_mime=? WHERE id=?",
            (attachment_name, attachment_stored, attachment_size, attachment_mime, request_id),
        )
    db.commit()
    out = _request_row(db, request_id)
    out["auto"] = auto
    db.close()
    if not auto:
        code_label = code
        for item in (load_settings().get("codes") or []):
            if item.get("code") == code:
                code_label = item.get("libelle") or code
                break
        notify_validator(
            validator_email=validator_email,
            validator_name=validator_label,
            agent_name=agent_name,
            code=code,
            code_label=code_label,
            cells=cells,
            year=agent_year,
            days=len(cells) / 2.0,
            comment=comment,
            fiche_id=agent_id,
            request_id=request_id,
        )
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/approve", methods=["POST"])
@login_required
def requests_approve(request_id):
    data = request.get_json(force=True) or {}
    comment = (data.get("comment") or "").strip()
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "en_attente":
        db.close()
        return jsonify({"error": "Cette demande n'est plus en attente"}), 400
    if not _can_validate_request(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous n'êtes pas le responsable de cette demande"}), 403
    agent = _agent_by_id(db, row["agent_id"])
    if not agent:
        db.close()
        return jsonify({"error": "Fiche introuvable"}), 404
    request_type = (row["request_type"] or "absence")
    if request_type == "cassage":
        ok, result = _request_cassage_balance(
            db, agent, row["code"], row["days"] or 1, exclude_id=request_id
        )
        if not ok:
            restant = result.get("ca_current_dispo" if row["code"] == "CA" else "rtt_current_dispo")
            db.close()
            return jsonify({"error": "Droits insuffisants pour casser un jour : il resterait %s j" % restant}), 400
        valid_until = add_months(dt.date.today(), 6).isoformat()
        db.execute(
            "UPDATE leave_requests SET status='validee', decision_comment=?, "
            "decide_le=CURRENT_TIMESTAMP, valid_until=? WHERE id=?",
            (comment, valid_until, request_id),
        )
        _audit_request(db, request_id, "validee", request.user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        db.close()
        return jsonify(out)
    if request_type == "heures":
        if _hourly_overlaps(
            db, row["agent_id"], row["absence_date"], row["start_time"], row["end_time"],
            exclude_request_id=request_id,
        ):
            db.close()
            return jsonify({"error": "Cette plage horaire chevauche une absence existante"}), 409
        ok, result = _request_hourly_balance(
            db, agent, row["code"], row["absence_date"], row["start_time"],
            row["end_time"], row["hours"], exclude_id=request_id,
        )
        if not ok:
            restant = ((result.get("solde") or {}).get("cah" if row["code"] == "CAH" else "rth") or {}).get("restant")
            db.close()
            return jsonify({"error": "Solde d'heures insuffisant : il resterait %s h" % restant}), 400
        db.execute(
            "UPDATE leave_requests SET status='validee', decision_comment=?, "
            "decide_le=CURRENT_TIMESTAMP WHERE id=?",
            (comment, request_id),
        )
        _write_hourly_absence(db, row, request.user["id"])
        _audit_request(db, request_id, "validee", request.user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        db.close()
        return jsonify(out)
    if request_type == "recuperation":
        try:
            ad = dt.date.fromisoformat(str(row["absence_date"])[:10])
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "Date de réalisation invalide"}), 400
        valid_until = add_months(ad, 6).isoformat()
        db.execute(
            "UPDATE leave_requests SET status='validee', decision_comment=?, "
            "decide_le=CURRENT_TIMESTAMP, valid_until=? WHERE id=?",
            (comment, valid_until, request_id),
        )
        _audit_request(db, request_id, "validee", request.user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        db.close()
        return jsonify(out)
    try:
        cells = json_loads(row["cells"])
    except (ValueError, TypeError):
        cells = []
    existing = _agent_cells(db, row["agent_id"])
    if any(str(key) in existing for key in cells):
        db.close()
        return jsonify({"error": "Une absence a été saisie entre-temps sur une des cases"}), 409
    hourly_occupied = _hourly_occupied_half(db, row["agent_id"], exclude_request_id=request_id)
    if any(str(key) in hourly_occupied for key in cells):
        db.close()
        return jsonify({"error": "Une absence en heures existe entre-temps sur une des demi-journées"}), 409
    ok, result = _request_balance(db, agent, cells, row["code"], exclude_id=request_id)
    if not ok:
        restant = _balance_restant(result, row["code"])
        db.close()
        return jsonify({"error": "Solde insuffisant : il resterait %s j" % restant}), 400
    _write_request_cells(db, row["agent_id"], cells, row["code"])
    db.execute(
        "UPDATE leave_requests SET status='validee', decision_comment=?, decide_le=CURRENT_TIMESTAMP WHERE id=?",
        (comment, request_id),
    )
    _audit_request(db, request_id, "validee", request.user["id"], comment)
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/refuse", methods=["POST"])
@login_required
def requests_refuse(request_id):
    data = request.get_json(force=True) or {}
    comment = (data.get("comment") or "").strip()
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "en_attente":
        db.close()
        return jsonify({"error": "Cette demande n'est plus en attente"}), 400
    if not _can_validate_request(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous n'êtes pas le responsable de cette demande"}), 403
    db.execute(
        "UPDATE leave_requests SET status='refusee', decision_comment=?, decide_le=CURRENT_TIMESTAMP WHERE id=?",
        (comment, request_id),
    )
    _audit_request(db, request_id, "refusee", request.user["id"], comment)
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/cancel", methods=["POST"])
@login_required
def requests_cancel(request_id):
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "en_attente":
        db.close()
        return jsonify({"error": "Seule une demande en attente peut être annulée"}), 400
    if not _can_cancel_request(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous ne pouvez pas annuler cette demande"}), 403
    db.execute(
        "UPDATE leave_requests SET status='annulee', decide_le=CURRENT_TIMESTAMP WHERE id=?",
        (request_id,),
    )
    _audit_request(db, request_id, "annulee", request.user["id"])
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/cancel-request", methods=["POST"])
@login_required
def requests_cancel_request(request_id):
    data = request.get_json(force=True) or {}
    reason = (data.get("comment") or "").strip()
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "validee":
        db.close()
        return jsonify({"error": "Seule une demande validée peut faire l'objet d'une demande d'annulation"}), 400
    if not _can_cancel_request(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous ne pouvez pas demander l'annulation de cette demande"}), 403
    if (row["request_type"] or "absence") in ("cassage", "recuperation"):
        agent = _agent_by_id(db, row["agent_id"])
        if agent and _request_allocated_hours(db, agent, request_id) > 0:
            db.close()
            return jsonify({"error": "Impossible d'annuler : des heures ont déjà été consommées"}), 400
    db.execute(
        "UPDATE leave_requests SET status='annulation_demandee', "
        "cancel_requested_at=CURRENT_TIMESTAMP, cancel_requested_by=?, cancel_reason=? WHERE id=?",
        (request.user["id"], reason, request_id),
    )
    _audit_request(db, request_id, "annulation_demandee", request.user["id"], reason)
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/cancel-approve", methods=["POST"])
@login_required
def requests_cancel_approve(request_id):
    data = request.get_json(force=True) or {}
    comment = (data.get("comment") or "").strip()
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "annulation_demandee":
        db.close()
        return jsonify({"error": "Cette demande n'a pas d'annulation en attente"}), 400
    if not _can_approve_cancel(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous n'êtes pas le responsable de cette demande"}), 403
    request_type = (row["request_type"] or "absence")
    if request_type in ("cassage", "recuperation"):
        agent = _agent_by_id(db, row["agent_id"])
        if agent and _request_allocated_hours(db, agent, request_id) > 0:
            db.close()
            return jsonify({"error": "Impossible d'annuler : des heures ont déjà été consommées"}), 400
        db.execute(
            "UPDATE leave_requests SET status='annulee', cancel_decided_at=CURRENT_TIMESTAMP, "
            "cancel_decided_by=?, cancel_decision_comment=? WHERE id=?",
            (request.user["id"], comment, request_id),
        )
        _audit_request(db, request_id, "annulation_validee", request.user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        db.close()
        return jsonify(out)
    if request_type == "heures":
        _delete_hourly_absence(db, request_id)
        db.execute(
            "UPDATE leave_requests SET status='annulee', cancel_decided_at=CURRENT_TIMESTAMP, "
            "cancel_decided_by=?, cancel_decision_comment=? WHERE id=?",
            (request.user["id"], comment, request_id),
        )
        _audit_request(db, request_id, "annulation_validee", request.user["id"], comment)
        db.commit()
        out = _request_row(db, request_id)
        db.close()
        return jsonify(out)
    try:
        cells = json_loads(row["cells"])
    except (ValueError, TypeError):
        cells = []
    for key in cells:
        db.execute(
            "DELETE FROM cells WHERE agent_id=? AND jour=? AND code=?",
            (row["agent_id"], int(key), row["code"]),
        )
    db.execute("UPDATE agents SET modifie_le=CURRENT_TIMESTAMP WHERE id=?", (row["agent_id"],))
    db.execute(
        "UPDATE leave_requests SET status='annulee', cancel_decided_at=CURRENT_TIMESTAMP, "
        "cancel_decided_by=?, cancel_decision_comment=? WHERE id=?",
        (request.user["id"], comment, request_id),
    )
    _audit_request(db, request_id, "annulation_validee", request.user["id"], comment)
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/cancel-refuse", methods=["POST"])
@login_required
def requests_cancel_refuse(request_id):
    data = request.get_json(force=True) or {}
    comment = (data.get("comment") or "").strip()
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    if row["status"] != "annulation_demandee":
        db.close()
        return jsonify({"error": "Cette demande n'a pas d'annulation en attente"}), 400
    if not _can_approve_cancel(db, request.user, row):
        db.close()
        return jsonify({"error": "Vous n'êtes pas le responsable de cette demande"}), 403
    db.execute(
        "UPDATE leave_requests SET status='validee', cancel_decided_at=CURRENT_TIMESTAMP, "
        "cancel_decided_by=?, cancel_decision_comment=? WHERE id=?",
        (request.user["id"], comment, request_id),
    )
    _audit_request(db, request_id, "annulation_refusee", request.user["id"], comment)
    db.commit()
    out = _request_row(db, request_id)
    db.close()
    return jsonify(out)


@app.route("/api/requests/<int:request_id>/attachment", methods=["GET"])
@login_required
def requests_attachment(request_id):
    db = get_db()
    row = db.execute("SELECT * FROM leave_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Demande introuvable"}), 404
    agent = _agent_by_id(db, row["agent_id"])
    allowed = (
        request.user.get("admin")
        or row["user_id"] == request.user["id"]
        or row["validator_id"] == request.user["id"]
        or (agent is not None and _can_view_agent(db, request.user, agent))
    )
    if not allowed:
        db.close()
        return jsonify({"error": "Accès refusé"}), 403
    stored = os.path.basename(row["attachment_file"] or "")
    if not stored:
        db.close()
        return jsonify({"error": "Aucune pièce jointe"}), 404
    path = os.path.join(UPLOAD_DIR, stored)
    if not os.path.isfile(path):
        db.close()
        return jsonify({"error": "Pièce jointe introuvable"}), 404
    download_name = row["attachment_name"] or "piece-jointe"
    db.close()
    return send_file(path, as_attachment=True, download_name=download_name)


# --------------------------------------------------------------------------- #
#  Calcul
# --------------------------------------------------------------------------- #
def _validate_params(params, year=None):
    """Contrôles cohérents avec les validations du classeur Excel."""
    if year is None:
        year = int(load_settings().get("general", {}).get("year", 2027))
    year = int(year)
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)

    def _check_date(value, label):
        if not value:
            return None
        try:
            d = dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            return "%s : date invalide" % label
        if not (start <= d <= end):
            return "%s : la date doit être comprise dans l'année %d" % (label, year)
        return None

    def _check_num(value, label, lo, hi):
        if value in ("", None):
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "%s : valeur numérique invalide" % label
        if not (lo <= v <= hi):
            return "%s : la valeur doit être comprise entre %s et %s" % (label, lo, hi)
        return None

    checks = [
        _check_date(params.get("date_arrivee"), "Date d'arrivée"),
        _check_date(params.get("date_depart"), "Date de départ"),
        _check_date(params.get("conges_ant_dt"), "Congés antérieurs (du)"),
        _check_date(params.get("conges_ant_au"), "Congés antérieurs (au)"),
        _check_num(params.get("reliquat"), "Reliquat", 0, 100),
        _check_num(params.get("solde_cet"), "Solde CET", 0.5, 70),
    ]
    return [c for c in checks if c]


@app.route("/api/compute", methods=["POST"])
@login_required
def api_compute():
    data = request.get_json(force=True) or {}
    params = _normalize_params(data.get("params"))
    try:
        year = int(data.get("year") or load_settings().get("general", {}).get("year", 2027))
    except (TypeError, ValueError):
        year = int(load_settings().get("general", {}).get("year", 2027))
    if not (2000 <= year <= 2100):
        year = int(load_settings().get("general", {}).get("year", 2027))
    errors = _validate_params(params, year)
    if errors:
        return jsonify({"errors": errors}), 400
    settings = _settings_for_year(load_settings(), year)
    cells = cells_to_list(data.get("cells") or {})
    periods = data.get("periods") or []
    if periods:
        normalized = _normalize_periods(periods, params, year)
        periods = normalized if normalized is not None else []
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = periods
    cassages = data.get("cassages") or []
    hourly = data.get("hourly") or []
    recoveries = data.get("recoveries") or []
    result = rule_compute(agent_for_rules, cells, settings,
                          cassages=cassages, hourly=hourly,
                          recoveries=recoveries)
    return jsonify(result)


# --------------------------------------------------------------------------- #
#  Tableau de bord global
# --------------------------------------------------------------------------- #
def _agent_summary_for_row(agent_row, settings):
    """Synthèse des soldes d'une fiche (ligne `agents` + `proprietaire`) ; {"error": …} si le calcul échoue."""
    params = json_loads(agent_row["params"])
    db = get_db()
    cells_rows = db.execute("SELECT jour, code FROM cells WHERE agent_id=?", (agent_row["id"],)).fetchall()
    cassages = _agent_cassages(db, agent_row["id"])
    hourly = _agent_hourly(db, agent_row["id"])
    recoveries = _agent_recoveries(db, agent_row["id"])
    db.close()
    cells = {str(c["jour"]): c["code"] for c in cells_rows}
    agent_for_rules = dict(params)
    agent_for_rules["periods"] = json_loads(agent_row["periods"]) if agent_row["periods"] else []
    agent_for_rules["id"] = agent_row["id"]
    agent_for_rules["nom"] = ("%s %s" % (agent_row["nom"], agent_row["prenom"] or "")).strip()
    agent_for_rules["owner_id"] = agent_row["user_id"]
    agent_for_rules["owner_name"] = agent_row["proprietaire"]
    agent_for_rules["is_manager"] = agent_row["is_manager"]
    agent_for_rules["updated_at"] = agent_row["modifie_le"]
    try:
        return agent_summary(agent_for_rules, cells_to_list(cells), settings,
                             cassages=cassages, hourly=hourly, recoveries=recoveries)
    except Exception as exc:  # noqa: BLE001 — fiche incomplète ne doit pas casser le dashboard
        return {"id": agent_row["id"], "nom": agent_row["nom"], "error": str(exc)}


@app.route("/api/dashboard", methods=["GET"])
@login_required
def dashboard():
    year = _request_year()
    db = get_db()
    if request.args.get("all") == "1":
        agents = _scope_agents(db, request.user, year)
    elif _user_role(request.user) == "agent":
        agents = db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE a.agent_user_id=? AND a.year=? ORDER BY a.nom",
            (request.user["id"], year),
        ).fetchall()
    else:
        agents = db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE a.user_id=? AND a.year=? ORDER BY a.nom",
            (request.user["id"], year),
        ).fetchall()
    db.close()

    settings = _settings_for_year(load_settings(), year)
    return jsonify([_agent_summary_for_row(agent_row, settings) for agent_row in agents])


@app.route("/api/hr-dashboard", methods=["GET"])
@login_required
def hr_dashboard():
    """Indicateurs RH : absences par unité, taux, retards et RCH à échéance."""
    if _user_role(request.user) == "agent":
        return jsonify({"error": "Accès réservé aux valideurs et administrateurs"}), 403
    year = _request_year()
    db = get_db()
    agents = _scope_agents(db, request.user, year)
    settings = _settings_for_year(load_settings(), year)
    absence_codes = set(ABSENCE_CODES)
    absence_codes.add(ca_prev_code(settings))
    holidays = set()
    for item in settings.get("jours_feries") or []:
        if isinstance(item, (list, tuple)) and item:
            holidays.add(str(item[0])[:10])
    working = 0
    cursor = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    while cursor <= end:
        if cursor.weekday() < 5 and cursor.isoformat() not in holidays:
            working += 1
        cursor += dt.timedelta(days=1)

    groups = {}
    fiche_stats = []
    total_absences = 0.0
    total_capacity = 0.0
    agent_ids = []
    for agent_row in agents:
        agent_ids.append(agent_row["id"])
        params = json_loads(agent_row["params"])
        service = _org_ancestor_name(db, agent_row["user_id"], "service")
        direction = _org_ancestor_name(db, agent_row["user_id"], "direction")
        label = " / ".join(x for x in (direction, service) if x) or "Sans rattachement"
        days_week = float(params.get("jours_hebdo") or 5) or 5
        capacity = working * days_week / 5.0
        marks_codes = ",".join("?" for _ in absence_codes)
        half_days = db.execute(
            "SELECT COUNT(*) FROM cells WHERE agent_id=? AND code IN (%s)" % marks_codes,
            [agent_row["id"]] + list(absence_codes),
        ).fetchone()[0]
        hourly_hours = db.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM hourly_absences "
            "WHERE agent_id=? AND year=? AND code IN ('CAH','RTTH','RCH')",
            (agent_row["id"], int(agent_row["year"])),
        ).fetchone()[0]
        absence_days = half_days / 2.0 + float(hourly_hours or 0) / 7.0
        fiche_stats.append({
            "id": "f:%s" % agent_row["id"],
            "label": ("%s %s" % (agent_row["nom"], agent_row["prenom"] or "")).strip(),
            "role": "agent",
            "kind": "fiche",
            "owner_id": agent_row["user_id"],
            "absences": absence_days,
            "capacity": capacity,
            "rate": round(absence_days / capacity * 100, 2) if capacity else 0,
            "agents": 1,
            "children": [],
            "fiches": [],
        })
        group = groups.setdefault(label, {
            "label": label, "agents": 0, "absences": 0.0, "capacity": 0.0,
        })
        group["agents"] += 1
        group["absences"] += absence_days
        group["capacity"] += capacity
        total_absences += absence_days
        total_capacity += capacity

    scope_ids = set(_scope_ids(db, request.user))
    nodes = {}
    for u in db.execute(
        "SELECT id, login, nom, role, parent_id FROM users"
    ).fetchall():
        if u["id"] not in scope_ids:
            continue
        role = _user_role(row_to_dict(u))
        nodes[u["id"]] = {
            "id": "u:%s" % u["id"],
            "label": u["nom"] or u["login"] or "",
            "role": role,
            "kind": "user",
            "_parent": u["parent_id"],
            "children": [],
            "fiches": [],
        }
    for fiche in fiche_stats:
        owner = nodes.get(fiche["owner_id"])
        if owner:
            owner["fiches"].append(fiche)
    roots = []
    for node in nodes.values():
        parent = nodes.get(node["_parent"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)

    def finalize(node):
        children = [c for c in (finalize(child) for child in node["children"]) if c]
        fiches = node["fiches"]
        if not children and not fiches:
            return None
        node["children"] = sorted(
            children,
            key=lambda c: (-ROLE_LEVELS.get(c.get("role"), 0), c.get("label", "")),
        )
        node["fiches"] = sorted(fiches, key=lambda f: f.get("label", ""))
        node["agents"] = sum(f["agents"] for f in fiches) + sum(c["agents"] for c in children)
        node["absences"] = sum(f["absences"] for f in fiches) + sum(c["absences"] for c in children)
        node["capacity"] = sum(f["capacity"] for f in fiches) + sum(c["capacity"] for c in children)
        node["absences"] = round(node["absences"], 1)
        node["rate"] = round(node["absences"] / node["capacity"] * 100, 2) if node["capacity"] else 0
        node.pop("_parent", None)
        return node

    tree = [n for n in (finalize(root) for root in roots) if n]
    tree.sort(key=lambda n: (-ROLE_LEVELS.get(n.get("role"), 0), n.get("label", "")))

    late_items = []
    rch_items = []
    if agent_ids:
        marks = ",".join("?" for _ in agent_ids)
        late_items = [
            row_to_dict(r) for r in db.execute(
                "SELECT r.id, r.code, r.soumis_le, r.cree_le, "
                "TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, "
                "v.login AS validator_login, v.nom AS validator_nom, " + SQL_DAYS_SINCE_SUBMIT + " AS jours "
                "FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
                "LEFT JOIN users v ON v.id=r.validator_id "
                "WHERE r.agent_id IN (" + marks + ") AND r.status IN ('en_attente','annulation_demandee') "
                "AND COALESCE(r.soumis_le, r.cree_le) < " + SQL_NOW_MINUS + " "
                "ORDER BY r.soumis_le ASC",
                list(agent_ids) + ["-3 days"],
            ).fetchall()
        ]
        today = dt.date.today()
        limit = (today + dt.timedelta(days=30)).isoformat()
        rch_items = [
            row_to_dict(r) for r in db.execute(
                "SELECT r.id, r.hours, r.absence_date, r.valid_until, "
                "TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom "
                "FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
                "WHERE r.agent_id IN (%s) AND r.request_type='recuperation' "
                "AND r.status IN ('validee','annulation_demandee') "
                "AND r.valid_until>=? AND r.valid_until<=? "
                "ORDER BY r.valid_until ASC" % marks,
                agent_ids + [today.isoformat(), limit],
            ).fetchall()
        ]
    db.close()
    by_service = []
    for group in groups.values():
        rate = (group["absences"] / group["capacity"] * 100) if group["capacity"] else 0
        by_service.append({
            "label": group["label"],
            "agents": group["agents"],
            "absences": round(group["absences"], 1),
            "rate": round(rate, 2),
        })
    by_service.sort(key=lambda x: x["label"])
    total_rate = (total_absences / total_capacity * 100) if total_capacity else 0
    return jsonify({
        "year": year,
        "totals": {
            "agents": len(agents),
            "absences": round(total_absences, 1),
            "rate": round(total_rate, 2),
            "late_requests": len(late_items),
            "rch_expiring": len(rch_items),
        },
        "by_service": by_service,
        "tree": tree,
        "late_items": late_items,
        "rch_items": rch_items,
    })


# --------------------------------------------------------------------------- #
#  Planning mensuel (absences de toutes les fiches)
# --------------------------------------------------------------------------- #
@app.route("/api/planning", methods=["GET"])
@login_required
def planning():
    """Absences d'un mois, fiche par fiche, pour le planning d'équipe."""
    settings = load_settings()
    try:
        year = int(request.args.get("year") or settings.get("general", {}).get("year", 2027))
    except (TypeError, ValueError):
        year = int(settings.get("general", {}).get("year", 2027))
    try:
        month = int(request.args.get("month") or 1)
    except (TypeError, ValueError):
        month = 1
    month = max(1, min(12, month))

    db = get_db()
    user_id = request.args.get("user_id")
    if request.args.get("all") == "1":
        if _user_role(request.user) == "agent":
            target = _planning_scope_user(db, request.user)
            agents = _scope_agents(db, target, year)
        else:
            agents = _scope_agents(db, request.user, year)
    elif user_id:
        try:
            target = int(user_id)
        except (TypeError, ValueError):
            target = request.user["id"]
        if target not in set(_scope_ids(db, request.user)):
            db.close()
            return jsonify({"error": "Utilisateur hors de votre périmètre"}), 403
        target_row = db.execute("SELECT * FROM users WHERE id=?", (target,)).fetchone()
        if target_row and _user_role(row_to_dict(target_row)) == "agent":
            agents = db.execute(
                "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
                "WHERE a.agent_user_id=? AND a.year=? ORDER BY a.nom",
                (target, year),
            ).fetchall()
        else:
            agents = db.execute(
                "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
                "WHERE a.user_id=? AND a.year=? ORDER BY a.nom",
                (target, year),
            ).fetchall()
    elif _user_role(request.user) == "agent":
        agents = db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE a.agent_user_id=? AND a.year=? ORDER BY a.nom",
            (request.user["id"], year),
        ).fetchall()
    else:
        agents = db.execute(
            "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id "
            "WHERE a.user_id=? AND a.year=? ORDER BY a.nom",
            (request.user["id"], year),
        ).fetchall()

    out = []
    for a in agents:
        rows = db.execute(
            "SELECT jour, code FROM cells WHERE agent_id=? AND jour>=? AND jour<? ORDER BY jour",
            (a["id"], month * 1000, (month + 1) * 1000),
        ).fetchall()
        params = json_loads(a["params"])
        pending_all = _pending_cells(db, a["id"])
        pending = {
            k: code for k, code in pending_all.items()
            if month * 1000 <= int(k) < (month + 1) * 1000
        }
        cells_out = {str(r["jour"]): r["code"] for r in rows}
        if _user_role(request.user) == "agent":
            # Planning d'équipe : l'agent voit les absences, pas leur nature.
            cells_out = {key: "A" for key in cells_out}
            pending = {key: "A" for key in pending}
        start_iso = dt.date(year, month, 1).isoformat()
        if month == 12:
            end_iso = dt.date(year + 1, 1, 1).isoformat()
        else:
            end_iso = dt.date(year, month + 1, 1).isoformat()
        hourly_out = {}
        for h in db.execute(
            "SELECT absence_date, code, start_time, end_time, hours "
            "FROM hourly_absences WHERE agent_id=? AND absence_date>=? AND absence_date<? "
            "ORDER BY absence_date, start_time",
            (a["id"], start_iso, end_iso),
        ).fetchall():
            for key, part_hours in _hourly_half_parts(h["absence_date"], h["start_time"], h["end_time"]).items():
                item = {
                    "code": "A" if _user_role(request.user) == "agent" else h["code"],
                    "start_time": h["start_time"],
                    "end_time": h["end_time"],
                    "hours": part_hours,
                }
                hourly_out.setdefault(str(key), []).append(item)
        out.append({
            "id": a["id"],
            "nom": a["nom"],
            "prenom": a["prenom"],
            "user_id": a["user_id"],
            "agent_user_id": a["agent_user_id"],
            "proprietaire": a["proprietaire"],
            "is_manager": int(a["is_manager"] or 0),
            "penibilite": params.get("penibilite", ""),
            "cells": cells_out,
            "pending": pending,
            "hourly": hourly_out,
        })
    db.close()
    return jsonify({"year": year, "month": month, "agents": out})


@app.route("/api/scope-users", methods=["GET"])
@login_required
def scope_users():
    """Utilisateurs du périmètre du compte connecté (pour les filtres)."""
    db = get_db()
    if _user_role(request.user) == "agent":
        target = _planning_scope_user(db, request.user)
        ids = _scope_ids(db, target)
    else:
        ids = _scope_ids(db, request.user)
    if not ids:
        db.close()
        return jsonify([])
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        "SELECT id, login, nom, role, parent_id FROM users WHERE id IN (%s) ORDER BY login" % marks,
        ids,
    ).fetchall()
    db.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/validators", methods=["GET"])
@login_required
def validators_list():
    """Comptes valideurs autorisés pour une fiche.

    Sans paramètre : le compte connecté et ses supérieurs hiérarchiques
    (création d'une fiche). Avec agent_id : le propriétaire de la fiche et
    ses supérieurs hiérarchiques.
    """
    db = get_db()
    raw_owner = request.args.get("owner_id")
    raw_agent = request.args.get("agent_id")
    if raw_owner:
        try:
            owner_id = int(raw_owner)
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "Propriétaire invalide"}), 400
        owner = db.execute(
            "SELECT * FROM users WHERE id=? AND actif=1", (owner_id,)
        ).fetchone()
        if not owner or _user_role(row_to_dict(owner)) not in VALIDATOR_ROLES:
            db.close()
            return jsonify({"error": "Le propriétaire doit être un valideur actif"}), 400
        if not request.user.get("admin") and owner_id not in set(_scope_ids(db, request.user)):
            db.close()
            return jsonify({"error": "Ce valideur n'est pas dans votre périmètre"}), 403
    elif raw_agent:
        try:
            aid = int(raw_agent)
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "Fiche invalide"}), 400
        agent = _agent_by_id(db, aid)
        if not agent or not _can_view_agent(db, request.user, agent):
            db.close()
            return jsonify({"error": "Fiche introuvable"}), 404
        owner_id = agent["user_id"]
    else:
        owner_id = request.user["id"]
    rows = _validator_chain(db, owner_id)
    year = _request_year()
    for row in rows:
        row["manager_name"] = _manager_name_for_user(db, row["id"], year)
    db.close()
    return jsonify(rows)


# --------------------------------------------------------------------------- #
#  Frontend
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    if not os.path.isfile(os.path.join(app.static_folder, "index.html")):
        return jsonify({"error": "Frontend non servi par ce conteneur (voir le conteneur frontend)"}), 404
    return send_from_directory(app.static_folder, "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True})


import api_keys  # noqa: E402
import api_v1  # noqa: E402
from openapi_spec import register_docs  # noqa: E402

app.register_blueprint(api_v1.bp)
api_keys.init_admin(app, admin_required)
register_docs(app)
act_as.init_act_as(app, current_user, _audit_user)
import admin_settings  # noqa: E402

admin_settings.init_admin_settings(app, admin_required)


def bootstrap():
    init_db()
    try:
        audit_logs.purge()
    except Exception as exc:  # noqa: BLE001
        print("[boot] Purge des journaux impossible :", exc)
    db = get_db()
    if not db.execute("SELECT id FROM users LIMIT 1").fetchone():
        # Premier démarrage : import des paramètres du classeur + admin par défaut
        try:
            from seed import extract

            db.close()
            extract()
            db = get_db()
        except Exception as exc:  # noqa: BLE001
            print("[boot] Import Excel impossible :", exc)
        generated = not config.INITIAL_ADMIN_PASSWORD
        admin_password = config.INITIAL_ADMIN_PASSWORD or uuid.uuid4().hex[:12]
        db.execute(
            "INSERT INTO users (login, nom, mot_de_passe, admin, role, actif) "
            "VALUES (?,?,?,?,?,1) ON CONFLICT (login) DO NOTHING",
            ("admin", "Administrateur", generate_password_hash(admin_password), 1, "administrateur"),
        )
        db.commit()
        print("[boot] Compte administrateur créé — identifiant : admin")
        if generated:
            print("[boot] Mot de passe initial (affiché une seule fois) : %s" % admin_password)
        print("[boot] Pensez à changer ce mot de passe dans l'onglet Paramétrage > Utilisateurs.")
    db.close()
    start_reminder_scheduler()


if __name__ == "__main__":
    bootstrap()
    app.run(host=config.HOST, port=config.PORT, debug=False)
