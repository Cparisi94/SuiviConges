# -*- coding: utf-8 -*-
"""Clés API des applications tierces : génération, vérification, périmètres et administration.

- une clé (`cgk_` + 64 caractères hexadécimaux) n'est affichée qu'une fois, à sa création ;
  seule son empreinte SHA-256 est conservée ;
- chaque clé porte des périmètres (scopes), une liste d'IP/réseaux autorisés et une date
  d'expiration facultatives ;
- chaque appel est journalisé (méthode, chemin, statut, IP), sans contenu.
"""
import datetime as dt
import hashlib
import ipaddress
import re
import secrets
from functools import wraps

from flask import Blueprint, g, jsonify, request

import config
import ratelimit
from db import get_db, row_to_dict
from http_utils import error, page_args, paged

PREFIX = "cgk_"
SCOPES = {
    "agents:read": "Liste et identité des fiches agents",
    "balances:read": "Soldes de congés, RTT, CET… d'une fiche",
    "absences:read": "Absences saisies (demi-journées) sur une période",
    "requests:read": "Demandes de congés et leur état",
}
PUBLIC_FIELDS = "id, name, key_prefix, scopes, allowed_ips, expires_at, actif, created_at, last_used_at"

admin_bp = Blueprint("api_keys_admin", __name__, url_prefix="/api/v1/admin/api-keys")


# --------------------------------------------------------------------------- #
#  Génération et validation des champs
# --------------------------------------------------------------------------- #
def hash_key(plain):
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def new_key():
    return PREFIX + secrets.token_hex(32)


def clean_scopes(raw):
    """Liste de périmètres (ou texte séparé par des virgules) -> texte normalisé ; ValueError si inconnu."""
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    scopes = sorted({str(s).strip() for s in items if str(s).strip()})
    unknown = [s for s in scopes if s != "*" and s not in SCOPES]
    if unknown:
        raise ValueError("Périmètre inconnu : %s" % ", ".join(unknown))
    if not scopes:
        raise ValueError("Au moins un périmètre est obligatoire")
    return ",".join(scopes)


def clean_ips(raw):
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    nets = []
    for item in (str(i).strip() for i in items):
        if item:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                raise ValueError("Adresse ou réseau invalide : %s" % item) from None
            nets.append(item)
    return ",".join(nets)


def clean_expiry(raw):
    raw = (raw or "").strip()
    if raw and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("Date d'expiration invalide (format AAAA-MM-JJ)")
    return raw


def _ip_allowed(allowed, ip):
    if not allowed:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in allowed.split(","))


# --------------------------------------------------------------------------- #
#  Contrôle d'accès des routes /api/v1 (décorateur)
# --------------------------------------------------------------------------- #
def _presented_key():
    key = request.headers.get("X-API-Key", "")
    if not key:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:]
    return key.strip()


def _log_call(key_id, status):
    db = get_db()
    db.execute(
        "INSERT INTO api_key_logs (key_id, method, path, status, ip) VALUES (?,?,?,?,?)",
        (key_id, request.method, request.path[:200], status, request.remote_addr or ""),
    )
    db.commit()
    db.close()


def api_key_required(scope):
    """Exige une clé valide portant le périmètre `scope` (ou `*`)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            plain = _presented_key()
            if not plain.startswith(PREFIX):
                return error("Clé API requise (en-tête X-API-Key)", 401)
            if not ratelimit.allow("apikey:" + hash_key(plain)[:16], config.API_RATE_LIMIT, 60):
                return error("Trop de requêtes, réessayez dans une minute", 429)
            db = get_db()
            row = db.execute(
                "SELECT * FROM api_keys WHERE key_hash=?", (hash_key(plain),)
            ).fetchone()
            db.close()
            if not row or not row["actif"]:
                return error("Clé API invalide ou désactivée", 401)
            if row["expires_at"] and row["expires_at"] < dt.date.today().isoformat():
                return error("Clé API expirée", 401)
            if not _ip_allowed(row["allowed_ips"], request.remote_addr or ""):
                _log_call(row["id"], 403)
                return error("Adresse IP non autorisée pour cette clé", 403)
            granted = set(row["scopes"].split(","))
            if "*" not in granted and scope not in granted:
                _log_call(row["id"], 403)
                return error("Périmètre insuffisant (%s requis)" % scope, 403)
            g.api_key = row_to_dict(row)
            response = fn(*args, **kwargs)
            status = response[1] if isinstance(response, tuple) else response.status_code
            _log_call(row["id"], status)
            db = get_db()
            db.execute("UPDATE api_keys SET last_used_at=to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS') WHERE id=?",
                       (row["id"],))
            db.commit()
            db.close()
            return response
        return wrapper
    return decorator


# --------------------------------------------------------------------------- #
#  Administration des clés (session administrateur) — branchée par init_admin()
# --------------------------------------------------------------------------- #
def _fields_from(data, current=None):
    current = current or {}
    name = (data.get("name", current.get("name")) or "").strip()
    if not name:
        raise ValueError("Le nom de l'application est obligatoire")
    return {
        "name": name,
        "scopes": clean_scopes(data["scopes"]) if "scopes" in data else current.get("scopes", ""),
        "allowed_ips": clean_ips(data["allowed_ips"]) if "allowed_ips" in data else current.get("allowed_ips", ""),
        "expires_at": clean_expiry(data["expires_at"]) if "expires_at" in data else current.get("expires_at", ""),
    }


def init_admin(app, admin_required):
    @admin_bp.route("", methods=["GET"])
    @admin_required
    def list_keys():
        db = get_db()
        rows = db.execute("SELECT %s FROM api_keys ORDER BY id" % PUBLIC_FIELDS).fetchall()
        db.close()
        return jsonify({"scopes": SCOPES, "items": [row_to_dict(r) for r in rows]})

    @admin_bp.route("", methods=["POST"])
    @admin_required
    def create_key():
        data = request.get_json(force=True) or {}
        try:
            f = _fields_from(data)
        except ValueError as exc:
            return error(str(exc), 400)
        plain = new_key()
        db = get_db()
        cur = db.execute(
            "INSERT INTO api_keys (name, key_prefix, key_hash, scopes, allowed_ips, expires_at, created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (f["name"], plain[:8], hash_key(plain), f["scopes"], f["allowed_ips"], f["expires_at"],
             request.user["id"]),
        )
        db.commit()
        row = db.execute("SELECT %s FROM api_keys WHERE id=?" % PUBLIC_FIELDS, (cur.lastrowid,)).fetchone()
        db.close()
        body = row_to_dict(row)
        body["key"] = plain  # affichée une seule fois
        return jsonify(body), 201

    @admin_bp.route("/<int:key_id>", methods=["PUT"])
    @admin_required
    def update_key(key_id):
        data = request.get_json(force=True) or {}
        db = get_db()
        row = db.execute("SELECT * FROM api_keys WHERE id=?", (key_id,)).fetchone()
        if not row:
            db.close()
            return error("Clé introuvable", 404)
        try:
            f = _fields_from(data, row_to_dict(row))
        except ValueError as exc:
            db.close()
            return error(str(exc), 400)
        actif = 1 if data.get("actif", row["actif"]) else 0
        db.execute(
            "UPDATE api_keys SET name=?, scopes=?, allowed_ips=?, expires_at=?, actif=? WHERE id=?",
            (f["name"], f["scopes"], f["allowed_ips"], f["expires_at"], actif, key_id),
        )
        db.commit()
        out = db.execute("SELECT %s FROM api_keys WHERE id=?" % PUBLIC_FIELDS, (key_id,)).fetchone()
        db.close()
        return jsonify(row_to_dict(out))

    @admin_bp.route("/<int:key_id>", methods=["DELETE"])
    @admin_required
    def delete_key(key_id):
        db = get_db()
        cur = db.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True}) if cur.rowcount else error("Clé introuvable", 404)

    @admin_bp.route("/<int:key_id>/logs", methods=["GET"])
    @admin_required
    def key_logs(key_id):
        limit, offset = page_args(default=50, maximum=500)
        db = get_db()
        total = db.execute("SELECT COUNT(*) AS c FROM api_key_logs WHERE key_id=?", (key_id,)).fetchone()["c"]
        rows = db.execute(
            "SELECT at, method, path, status, ip FROM api_key_logs WHERE key_id=? "
            "ORDER BY id DESC LIMIT ? OFFSET ?", (key_id, limit, offset),
        ).fetchall()
        db.close()
        return paged([row_to_dict(r) for r in rows], total, limit, offset)

    app.register_blueprint(admin_bp)
