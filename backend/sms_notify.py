# -*- coding: utf-8 -*-
"""SMS de confirmation pour les personnes SANS adresse e-mail.

Une personne qui n'a pas d'e-mail (agent ou valideur) mais dont le smartphone a été contrôlé (activation du compte) reçoit par SMS ce que les autres reçoivent
par e-mail : la confirmation de ses demandes, leur validation ou leur refus, l'annulation ; un valideur sans e-mail est prévenu d'une nouvelle demande et reçoit
la confirmation de sa décision. Les SMS partent par l'API Ville (APM), en arrière-plan ; une panne n'interrompt jamais l'action de l'utilisateur.
"""
import json
import threading

import apm
import audit_logs
import mailer
from db import user_label

SYNC = False                         # tests : envoi immédiat, sans fil d'exécution


def _qualifies(user):
    """Pas d'adresse e-mail, mais un smartphone contrôlé par SMS."""
    return bool(user and user["actif"] and not (user["email"] or "").strip() and user["mobile_verifie_le"] and (user["mobile"] or "").strip())


def _short_dates(cells, year, limit=2):
    lines = mailer.format_ranges(cells, year)
    return " ; ".join(lines[:limit]) + (" …" if len(lines) > limit else "")


def _deliver(items, request_id):
    def run():
        for mobile, text in items:
            masked = "%s ** ** ** %s" % (mobile[:2], mobile[-2:])
            try:
                apm.send_sms(mobile, text[:300])
                audit_logs.log_mail(masked, text, "sms", "envoye", "", text, request_id)
            except Exception as exc:  # noqa: BLE001 - un SMS non parti ne doit jamais bloquer une demande
                audit_logs.log_mail(masked, text, "sms", "echec", str(exc), text, request_id)
    if not items:
        return
    if SYNC:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


def on_request_event(db, request_id, action, actor_id):
    """Appelé à chaque événement d'une demande de congé (voir app._audit_request) ; ne lève jamais d'exception."""
    try:
        row = db.execute(
            "SELECT r.id, r.request_type, r.code, r.cells, r.year, r.days, r.validator_id, a.agent_user_id, a.nom AS agent_nom, a.prenom AS agent_prenom "
            "FROM leave_requests r JOIN agents a ON a.id=r.agent_id WHERE r.id=?", (request_id,)).fetchone()
        if not row or (row["request_type"] or "absence") != "absence":
            return
        cells = [int(c) for c in json.loads(row["cells"] or "[]")]
        if not cells:
            return
        users = {}
        for uid in {row["agent_user_id"], row["validator_id"], actor_id} - {None}:
            users[uid] = db.execute("SELECT id, login, nom, nom_ad, nom_famille, prenom, email, mobile, mobile_verifie_le, actif FROM users WHERE id=?", (uid,)).fetchone()
        agent, validator, actor = users.get(row["agent_user_id"]), users.get(row["validator_id"]), users.get(actor_id)
        who = ("%s %s" % (row["agent_nom"], row["agent_prenom"] or "")).strip() or (user_label(agent) if agent else "")
        what = "%s %s" % (row["code"], _short_dates(cells, row["year"]))
        days = ("%g" % float(row["days"] or len(cells) / 2.0)).replace(".", ",")
        boss = user_label(validator) if validator else "votre valideur"
        to_agent = to_validator = to_actor = None
        if action == "soumise":
            to_agent = "Suivi congés : votre demande %s (%s j) est envoyée à %s." % (what, days, boss)
            to_validator = "Suivi congés : demande de %s : %s (%s j). A valider dans l'application." % (who, what, days)
        elif action in ("validee", "auto_validee"):
            to_agent = "Suivi congés : votre demande %s est VALIDEE." % what
            to_actor = "Suivi congés : vous avez VALIDE la demande de %s (%s)." % (who, what)
        elif action == "refusee":
            to_agent = "Suivi congés : votre demande %s est REFUSEE." % what
            to_actor = "Suivi congés : vous avez REFUSE la demande de %s (%s)." % (who, what)
        elif action == "annulee":
            to_agent = "Suivi congés : votre demande %s est ANNULEE." % what
        elif action == "annulation_demandee":
            to_agent = "Suivi congés : votre demande d'annulation (%s) est envoyée à %s." % (what, boss)
            to_validator = "Suivi congés : %s demande l'annulation de %s. A traiter dans l'application." % (who, what)
        elif action == "annulation_validee":
            to_agent = "Suivi congés : l'annulation de votre demande %s est ACCEPTEE." % what
            to_actor = "Suivi congés : vous avez ACCEPTE l'annulation de %s (%s)." % (what, who)
        elif action == "annulation_refusee":
            to_agent = "Suivi congés : l'annulation de votre demande %s est REFUSEE (les jours restent posés)." % what
        sent, items = set(), []
        for person, text in ((agent, to_agent), (validator, to_validator), (actor, to_actor)):
            if text and _qualifies(person) and person["id"] not in sent:
                sent.add(person["id"])
                items.append((person["mobile"], text))
        _deliver(items, request_id)
    except Exception:  # noqa: BLE001
        return
