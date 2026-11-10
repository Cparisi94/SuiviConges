# -*- coding: utf-8 -*-
"""API publique /api/v1 (lecture seule) pour les applications de la Ville, et /api/status.

Authentification par clé API (`X-API-Key`) avec périmètres — voir api_keys.py. Les listes sont
paginées (`?limit=&offset=`). Les erreurs ont le corps normalisé {"error": "..."}.
La logique de calcul des soldes est celle de l'application (app.py), importée à l'appel
pour éviter une dépendance circulaire.
"""
import datetime as dt
import json
import time

from flask import Blueprint, jsonify, request

import apm
import config
from api_keys import api_key_required
from db import get_db, row_to_dict
from http_utils import error, page_args, paged

bp = Blueprint("api_v1", __name__)


def _core():
    import app as core
    return core


def _year_arg(core):
    try:
        year = int(request.args.get("year") or core._request_year())
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def _key_to_date(year, key):
    """Clé de demi-journée (mois*1000 + jour*10 + 0/1) -> (date ISO, 'matin' | 'apres_midi')."""
    key = int(key)
    month, day, half = key // 1000, (key % 1000) // 10, key % 10
    return dt.date(year, month, day).isoformat(), "matin" if half == 0 else "apres_midi"


def _iso_date(name):
    raw = request.args.get(name)
    if not raw:
        return None
    return dt.date.fromisoformat(raw).isoformat()


# --------------------------------------------------------------------------- #
#  Santé
# --------------------------------------------------------------------------- #
@bp.route("/api/status", methods=["GET"])
@bp.route("/api/v1/status", methods=["GET"])
def status():
    started = time.monotonic()
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        db_state = "ok"
    except Exception:  # noqa: BLE001 — l'état de la base ne doit jamais faire échouer /status
        db_state = "error"
    body = {
        "status": "ok" if db_state == "ok" else "degraded",
        "service": "suivi-conges",
        "database": {"state": db_state, "latency_ms": round((time.monotonic() - started) * 1000)},
        "apm": "configured" if apm.configured() else "not_configured",
        "auth_mode": config.AUTH_MODE,
    }
    return jsonify(body), 200 if db_state == "ok" else 503


# --------------------------------------------------------------------------- #
#  Fiches agents
# --------------------------------------------------------------------------- #
_AGENT_SQL = (
    "SELECT a.id, a.nom, a.prenom, a.email, a.year, a.is_manager, a.modifie_le AS updated_at, "
    "u.login AS owner_login, v.login AS validator_login "
    "FROM agents a JOIN users u ON u.id=a.user_id LEFT JOIN users v ON v.id=a.validator_id "
)


@bp.route("/api/v1/agents", methods=["GET"])
@api_key_required("agents:read")
def agents():
    core = _core()
    year = _year_arg(core)
    if year is None:
        return error("Paramètre year invalide", 400)
    limit, offset = page_args()
    where, params = "WHERE a.year=?", [year]
    q = (request.args.get("q") or "").strip()
    if q:
        where += " AND (a.nom ILIKE ? OR a.prenom ILIKE ?)"
        params += ["%" + q + "%"] * 2
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM agents a " + where, params).fetchone()["c"]
    rows = db.execute(
        _AGENT_SQL + where + " ORDER BY a.nom, a.prenom, a.id LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    db.close()
    return paged([row_to_dict(r) for r in rows], total, limit, offset)


@bp.route("/api/v1/agents/<int:agent_id>", methods=["GET"])
@api_key_required("agents:read")
def agent_detail(agent_id):
    db = get_db()
    row = db.execute(_AGENT_SQL + "WHERE a.id=?", (agent_id,)).fetchone()
    db.close()
    return jsonify(row_to_dict(row)) if row else error("Fiche introuvable", 404)


@bp.route("/api/v1/agents/<int:agent_id>/balance", methods=["GET"])
@api_key_required("balances:read")
def agent_balance(agent_id):
    core = _core()
    db = get_db()
    agent = db.execute(
        "SELECT a.*, u.login AS proprietaire FROM agents a JOIN users u ON u.id=a.user_id WHERE a.id=?",
        (agent_id,),
    ).fetchone()
    db.close()
    if not agent:
        return error("Fiche introuvable", 404)
    settings = core._settings_for_year(core.load_settings(), agent["year"])
    summary = core._agent_summary_for_row(agent, settings)
    if "error" in summary:
        return error("Calcul impossible pour cette fiche : %s" % summary["error"], 422)
    return jsonify({
        "agent_id": agent["id"], "nom": agent["nom"], "prenom": agent["prenom"], "year": agent["year"],
        "updated_at": agent["modifie_le"],
        "balances": {k: summary[k] for k in ("ca", "rtt", "js", "jb", "cet", "cah", "rth", "rch", "total")},
    })


# --------------------------------------------------------------------------- #
#  Absences saisies et demandes
# --------------------------------------------------------------------------- #
@bp.route("/api/v1/absences", methods=["GET"])
@api_key_required("absences:read")
def absences():
    core = _core()
    year = _year_arg(core)
    if year is None:
        return error("Paramètre year invalide", 400)
    try:
        start, end = _iso_date("from"), _iso_date("to")
    except ValueError:
        return error("Dates invalides (format AAAA-MM-JJ)", 400)
    limit, offset = page_args(default=200, maximum=1000)
    where, params = "WHERE a.year=?", [year]
    if request.args.get("agent_id"):
        where += " AND a.id=?"
        params.append(request.args.get("agent_id", type=int) or 0)
    db = get_db()
    rows = db.execute(
        "SELECT a.id AS agent_id, TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, c.jour, c.code "
        "FROM cells c JOIN agents a ON a.id=c.agent_id " + where + " ORDER BY a.id, c.jour", params,
    ).fetchall()
    db.close()
    items = []
    for r in rows:
        try:
            day, half = _key_to_date(year, r["jour"])
        except ValueError:
            continue  # clé de calendrier invalide (ex. 30 février) : ignorée
        if (start and day < start) or (end and day > end):
            continue
        items.append({"agent_id": r["agent_id"], "agent_nom": r["agent_nom"], "date": day,
                      "half": half, "code": r["code"]})
    return paged(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/api/v1/requests", methods=["GET"])
@api_key_required("requests:read")
def leave_requests():
    core = _core()
    year = _year_arg(core)
    if year is None:
        return error("Paramètre year invalide", 400)
    limit, offset = page_args()
    where, params = "WHERE r.year=?", [year]
    for arg, column in (("status", "r.status"), ("agent_id", "r.agent_id")):
        if request.args.get(arg):
            where += " AND %s=?" % column
            params.append(request.args[arg] if arg == "status" else (request.args.get(arg, type=int) or 0))
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM leave_requests r " + where, params).fetchone()["c"]
    rows = db.execute(
        "SELECT r.id, r.agent_id, TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, "
        "r.request_type, r.code, r.days, r.hours, r.status, r.cells, r.absence_date, "
        "r.soumis_le AS submitted_at, r.decide_le AS decided_at "
        "FROM leave_requests r JOIN agents a ON a.id=r.agent_id " + where +
        " ORDER BY r.id DESC LIMIT ? OFFSET ?", params + [limit, offset],
    ).fetchall()
    db.close()
    items = []
    for r in rows:
        item = row_to_dict(r)
        raw = json.loads(item.pop("cells") or "[]")
        keys = list(raw.keys()) if isinstance(raw, dict) else [c.get("key") if isinstance(c, dict) else c for c in raw]
        dates = []
        for key in keys:
            try:
                day, half = _key_to_date(year, key)
                dates.append({"date": day, "half": half})
            except (TypeError, ValueError):
                continue
        item["dates"] = dates
        items.append(item)
    return paged(items, total, limit, offset)
