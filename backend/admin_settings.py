# -*- coding: utf-8 -*-
"""Routes d'administration du paramétrage : journaux (connexions, e-mails), réglages et gabarits des e-mails.

Toutes ces routes sont réservées aux administrateurs (décorateur fourni par app.py).
"""
import datetime as dt

from flask import Blueprint, jsonify, request

import apm
import audit_logs
import config
import mail_templates
import mailer
from http_utils import error, page_args, paged

bp = Blueprint("admin_settings", __name__, url_prefix="/api/admin")


def _date_filters(column):
    """Filtres ?from=AAAA-MM-JJ&to=AAAA-MM-JJ sur une colonne texte « AAAA-MM-JJ HH:MM:SS »."""
    start, end = request.args.get("from"), request.args.get("to")
    for value in (start, end):
        if value:
            dt.date.fromisoformat(value)  # ValueError si invalide
    return [(column + " >= ?", (start + " 00:00:00") if start else None),
            (column + " <= ?", (end + " 23:59:59") if end else None)]


def init_admin_settings(app, admin_required):
    # ------------------------------------------------------------------ journal des connexions
    @bp.route("/login-logs", methods=["GET"])
    @admin_required
    def login_logs():
        limit, offset = page_args(default=50, maximum=200)
        q = (request.args.get("q") or "").strip()
        try:
            filters = _date_filters("at")
        except ValueError:
            return error("Dates invalides (format AAAA-MM-JJ)", 400)
        like = "%" + q + "%" if q else None
        filters += [
            ("(login ILIKE ? OR ip ILIKE ?)", [like, like] if q else None),
            ("event = ?", request.args.get("event")),
            ("success = ?", {"1": 1, "0": 0}.get(request.args.get("success", ""))),
        ]
        items, total = audit_logs.query(
            "login_logs", "id, at, event, login, user_id, success, reason, method, ip, user_agent",
            filters, limit, offset)
        return jsonify({"total": total, "limit": limit, "offset": offset, "items": items,
                        "retention_days": audit_logs.retention()["connexions_jours"]})

    # ------------------------------------------------------------------ journal des e-mails
    @bp.route("/mail-logs", methods=["GET"])
    @admin_required
    def mail_logs():
        limit, offset = page_args(default=50, maximum=200)
        q = (request.args.get("q") or "").strip()
        try:
            filters = _date_filters("at")
        except ValueError:
            return error("Dates invalides (format AAAA-MM-JJ)", 400)
        like = "%" + q + "%" if q else None
        filters += [
            ("(to_addr ILIKE ? OR subject ILIKE ?)", [like, like] if q else None),
            ("status = ?", request.args.get("status")),
            ("template = ?", request.args.get("template")),
        ]
        items, total = audit_logs.query(
            "mail_logs", "id, at, to_addr, subject, template, status, error, request_id", filters, limit, offset)
        return jsonify({"total": total, "limit": limit, "offset": offset, "items": items,
                        "retention_days": audit_logs.retention()["emails_jours"],
                        "templates": {k: v["label"] for k, v in mail_templates.TEMPLATES.items()}})

    @bp.route("/mail-logs/<int:log_id>", methods=["GET"])
    @admin_required
    def mail_log(log_id):
        items, total = audit_logs.query(
            "mail_logs", "id, at, to_addr, subject, template, status, error, body, request_id",
            [("id = ?", log_id)], 1, 0)
        return jsonify(items[0]) if total else error("Entrée introuvable", 404)

    # ------------------------------------------------------------------ conservation des journaux
    @bp.route("/log-retention", methods=["GET", "PUT"])
    @admin_required
    def log_retention():
        if request.method == "PUT":
            data = request.get_json(force=True) or {}
            try:
                a, b = int(data.get("connexions_jours")), int(data.get("emails_jours"))
            except (TypeError, ValueError):
                return error("Durées invalides", 400)
            if not (30 <= a <= 3650 and 30 <= b <= 3650):
                return error("La durée de conservation doit être comprise entre 30 et 3650 jours", 400)
            audit_logs.save_retention(a, b)
        return jsonify(audit_logs.retention())

    # ------------------------------------------------------------------ e-mails : réglages et gabarits
    def _settings_payload():
        current = mail_templates.load()
        return {
            "enabled": current["enabled"], "apm_configured": apm.configured(),
            "mail_enabled": bool(current["enabled"] and apm.configured()),
            "layout": current["layout"], "layout_defaults": mail_templates.DEFAULT_LAYOUT,
            "templates": [
                {"key": key, "label": tpl["label"], "description": tpl["description"], "recipients": tpl["recipients"],
                 "variables": tpl["variables"], "default_subject": tpl["subject"], "default_body": tpl["body"],
                 **current["templates"][key]}
                for key, tpl in mail_templates.TEMPLATES.items()
            ],
        }

    @bp.route("/mail-settings", methods=["GET"])
    @admin_required
    def mail_settings_get():
        return jsonify(_settings_payload())

    @bp.route("/mail-settings", methods=["PUT"])
    @admin_required
    def mail_settings_put():
        update, err = mail_templates.validate(request.get_json(force=True) or {})
        if err:
            return error(err, 400)
        mail_templates.save(update)
        return jsonify(_settings_payload())

    @bp.route("/mail-settings/reset", methods=["POST"])
    @admin_required
    def mail_settings_reset():
        key = (request.get_json(force=True) or {}).get("key")
        if key not in mail_templates.TEMPLATES:
            return error("Message inconnu", 404)
        mail_templates.reset(key)
        return jsonify(_settings_payload())

    @bp.route("/mail-settings/preview", methods=["POST"])
    @admin_required
    def mail_settings_preview():
        data = request.get_json(force=True) or {}
        key = data.get("key")
        if key not in mail_templates.TEMPLATES:
            return error("Message inconnu", 404)
        update, err = mail_templates.validate({
            "layout": data.get("layout") or {},
            "templates": {key: {"subject": data.get("subject"), "body": data.get("body")}},
        })
        if err:
            return error(err, 400)
        settings = mail_templates.load()
        settings["layout"].update(update["layout"])
        settings["templates"][key].update(update["templates"][key])
        rendered = mail_templates.render(key, mail_templates.TEMPLATES[key]["sample"], settings)
        # Aperçu du message seul : l'en-tête (gabarit de l'APM) et le pied de page ne sont pas prévisualisés.
        return jsonify({"subject": rendered["subject"], "html": rendered["html"], "text": rendered["text"]})

    @bp.route("/mail-settings/test", methods=["POST"])
    @admin_required
    def mail_settings_test():
        data = request.get_json(force=True) or {}
        to = (data.get("to") or request.user.get("email") or "").strip()
        if not to or "@" not in to:
            return error("Saisissez une adresse e-mail pour le test", 400)
        key = data.get("key") or "test_envoi"
        if key not in mail_templates.TEMPLATES:
            return error("Message inconnu", 404)
        values = dict(mail_templates.TEMPLATES[key]["sample"])
        if key == "test_envoi":
            values = {"administrateur": request.user.get("nom") or request.user["login"],
                      "date": dt.datetime.now().strftime("%d/%m/%Y %H:%M")}
        rendered = mail_templates.render(key, values)
        if key != "test_envoi":
            rendered["subject"] = "[TEST] " + rendered["subject"]
        # Un test part même si l'envoi automatique ou ce message est désactivé.
        ok, err = mailer.send_rendered(to, rendered, key, force=True)
        return jsonify({"ok": ok, "error": err, "to": to})

    app.register_blueprint(bp)
