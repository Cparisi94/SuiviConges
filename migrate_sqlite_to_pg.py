# -*- coding: utf-8 -*-
"""Transfert unique des données de l'ancienne base SQLite vers le schéma PostgreSQL.

    python migrate_sqlite_to_pg.py            # refuse d'écrire si le schéma contient déjà des données
    python migrate_sqlite_to_pg.py --replace  # vide les tables du schéma avant de recharger

La base SQLite (CONGES_SQLITE_PATH) n'est ouverte qu'en lecture seule. Tout est chargé dans
une seule transaction : en cas d'erreur, rien n'est écrit. Les séquences d'identifiants sont
recalées et les effectifs de chaque table sont comparés à ceux de la source.
"""
import sqlite3
import sys

import config
import pg_db

# Ordre de chargement imposé par les clés étrangères.
TABLES = [
    "users", "user_audit", "agents", "cells", "settings",
    "leave_requests", "leave_request_events", "hourly_absences",
]
WITH_ID = [t for t in TABLES if t not in ("cells", "settings")]


def _source_columns(src, table):
    return [r[1] for r in src.execute("PRAGMA table_info(%s)" % table)]


def main(replace=False):
    pg_db.migrate()
    src = sqlite3.connect("file:%s?mode=ro" % config.SQLITE_PATH.replace("\\", "/"), uri=True)
    src.row_factory = sqlite3.Row
    dst = pg_db.get_db()
    try:
        existing = {t: dst.execute("SELECT COUNT(*) AS c FROM %s" % t).fetchone()["c"] for t in TABLES}
        if any(existing.values()):
            if not replace:
                print("Le schéma %s contient déjà des données : %s" % (config.PG_SCHEMA, existing))
                print("Relancer avec --replace pour les remplacer.")
                return 1
            dst.execute("TRUNCATE %s RESTART IDENTITY CASCADE" % ", ".join(TABLES))

        for table in TABLES:
            cols = _source_columns(src, table)
            rows = [tuple(r[c] for c in cols) for r in src.execute("SELECT * FROM %s" % table)]
            if table == "users":
                parent_idx = cols.index("parent_id")
                parents = {r[cols.index("id")]: r[parent_idx] for r in rows}
                rows = [r[:parent_idx] + (None,) + r[parent_idx + 1:] for r in rows]
            dst.executemany(
                "INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(cols), ",".join("?" * len(cols))),
                rows,
            )
            if table == "users":
                dst.executemany(
                    "UPDATE users SET parent_id=? WHERE id=?",
                    [(p, i) for i, p in parents.items() if p is not None],
                )
            print("  %-22s %5d ligne(s)" % (table, len(rows)))

        for table in WITH_ID:
            dst.execute(
                "SELECT setval(pg_get_serial_sequence('%s', 'id'), "
                "COALESCE((SELECT MAX(id) FROM %s), 0) + 1, false)" % (table, table)
            )

        for table in TABLES:
            expected = src.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            got = dst.execute("SELECT COUNT(*) AS c FROM %s" % table).fetchone()["c"]
            if expected != got:
                raise RuntimeError("%s : %s ligne(s) attendue(s), %s chargée(s)" % (table, expected, got))
        dst.commit()
        print("Transfert terminé vers le schéma %s." % config.PG_SCHEMA)
        return 0
    except Exception:
        dst.rollback()
        raise
    finally:
        dst.close()
        src.close()


if __name__ == "__main__":
    sys.exit(main(replace="--replace" in sys.argv[1:]))
