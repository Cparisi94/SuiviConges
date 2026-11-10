# -*- coding: utf-8 -*-
"""Rapprochement avec Sedit RH : matricules des agents de la base, organisation RH, création d'agents.

- **matricules** : pour chaque agent de la base sans matricule, recherche dans Sedit RH (nom + prénom) ; on ne propose
  que les correspondances certaines, l'administrateur coche ce qu'il applique ;
- **organisation** : arbre Direction > Service > Secteur > Agents construit depuis les agents en poste de Sedit RH,
  avec, pour chaque agent, sa présence dans l'application ;
- **création d'agents** : à partir d'agents RH cochés (un agent, un secteur, un service, une direction…), crée leur compte et
  leur fiche ; les comptes valideurs manquants de l'organisation peuvent être créés (miroir de l'arborescence RH) ;
  l'e-mail et l'identifiant AD sont cherchés dans l'Active Directory (via l'APM) quand le nom correspond à un seul compte.

Les données RH ne sont jamais copiées en masse : seul ce que l'administrateur choisit de créer est enregistré.
Toutes les routes sont réservées aux administrateurs.
"""
import re
import secrets
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

import apm
import sedit_rh
from db import get_db, row_to_dict
from http_utils import error

bp = Blueprint("rh_import", __name__, url_prefix="/api/admin/rh")

LEVEL_ROLE = {"direction": "direction", "service": "service", "secteur": "secteur"}
LEVEL_PREFIX = {"direction": "DIR", "service": "SRV", "secteur": "SEC"}
UNIT_ROLES = tuple(LEVEL_ROLE.values())


def norm(value):
    """Minuscules sans accents ni ponctuation : comparaison de noms."""
    text = unicodedata.normalize("NFKD", (value or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text)


def name_key(nom, prenom):
    return norm(nom) + "|" + norm(prenom)


def _label(node):
    return ((node or {}).get("libelle") or "").strip()


def units(agent):
    """(direction, service, secteur) de l'agent ; un niveau identique au niveau supérieur (même code ou même libellé) est fusionné."""
    d = agent.get("direction") or {}
    s = agent.get("service") or {}
    sec = agent.get("secteur") or {}
    d = d if d.get("code") else None
    s = s if s.get("code") and not (d and (s["code"] == d["code"] or norm(_label(s)) == norm(_label(d)))) else None
    ref = s or d
    sec = sec if sec.get("code") and not (ref and (sec["code"] == ref["code"] or norm(_label(sec)) == norm(_label(ref)))) else None
    return d, s, sec


def _chain(agent):
    d, s, sec = units(agent)
    return [(lv, u) for lv, u in (("direction", d), ("service", s), ("secteur", sec)) if u]


# --------------------------------------------------------------------------- #
#  État de l'application
# --------------------------------------------------------------------------- #
def _app_state(db):
    users = [row_to_dict(r) for r in db.execute(
        "SELECT id, login, nom, role, matricule, actif FROM users").fetchall()]
    fiches = db.execute(
        "SELECT DISTINCT a.agent_user_id, a.nom, a.prenom, a.matricule FROM agents a WHERE a.agent_user_id IS NOT NULL").fetchall()
    by_matricule = {u["matricule"]: u for u in users if u["matricule"]}
    by_user = {u["id"]: u for u in users}
    names = {}
    for f in fiches:
        u = by_user.get(f["agent_user_id"])
        if u:
            names.setdefault(name_key(f["nom"], f["prenom"]), u)
    unit_accounts = {}
    for u in users:
        if u["role"] in UNIT_ROLES and u["actif"]:
            unit_accounts.setdefault((u["role"], norm(u["nom"])), u)
    return {"users": users, "by_matricule": by_matricule, "names": names, "unit_accounts": unit_accounts, "fiches": fiches}


def _in_app(agent, app):
    return app["by_matricule"].get(agent.get("matricule")) or app["names"].get(name_key(agent.get("nom"), agent.get("prenom")))


# --------------------------------------------------------------------------- #
#  1. Matricules des agents de la base
# --------------------------------------------------------------------------- #
def propose_matricules(db, rh):
    """Pour chaque agent de la base sans matricule : correspondance certaine, ambiguë ou introuvable dans Sedit RH."""
    index = {}
    for a in rh:
        index.setdefault(name_key(a["nom"], a["prenom"]), []).append(a)
    rows = db.execute(
        "SELECT a.agent_user_id, a.nom, a.prenom, u.login, u.matricule AS user_matricule "
        "FROM agents a JOIN users u ON u.id = a.agent_user_id WHERE a.agent_user_id IS NOT NULL "
        "ORDER BY a.nom, a.prenom, a.id").fetchall()
    seen, out = set(), []
    app = _app_state(db)
    for r in rows:
        if r["agent_user_id"] in seen:
            continue
        seen.add(r["agent_user_id"])
        if r["user_matricule"]:
            continue
        matches = index.get(name_key(r["nom"], r["prenom"]), [])
        item = {"agent_user_id": r["agent_user_id"], "login": r["login"], "nom": r["nom"], "prenom": r["prenom"]}
        if len(matches) == 1:
            m = matches[0]
            holder = app["by_matricule"].get(m["matricule"])
            item.update(status="deja_pris" if holder else "certain", matricule=m["matricule"],
                        rh=_summary(m), holder=holder["login"] if holder else "")
        elif matches:
            item.update(status="ambigu", candidates=[{"matricule": m["matricule"], **_summary(m)} for m in matches[:6]])
        else:
            item.update(status="introuvable")
        out.append(item)
    return out


def _summary(a):
    d, s, sec = units(a)
    return {"direction": _label(d), "service": _label(s) or _label(d), "secteur": _label(sec),
            "statut": _label(a.get("statut")), "fonction": _label(a.get("fonction")),
            "date_arrivee": (a.get("date_arrivee") or "")[:10]}


# --------------------------------------------------------------------------- #
#  2. Organisation RH
# --------------------------------------------------------------------------- #
def build_tree(db, rh):
    app = _app_state(db)

    def new_node(level, unit):
        acct = app["unit_accounts"].get((LEVEL_ROLE[level], norm(_label(unit))))
        return {"level": level, "code": unit["code"], "libelle": _label(unit), "agents": [], "children": {},
                "account": {"id": acct["id"], "login": acct["login"]} if acct else None}

    roots = {}
    for a in rh:
        chain = _chain(a)
        if not chain:
            chain = [("direction", {"code": "-", "libelle": "(sans direction)"})]
        nodes, container = [], roots
        for level, unit in chain:
            node = container.setdefault(unit["code"], new_node(level, unit))
            nodes.append(node)
            container = node["children"]
        holder = _in_app(a, app)
        nodes[-1]["agents"].append({
            "matricule": a["matricule"], "nom": a["nom"], "prenom": a["prenom"],
            "statut": _label(a.get("statut")), "fonction": _label(a.get("fonction")),
            "in_app": bool(holder), "login": holder["login"] if holder else ""})

    def finish(node):
        node["agents"].sort(key=lambda x: (x["nom"], x["prenom"]))
        node["children"] = sorted((finish(c) for c in node["children"].values()), key=lambda c: c["libelle"])
        node["total"] = len(node["agents"]) + sum(c["total"] for c in node["children"])
        node["missing"] = sum(1 for x in node["agents"] if not x["in_app"]) + sum(c["missing"] for c in node["children"])
        return node

    tree = sorted((finish(n) for n in roots.values()), key=lambda n: n["libelle"])
    return {"tree": tree, "total": len(rh), "missing": sum(n["missing"] for n in tree)}


# --------------------------------------------------------------------------- #
#  3. Création d'agents
# --------------------------------------------------------------------------- #
def _ad_lookup(agent):
    """E-mail et identifiant AD si le nom correspond à UN SEUL compte de l'annuaire, sinon None."""
    try:
        hits = apm.ad_search(agent["nom"].strip(), limit=50)
    except apm.ApmError:
        return None
    nom, prenom = norm(agent["nom"]), norm(agent["prenom"])
    found = [h for h in hits if nom in norm(h["displayName"]) and prenom in norm(h["displayName"])]
    return {"email": found[0]["email"], "username": found[0]["username"]} if len(found) == 1 else None


def plan_import(db, rh, matricules, default_owner_id, create_units, use_ad):
    """Prépare la création (sans rien écrire) : agents à créer, déjà présents, comptes d'unité à créer."""
    by_m = {a["matricule"]: a for a in rh}
    app = _app_state(db)
    owners = {u["id"]: u for u in app["users"] if u["actif"]}
    default_owner = owners.get(default_owner_id) if default_owner_id else None
    if default_owner and default_owner["role"] == "agent":
        default_owner = None  # un propriétaire doit être un valideur
    unit_plan, items = {}, []
    for m in dict.fromkeys(matricules):
        a = by_m.get(m)
        if not a:
            items.append({"matricule": m, "status": "ignore", "reason": "Agent introuvable dans Sedit RH"})
            continue
        base = {"matricule": m, "nom": a["nom"], "prenom": a["prenom"]}
        holder = _in_app(a, app)
        if holder:
            items.append({**base, "status": "existe", "reason": "Déjà dans l'application (%s)" % holder["login"]})
            continue
        owner_ref, level_keys = None, []
        for level, unit in _chain(a):
            key = "%s:%s" % (level, unit["code"])
            acct = app["unit_accounts"].get((LEVEL_ROLE[level], norm(_label(unit))))
            if key not in unit_plan:
                unit_plan[key] = {"key": key, "level": level, "code": unit["code"], "libelle": _label(unit),
                                  "existing": acct, "parent_key": level_keys[-1] if level_keys else None, "used": False}
            level_keys.append(key)
            if acct or create_units:
                owner_ref = key
        owner = None
        if owner_ref:
            owner = {"unit": owner_ref}
            for k in level_keys:
                unit_plan[k]["used"] = True
        elif default_owner:
            owner = {"user": default_owner["id"]}
        if not owner:
            items.append({**base, "status": "ignore", "reason": "Aucun propriétaire : créer les comptes d'unité ou choisir un propriétaire par défaut"})
            continue
        items.append({**base, "status": "a_creer", "owner": owner, "chain": level_keys, "arrivee": (a.get("date_arrivee") or "")[:10],
                      "depart": (a.get("date_depart") or "")[:10], "rh": a})
    to_create = [a for a in items if a["status"] == "a_creer"]
    if use_ad and to_create and apm.configured():
        with ThreadPoolExecutor(max_workers=6) as pool:
            for item, info in zip(to_create, pool.map(lambda i: _ad_lookup(i["rh"]), to_create)):
                item["ad"] = info
    units_new = [u for u in unit_plan.values() if u["used"] and not u["existing"]]
    return {"items": items, "units": unit_plan, "units_new": units_new, "default_owner": default_owner}


def _public(plan):
    """Version affichable du plan (sans l'enregistrement RH complet)."""
    items = []
    for i in plan["items"]:
        out = {k: v for k, v in i.items() if k not in ("rh", "owner", "chain")}
        if i["status"] == "a_creer":
            out["email"] = (i.get("ad") or {}).get("email", "")
            out["ad_login"] = (i.get("ad") or {}).get("username", "")
            ref = i["owner"].get("unit")
            u = plan["units"].get(ref) if ref else None
            out["owner"] = ((u["existing"]["login"] if u and u["existing"] else "(compte à créer) " + u["libelle"]) if u
                            else plan["default_owner"]["login"])
        items.append(out)
    return {"items": items,
            "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("a_creer", "existe", "ignore")},
            "units_new": [{"level": u["level"], "code": u["code"], "libelle": u["libelle"]} for u in plan["units_new"]]}


def _unit_login(db, level, code):
    base = "%s-%s" % (LEVEL_PREFIX[level], re.sub(r"[^A-Z0-9]", "", code.upper()) or "X")
    login, n = base, 2
    while db.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
        login, n = "%s%d" % (base, n), n + 1
    return login


def run_import(db, plan, year, actor, create_fiche, audit_user, normalize_params, matricule_holder):
    """Écrit le plan dans la base (l'appelant commite). Retourne le résumé."""
    created_units, key_to_id = [], {}
    for key, u in plan["units"].items():
        if u["existing"]:
            key_to_id[key] = u["existing"]["id"]
    for u in sorted(plan["units_new"], key=lambda x: ("direction", "service", "secteur").index(x["level"])):
        parent = key_to_id.get(u["parent_key"]) or actor["id"]
        login = _unit_login(db, u["level"], u["code"])
        cur = db.execute(
            "INSERT INTO users (login, nom, mot_de_passe, admin, role, parent_id, actif) VALUES (?,?,?,0,?,?,1)",
            (login, u["libelle"], generate_password_hash(secrets.token_urlsafe(24)), LEVEL_ROLE[u["level"]], parent))
        key_to_id[u["key"]] = cur.lastrowid
        audit_user(db, cur.lastrowid, login, actor, "creation", "compte", "", "role=%s; responsable=%s" % (LEVEL_ROLE[u["level"]], parent),
                   "Création depuis l'organisation Sedit RH")
        created_units.append({"login": login, "libelle": u["libelle"], "role": LEVEL_ROLE[u["level"]]})
    created, skipped = [], []
    for i in plan["items"]:
        if i["status"] != "a_creer":
            skipped.append({"matricule": i["matricule"], "reason": i.get("reason", "")})
            continue
        owner_id = key_to_id[i["owner"]["unit"]] if "unit" in i["owner"] else i["owner"]["user"]
        holder = matricule_holder(db, i["matricule"])
        if holder:
            skipped.append({"matricule": i["matricule"], "reason": "Matricule déjà attribué au compte %s" % holder})
            continue
        params = normalize_params({})
        for field, value in (("date_arrivee", i["arrivee"]), ("date_depart", i["depart"])):
            if value.startswith(str(year)):
                params[field] = value  # seulement si la date tombe dans l'année de la fiche (prorata correct)
        ad = i.get("ad") or {}
        ad_login = ad.get("username", "")
        if ad_login and db.execute("SELECT 1 FROM users WHERE lower(login)=? OR lower(ad_login)=?", (ad_login.lower(), ad_login.lower())).fetchone():
            ad_login = ""
        fiche_id, user_id, login, _password = create_fiche(
            db, i["nom"].strip().upper(), i["prenom"].strip().upper(), ad.get("email", ""), i["matricule"],
            owner_id, owner_id, year, params, 0, ad_login)
        audit_user(db, user_id, login, actor, "creation", "compte", "", "role=agent; responsable=%s; matricule=%s" % (owner_id, i["matricule"]),
                   "Création depuis Sedit RH")
        created.append({"matricule": i["matricule"], "login": login, "fiche_id": fiche_id, "email": bool(ad.get("email")),
                        "ad_login": bool(ad_login)})
    return {"created": created, "units_created": created_units, "skipped": skipped}


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #
def init_rh(app, admin_required, create_fiche, audit_user, normalize_params, matricule_holder, clean_matricule):
    def rh_or_error():
        try:
            return sedit_rh.all_agents(force=request.args.get("refresh") == "1"), None
        except sedit_rh.SeditError as exc:
            return None, error(str(exc), 502)

    @bp.route("/organisation", methods=["GET"])
    @admin_required
    def organisation():
        rh, err = rh_or_error()
        if err:
            return err
        db = get_db()
        try:
            return jsonify(build_tree(db, rh))
        finally:
            db.close()

    @bp.route("/matricules", methods=["GET"])
    @admin_required
    def matricules():
        rh, err = rh_or_error()
        if err:
            return err
        db = get_db()
        try:
            items = propose_matricules(db, rh)
        finally:
            db.close()
        return jsonify({"items": items, "counts": {s: sum(1 for i in items if i["status"] == s)
                                                   for s in ("certain", "ambigu", "introuvable", "deja_pris")}})

    @bp.route("/matricules/apply", methods=["POST"])
    @admin_required
    def matricules_apply():
        data = request.get_json(force=True) or {}
        rh, err = rh_or_error()
        if err:
            return err
        known = {a["matricule"] for a in rh}
        db = get_db()
        applied, refused = 0, []
        try:
            for item in data.get("items") or []:
                m, merr = clean_matricule(item.get("matricule"))
                uid = int(item.get("agent_user_id") or 0)
                user = db.execute("SELECT id, login, matricule FROM users WHERE id=?", (uid,)).fetchone()
                holder = matricule_holder(db, m, uid)
                if merr or not m or m not in known or not user or holder or user["matricule"]:
                    refused.append({"agent_user_id": uid, "reason": merr or ("Matricule inconnu de Sedit RH" if m not in known else
                                    ("Déjà attribué à %s" % holder if holder else "Compte introuvable ou matricule déjà renseigné"))})
                    continue
                db.execute("UPDATE users SET matricule=? WHERE id=?", (m, uid))
                db.execute("UPDATE agents SET matricule=? WHERE agent_user_id=?", (m, uid))
                audit_user(db, uid, user["login"], request.user, "modification", "matricule", "", m, "Rapprochement avec Sedit RH")
                applied += 1
            db.commit()
        finally:
            db.close()
        return jsonify({"applied": applied, "refused": refused})

    def _plan_from_request(db, rh):
        data = request.get_json(force=True) or {}
        try:
            year = int(data.get("year"))
        except (TypeError, ValueError):
            year = None
        if not year or not (2000 <= year <= 2100):
            return None, None, error("Année invalide", 400)
        matricules = [str(m) for m in (data.get("matricules") or [])][:2000]
        if not matricules:
            return None, None, error("Aucun agent sélectionné", 400)
        owner_id = int(data.get("default_owner_id") or 0) or None
        plan = plan_import(db, rh, matricules, owner_id, bool(data.get("create_units")), bool(data.get("use_ad", True)))
        return plan, year, None

    @bp.route("/import/preview", methods=["POST"])
    @admin_required
    def import_preview():
        rh, err = rh_or_error()
        if err:
            return err
        db = get_db()
        try:
            plan, _year, err = _plan_from_request(db, rh)
            return err or jsonify(_public(plan))
        finally:
            db.close()

    @bp.route("/import", methods=["POST"])
    @admin_required
    def import_run():
        rh, err = rh_or_error()
        if err:
            return err
        db = get_db()
        try:
            plan, year, err = _plan_from_request(db, rh)
            if err:
                return err
            try:
                result = run_import(db, plan, year, request.user, create_fiche, audit_user, normalize_params, matricule_holder)
                db.commit()
            except Exception:  # noqa: BLE001 — tout ou rien
                db.rollback()
                app.logger.exception("Import Sedit RH impossible")
                return error("Création impossible : rien n'a été enregistré", 500)
            return jsonify({**result, "preview": _public(plan)})
        finally:
            db.close()

    app.register_blueprint(bp)
