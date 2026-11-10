"""Restaure le proprietaire des fiches migrees.

Apres la premiere migration, les fiches appartenaient au compte agent
(agents.user_id). On remet le proprietaire d'origine (le valideur createur,
c'est-a-dire le responsable du compte agent) et on conserve le lien vers le
compte agent dans la nouvelle colonne agents.agent_user_id.

Le script est idempotent : les fiches ayant deja un agent_user_id sont ignorees.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app import _user_role  # noqa: E402
from db import get_db, init_db, row_to_dict  # noqa: E402

VALIDATOR_ROLES = ("administrateur", "direction", "service", "secteur")


def migrate():
    init_db()  # ajoute la colonne agent_user_id si necessaire
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id AS fiche_id, a.user_id AS agent_user_id,
               u.login AS agent_login, u.parent_id AS owner_id,
               u.role AS agent_role
        FROM agents a
        JOIN users u ON u.id = a.user_id
        WHERE a.agent_user_id IS NULL AND COALESCE(u.role, '') = 'agent'
        ORDER BY a.id
        """
    ).fetchall()

    done, skipped = [], []
    for row in rows:
        fiche = row_to_dict(row)
        owner_id = fiche["owner_id"]
        owner = db.execute("SELECT * FROM users WHERE id=?", (owner_id,)).fetchone() if owner_id else None
        if not owner or _user_role(row_to_dict(owner)) not in VALIDATOR_ROLES:
            skipped.append((fiche["fiche_id"], fiche["agent_login"], "responsable introuvable ou invalide"))
            continue
        db.execute(
            "UPDATE agents SET agent_user_id=?, user_id=? WHERE id=?",
            (fiche["agent_user_id"], owner_id, fiche["fiche_id"]),
        )
        done.append((fiche["fiche_id"], fiche["agent_login"], row_to_dict(owner)["login"]))

    db.commit()
    db.close()

    for fiche_id, agent_login, owner_login in done:
        print("Fiche %s : compte agent %s -> proprietaire %s" % (fiche_id, agent_login, owner_login))
    for fiche_id, agent_login, reason in skipped:
        print("Fiche %s : IGNOREE (%s) - compte agent %s" % (fiche_id, reason, agent_login))

    print("\n%d fiche(s) restauree(s), %d ignoree(s)." % (len(done), len(skipped)))


if __name__ == "__main__":
    migrate()
