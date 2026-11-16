# -*- coding: utf-8 -*-
"""Délégation des valideurs (voir REGLES_METIER.md, section 6).

Le délégataire est toujours **le valideur du valideur** (son responsable direct, `users.parent_id`) : il peut déjà valider
(un supérieur hiérarchique valide les demandes de ses subordonnés) ; la délégation sert à le **prévenir** (mail avec boutons)
quand le valideur est absent, et à **tracer** ce qu'il a fait à sa place.

- délégation **automatique** (`users.delegate_auto`) : le valideur est absent le jour même (journée complète posée dans sa
  propre fiche) ;
- délégation **sur période** (table `delegations`) : du / au, même sans congés ;
- le valideur consulte les validations faites à sa place par d'autres que lui.
"""
import datetime as dt
import json

from flask import Blueprint, jsonify, request

import mailer
from db import get_db, row_to_dict
from http_utils import error

bp = Blueprint("delegation", __name__, url_prefix="/api/delegation")


def is_absent(db, user_id, day):
    """Le valideur est-il absent ce jour-là (journée complète posée dans sa propre fiche) ?"""
    base = day.month * 1000 + day.day * 10
    row = db.execute(
        "SELECT COUNT(*) AS n FROM cells c JOIN agents a ON a.id=c.agent_id "
        "WHERE a.agent_user_id=? AND a.year=? AND c.jour IN (?,?)",
        (user_id, day.year, base, base + 1)).fetchone()
    return row["n"] >= 2


def active_delegate(db, validator_id, day=None):
    """Compte (id, login, nom, email) à qui le valideur délègue ce jour-là — son propre valideur — ou None."""
    day = day or dt.date.today()
    row = db.execute("SELECT id, parent_id, delegate_auto FROM users WHERE id=?", (validator_id,)).fetchone()
    if not row or not row["parent_id"]:
        return None
    parent = db.execute("SELECT id, login, nom, email, actif FROM users WHERE id=?", (row["parent_id"],)).fetchone()
    if not parent or not parent["actif"]:
        return None
    iso = day.isoformat()
    if db.execute("SELECT 1 FROM delegations WHERE user_id=? AND start_date<=? AND end_date>=?",
                  (validator_id, iso, iso)).fetchone():
        return row_to_dict(parent)
    if row["delegate_auto"] and is_absent(db, validator_id, day):
        return row_to_dict(parent)
    return None


def delegators_of(db, delegate_id, day=None):
    """Valideurs qui délèguent à `delegate_id` ce jour-là (pour les relances)."""
    day = day or dt.date.today()
    out = []
    for r in db.execute("SELECT id FROM users WHERE parent_id=? AND actif=1", (delegate_id,)).fetchall():
        if active_delegate(db, r["id"], day):
            out.append(r["id"])
    return out


def init_delegation(app, login_required, can_manage):
    def guard():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        return None

    @bp.route("", methods=["GET"])
    @login_required
    def overview():
        denied = guard()
        if denied:
            return denied
        me = request.user["id"]
        db = get_db()
        try:
            parent = db.execute("SELECT id, login, nom, email FROM users WHERE id=? AND actif=1",
                                (request.user.get("parent_id"),)).fetchone() if request.user.get("parent_id") else None
            periods = [row_to_dict(r) for r in db.execute(
                "SELECT id, start_date, end_date FROM delegations WHERE user_id=? ORDER BY start_date DESC, id DESC", (me,)).fetchall()]
            auto = db.execute("SELECT delegate_auto FROM users WHERE id=?", (me,)).fetchone()["delegate_auto"]
            done = []
            for r in db.execute(
                    "SELECT e.id, e.cree_le, e.action, e.comment, r.id AS request_id, r.code, r.cells, a.year, "
                    "TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent, u.nom AS par "
                    "FROM leave_request_events e "
                    "JOIN leave_requests r ON r.id=e.request_id JOIN agents a ON a.id=r.agent_id "
                    "JOIN users u ON u.id=e.actor_id "
                    "WHERE e.action IN ('validee','refusee') AND e.actor_id<>? "
                    "AND (r.validator_id=? OR (r.validator_id IS NULL AND COALESCE(a.validator_id, a.user_id)=?)) "
                    "ORDER BY e.id DESC LIMIT 100", (me, me, me)).fetchall():
                try:
                    dates = mailer.format_ranges(json.loads(r["cells"] or "[]"), r["year"])
                except (ValueError, TypeError):
                    dates = []
                done.append({"id": r["id"], "at": r["cree_le"], "action": r["action"], "comment": r["comment"],
                             "request_id": r["request_id"], "code": r["code"], "agent": r["agent"], "par": r["par"],
                             "dates": dates})
            return jsonify({
                "delegate": row_to_dict(parent) if parent else None, "auto": bool(auto), "periods": periods,
                "active_now": bool(active_delegate(db, me)), "done": done})
        finally:
            db.close()

    @bp.route("/auto", methods=["PUT"])
    @login_required
    def set_auto():
        denied = guard()
        if denied:
            return denied
        flag = 1 if (request.get_json(force=True) or {}).get("auto") else 0
        if flag and not request.user.get("parent_id"):
            return error("Vous n'avez pas de valideur à qui déléguer", 400)
        db = get_db()
        try:
            db.execute("UPDATE users SET delegate_auto=? WHERE id=?", (flag, request.user["id"]))
            db.commit()
            return jsonify({"auto": bool(flag)})
        finally:
            db.close()

    @bp.route("/periods", methods=["POST"])
    @login_required
    def add_period():
        denied = guard()
        if denied:
            return denied
        d = request.get_json(force=True) or {}
        try:
            start, end = dt.date.fromisoformat(str(d.get("start"))[:10]), dt.date.fromisoformat(str(d.get("end"))[:10])
        except ValueError:
            return error("Dates invalides (du / au)", 400)
        if end < start:
            return error("La date de fin précède la date de début", 400)
        if end < dt.date.today():
            return error("Cette période est déjà passée", 400)
        if not request.user.get("parent_id"):
            return error("Vous n'avez pas de valideur à qui déléguer", 400)
        db = get_db()
        try:
            cur = db.execute("INSERT INTO delegations (user_id, start_date, end_date) VALUES (?,?,?)",
                             (request.user["id"], start.isoformat(), end.isoformat()))
            db.commit()
            return jsonify({"id": cur.lastrowid, "start_date": start.isoformat(), "end_date": end.isoformat()})
        finally:
            db.close()

    @bp.route("/periods/<int:pid>", methods=["DELETE"])
    @login_required
    def delete_period(pid):
        denied = guard()
        if denied:
            return denied
        db = get_db()
        try:
            db.execute("DELETE FROM delegations WHERE id=? AND user_id=?", (pid, request.user["id"]))
            db.commit()
            return jsonify({"ok": True})
        finally:
            db.close()

    app.register_blueprint(bp)
