# -*- coding: utf-8 -*-
"""« Se souvenir de moi » : connexion persistante de 30 jours.

À la connexion, si la personne le demande (et qu'elle n'est pas administrateur), un jeton aléatoire est généré ; seul son haché est conservé en base, le jeton lui-même
voyage dans un cookie HttpOnly. Quand la session a expiré, `user_id_from_cookie` retrouve la personne par ce cookie (et prolonge le jeton). Le jeton est supprimé à la
déconnexion et à chaque changement de mot de passe ; 5 appareils au plus par personne (le plus ancien est retiré).
"""
import datetime as dt
import hashlib
import secrets

from flask import request

import config

COOKIE = "conges_remember"
DAYS = 30
MAX_DEVICES = 5


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(db, user_id, response):
    """Crée un jeton pour la personne et le pose dans le cookie de la réponse."""
    token = secrets.token_urlsafe(32)
    expire = dt.datetime.now() + dt.timedelta(days=DAYS)
    db.execute("INSERT INTO remember_tokens (user_id, token_hash, expire_le, appareil) VALUES (?,?,?,?)",
               (user_id, _hash(token), expire, (request.headers.get("User-Agent") or "")[:200]))
    old = db.execute("SELECT id FROM remember_tokens WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    for row in old[MAX_DEVICES:]:
        db.execute("DELETE FROM remember_tokens WHERE id=?", (row["id"],))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=DAYS * 86400, httponly=True, samesite="Lax", secure=bool(config.COOKIE_SECURE), path="/")


def user_id_from_cookie(db):
    """Identifiant de la personne dont le jeton (cookie) est valable, sinon None ; prolonge le jeton de 30 jours."""
    token = request.cookies.get(COOKIE) or ""
    if not token:
        return None
    row = db.execute("SELECT id, user_id FROM remember_tokens WHERE token_hash=? AND expire_le > ?", (_hash(token), dt.datetime.now())).fetchone()
    if not row:
        return None
    db.execute("UPDATE remember_tokens SET derniere_utilisation=?, expire_le=? WHERE id=?",
               (dt.datetime.now(), dt.datetime.now() + dt.timedelta(days=DAYS), row["id"]))
    db.commit()
    return row["user_id"]


def revoke_cookie(db, response=None):
    """Supprime le jeton de ce navigateur (déconnexion)."""
    token = request.cookies.get(COOKIE) or ""
    if token:
        db.execute("DELETE FROM remember_tokens WHERE token_hash=?", (_hash(token),))
        db.commit()
    if response is not None:
        response.delete_cookie(COOKIE, path="/")


def revoke_all(db, user_id):
    """Supprime tous les jetons de la personne (changement de mot de passe)."""
    db.execute("DELETE FROM remember_tokens WHERE user_id=?", (user_id,))
