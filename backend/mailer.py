# -*- coding: utf-8 -*-
"""E-mails automatiques de l'application (notifications aux valideurs, relances, test d'envoi).

Les mails partent par l'API centrale de la Ville (APM, `POST /api/v1/mail/send`). Le contenu de chaque message
et la mise en page commune (expéditeur, en-tête, signature, pied de page) viennent de `mail_templates.py`
(modifiables dans Paramétrage > E-mails). Chaque envoi, réussi ou non, est inscrit au journal des e-mails.
Si l'envoi est désactivé (Paramétrage > E-mails) ou si l'APM n'est pas configurée, aucun e-mail automatique ne part ;
les messages de test, eux, partent même lorsque l'envoi est désactivé (dès que l'APM est configurée).
"""
import datetime as dt
import os
import threading

import apm
import audit_logs
import config
import mail_templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "mail.log")

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _log(message):
    line = "%s [mail] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line)


def load_config():
    """Configuration des mails (via l'APM), ou None si l'envoi est désactivé / incomplet."""
    if not mail_templates.is_enabled() or not apm.configured():
        return None
    return {"base_url": config.BASE_URL}


def _format_days(days):
    return ("%g" % float(days)).replace(".", ",")


def _half_pos(key, year):
    key = int(key)
    return dt.date(int(year), key // 1000, (key % 1000) // 10), key % 10


def _follows(last, new):
    """`new` (date, demi) suit-il `last` ? Même jour matin → après-midi, ou jour ouvré suivant (week-ends sautés)."""
    (d1, h1), (d2, h2) = last, new
    if d2 == d1:
        return h1 == 0 and h2 == 1
    if h1 != 1 or h2 != 0 or d2 <= d1:
        return False
    day = d1 + dt.timedelta(days=1)
    while day < d2:
        if day.isoweekday() < 6:      # un jour ouvré manque entre les deux : ce sont deux plages distinctes
            return False
        day += dt.timedelta(days=1)
    return True


def _fmt_day(d):
    return "%d %s %d" % (d.day, MOIS[d.month - 1], d.year)


def format_ranges(cells, year):
    """Demi-journées (clés mois*1000 + jour*10 + 0/1) -> plages lisibles : « du 20 avril 2026 au 24 avril 2026 »."""
    try:
        points = sorted(_half_pos(k, year) for k in cells)
    except (TypeError, ValueError):
        return [str(k) for k in cells]
    blocks = []
    for pt in points:
        if blocks and _follows(blocks[-1][1], pt):
            blocks[-1][1] = pt
        else:
            blocks.append([pt, pt])
    out = []
    for (d1, h1), (d2, h2) in blocks:
        if d1 == d2:
            part = "" if (h1, h2) == (0, 1) else " (%s)" % ("matin" if h1 == 0 else "après-midi")
            out.append("le %s%s" % (_fmt_day(d1), part))
        else:
            left = "du %s%s" % (_fmt_day(d1), " (après-midi)" if h1 == 1 else "")
            right = "au %s%s" % (_fmt_day(d2), " (matin)" if h2 == 0 else "")
            out.append("%s %s" % (left, right))
    return out


def cell_label(key, year):
    """Libellé d'une demi-journée à partir de la clé (mois*1000 + jour*10 + 0/1)."""
    try:
        key = int(key)
    except (TypeError, ValueError):
        return str(key)
    month = key // 1000
    day = (key % 1000) // 10
    half = key % 10
    if not (1 <= month <= 12):
        return str(key)
    return "%d %s %d — %s" % (
        day, MOIS[month - 1], int(year), "matin" if half == 0 else "après-midi"
    )


# --------------------------------------------------------------------------- #
#  Envoi
# --------------------------------------------------------------------------- #
def _deliver(rendered, to):
    layout = rendered["layout"]
    apm.send_mail(
        to, rendered["subject"], rendered["html"],
        footer={"line1": layout["footer1"], "line2": layout["footer2"],
                "line3": layout["footer3"], "color": layout["footer_color"]},
        from_name=layout["from_name"], from_email=layout["from_email"],
    )


def send_rendered(to, rendered, template="", request_id=None, force=False):
    """Envoie un message déjà rendu et le journalise. Retourne (ok, message_erreur).

    `force` : message de test, envoyé même si l'envoi automatique est désactivé (l'APM doit être configurée)."""
    to = (to or "").strip()
    subject, text = rendered["subject"], rendered["text"]

    def finish(status, error=""):
        audit_logs.log_mail(to, subject, template, status, error, text, request_id)
        return status == "envoye", error

    if not apm.configured():
        return finish("non_envoye", "API centrale (APM) non configurée")
    if not force and not load_config():
        return finish("non_envoye", "Envoi des e-mails désactivé (Paramétrage > E-mails)")
    if not force and not rendered.get("enabled", True):
        return finish("non_envoye", "Message désactivé dans le paramétrage")
    if not to:
        return finish("non_envoye", "Aucune adresse e-mail de destinataire")
    try:
        _deliver(rendered, to)
    except Exception as exc:  # noqa: BLE001 — l'échec mail ne doit pas bloquer l'app
        _log("échec pour %s : %s" % (to, exc))
        return finish("echec", str(exc))
    _log("envoyé à %s" % to)
    return finish("envoye")


def send_template(key, to, values, request_id=None):
    """Rend le message automatique `key` avec `values` et l'envoie."""
    return send_rendered(to, mail_templates.render(key, values), key, request_id)


def send_mail(to, subject, body, template="", request_id=None):
    """Envoi d'un texte libre avec la mise en page commune (sans gabarit). Retourne (ok, erreur)."""
    layout = mail_templates.load()["layout"]
    text = mail_templates.with_signature(body, layout)
    rendered = {"subject": subject, "text": text, "enabled": True, "layout": layout,
                "html": mail_templates.wrap(text, layout)}
    return send_rendered(to, rendered, template, request_id)


def notify_validator(validator_email, validator_name, agent_name, code, code_label,
                     cells, year, days, comment, fiche_id, request_id, extra=None):
    """Prévient le valideur d'une nouvelle demande (en arrière-plan). `extra` : variables supplémentaires
    (liens Valider / Refuser / calendrier d'équipe propres au destinataire)."""
    cfg = load_config()
    if not cfg:
        return
    to = (validator_email or "").strip()
    if not to:
        _log("aucune adresse e-mail pour le valideur %s (demande %s)" % (validator_name or "?", request_id))
        audit_logs.log_mail("", "Nouvelle demande de %s" % agent_name, "nouvelle_demande", "non_envoye",
                            "Le valideur %s n'a pas d'adresse e-mail" % (validator_name or "?"), "", request_id)
        return
    base = (cfg.get("base_url") or "").rstrip("/")
    values = {
        "agent": agent_name, "code": code, "code_libelle": code_label,
        "dates": "\n".join("  - %s" % line for line in format_ranges(cells, year)),
        "jours": _format_days(days), "commentaire": comment or "—", "annee": str(year),
        "lien_fiche": "%s/#/agent/%s" % (base, fiche_id) if base else "",
        "lien_demandes": "%s/#/requests" % base if base else "",
    }
    values.update(extra or {})
    threading.Thread(
        target=send_template, args=("nouvelle_demande", to, values, request_id), daemon=True
    ).start()
