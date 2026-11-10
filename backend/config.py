# -*- coding: utf-8 -*-
"""Configuration centralisée de l'application.

Toutes les valeurs (ports, chemins, secrets, URLs d'API) proviennent de
variables d'environnement, chargées au besoin depuis un fichier `.env` situé à
côté de ce module. Aucune valeur sensible n'est écrite en dur dans le code.
Voir `.env.example` pour la liste documentée.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # backend/
ROOT_DIR = os.path.dirname(BASE_DIR)                          # racine du dépôt


def _load_dotenv(path):
    """Charge un fichier .env (KEY=VALUE) sans écraser l'environnement existant."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key.strip(), value)


# .env à la racine du dépôt (partagé avec docker-compose) ; un .env dans backend/ reste accepté.
_load_dotenv(os.path.join(ROOT_DIR, ".env"))
_load_dotenv(os.path.join(BASE_DIR, ".env"))


def _path(name, default):
    value = os.environ.get(name) or default
    return value if os.path.isabs(value) else os.path.join(BASE_DIR, value)


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "oui", "yes")


# --- Application --------------------------------------------------------- #
HOST = os.environ.get("CONGES_HOST", "127.0.0.1")
PORT = int(os.environ.get("CONGES_PORT", "8110"))
SECRET_KEY = os.environ.get("CONGES_SECRET_KEY", "")
COOKIE_SECURE = _flag("CONGES_COOKIE_SECURE")
SESSION_HOURS = int(os.environ.get("CONGES_SESSION_HOURS", "10"))
# Sécurité réseau : nombre de proxys de confiance devant l'application (X-Forwarded-For), origines CORS
# autorisées (séparées par des virgules), limites de débit.
PROXY_HOPS = int(os.environ.get("CONGES_PROXY_HOPS", "0"))
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CONGES_CORS_ORIGINS", "").split(",") if o.strip()]
API_RATE_LIMIT = int(os.environ.get("CONGES_API_RATE_LIMIT", "120"))        # requêtes / minute / clé API
LOGIN_MAX_FAILURES = int(os.environ.get("CONGES_LOGIN_MAX_FAILURES", "8"))  # échecs / 15 min / IP
INITIAL_ADMIN_PASSWORD = os.environ.get("CONGES_INITIAL_ADMIN_PASSWORD", "")
BASE_URL = os.environ.get("CONGES_BASE_URL", "").rstrip("/")  # lien vers l'application dans les mails
# local : mots de passe de l'application ; ad : Active Directory via l'APM
# (les comptes administrateurs gardent aussi leur mot de passe local, compte de secours si l'AD est indisponible).
AUTH_MODE = os.environ.get("CONGES_AUTH_MODE", "local").strip().lower()

# --- Stockage ------------------------------------------------------------- #
# Ancienne base SQLite : lue uniquement par le script de transfert (migrate_sqlite_to_pg.py).
SQLITE_PATH = _path("CONGES_SQLITE_PATH", os.path.join(ROOT_DIR, "suivi-conges.db"))
# Frontend servi par Flask en développement seulement (en Docker, c'est nginx qui le sert).
FRONTEND_DIR = _path("CONGES_FRONTEND_DIR", os.path.join(ROOT_DIR, "frontend", "public"))
UPLOAD_DIR = _path("CONGES_UPLOAD_DIR", os.path.join("uploads", "requests"))
SECRET_FILE = _path("CONGES_SECRET_FILE", ".secret_key")

# --- Tâches de fond ------------------------------------------------------- #
DISABLE_REMINDERS = _flag("CONGES_DISABLE_REMINDERS")

# --- Services de la Ville (utilisés aux étapes suivantes) ---------------- #
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "ivry_admin")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
PG_SCHEMA = os.environ.get("CONGES_PG_SCHEMA", "conges")
PG_POOL_MAX = int(os.environ.get("CONGES_PG_POOL_MAX", "10"))
APM_API_URL = os.environ.get("APM_API_URL", "")
APM_API_KEY = os.environ.get("APM_API_KEY", "")
HUBDSI_API_URL = os.environ.get("HUBDSI_API_URL", "")
HUBDSI_API_KEY = os.environ.get("HUBDSI_API_KEY", "")

# --- TLS vers les services internes (certificats auto-signés de la Ville) -- #
VILLE_CA_FILE = os.environ.get("VILLE_CA_FILE", "")
VILLE_ALLOW_SELF_SIGNED_CERTS = _flag("VILLE_ALLOW_SELF_SIGNED_CERTS")

# --- Mails (envoyés via l'APM ; pied de page transmis en paramètres) ------- #
MAIL_ENABLED = _flag("CONGES_MAIL_ENABLED")
MAIL_FOOTER1 = os.environ.get("CONGES_MAIL_FOOTER1", "Ville d'Ivry-sur-Seine")
MAIL_FOOTER2 = os.environ.get("CONGES_MAIL_FOOTER2", "Direction des Ressources Humaines")
MAIL_FOOTER3 = os.environ.get("CONGES_MAIL_FOOTER3", "")
MAIL_FOOTER_COLOR = os.environ.get("CONGES_MAIL_FOOTER_COLOR", "#0055A4")
