# -*- coding: utf-8 -*-
"""Boutons « Valider » / « Refuser » des e-mails : page de confirmation protégée par un jeton signé.

Le lien d'un e-mail contient un jeton signé (demande + destinataire, valable 14 jours). Ouvrir le lien (GET) n'a **aucun
effet** : il affiche la demande et deux boutons ; la décision n'est enregistrée qu'au clic (POST), ce qui évite qu'un antivirus
ou un aperçu de messagerie valide à la place du valideur. La décision réutilise exactement la même logique que l'écran
(contrôles de solde et de droits compris) : le destinataire doit toujours être habilité à valider la demande.
Quiconque détient le lien peut décider au nom du destinataire : le jeton est personnel et n'est à transférer à personne.
"""
import html
import json

from flask import Blueprint, Response, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import config
import mailer
from db import get_db, row_to_dict

bp = Blueprint("mail_actions", __name__, url_prefix="/api/mail-action")
MAX_AGE = 14 * 24 * 3600
STATUS = {"en_attente": "en attente", "validee": "validée", "refusee": "refusée", "annulee": "annulée",
          "annulation_demandee": "annulation demandée"}


def _serializer(secret):
    return URLSafeTimedSerializer(secret, salt="mail-action")


def make_token(secret, request_id, user_id):
    return _serializer(secret).dumps({"r": int(request_id), "u": int(user_id)})


def read_token(secret, token):
    """(request_id, user_id) ou lève BadSignature / SignatureExpired."""
    data = _serializer(secret).loads(token, max_age=MAX_AGE)
    return int(data["r"]), int(data["u"])


def _page(title, body):
    css = ("body{font-family:Segoe UI,Arial,sans-serif;background:#f6efeb;margin:0;padding:24px;color:#3b2a24}"
           ".card{max-width:620px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 4px 18px rgba(0,0,0,.1)}"
           "h1{font-size:20px;margin:0 0 12px;color:#8a3b25}.muted{color:#7a6a63;font-size:13px}"
           "button{border:0;border-radius:6px;padding:10px 18px;font-size:15px;font-weight:600;color:#fff;cursor:pointer;margin:6px 8px 6px 0}"
           ".ok{background:#1b7a3d}.ko{background:#b3261e}.lnk{background:#c4573a;display:inline-block;color:#fff;padding:10px 18px;"
           "border-radius:6px;text-decoration:none;font-weight:600}textarea{width:100%;height:64px;border:1px solid #d9c9c1;"
           "border-radius:6px;padding:6px;font:inherit;box-sizing:border-box}")
    return Response("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,"
                    "initial-scale=1\"><title>%s</title><style>%s</style></head><body><div class=\"card\"><h1>%s</h1>%s</div></body></html>"
                    % (html.escape(title), css, html.escape(title), body), mimetype="text/html")


def init_mail_actions(app, approve_view, refuse_view, load_settings):
    def summary(db, rid):
        row = db.execute(
            "SELECT r.*, a.nom, a.prenom, a.year AS fiche_year FROM leave_requests r JOIN agents a ON a.id=r.agent_id WHERE r.id=?",
            (rid,)).fetchone()
        return row_to_dict(row) if row else None

    def describe(r):
        label = r["code"]
        for item in (load_settings().get("codes") or []):
            if item.get("code") == r["code"]:
                label = "%s (%s)" % (item.get("libelle") or r["code"], r["code"])
        try:
            dates = mailer.format_ranges(json.loads(r["cells"] or "[]"), r["fiche_year"])
        except (ValueError, TypeError):
            dates = []
        parts = ["<p><strong>%s</strong> — %s</p>" % (html.escape(("%s %s" % (r["nom"], r["prenom"] or "")).strip()), html.escape(label))]
        if dates:
            parts.append("<p>%s</p>" % "<br>".join(html.escape(x) for x in dates))
        if r.get("days"):
            parts.append("<p class=\"muted\">%s jour(s)</p>" % html.escape(("%g" % float(r["days"])).replace(".", ",")))
        if r.get("comment"):
            parts.append("<p class=\"muted\">Commentaire : %s</p>" % html.escape(r["comment"]))
        return "".join(parts)

    def calendar_link(r):
        base = config.BASE_URL
        if not base:
            return ""
        month = ""
        try:
            month = "&mois=%d" % (min(int(k) for k in json.loads(r["cells"] or "[]")) // 1000)
        except (ValueError, TypeError):
            month = ""
        return "<p><a class=\"lnk\" href=\"%s/#/planning?equipe=1%s&annee=%s\">Voir le calendrier d'équipe</a></p>" % (
            html.escape(base), month, r["fiche_year"])

    def open_token(token):
        try:
            return read_token(app.secret_key, token), None
        except SignatureExpired:
            return None, _page("Lien expiré", "<p>Ce lien n'est plus valable (14 jours). Ouvrez l'application pour traiter la demande.</p>")
        except BadSignature:
            return None, _page("Lien invalide", "<p>Ce lien n'est pas valable.</p>")

    @bp.route("/<token>", methods=["GET", "POST"])
    def action(token):
        parsed, bad = open_token(token)
        if bad:
            return bad
        rid, uid = parsed
        db = get_db()
        try:
            r = summary(db, rid)
            user = db.execute("SELECT * FROM users WHERE id=? AND actif=1", (uid,)).fetchone()
            if not r or not user:
                return _page("Demande introuvable", "<p>Cette demande ou ce compte n'existe plus.</p>")
            user = row_to_dict(user)
            if request.method == "GET":
                if r["status"] != "en_attente":
                    return _page("Demande déjà traitée", describe(r) + "<p>Statut : <strong>%s</strong>.</p>" %
                                 html.escape(STATUS.get(r["status"], r["status"])) + calendar_link(r))
                pre = request.args.get("a")
                return _page("Demande de congé à traiter", describe(r) + (
                    "<form method=\"post\"><p class=\"muted\">Commentaire (facultatif, utile en cas de refus)</p>"
                    "<textarea name=\"comment\"></textarea><p><button class=\"ok\" name=\"decision\" value=\"validee\">%sValider</button>"
                    "<button class=\"ko\" name=\"decision\" value=\"refusee\">%sRefuser</button></p></form>" % (
                        "✔ " if pre == "validee" else "", "✖ " if pre == "refusee" else "")) + calendar_link(r))
            decision = request.form.get("decision")
            if decision not in ("validee", "refusee"):
                return _page("Décision invalide", "<p>Choisissez Valider ou Refuser.</p>")
            comment = (request.form.get("comment") or "").strip()
        finally:
            db.close()
        view = approve_view if decision == "validee" else refuse_view
        with app.test_request_context(method="POST", json={"comment": comment}):
            request.user = user
            request.real_user = None
            resp = view(rid)
        status = resp[1] if isinstance(resp, tuple) else resp.status_code
        data = (resp[0] if isinstance(resp, tuple) else resp).get_json() or {}
        if status == 200:
            return _page("Demande %s" % ("validée" if decision == "validee" else "refusée"),
                         "<p>Votre décision est enregistrée. L'agent peut la consulter dans l'application.</p>" + calendar_link(r))
        return _page("Décision non enregistrée", "<p>%s</p>" % html.escape(data.get("error") or "Erreur %s" % status))

    app.register_blueprint(bp)
