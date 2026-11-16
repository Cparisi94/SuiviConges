# -*- coding: utf-8 -*-
"""Création d'une personne (agent ou valideur) à partir de Sedit RH et de l'Active Directory.

Trois profils seulement sont proposés : **Administrateur**, **Valideur** et **Agent**. En interne, le champ `users.role`
garde le niveau (direction, service, secteur, équipe…) qui sert au calcul des périmètres ; il est déduit de l'unité
organisationnelle de la personne, jamais saisi.

Parcours de création (écran Utilisateurs) :
1. recherche prédictive de la personne dans Sedit RH (nom, prénom, matricule, unité d'affectation) ;
2. rapprochement avec l'Active Directory (adresse e-mail, identifiant) ;
3. agent : choix de l'unité d'affectation ; valideur : en plus, choix de l'unité qui le valide (unité supérieure à la sienne).
"""
import re
import secrets
import unicodedata
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

import apm
import config
import sedit_rh
from db import get_db, row_to_dict
from http_utils import error

bp = Blueprint("people", __name__, url_prefix="/api")

LEVEL_RANK = {"direction": 4, "service": 3, "secteur": 2, "equipe": 1}
PROFILS = ("administrateur", "valideur", "agent")


def norm(value):
    text = unicodedata.normalize("NFKD", (value or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text)


# --------------------------------------------------------------------------- #
#  Unités
# --------------------------------------------------------------------------- #
def sync_units(db, force=False):
    """Recopie les unités de Sedit RH dans `org_units` (au besoin) et retourne la liste à plat."""
    have = db.execute("SELECT COUNT(*) AS n FROM org_units").fetchone()["n"]
    if force or not have:
        units = sedit_rh.organisation_units(force=force)
        if units:
            # Mise à jour par « upsert » : deux requêtes simultanées (première ouverture de l'écran) ne se heurtent pas.
            for u in units:
                db.execute(
                    "INSERT INTO org_units (code, libelle, level, parent_code, position) VALUES (?,?,?,?,?) "
                    "ON CONFLICT (code) DO UPDATE SET libelle=excluded.libelle, level=excluded.level, "
                    "parent_code=excluded.parent_code, position=excluded.position, "
                    "synced_at=to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS')",
                    (u["code"], u["libelle"], u["level"], u["parent_code"], u["position"]))
            marks = ",".join("?" for _ in units)
            db.execute("DELETE FROM org_units WHERE local=0 AND code NOT IN (%s)" % marks, [u["code"] for u in units])   # les unités locales restent
            db.commit()
    return load_units(db)


def load_units(db):
    return [row_to_dict(r) for r in db.execute(
        "SELECT code, libelle, level, parent_code, position, local, head_user_id FROM org_units ORDER BY position, code").fetchall()]


def unit_index(units):
    return {u["code"]: u for u in units}


def ancestors(index, code):
    """Codes des unités supérieures, de la plus proche à la plus haute."""
    out, seen = [], {code}
    cur = (index.get(code) or {}).get("parent_code")
    while cur and cur not in seen and cur in index:
        out.append(cur)
        seen.add(cur)
        cur = index[cur]["parent_code"]
    return out


def descendants(units, code):
    kids, out, stack = {}, [], [code]
    for u in units:
        kids.setdefault(u["parent_code"], []).append(u["code"])
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(kids.get(c, []))
    return out


def unit_path(index, code):
    chain = [code] + ancestors(index, code)
    return " › ".join(index[c]["libelle"] for c in reversed(chain) if c in index)


def unit_valideur(db, index, code):
    """Valideur (compte actif non agent) de l'unité, sinon de l'unité supérieure la plus proche ; None si aucun.

    Un compte d'unité hérité (créé avant les profils) est reconnu par son niveau et son nom identique au libellé de l'unité."""
    users = [row_to_dict(r) for r in db.execute(
        "SELECT id, login, nom, role, admin, unit_code FROM users WHERE actif=1 AND role<>'agent' AND admin=0").fetchall()]
    for c in [code] + ancestors(index, code):
        unit = index.get(c)
        if not unit:
            continue
        # Le responsable de l'unité en est automatiquement le valideur (même s'il est aussi administrateur).
        head_id = unit.get("head_user_id")
        if head_id:
            head = db.execute("SELECT id, login, nom, role, admin, unit_code FROM users WHERE id=? AND actif=1 AND role<>'agent'", (head_id,)).fetchone()
            if head:
                return row_to_dict(head)
        direct = [u for u in users if u["unit_code"] == c]
        if direct:
            return max(direct, key=lambda u: LEVEL_RANK.get(u["role"], 0))
        legacy = [u for u in users if not u["unit_code"] and u["role"] == unit["level"] and norm(u["nom"]) == norm(unit["libelle"])]
        if legacy:
            return legacy[0]
    return None


# --------------------------------------------------------------------------- #
#  Rapprochement avec l'Active Directory
# --------------------------------------------------------------------------- #
def ad_match(nom, prenom):
    """{status: unique|plusieurs|aucun|indisponible, candidates: [{username, displayName, email}]}.

    Exemple : Christophe PARISI → identifiant « cparisi » (première lettre du prénom + nom)."""
    if not apm.configured():
        return {"status": "indisponible", "candidates": [], "message": "API centrale non configurée"}
    n, p = norm(nom), norm(prenom)
    guess = (p[:1] + n)
    seen, hits = set(), []
    try:
        for q in (nom.strip(), guess):
            for h in apm.ad_search(q, limit=50):
                if h["username"] not in seen:
                    seen.add(h["username"])
                    hits.append(h)
    except apm.ApmError as exc:
        return {"status": "indisponible", "candidates": [], "message": str(exc)}
    found = [h for h in hits if n in norm(h["displayName"]) and p in norm(h["displayName"])]
    exact = [h for h in found if h["username"] == guess]
    if not found:
        exact = [h for h in hits if h["username"] == guess]
        found = exact
    if len(exact) == 1:
        found = exact
    if len(found) > 1:
        # Plusieurs comptes de même nom (ex. un compte de test sans messagerie) : on retient le seul qui a une adresse e-mail.
        with_mail = [h for h in found if h["email"]]
        if len(with_mail) == 1:
            found = with_mail
    status = "unique" if len(found) == 1 else ("plusieurs" if found else "aucun")
    return {"status": status, "candidates": found[:8]}


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #
def init_people(app, login_required, can_manage, scope_ids, create_account, audit_user, clean_matricule,
                matricule_holder, normalize_params, valid_email, request_year, role_levels):
    @bp.route("/sirh/agents", methods=["GET"])
    @login_required
    def sirh_agents():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        try:
            return jsonify(sedit_rh.search_agents(request.args.get("q", "")))
        except sedit_rh.SeditError as exc:
            return error(str(exc), 502)

    @bp.route("/ad/match", methods=["GET"])
    @login_required
    def ad_match_route():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        nom, prenom = request.args.get("nom", "").strip(), request.args.get("prenom", "").strip()
        if not nom:
            return error("Nom obligatoire", 400)
        return jsonify(ad_match(nom, prenom))

    @bp.route("/org-units", methods=["GET"])
    @login_required
    def org_units():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            force = request.args.get("refresh") == "1" and request.user.get("admin")
            try:
                units = sync_units(db, force=bool(force))
            except sedit_rh.SeditError as exc:
                units = load_units(db)
                if not units:
                    return error(str(exc), 502)
            index = unit_index(units)
            mine = (request.user.get("unit_code") or "")
            scope = request.args.get("scope")
            restrict = scope == "mine" or (not request.user.get("admin") and scope != "all")
            if restrict and mine in index:
                allowed = set(descendants(units, mine))
                units = [u for u in units if u["code"] in allowed]
            for u in units:
                u["path"] = unit_path(index, u["code"])
            return jsonify(units)
        finally:
            db.close()

    @bp.route("/users/person", methods=["POST"])
    @login_required
    def create_person():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        d = request.get_json(force=True) or {}
        profil = (d.get("profil") or "agent").strip()
        if profil not in PROFILS:
            return error("Profil invalide (administrateur, valideur ou agent)", 400)
        is_admin_actor = bool(request.user.get("admin"))
        make_admin = profil == "administrateur" or bool(d.get("admin"))
        if make_admin and not is_admin_actor:
            return error("Seul un administrateur peut créer un administrateur", 403)
        nom, prenom = (d.get("nom") or "").strip().upper(), (d.get("prenom") or "").strip().upper()
        email = (d.get("email") or "").strip()
        ad_login = (d.get("ad_login") or "").strip().lower()
        if not nom or not prenom:
            return error("Nom et prénom obligatoires", 400)
        if email and not valid_email(email):
            return error("Adresse e-mail invalide", 400)
        matricule, merr = clean_matricule(d.get("matricule"))
        if merr:
            return error(merr, 400)
        unit_code = (d.get("unit_code") or "").strip()
        validator_unit = (d.get("validator_unit_code") or "").strip()
        # Niveau de validation hors organisation RH : un DGA ou un DGS n'a pas d'unité dans Sedit RH.
        level = (d.get("level") or "").strip()
        top = profil == "valideur" and level in ("dga", "dgs")
        supervisor_id = d.get("supervisor_id")
        db = get_db()
        try:
            if matricule:
                holder = matricule_holder(db, matricule)
                if holder:
                    return error("Ce matricule est déjà attribué au compte %s" % holder, 400)
            if ad_login and db.execute("SELECT 1 FROM users WHERE lower(login)=? OR lower(ad_login)=?",
                                       (ad_login, ad_login)).fetchone():
                return error("Cet identifiant AD est déjà utilisé par un compte", 400)
            units = load_units(db)
            index = unit_index(units)
            if profil != "administrateur" and not top and unit_code not in index:
                return error("Choisissez l'unité d'affectation (liste issue de Sedit RH)", 400)
            if not is_admin_actor and not top:
                mine = request.user.get("unit_code") or ""
                if mine in index and unit_code not in set(descendants(units, mine)):
                    return error("Cette unité n'est pas dans votre périmètre", 403)

            parent_id, role, level_unit = None, "agent", index.get(unit_code)
            if profil == "valideur":
                role = level if top else level_unit["level"]
                if validator_unit and not top:
                    if validator_unit not in ancestors(index, unit_code):
                        return error("L'unité qui valide doit être une unité supérieure à celle de la personne", 400)
                    parent = unit_valideur(db, index, validator_unit)
                    if not parent:
                        return error("Aucun valideur n'existe encore pour l'unité « %s » : créez-le d'abord" %
                                     index[validator_unit]["libelle"], 400)
                    parent_id = parent["id"]
                elif supervisor_id not in (None, "", 0):
                    # Valideur supérieur choisi directement (ex. le DGA d'une direction, le DGS d'un DGA).
                    sup = db.execute("SELECT id, role, admin FROM users WHERE id=? AND actif=1 AND role<>'agent'",
                                     (int(supervisor_id),)).fetchone()
                    if not sup:
                        return error("Valideur supérieur introuvable ou inactif", 400)
                    parent_id = sup["id"]
                elif not is_admin_actor:
                    parent_id = request.user["id"]
            elif profil == "agent":
                parent = unit_valideur(db, index, unit_code)
                if not parent and d.get("owner_id"):
                    parent = db.execute("SELECT id, role FROM users WHERE id=? AND actif=1 AND role<>'agent'",
                                        (int(d["owner_id"]),)).fetchone()
                if not parent:
                    return error("Aucun valideur n'existe pour l'unité « %s » ni pour ses unités supérieures : "
                                 "créez d'abord son valideur" % level_unit["libelle"], 400)
                parent_id = parent["id"]
            if parent_id and not is_admin_actor and parent_id not in set(scope_ids(db, request.user)):
                return error("Le valideur de rattachement n'est pas dans votre périmètre", 403)
            if profil == "valideur" and parent_id:
                prow = db.execute("SELECT role FROM users WHERE id=?", (parent_id,)).fetchone()
                if role_levels.get(prow["role"], 0) <= role_levels.get(role, 0):
                    return error("Le valideur supérieur doit être d'un niveau plus élevé", 400)

            year = request_year()
            result = {}
            if profil == "agent":
                # Pas de fiche à la création : elle naît quand on définit la première période de paramètres (Mes agents).
                user_id, login = create_account(db, nom, prenom, email, matricule, parent_id, ad_login)
                result = {"fiche_id": None}
            else:
                # Identifiant = celui de l'Active Directory quand il est connu (cn « machevalier »), sinon initiale du prénom + nom.
                base = re.sub(r"[^A-Za-z0-9._-]", "", ad_login) if ad_login else ""
                if not base:
                    base = (prenom[:1] + nom).upper()
                    base = re.sub(r"[^A-Z0-9]", "", base) or "USER"
                login, n = base, 2
                while db.execute("SELECT 1 FROM users WHERE lower(login)=lower(?)", (login,)).fetchone():
                    login, n = "%s%d" % (base, n), n + 1
                password = secrets.token_urlsafe(18) + "Aa1!" if config.AUTH_MODE == "ad" and profil != "administrateur" \
                    else (d.get("password") or "")
                if not password:
                    return error("Mot de passe local obligatoire pour un administrateur (compte de secours)", 400)
                cur = db.execute(
                    "INSERT INTO users (login, ad_login, matricule, nom, nom_famille, prenom, email, mot_de_passe, admin, role, parent_id, actif) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (login, ad_login, matricule, ("%s %s" % (nom, prenom)).strip(), nom, prenom, email,
                     generate_password_hash(password), 1 if profil == "administrateur" else 0,
                     "administrateur" if profil == "administrateur" else role, parent_id))
                user_id = cur.lastrowid
            if make_admin and profil != "administrateur":
                # Agent ou valideur qui est aussi administrateur : mot de passe local de secours obligatoire.
                if not d.get("password"):
                    db.rollback()
                    return error("Mot de passe local obligatoire pour un compte administrateur (compte de secours)", 400)
                db.execute("UPDATE users SET admin=1, mot_de_passe=? WHERE id=?",
                           (generate_password_hash(d["password"]), user_id))
            db.execute("UPDATE users SET unit_code=?, validator_unit_code=? WHERE id=?",
                       (unit_code if profil != "administrateur" else "",
                        validator_unit if profil == "valideur" else "", user_id))
            audit_user(db, user_id, login, request.user, "creation", "compte", "",
                       "profil=%s%s; niveau=%s; unité=%s; unité validatrice=%s; matricule=%s" % (
                           profil, " + administrateur" if make_admin and profil != "administrateur" else "", "administrateur" if profil == "administrateur" else role, unit_code or "—",
                           validator_unit or "—", matricule or "—"),
                       "Création depuis Sedit RH / Active Directory")
            db.commit()
            row = row_to_dict(db.execute(
                "SELECT id, login, ad_login, matricule, nom, email, admin, role, unit_code, validator_unit_code, parent_id "
                "FROM users WHERE id=?", (user_id,)).fetchone())
            row["profil"] = profil
            row.update(result)
            return jsonify(row)
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()

    app.register_blueprint(bp)
