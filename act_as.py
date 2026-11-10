# -*- coding: utf-8 -*-
"""« Se connecter en tant que » : un administrateur agit avec les droits exacts d'un agent.

Principe (identique à l'application delib) :
- l'administrateur cherche l'agent (recherche prédictive dans l'AD, via l'APM, complétée par les
  comptes de l'application) puis bascule sur son compte, sans connaître son mot de passe ;
- la session garde l'identité réelle (`real_uid`) : tout est journalisé au nom de l'administrateur,
  avec la mention « en tant que » ; le début et la fin de l'opération sont tracés ;
- on ne peut pas usurper un autre administrateur, ni enchaîner deux usurpations, ni changer le
  mot de passe du compte usurpé ; « Revenir à mon compte » (ou la déconnexion) y met fin.
"""
from flask import Blueprint, jsonify, request, session

import apm
from db import get_db, public_user, row_to_dict
from http_utils import error

bp = Blueprint("act_as", __name__, url_prefix="/api/admin/act-as")
_FIELDS = "id, login, ad_login, nom, role, admin, actif"


def _account_for(db, username):
    row = db.execute(
        "SELECT %s FROM users WHERE lower(login)=? OR lower(ad_login)=? ORDER BY id LIMIT 1" % _FIELDS,
        (username, username),
    ).fetchone()
    return row_to_dict(row)


def _verdict(account, self_id):
    """(sélectionnable, motif) pour une suggestion."""
    if not account:
        return False, "Pas de compte dans l'application"
    if account["id"] == self_id:
        return False, "C'est votre compte"
    if not account["actif"]:
        return False, "Compte désactivé"
    if account["admin"]:
        return False, "Compte administrateur"
    return True, ""


def end_impersonation(audit_user):
    """Termine l'usurpation en cours (journalisée). Retourne l'id de l'administrateur, ou None."""
    real_id = session.get("real_uid")
    if not real_id:
        return None
    db = get_db()
    admin = db.execute("SELECT * FROM users WHERE id=?", (int(real_id),)).fetchone()
    target = db.execute("SELECT id, login FROM users WHERE id=?", (int(session.get("uid") or 0),)).fetchone()
    if admin and target:
        audit_user(db, target["id"], target["login"], row_to_dict(admin), "usurpation", "fin",
                   "", "", "Fin de « se connecter en tant que »")
        db.commit()
    db.close()
    session["uid"] = int(real_id)
    session.pop("real_uid", None)
    return int(real_id)


def init_act_as(app, current_user, audit_user):
    def real_admin():
        """Administrateur réellement connecté (pas d'usurpation en cours), sinon None."""
        user = current_user()
        return user if user and user["admin"] and not session.get("real_uid") else None

    @bp.route("/search", methods=["GET"])
    def search():
        admin = real_admin()
        if not admin:
            return error("Réservé aux administrateurs (hors mode « en tant que »)", 403)
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"items": [], "ad_error": False})
        db = get_db()
        items, seen, ad_error = [], set(), False
        try:
            hits = apm.ad_search(q) if apm.configured() else []
        except apm.ApmError as exc:
            app.logger.warning("Recherche AD indisponible : %s", exc)
            hits, ad_error = [], True
        for hit in hits:
            account = _account_for(db, hit["username"])
            if account:
                seen.add(account["id"])
            ok, reason = _verdict(account, admin["id"])
            items.append({"username": hit["username"], "displayName": hit["displayName"],
                          "email": hit["email"], "source": "ad", "account": account,
                          "selectable": ok, "reason": reason})
        like = "%" + q + "%"
        for row in db.execute(
            "SELECT %s FROM users WHERE login ILIKE ? OR nom ILIKE ? OR ad_login ILIKE ? "
            "ORDER BY login LIMIT 15" % _FIELDS, (like, like, like),
        ).fetchall():
            account = row_to_dict(row)
            if account["id"] in seen:
                continue
            ok, reason = _verdict(account, admin["id"])
            items.append({"username": account["ad_login"] or account["login"], "displayName": account["nom"],
                          "email": "", "source": "local", "account": account, "selectable": ok, "reason": reason})
        db.close()
        return jsonify({"items": items[:20], "ad_error": ad_error})

    @bp.route("", methods=["POST"])
    def start():
        admin = real_admin()
        if not admin:
            return error("Réservé aux administrateurs (hors mode « en tant que »)", 403)
        data = request.get_json(force=True) or {}
        db = get_db()
        target = db.execute("SELECT * FROM users WHERE id=?", (int(data.get("user_id") or 0),)).fetchone()
        if not target:
            db.close()
            return error("Compte introuvable", 404)
        ok, reason = _verdict(row_to_dict(target), admin["id"])
        if not ok:
            db.close()
            return error(reason, 403)
        audit_user(db, target["id"], target["login"], admin, "usurpation", "début", "", "",
                   "Début de « se connecter en tant que »")
        db.commit()
        db.close()
        session["real_uid"] = admin["id"]
        session["uid"] = target["id"]
        return jsonify({"ok": True, "user": public_user(target)})

    @bp.route("", methods=["DELETE"])
    def stop():
        real_id = end_impersonation(audit_user)
        if not real_id:
            return error("Aucune usurpation en cours", 400)
        return jsonify({"ok": True})

    app.register_blueprint(bp)
