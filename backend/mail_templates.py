# -*- coding: utf-8 -*-
"""Gabarits des e-mails automatiques et mise en page commune (en-tête, pied de page, expéditeur).

- chaque e-mail automatique est décrit dans TEMPLATES (objet, texte, variables disponibles, exemple) ;
  l'administrateur peut modifier l'objet, le texte et l'activation (Paramétrage > E-mails) ;
- la mise en page commune (expéditeur, signature, pied de page) s'applique à TOUS les e-mails : l'expéditeur et le pied de
  page sont transmis à l'API centrale en paramètres, l'en-tête est le gabarit institutionnel de l'APM (non paramétrable ici) ;
- l'envoi des e-mails est activé ou désactivé dans Paramétrage > E-mails (clé `mail`, champ `enabled`, désactivé par défaut) ;
- les réglages sont stockés dans la table `settings` (clé `mail`) ; ce qui n'y figure pas prend la valeur
  par défaut ci-dessous (ou les variables d'environnement CONGES_MAIL_FOOTER* pour le pied de page).

Variables : `{nom}` dans l'objet ou le texte. Une ligne dont toutes les variables sont vides est supprimée
(ex. « Fiche : {lien_fiche} » quand l'adresse de l'application n'est pas renseignée). Le texte est du texte
brut : tout est échappé avant envoi, les adresses http(s) deviennent des liens.
"""
import html
import json
import re

import config
from db import get_db

VAR = re.compile(r"\{([a-z_]+)\}")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

TEMPLATES = {
    "nouvelle_demande": {
        "label": "Nouvelle demande à valider",
        "description": "Envoyé au valideur dès qu'un agent soumet une demande d'absence.",
        "recipients": "le valideur de la demande",
        "variables": {
            "agent": "Nom et prénom de l'agent",
            "code": "Code de l'absence (CA, RTT…)",
            "code_libelle": "Libellé du code",
            "dates": "Liste des demi-journées demandées",
            "jours": "Nombre de jours",
            "commentaire": "Commentaire de l'agent",
            "annee": "Année de la fiche",
            "lien_fiche": "Lien vers la fiche de l'agent",
            "lien_demandes": "Lien vers les demandes à valider",
        },
        "subject": "[Suivi congés] Demande de {agent} — {code_libelle}",
        "body": (
            "Bonjour,\n\n{agent} a soumis une demande de congé.\n\n"
            "Code : {code_libelle} ({code})\nDemi-journées :\n{dates}\n\n"
            "Nombre de jours : {jours}\nCommentaire : {commentaire}\n\n"
            "Fiche : {lien_fiche}\nDemandes à valider : {lien_demandes}\n\n"
            "Cette demande est en attente de votre validation."
        ),
        "sample": {
            "agent": "DUPONT Marie", "code": "CA", "code_libelle": "Congé annuel",
            "dates": "  - 3 mai 2027 — matin\n  - 3 mai 2027 — après-midi", "jours": "1",
            "commentaire": "Pont de l'Ascension", "annee": "2027",
            "lien_fiche": "https://conges.example.fr/#/agent/12", "lien_demandes": "https://conges.example.fr/#/requests",
        },
    },
    "relance_demandes": {
        "label": "Relance des demandes en attente",
        "description": "Envoyé chaque jour au valideur qui a des demandes en attente depuis plusieurs jours.",
        "recipients": "chaque valideur concerné (au plus un mail par jour)",
        "variables": {
            "nombre": "Nombre de demandes en attente",
            "jours": "Ancienneté à partir de laquelle on relance",
            "liste": "Liste des demandes (agent, code, date)",
            "lien_demandes": "Lien vers les demandes à valider",
        },
        "subject": "[Suivi congés] Relance : {nombre} demande(s) en attente",
        "body": (
            "Bonjour,\n\nLes demandes suivantes sont en attente depuis plus de {jours} jours :\n\n{liste}\n\n"
            "Merci de les traiter dans l'outil de suivi des congés.\n{lien_demandes}"
        ),
        "sample": {
            "nombre": "2", "jours": "3", "lien_demandes": "https://conges.example.fr/#/requests",
            "liste": "- DUPONT Marie — CA — demande du 28/04/2027\n- MARTIN Paul — RTT — demande du 29/04/2027",
        },
    },
    "test_envoi": {
        "label": "Message de test",
        "description": "Envoyé uniquement depuis cet écran, pour vérifier la mise en page.",
        "recipients": "l'adresse saisie pour le test",
        "variables": {"administrateur": "Nom de l'administrateur qui fait le test", "date": "Date et heure du test"},
        "subject": "[Suivi congés] Test d'envoi",
        "body": "Bonjour,\n\nCeci est un message de test envoyé par {administrateur} le {date}.\n"
                "Il permet de vérifier l'en-tête, le pied de page et l'expéditeur des e-mails de l'application.",
        "sample": {"administrateur": "Marc CHEVALIER", "date": "03/05/2027 09:30"},
    },
}

DEFAULT_LAYOUT = {
    "from_name": "",            # vide : expéditeur par défaut de l'APM
    "from_email": "",
    "signature": "Cordialement,\nOutil de suivi des congés",
    "footer1": config.MAIL_FOOTER1,
    "footer2": config.MAIL_FOOTER2,
    "footer3": config.MAIL_FOOTER3,
    "footer_color": config.MAIL_FOOTER_COLOR,
}
LAYOUT_MAX = {"from_name": 80, "from_email": 120, "header_title": 120, "signature": 500,
              "footer1": 160, "footer2": 160, "footer3": 160}


# --------------------------------------------------------------------------- #
#  Lecture / écriture des réglages
# --------------------------------------------------------------------------- #
def _stored():
    db = get_db()
    try:
        row = db.execute("SELECT valeur FROM settings WHERE cle='mail'").fetchone()
    finally:
        db.close()
    try:
        data = json.loads(row["valeur"]) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def load():
    """Réglages effectifs : valeurs enregistrées, sinon valeurs par défaut."""
    stored = _stored()
    layout = {**DEFAULT_LAYOUT, **{k: v for k, v in (stored.get("layout") or {}).items() if k in DEFAULT_LAYOUT}}
    templates = {}
    for key, tpl in TEMPLATES.items():
        mine = (stored.get("templates") or {}).get(key) or {}
        templates[key] = {
            "subject": mine.get("subject") or tpl["subject"],
            "body": mine.get("body") or tpl["body"],
            "enabled": bool(mine.get("enabled", True)),
        }
    return {"enabled": bool(stored.get("enabled", False)), "layout": layout, "templates": templates}


def is_enabled():
    """L'envoi automatique des e-mails est-il activé (réglage de l'administrateur) ?"""
    return bool(_stored().get("enabled", False))


def unknown_variables(key, *texts):
    allowed = set(TEMPLATES[key]["variables"])
    return sorted({v for text in texts for v in VAR.findall(text or "")} - allowed)


def validate(payload):
    """Contrôle une mise à jour {layout, templates} ; retourne (réglages à stocker, erreur)."""
    out = {"layout": {}, "templates": {}}
    if "enabled" in payload:
        out["enabled"] = bool(payload["enabled"])
    for key, value in (payload.get("layout") or {}).items():
        if key not in DEFAULT_LAYOUT:
            return None, "Réglage inconnu : %s" % key
        value = str(value or "").strip()
        if key.endswith("_color"):
            if not COLOR.match(value):
                return None, "Couleur invalide (format #RRGGBB) : %s" % key
        elif len(value) > LAYOUT_MAX[key]:
            return None, "Texte trop long : %s" % key
        if key == "from_email" and value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            return None, "Adresse d'expéditeur invalide"
        out["layout"][key] = value
    for key, value in (payload.get("templates") or {}).items():
        if key not in TEMPLATES:
            return None, "Message inconnu : %s" % key
        subject, body = str(value.get("subject") or "").strip(), str(value.get("body") or "").strip()
        if not subject or not body:
            return None, "L'objet et le texte de « %s » sont obligatoires" % TEMPLATES[key]["label"]
        if len(subject) > 200 or len(body) > 5000:
            return None, "Objet ou texte trop long pour « %s »" % TEMPLATES[key]["label"]
        unknown = unknown_variables(key, subject, body)
        if unknown:
            return None, "Variable(s) inconnue(s) dans « %s » : %s" % (
                TEMPLATES[key]["label"], ", ".join("{%s}" % v for v in unknown))
        out["templates"][key] = {"subject": subject, "body": body, "enabled": bool(value.get("enabled", True))}
    return out, None


def save(update):
    """Fusionne `update` (déjà validé) avec les réglages enregistrés."""
    current = _stored()
    if "enabled" in update:
        current["enabled"] = bool(update["enabled"])
    current.setdefault("layout", {}).update(update.get("layout") or {})
    current.setdefault("templates", {}).update(update.get("templates") or {})
    db = get_db()
    db.execute(
        "INSERT INTO settings (cle, valeur) VALUES ('mail', ?) ON CONFLICT (cle) DO UPDATE SET valeur=excluded.valeur",
        (json.dumps(current, ensure_ascii=False),),
    )
    db.commit()
    db.close()


def reset(key):
    current = _stored()
    (current.get("templates") or {}).pop(key, None)
    db = get_db()
    db.execute(
        "INSERT INTO settings (cle, valeur) VALUES ('mail', ?) ON CONFLICT (cle) DO UPDATE SET valeur=excluded.valeur",
        (json.dumps(current, ensure_ascii=False),),
    )
    db.commit()
    db.close()


# --------------------------------------------------------------------------- #
#  Rendu
# --------------------------------------------------------------------------- #
def substitute(text, values):
    """Remplace {variable} ; supprime les lignes dont toutes les variables sont vides."""
    lines = []
    for line in (text or "").split("\n"):
        names = VAR.findall(line)
        if names and all(not str(values.get(n, "")).strip() for n in names):
            continue
        lines.append(VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), line))
    return "\n".join(lines)


def to_html(text):
    """Texte brut -> HTML (échappé ; les adresses http(s) deviennent des liens)."""
    out = []
    for line in text.split("\n"):
        escaped = html.escape(line)
        out.append(re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escaped))
    return "<br>\n".join(out)


def wrap(text, layout=None):
    """Texte complet (signature comprise) -> HTML du corps du message (l'en-tête et le pied de page viennent de l'APM)."""
    return "<p>" + to_html(text).replace("<br>\n<br>\n", "</p>\n<p>") + "</p>"


def with_signature(text, layout):
    return text + ("\n\n" + layout["signature"] if layout["signature"] else "")


def render(key, values, settings=None):
    """Retourne {subject, text, html, enabled, layout} prêt à l'envoi."""
    settings = settings or load()
    tpl, layout = settings["templates"][key], settings["layout"]
    subject = substitute(tpl["subject"], values).replace("\n", " ").strip()
    full_text = with_signature(substitute(tpl["body"], values), layout)
    return {"subject": subject, "text": full_text, "html": wrap(full_text, layout),
            "enabled": tpl["enabled"], "layout": layout}
