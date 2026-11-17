# -*- coding: utf-8 -*-
"""Mode « backend mobile » : le même code, lancé dans un conteneur séparé (CONGES_MODE=mobile, point d'entrée `wsgi_mobile`),
ne répond QU'aux routes de la version mobile ; tout le reste est un 404, même si un nginx mal réglé le laisse passer.

Ce backend sert aussi la page mobile (dossier `conges-mobile-dmz/public`, monté en lecture seule) : un seul conteneur répond à l'adresse
`/mobile/` du serveur (le nginx retire le préfixe), sans que la page fasse le moindre appel au backend complet.

- cookie de session propre (`conges_mobile`, chemin `CONGES_COOKIE_PATH`) : une session ouverte ici n'authentifie rien dans l'application complète ;
- en-têtes de sécurité stricts sur toutes les réponses (même politique que le nginx de la DMZ) ;
- ni relances, ni synchronisation Outlook, ni migrations : ces tâches restent celles du backend principal (voir `wsgi_mobile.py`).

Routes autorisées : voir ALLOWED. La première connexion d'un compte sans AD (`/api/activation/*`) en fait partie.
"""
import os
import re
from pathlib import Path

from flask import jsonify, request, send_from_directory

MODE = os.environ.get("CONGES_MODE", "full").strip().lower()

TOKEN = r"[A-Za-z0-9_-]{20,80}"
ALLOWED = [
    ({"POST"}, re.compile(r"^/api/auth/login$")),
    ({"POST"}, re.compile(r"^/api/auth/logout$")),
    ({"GET"}, re.compile(r"^/api/me$")),
    ({"GET"}, re.compile(r"^/api/status$")),                                           # sonde de santé du conteneur
    ({"GET"}, re.compile(r"^/api/mobile/(summary|days|calendar)$")),
    ({"POST"}, re.compile(r"^/api/mobile/calendar/(link|revoke)$")),
    ({"POST"}, re.compile(r"^/api/mobile/requests/[0-9]+/(cancel|cancel-request)$")),
    ({"POST"}, re.compile(r"^/api/requests$")),
    ({"POST"}, re.compile(r"^/api/activation/[a-z_-]+$")),                             # première connexion d'un compte sans AD (code, SMS, mot de passe)
    ({"GET", "HEAD"}, re.compile(r"^/api/ical/%s\.ics$" % TOKEN)),                     # flux d'abonnement : le jeton fait foi, sans session
    ({"GET", "HEAD"}, re.compile(r"^/cal/%s\.ics$" % TOKEN)),
]
PAGE_FILES = {"/": "index.html", "/index.html": "index.html", "/mobile.js": "mobile.js", "/mobile.css": "mobile.css"}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def is_allowed(method, path):
    """La requête fait-elle partie des routes de la version mobile ?"""
    return any(method in methods and rx.match(path) for methods, rx in ALLOWED)


def public_dir():
    """Dossier de la page mobile : CONGES_MOBILE_PUBLIC (conteneur), sinon `conges-mobile-dmz/public` à côté du dossier backend (poste de développement)."""
    env = os.environ.get("CONGES_MOBILE_PUBLIC", "").strip()
    return Path(env) if env else Path(__file__).resolve().parent.parent / "conges-mobile-dmz" / "public"


def apply(app, force=False):
    """Active le mode mobile sur `app` (si CONGES_MODE=mobile, ou `force`) ; retourne True s'il est actif. Sans effet la seconde fois."""
    if (MODE != "mobile" and not force) or app.extensions.get("mobile_mode"):
        return bool(app.extensions.get("mobile_mode"))
    app.extensions["mobile_mode"] = True
    app.config["SESSION_COOKIE_NAME"] = "conges_mobile"
    cookie_path = os.environ.get("CONGES_COOKIE_PATH", "").strip()
    if cookie_path:
        app.config["SESSION_COOKIE_PATH"] = cookie_path

    def guard():
        path, method = request.path, request.method
        if method in ("GET", "HEAD") and path in PAGE_FILES:
            return send_from_directory(str(public_dir()), PAGE_FILES[path], max_age=0)
        if is_allowed(method, path):
            return None
        return jsonify({"error": "Introuvable"}), 404

    # en tête des filtres : une route interdite ne touche jamais la base
    app.before_request_funcs.setdefault(None, []).insert(0, guard)

    @app.after_request
    def secure(resp):
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.path in PAGE_FILES:
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    return True
