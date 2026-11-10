# -*- coding: utf-8 -*-
"""Client unique de l'API centrale APM (services transverses de la Ville).

Tous les appels à l'APM passent par ce module (clé `X-API-KEY`, URL et TLS lus dans la
configuration) : authentification Active Directory (`ad_auth`) et envoi de mail (`mail_send`).
Une panne réseau ou une réponse 5xx lève `ApmError` (service indisponible) ; un refus
d'identifiants n'est PAS une erreur, c'est un résultat (`False`).
"""
import requests

import config


class ApmError(Exception):
    """L'APM est injoignable ou répond de façon inattendue (≠ identifiants invalides)."""


def configured():
    return bool(config.APM_API_URL and config.APM_API_KEY)


def _verify():
    if config.VILLE_CA_FILE:
        return config.VILLE_CA_FILE
    return not config.VILLE_ALLOW_SELF_SIGNED_CERTS


def _post(route, payload, timeout=15):
    if not configured():
        raise ApmError("APM non configurée (APM_API_URL / APM_API_KEY)")
    url = config.APM_API_URL.rstrip("/") + route
    try:
        resp = requests.post(
            url, json=payload, headers={"X-API-KEY": config.APM_API_KEY},
            timeout=timeout, verify=_verify(),
        )
    except requests.RequestException as exc:
        raise ApmError("APM %s : %s" % (route, exc.__class__.__name__)) from exc
    if resp.status_code >= 500:
        raise ApmError("APM %s : HTTP %s" % (route, resp.status_code))
    return resp


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}


def ad_authenticate(username, password):
    """True si l'AD valide le couple identifiant / mot de passe, False sinon."""
    if not username or not password:
        return False
    resp = _post("/api/v1/ad/authenticate", {"username": username, "password": password})
    data = _json(resp)
    if resp.status_code == 200 and data.get("success") is True:
        return True
    if resp.status_code in (400, 401) or data.get("success") is False:
        return False
    # 403/404… : permission `ad_auth` absente ou route modifiée — ce n'est pas un mauvais mot de passe.
    raise ApmError("APM ad/authenticate : HTTP %s (permission ad_auth ?)" % resp.status_code)


def send_mail(to, subject, html, footer=None):
    """Envoie un mail via l'APM. `html` = corps seul (l'APM l'insère dans le gabarit institutionnel)."""
    body = {"to": to, "subject": subject, "content": html}
    footer = footer or {}
    for key, name in (("line1", "footer1"), ("line2", "footer2"), ("line3", "footer3"),
                      ("color", "footerColor")):
        if footer.get(key):
            body[name] = footer[key]
    resp = _post("/api/v1/mail/send", body, timeout=30)
    data = _json(resp)
    if resp.status_code == 200 and (data.get("status") == "success" or data.get("success") is True):
        return
    raise ApmError("APM mail/send : HTTP %s %s" % (resp.status_code, data.get("message", "")))


def _normalize_ad_user(item):
    if not isinstance(item, dict):
        return None
    username = str(item.get("sAMAccountName") or item.get("username") or item.get("login") or "").strip().lower()
    if not username:
        return None
    return {
        "username": username,
        "displayName": item.get("displayName") or item.get("cn") or username,
        "email": (item.get("mail") or item.get("email") or "").lower(),
    }


def ad_search(query, limit=15):
    """Recherche d'agents dans l'AD (`ad_search`) : liste de {username, displayName, email}."""
    if not configured():
        raise ApmError("APM non configurée (APM_API_URL / APM_API_KEY)")
    try:
        resp = requests.get(
            config.APM_API_URL.rstrip("/") + "/api/v1/ad/search", params={"q": query},
            headers={"X-API-KEY": config.APM_API_KEY}, timeout=15, verify=_verify(),
        )
    except requests.RequestException as exc:
        raise ApmError("APM ad/search : %s" % exc.__class__.__name__) from exc
    if resp.status_code != 200:
        raise ApmError("APM ad/search : HTTP %s (permission ad_search ?)" % resp.status_code)
    data = _json(resp)
    items = data if isinstance(data, list) else next(
        (data[k] for k in ("data", "users", "results") if isinstance(data.get(k), list)), [])
    users = [u for u in (_normalize_ad_user(i) for i in items) if u]
    return users[:limit]
