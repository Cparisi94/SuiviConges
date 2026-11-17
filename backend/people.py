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
import threading
import time
import unicodedata
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

import apm
import config
import sedit_rh
from db import ad_display, get_db, row_to_dict, user_label
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


def name_words(value):
    """Mots d'un nom, sans accents ni majuscules : « Éloïse DUPONT-MARTIN » -> [eloise, dupont, martin]."""
    text = unicodedata.normalize("NFKD", (value or "").lower()).encode("ascii", "ignore").decode()
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


def find_users(db, q, with_inactive=False):
    """Recherche d'une personne : (comptes trouvés, tous les comptes par identifiant).

    `q` = matricule ou e-mail exact, ou un ou plusieurs mots du **nom RH** (Sedit RH : nom, nom de famille, prénom ; accents et casse ignorés,
    début de mot suffisant). Le nom AD n'est pas cherché. Comptes actifs seulement, sauf `with_inactive` ; les comptes administrateurs purs sont écartés.
    Résultat trié : correspondances exactes (matricule, e-mail) d'abord, puis par nom."""
    q = (q or "").strip()
    words = name_words(q)
    users = {r["id"]: r for r in db.execute(
        "SELECT id, login, ad_login, nom, nom_ad, nom_famille, prenom, email, matricule, role, admin, actif, parent_id, unit_code FROM users").fetchall()}
    hits = []
    for u in users.values():
        if u["role"] == "administrateur" or (not u["actif"] and not with_inactive):
            continue
        mat, mail = (u["matricule"] or "").strip().lower(), (u["email"] or "").strip().lower()
        if (mat and mat == q.lower()) or (mail and mail == q.lower()):
            hits.append((0, u))
        elif words:
            rh_words = name_words(" ".join([u["nom"] or "", u["nom_famille"] or "", u["prenom"] or ""]))
            if all(any(rw.startswith(w) for rw in rh_words) for w in words):
                hits.append((1, u))
    hits.sort(key=lambda h: (h[0], (h[1]["nom"] or "").lower(), h[1]["id"]))
    return [u for _rank, u in hits], users


def fetch_ad_name(ad_login):
    """Nom affiché (displayName) du compte AD `ad_login` ; « » si l'AD ne le connaît pas, None si l'AD est indisponible (jamais d'exception)."""
    ad_login = (ad_login or "").strip().lower()
    if not ad_login:
        return ""
    if not apm.configured():
        return None
    try:
        hits = apm.ad_search(ad_login, limit=15)
    except apm.ApmError:
        return None
    exact = [h for h in hits if h["username"] == ad_login]
    return ad_display(exact[0]["displayName"]) if len(exact) == 1 else ""


_ad_unknown = set()           # comptes déjà cherchés sans succès dans l'AD (ou AD en panne) : pas de nouvelle recherche avant le redémarrage
_ad_fill = {"running": False, "retry_after": 0.0}
_ad_fill_lock = threading.Lock()


def normalize_ad_names():
    """Remet les noms AD déjà enregistrés au format « Prénom NOM » (« GAULTIER Djamel » -> « Djamel GAULTIER ») ; sans effet sur ceux qui le sont déjà."""
    db = get_db()
    try:
        changed = 0
        for r in db.execute("SELECT id, nom_ad FROM users WHERE nom_ad<>''").fetchall():
            fixed = ad_display(r["nom_ad"])
            if fixed != r["nom_ad"]:
                db.execute("UPDATE users SET nom_ad=? WHERE id=?", (fixed, r["id"]))
                changed += 1
        db.commit()
        return changed
    finally:
        db.close()


def fill_ad_names(limit=60):
    """Renseigne `users.nom_ad` des comptes actifs qui ont un identifiant AD mais pas encore de nom AD. Retourne le nombre de noms trouvés.

    Un compte que l'AD ne connaît pas n'est pas réinterrogé avant le redémarrage de l'application."""
    db = get_db()
    try:
        rows = [r for r in db.execute(
            "SELECT id, login, ad_login FROM users WHERE actif=1 AND nom_ad='' AND ad_login<>'' ORDER BY id").fetchall()
            if r["id"] not in _ad_unknown][:limit]
        found = 0
        for r in rows:
            name = fetch_ad_name(r["ad_login"])
            if name is None:
                break                                    # AD indisponible : on réessaiera au prochain passage
            if not name:
                _ad_unknown.add(r["id"])
                continue
            db.execute("UPDATE users SET nom_ad=? WHERE id=?", (name, r["id"]))
            found += 1
        db.commit()
        return found
    finally:
        db.close()


def fill_ad_names_async():
    """Lance `fill_ad_names` en arrière-plan (un seul passage à la fois, pause de 10 minutes entre deux passages) : l'écran n'attend pas l'AD."""
    with _ad_fill_lock:
        if _ad_fill["running"] or time.time() < _ad_fill["retry_after"] or not apm.configured():
            return
        _ad_fill["running"] = True

    def run():
        try:
            fill_ad_names()
        except Exception as exc:  # noqa: BLE001 - tâche de fond : on journalise sans propager
            print("[people] noms AD non renseignés : %s" % exc)
        finally:
            with _ad_fill_lock:
                _ad_fill["running"] = False
                _ad_fill["retry_after"] = time.time() + 600

    threading.Thread(target=run, name="conges-ad-names", daemon=True).start()


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

    @bp.route("/users/ad-names/sync", methods=["POST"])
    @login_required
    def ad_names_sync():
        """Renseigne tout de suite les noms AD manquants (administrateur) ; l'application le fait aussi seule, en arrière-plan."""
        if not request.user.get("admin"):
            return error("Accès réservé aux administrateurs", 403)
        _ad_unknown.clear()
        return jsonify({"renseignes": fill_ad_names(limit=500)})

    @bp.route("/admin/agent-search", methods=["GET"])
    @login_required
    def agent_search():
        """Recherche rapide d'une personne (administrateur) : nom RH, matricule ou e-mail ; renvoie pour chacune son valideur, son délégataire du
        moment et ses comptes (application, Active Directory, fiches congés) — de quoi répondre sans ouvrir plusieurs écrans."""
        if not request.user.get("admin"):
            return error("Accès réservé aux administrateurs", 403)
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"items": [], "total": 0})
        import delegation
        db = get_db()
        try:
            found, users = find_users(db, q, with_inactive=True)
            units = {r["code"]: r["libelle"] for r in db.execute("SELECT code, libelle FROM org_units").fetchall()}
            shown = found[:12]
            ids = [u["id"] for u in shown] or [0]
            marks = ",".join("?" for _ in ids)
            fiches = {}
            for r in db.execute("SELECT id, year, agent_user_id FROM agents WHERE agent_user_id IN (%s) ORDER BY year DESC" % marks, ids).fetchall():
                fiches.setdefault(r["agent_user_id"], []).append({"id": r["id"], "year": r["year"]})
            logins = {r["user_id"]: r["dernier"] for r in db.execute(
                "SELECT user_id, MAX(at) AS dernier FROM login_logs WHERE success=1 AND event='connexion' AND user_id IN (%s) GROUP BY user_id" % marks, ids).fetchall()}
            team = {}
            for u in users.values():
                if u["actif"] and u["parent_id"]:
                    team[u["parent_id"]] = team.get(u["parent_id"], 0) + 1

            def who(row):
                return None if not row else {"id": row["id"], "nom": user_label(row), "nom_rh": row["nom"], "nom_ad": row["nom_ad"] or None, "login": row["login"],
                                             "email": row["email"] or None, "matricule": row["matricule"] or None, "actif": bool(row["actif"])}

            items = []
            for u in shown:
                boss = users.get(u["parent_id"])
                delegate = delegation.active_delegate(db, boss["id"]) if boss else None
                items.append({
                    "id": u["id"], "nom_rh": u["nom"], "nom_ad": u["nom_ad"] or None, "matricule": u["matricule"] or None,
                    "email": u["email"] or None, "actif": bool(u["actif"]), "role": u["role"], "admin": bool(u["admin"]),
                    "profil": "agent" if u["role"] == "agent" else "valideur",
                    "unite": units.get(u["unit_code"]) if u["unit_code"] else None,
                    "valideur": who(boss), "delegue_actuel": who(users.get(delegate["id"])) if delegate else None,
                    "equipe": team.get(u["id"], 0),
                    "compte_application": {"login": u["login"], "actif": bool(u["actif"]), "derniere_connexion": str(logins[u["id"]])[:16] if logins.get(u["id"]) else None},
                    "compte_ad": {"identifiant": u["ad_login"] or None, "nom": u["nom_ad"] or None, "email": u["email"] or None},
                    "fiches": fiches.get(u["id"], []),
                })
            return jsonify({"items": items, "total": len(found)})
        finally:
            db.close()

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
                # Mode AD : le mot de passe est celui du compte Ville ; le mot de passe local de secours d'un administrateur
                # est facultatif (à défaut, un mot de passe aléatoire jamais communiqué remplit la colonne).
                password = d.get("password") or ""
                if config.AUTH_MODE == "ad" and (profil != "administrateur" or not password):
                    password = secrets.token_urlsafe(18) + "Aa1!"
                if not password:
                    return error("Mot de passe local obligatoire (mode d'authentification local)", 400)
                cur = db.execute(
                    "INSERT INTO users (login, ad_login, matricule, nom, nom_famille, prenom, email, mot_de_passe, admin, role, parent_id, actif) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (login, ad_login, matricule, ("%s %s" % (nom, prenom)).strip(), nom, prenom, email,
                     generate_password_hash(password), 1 if profil == "administrateur" else 0,
                     "administrateur" if profil == "administrateur" else role, parent_id))
                user_id = cur.lastrowid
            if make_admin and profil != "administrateur":
                # Agent ou valideur qui est aussi administrateur : mot de passe local de secours facultatif en mode AD.
                if d.get("password"):
                    db.execute("UPDATE users SET admin=1, mot_de_passe=? WHERE id=?",
                               (generate_password_hash(d["password"]), user_id))
                elif config.AUTH_MODE != "ad":
                    db.rollback()
                    return error("Mot de passe local obligatoire pour un compte administrateur", 400)
                else:
                    db.execute("UPDATE users SET admin=1 WHERE id=?", (user_id,))
            ad_name = fetch_ad_name(ad_login) if ad_login else ""
            if ad_name:
                db.execute("UPDATE users SET nom_ad=? WHERE id=?", (ad_name, user_id))
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
