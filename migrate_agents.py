"""Migration des fiches anciennes vers des comptes agents.

Chaque fiche dont le proprietaire actuel est un valideur (ou l'administrateur)
recoit un nouveau compte agent, sans changer le proprietaire de la fiche :
  - identifiant = premiere lettre du prenom + nom (majuscules, suffixe si doublon)
  - mot de passe genere
  - responsable (parent) = proprietaire / createur de la fiche
  - compte valideur = valideur deja renseigne, sinon l'ancien proprietaire
  - e-mail = celui de la fiche s'il existe (sinon vide, a completer ensuite)

Le compte agent est stocke dans agents.agent_user_id ; agents.user_id reste
le proprietaire (le valideur createur). Le script est idempotent : les fiches
ayant deja un compte agent sont ignorees.
Un CSV des identifiants/mots de passe est ecrit dans le dossier du prototype.
"""
import csv
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from werkzeug.security import generate_password_hash  # noqa: E402

from app import _agent_login, _agent_password, _user_role  # noqa: E402
from db import get_db, row_to_dict  # noqa: E402

CSV_PATH = os.path.join(BASE_DIR, "migration-comptes-agents.csv")


def migrate():
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id AS fiche_id, a.nom, a.prenom, a.email AS fiche_email,
               a.validator_id, a.year, a.user_id AS owner_id,
               u.login AS owner_login, u.role AS owner_role, u.admin AS owner_admin
        FROM agents a
        JOIN users u ON u.id = a.user_id
        WHERE COALESCE(u.role, '') <> 'agent' AND a.agent_user_id IS NULL
        ORDER BY a.id
        """
    ).fetchall()

    results = []
    for row in rows:
        fiche = row_to_dict(row)
        owner_id = fiche["owner_id"]
        nom = (fiche["nom"] or "").strip().upper()
        prenom = (fiche["prenom"] or "").strip().upper()
        email = (fiche["fiche_email"] or "").strip()

        validator_id = fiche["validator_id"] or owner_id
        validator = db.execute(
            "SELECT * FROM users WHERE id=? AND actif=1", (validator_id,)
        ).fetchone()
        if not validator or _user_role(row_to_dict(validator)) not in (
            "administrateur", "direction", "service", "secteur"
        ):
            validator_id = owner_id
            validator = db.execute(
                "SELECT * FROM users WHERE id=? AND actif=1", (owner_id,)
            ).fetchone()

        login = _agent_login(db, prenom, nom)
        password = _agent_password()
        full_name = ("%s %s" % (nom, prenom)).strip()

        try:
            cur = db.execute(
                "INSERT INTO users (login, nom, email, mot_de_passe, admin, role, parent_id, actif) "
                "VALUES (?,?,?,?,0,'agent',?,1)",
                (login, full_name, email, generate_password_hash(password), owner_id),
            )
            agent_user_id = cur.lastrowid
            db.execute(
                "UPDATE agents SET user_id=?, agent_user_id=?, validator_id=? WHERE id=?",
                (owner_id, agent_user_id, validator_id, fiche["fiche_id"]),
            )
            db.execute(
                "UPDATE leave_requests SET user_id=? WHERE agent_id=?",
                (agent_user_id, fiche["fiche_id"]),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        results.append({
            "fiche_id": fiche["fiche_id"],
            "nom": nom,
            "prenom": prenom,
            "login": login,
            "mot_de_passe": password,
            "email": email,
            "responsable_login": fiche["owner_login"],
            "valideur_login": row_to_dict(validator)["login"] if validator else fiche["owner_login"],
            "annee": fiche["year"],
        })
        print("Fiche %s : %s %s -> %s" % (fiche["fiche_id"], nom, prenom, login))

    db.close()

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "fiche_id", "nom", "prenom", "login", "mot_de_passe", "email",
                "responsable_login", "valideur_login", "annee",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(results)

    print("\n%d fiche(s) migree(s)." % len(results))
    print("Identifiants et mots de passe :", CSV_PATH)
    if any(not r["email"] for r in results):
        print("Attention : certaines fiches n'ont pas d'e-mail ; il reste a le renseigner.")


if __name__ == "__main__":
    migrate()
