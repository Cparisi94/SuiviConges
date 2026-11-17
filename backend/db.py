# -*- coding: utf-8 -*-
"""Accès aux données : façade au-dessus de PostgreSQL (voir pg_db.py) et helpers.

Le reste de l'application importe uniquement ce module ; le moteur de base de
données (pool, schéma dédié, migrations) est géré dans `pg_db.py`.
"""
import json

from config import BASE_DIR  # noqa: F401  (réexporté pour les scripts existants)
from pg_db import get_db, migrate  # noqa: F401

# Fragments SQL dépendant du moteur. Les dates sont stockées en texte « AAAA-MM-JJ HH:MM:SS »
# (heure de Paris) ; SQL_NOW_MINUS attend un paramètre du type '-3 days'.
SQL_NOW_MINUS = "to_char(localtimestamp + CAST(? AS interval), 'YYYY-MM-DD HH24:MI:SS')"
SQL_DAYS_SINCE_SUBMIT = (
    "CAST(FLOOR(EXTRACT(EPOCH FROM (localtimestamp - "
    "CAST(COALESCE(r.soumis_le, r.cree_le) AS timestamp))) / 86400) AS INTEGER)"
)


def init_db():
    """Applique les migrations SQL manquantes (crée le schéma dédié au besoin)."""
    return migrate()


def row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def ad_display(name):
    """Nom Active Directory présenté « Prénom NOM » : l'AD fournit « NOM Prénom » (« GAULTIER Djamel » -> « Djamel GAULTIER ») ;
    un nom déjà dans cet ordre, ou dont l'ordre n'est pas reconnaissable, reste tel quel."""
    name = (name or "").strip()
    parts = name.split()

    def upper(word):
        letters = [c for c in word if c.isalpha()]
        return len(letters) >= 2 and all(c.isupper() for c in letters)

    i = 0
    while i < len(parts) and upper(parts[i]):
        i += 1
    if 0 < i < len(parts):
        return " ".join(parts[i:] + parts[:i])
    return name


def user_label(row):
    """Nom d'affichage unique d'un compte, partout dans l'application, au format « Prénom NOM » : le nom Active Directory s'il est connu,
    sinon le prénom et le nom de famille, sinon le nom enregistré, sinon l'identifiant."""
    def get(key):
        try:
            return (row[key] or "").strip()
        except (KeyError, IndexError, TypeError):
            return ""
    if get("nom_ad"):
        return ad_display(get("nom_ad"))
    if get("nom_famille") and get("prenom"):
        return "%s %s" % (get("prenom").title(), get("nom_famille").upper())
    return get("nom") or get("login")


# Même règle en SQL (alias de la table users : `u`)
USER_LABEL_SQL = ("coalesce(nullif(u.nom_ad,''), nullif(trim(coalesce(initcap(nullif(u.prenom,'')),'') || ' ' || "
                  "coalesce(upper(nullif(u.nom_famille,'')),'')),''), nullif(u.nom,''), u.login)")


def public_user(row):
    """Ligne user sans le hash du mot de passe."""
    d = row_to_dict(row)
    if d:
        d.pop("mot_de_passe", None)
    return d


def set_setting(db, cle, valeur):
    if not isinstance(valeur, str):
        valeur = json.dumps(valeur, ensure_ascii=False)
    db.execute(
        "INSERT INTO settings (cle, valeur) VALUES (?,?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
        (cle, valeur),
    )


if __name__ == "__main__":
    print("Migrations appliquées :", init_db())
