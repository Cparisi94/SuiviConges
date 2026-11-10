# -*- coding: utf-8 -*-
"""Accès PostgreSQL (schéma dédié) et exécuteur de migrations.

- un pool de connexions ; le schéma de l'application et le fuseau Europe/Paris sont fixés
  au niveau de la connexion (search_path / TimeZone) ;
- une enveloppe de connexion qui reprend l'interface utilisée par le reste du code
  (`execute`, `executemany`, `commit`, `close`, `lastrowid`, lignes accessibles par nom
  ou par position) : les requêtes continuent d'utiliser les marqueurs `?` ;
- les migrations sont des fichiers SQL numérotés (`migrations/0001_*.sql`), chacun exécuté
  dans sa transaction et vérifié par somme de contrôle (même principe que les autres applications).
"""
import atexit
import hashlib
import os
import re
import threading

import psycopg
from psycopg_pool import ConnectionPool

import config

MIGRATIONS_DIR = os.path.join(config.BASE_DIR, "migrations")
_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+([a-z_]+)", re.IGNORECASE)
# Tables dont la clé primaire « id » est générée : on la renvoie comme `lastrowid`.
_ID_TABLES = {
    "users", "user_audit", "agents", "leave_requests",
    "leave_request_events", "hourly_absences", "api_keys", "api_key_logs",
}

_pool = None
_pool_lock = threading.Lock()


class Row(dict):
    """Ligne de résultat : accès par nom de colonne ou par position (comme sqlite3.Row)."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [col.name for col in (cursor.description or [])]
    return lambda values: Row(zip(names, values))


def _conn_kwargs():
    return {
        "host": config.POSTGRES_HOST,
        "port": config.POSTGRES_PORT,
        "dbname": config.POSTGRES_DB,
        "user": config.POSTGRES_USER,
        "password": config.POSTGRES_PASSWORD,
        "options": "-c search_path=%s,public -c TimeZone=Europe/Paris" % config.PG_SCHEMA,
        "connect_timeout": 10,
        "row_factory": _row_factory,
    }


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                kwargs=_conn_kwargs(), min_size=1, max_size=config.PG_POOL_MAX,
                open=True, name="conges",
            )
        return _pool


def reset_pool():
    """Ferme le pool (changement de schéma, tests)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(lambda: reset_pool())


def _translate(sql):
    """Marqueurs `?` (style SQLite) vers `%s` ; les `%` littéraux sont protégés."""
    return sql.replace("%", "%%").replace("?", "%s")


class Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class Connection:
    """Connexion prise dans le pool ; `close()` la rend au pool (annule toute transaction ouverte)."""

    def __init__(self, pool):
        self._pool = pool
        self._conn = pool.getconn()

    def execute(self, sql, params=()):
        match = _INSERT.match(sql)
        wants_id = (
            match and match.group(1).lower() in _ID_TABLES
            and "RETURNING" not in sql.upper()
            and "DO NOTHING" not in sql.upper()
        )
        text = _translate(sql) + (" RETURNING id" if wants_id else "")
        cur = self._conn.cursor()
        cur.execute(text, tuple(params) if params else None)
        if wants_id:
            row = cur.fetchone()
            return Cursor(cur, row["id"] if row else None)
        return Cursor(cur)

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(_translate(sql), [tuple(p) for p in seq])
        return Cursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._conn is not None:
            self._conn.rollback()  # lectures seules : ferme proprement la transaction ouverte
            self._pool.putconn(self._conn)
            self._conn = None


def get_db():
    return Connection(_get_pool())


# --------------------------------------------------------------------------- #
#  Migrations
# --------------------------------------------------------------------------- #
def read_migrations(directory=MIGRATIONS_DIR):
    files = sorted(f for f in os.listdir(directory) if _FILE.match(f))
    migrations = []
    for index, name in enumerate(files, start=1):
        number = int(_FILE.match(name).group(1))
        if number != index:
            raise RuntimeError(
                "Numérotation des migrations discontinue : attendu %04d, trouvé %s" % (index, name)
            )
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            sql = fh.read()
        migrations.append({
            "version": name[:-4], "sql": sql,
            "checksum": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        })
    return migrations


def migrate(directory=MIGRATIONS_DIR, log=print):
    """Crée le schéma au besoin et applique les migrations manquantes. Retourne leur nombre."""
    schema = config.PG_SCHEMA
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise RuntimeError("Nom de schéma invalide : %r" % schema)
    kwargs = _conn_kwargs()
    kwargs.pop("row_factory")
    kwargs.pop("options")
    applied_now = 0
    with psycopg.connect(**kwargs, autocommit=True) as conn:
        conn.execute("SET TimeZone = 'Europe/Paris'")
        conn.execute("CREATE SCHEMA IF NOT EXISTS %s" % schema)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS %s.schema_migrations ("
            "version text PRIMARY KEY, checksum text NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())" % schema
        )
        applied = dict(conn.execute(
            "SELECT version, checksum FROM %s.schema_migrations" % schema
        ).fetchall())
        for mig in read_migrations(directory):
            if mig["version"] in applied:
                if applied[mig["version"]] != mig["checksum"]:
                    raise RuntimeError(
                        "La migration %s a été modifiée après application" % mig["version"]
                    )
                continue
            with conn.transaction():
                conn.execute("SET LOCAL search_path TO %s, public" % schema)
                conn.execute(mig["sql"].replace("__SCHEMA__", schema))
                conn.execute(
                    "INSERT INTO %s.schema_migrations (version, checksum) VALUES (%%s, %%s)" % schema,
                    (mig["version"], mig["checksum"]),
                )
            applied_now += 1
            log("[db] migration appliquée : %s" % mig["version"])
    return applied_now


def drop_schema():
    """Supprime le schéma configuré (réservé aux tests : schéma temporaire)."""
    reset_pool()
    kwargs = _conn_kwargs()
    kwargs.pop("row_factory")
    kwargs.pop("options")
    with psycopg.connect(**kwargs, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS %s CASCADE" % config.PG_SCHEMA)
