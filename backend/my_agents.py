# -*- coding: utf-8 -*-
"""Écran « Mes agents » : arbre des personnes que je valide, agents Sedit RH à glisser dessus, déplacements.

Règles (voir REGLES_METIER.md, section 2) :
- l'arbre est celui des responsables (`users.parent_id`) : les personnes que je valide, puis celles que mes subordonnés valident…
- la liste Sedit RH ne montre que les agents en poste **de mon niveau ou en dessous** (mon unité et ses unités descendantes ;
  tous pour un administrateur) qui ne sont pas déjà dans l'application ;
- déposer un agent Sedit RH sur une personne le crée **sous elle** (compte, fiche, e-mail et identifiant AD si uniques) ;
  la personne qui reçoit devient **valideur** et, si elle n'a pas d'unité, prend celle de l'agent déposé ;
- déplacer une personne change son valideur (et le propriétaire de sa fiche) ; jamais sous elle-même ni sous un de ses subordonnés.
"""
from flask import Blueprint, jsonify, request

import apm
import delegation
import people
import rh_import
import sedit_rh
from db import get_db, row_to_dict
from http_utils import error

bp = Blueprint("my_agents", __name__, url_prefix="/api/my-agents")

LEVEL_ROLE = {"direction": "direction", "service": "service", "secteur": "secteur", "equipe": "equipe"}


def init_my_agents(app, login_required, can_manage, scope_ids, create_account, insert_fiche, audit_user,
                   normalize_params, request_year, role_levels, load_settings):
    rank_name = {v: k for k, v in role_levels.items()}

    def my_unit_codes(db, units, index):
        """(codes des unités de mon périmètre, ou None = toutes, message d'avertissement)."""
        if request.user.get("admin") and not request.user.get("unit_code"):
            return None, ""
        code = request.user.get("unit_code") or ""
        if code not in index and request.user.get("matricule"):
            try:
                hits = sedit_rh.search_agents(request.user["matricule"], limit=3)
                code = next((h["unit_code"] for h in hits if h["matricule"] == request.user["matricule"]), "")
            except sedit_rh.SeditError:
                code = ""
        if code not in index:
            if request.user.get("admin"):
                return None, ""
            return set(), "Votre unité n'est pas renseignée : demandez à un administrateur de l'indiquer sur votre compte."
        return set(people.descendants(units, code)), ""

    def load_units(db):
        try:
            return people.sync_units(db)
        except sedit_rh.SeditError:
            return people.load_units(db)

    def children_map(db):
        rows = [row_to_dict(r) for r in db.execute(
            "SELECT id, login, nom, matricule, email, role, admin, actif, parent_id, unit_code FROM users").fetchall()]
        kids = {}
        for u in rows:
            kids.setdefault(u["parent_id"], []).append(u)
        return {u["id"]: u for u in rows}, kids

    def subtree(kids, root_id):
        out, stack = set(), [root_id]
        while stack:
            i = stack.pop()
            if i in out:
                continue
            out.add(i)
            stack.extend(c["id"] for c in kids.get(i, []))
        return out

    def promote(db, parent, child_unit, users_by_id, index):
        """Fait de `parent` un valideur : niveau déduit de son unité, plafonné sous celui de son propre valideur."""
        parent = dict(parent)
        if not parent["unit_code"] and child_unit:
            db.execute("UPDATE users SET unit_code=? WHERE id=?", (child_unit, parent["id"]))
            parent["unit_code"] = child_unit
        if parent["role"] == "agent":
            unit = index.get(parent["unit_code"])
            rank = role_levels[LEVEL_ROLE.get(unit["level"], "secteur")] if unit else role_levels["secteur"]
            gp = users_by_id.get(parent["parent_id"])
            ceiling = role_levels.get(gp["role"], 8) if gp else 8
            if rank >= ceiling:
                rank = max(ceiling - 1, 1)
            new_role = rank_name[rank]
            db.execute("UPDATE users SET role=? WHERE id=?", (new_role, parent["id"]))
            audit_user(db, parent["id"], parent["login"], request.user, "modification", "rôle", "agent", new_role,
                       "Devient valideur (agent rattaché sous lui)")
            parent["role"] = new_role
        return parent

    def period_summary(row):
        """Résumé visuel de la période en cours (ou de la dernière) : quotité, durée, pénibilité, jours travaillés, fériés."""
        import datetime as _dt
        import json as _json
        try:
            periods = _json.loads(row["periods"]) if row["periods"] else []
            params = _json.loads(row["params"]) if row["params"] else {}
        except ValueError:
            return None
        today = _dt.date.today().isoformat()
        if periods:
            cur = next((p for p in periods if p.get("start", "") <= today <= p.get("end", "")), periods[-1])
        else:
            cur = {"penibilite": params.get("penibilite"), "duree_hebdo": params.get("duree_hebdo"), "quotite": params.get("quotite"),
                   "jours_hebdo": params.get("jours_hebdo"), "jours_travailles": params.get("jours_travailles"),
                   "ferie_travaille": params.get("ferie_travaille"), "start": params.get("date_arrivee") or "", "end": params.get("date_depart") or ""}
        try:
            n = int(cur.get("jours_hebdo") or 5)
        except (TypeError, ValueError):
            n = 5
        return {"quotite": cur.get("quotite") or "", "duree": cur.get("duree_hebdo") or "", "penibilite": cur.get("penibilite") or "",
                "days": cur.get("jours_travailles") or list(range(1, min(7, max(1, n)) + 1)), "ferie": bool(cur.get("ferie_travaille")),
                "count": max(1, len(periods)), "start": cur.get("start") or "", "end": cur.get("end") or ""}

    def fiche_complete(row):
        """Une fiche est exploitable quand elle a au moins une période de paramètres (ou des paramètres complets)."""
        import json as _json
        try:
            periods = _json.loads(row["periods"]) if row["periods"] else []
            params = _json.loads(row["params"]) if row["params"] else {}
        except ValueError:
            return False
        return bool(periods) or bool(params.get("penibilite") and params.get("quotite") and params.get("jours_hebdo"))

    def in_scope(db, uid):
        return request.user.get("admin") or uid in set(scope_ids(db, request.user))

    # ------------------------------------------------------------------ arbre
    @bp.route("", methods=["GET"])
    @login_required
    def tree():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            units = load_units(db)
            index = people.unit_index(units)
            by_id, kids = children_map(db)
            try:
                year = int(request.args.get("year") or request_year())
            except (TypeError, ValueError):
                year = request_year()
            fiches = {}
            for r in db.execute("SELECT id, agent_user_id, params, periods FROM agents WHERE year=? AND agent_user_id IS NOT NULL",
                                (year,)).fetchall():
                fiches[r["agent_user_id"]] = {"id": r["id"], "complete": fiche_complete(r), "period": period_summary(r)}
            # Fiches déjà dupliquées vers l'année suivante (N+1) : pas de bouton « Dupliquer » pour celles-là.
            next_year = {r["agent_user_id"] for r in db.execute(
                "SELECT agent_user_id FROM agents WHERE year=? AND agent_user_id IS NOT NULL", (year + 1,)).fetchall()}
            for uid_, fiche_ in fiches.items():
                fiche_["next_exists"] = uid_ in next_year

            # Par défaut : les personnes que je valide directement (et celles de mes délégants du moment) ;
            # « toute ma ligne hiérarchique » (depth=all) : de proche en proche, jusqu'au bas de l'arbre.
            deep = request.args.get("depth") == "all" or (request.user.get("admin") and request.headers.get("X-Scope") == "all")
            delegating = set(delegation.delegators_of(db, request.user["id"]))

            def node(u, seen, level=0):
                out = {"delegated": u["id"] in delegating and level == 1, "fiche": fiches.get(u["id"]), "year": year, "id": u["id"], "nom": u["nom"], "login": u["login"], "matricule": u["matricule"],
                       "role": u["role"], "admin": u["admin"], "actif": u["actif"], "no_email": not (u["email"] or "").strip(),
                       "profil": "agent" if u["role"] == "agent" else "valideur",
                       "unit_code": u["unit_code"], "unit_label": (index.get(u["unit_code"]) or {}).get("libelle", ""),
                       "children": []}
                expand = deep or level == 0 or (level == 1 and u["id"] in delegating)
                for c in sorted(kids.get(u["id"], []), key=lambda x: (x["nom"] or x["login"]).lower()):
                    if expand and c["id"] not in seen:
                        out["children"].append(node(c, seen | {c["id"]}, level + 1))
                out["count"] = len(subtree(kids, u["id"])) - 1          # tous les subordonnés, affichés ou non
                out["more"] = out["count"] > len(out["children"]) + sum(c["count"] for c in out["children"])
                return out

            me = by_id[request.user["id"]]
            if request.user.get("admin") and request.headers.get("X-Scope") == "all":
                # « Voir tout » : toute la collectivité, de ses racines vers le bas.
                top = sorted((u for u in by_id.values() if u["parent_id"] not in by_id),
                             key=lambda x: (x["nom"] or x["login"]).lower())
                out = node(me, {me["id"]})
                out["nom"], out["children"], out["profil"], out["unit_label"], out["matricule"] = "Toute la collectivité", \
                    [node(u, {u["id"]}) for u in top], "valideur", "", ""
                out["count"] = len(by_id) - 1
                out["fiche"] = None
                out["all"] = True
                return jsonify(out)
            return jsonify(node(me, {me["id"]}))
        finally:
            db.close()

    # ------------------------------------------------------------------ agents Sedit RH
    @bp.route("/sirh", methods=["GET"])
    @login_required
    def sirh_candidates():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            units = load_units(db)
            index = people.unit_index(units)
            allowed, warning = my_unit_codes(db, units, index)
            if request.args.get("scope") == "all":
                allowed, warning = None, ""          # agents de toute la collectivité (par défaut : mon unité et en dessous)
            try:
                rh = sedit_rh.all_agents(force=request.args.get("refresh") == "1")
            except sedit_rh.SeditError as exc:
                return error(str(exc), 502)
            state = rh_import._app_state(db)
            words = sedit_rh._fold(request.args.get("q", "")).split()
            me_tokens = sorted(sedit_rh._fold(request.user.get("nom", "")).split())
            out = []
            for a in rh:
                s = sedit_rh._agent_summary(a)
                if (s["matricule"] and s["matricule"] == request.user.get("matricule")) or                         sorted(sedit_rh._fold("%s %s" % (s["nom"], s["prenom"])).split()) == me_tokens:
                    continue  # moi-même
                if allowed is not None and s["unit_code"] not in allowed:
                    continue
                if rh_import._in_app(a, state):
                    continue
                hay = sedit_rh._fold("%s %s %s %s" % (s["nom"], s["prenom"], s["matricule"], s["unit_libelle"]))
                if all(w in hay for w in words):
                    out.append({k: s[k] for k in ("matricule", "nom", "prenom", "unit_code", "unit_libelle", "fonction", "statut")})
            out.sort(key=lambda x: (x["unit_libelle"], x["nom"], x["prenom"]))
            return jsonify({"total": len(out), "items": out[:300], "warning": warning})
        finally:
            db.close()

    # ------------------------------------------------------------------ rattacher un agent Sedit RH
    @bp.route("/attach", methods=["POST"])
    @login_required
    def attach():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        d = request.get_json(force=True) or {}
        matricule = (d.get("matricule") or "").strip()
        try:
            parent_id = int(d.get("parent_id"))
        except (TypeError, ValueError):
            return error("Destination invalide", 400)
        db = get_db()
        try:
            by_id, _kids = children_map(db)
            parent = by_id.get(parent_id)
            if not parent or not parent["actif"]:
                return error("Valideur de destination introuvable ou inactif", 400)
            if not in_scope(db, parent_id):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            units = load_units(db)
            index = people.unit_index(units)
            try:
                rh = sedit_rh.all_agents()
            except sedit_rh.SeditError as exc:
                return error(str(exc), 502)
            agent = next((a for a in rh if a.get("matricule") == matricule), None)
            if not agent:
                return error("Agent introuvable dans Sedit RH", 404)
            s = sedit_rh._agent_summary(agent)
            if rh_import._in_app(agent, rh_import._app_state(db)):
                return error("Cet agent est déjà dans l'application", 400)
            unit_code = (d.get("unit_code") or s["unit_code"] or "").strip()
            if unit_code not in index:
                return error("Choisissez l'unité de l'agent (liste issue de Sedit RH)", 400)
            ad = people.ad_match(s["nom"], s["prenom"])
            found = ad["candidates"][0] if ad["status"] == "unique" else None
            email = found["email"] if found else ""
            ad_login = found["username"] if found else ""
            if ad_login and db.execute("SELECT 1 FROM users WHERE lower(login)=? OR lower(ad_login)=?",
                                       (ad_login, ad_login)).fetchone():
                ad_login = ""
            user_id, login = create_account(db, s["nom"].upper(), s["prenom"].upper(), email, matricule, parent_id, ad_login)
            db.execute("UPDATE users SET unit_code=? WHERE id=?", (unit_code, user_id))
            audit_user(db, user_id, login, request.user, "creation", "compte", "",
                       "profil=agent; unité=%s; valideur=%s; matricule=%s" % (unit_code, parent["login"], matricule),
                       "Création par glisser-déposer depuis Sedit RH")
            promote(db, parent, unit_code, by_id, index)
            db.commit()
            return jsonify({"user_id": user_id, "fiche_id": None, "login": login,
                            "email_found": bool(email), "ad_login_found": bool(ad_login)})
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()

    def split_identity(db, uid, full):
        """(nom de famille, prénom) de la personne : ceux du compte, sinon ceux de Sedit RH (par matricule), sinon le nom
        affiché coupé au premier espace. Mémorise le résultat sur le compte."""
        nom, prenom = (full["nom_famille"] or "").strip(), (full["prenom"] or "").strip()
        if not (nom and prenom) and full["matricule"]:
            try:
                hit = next((a for a in sedit_rh.all_agents() if a.get("matricule") == full["matricule"]), None)
            except sedit_rh.SeditError:
                hit = None
            if hit:
                nom, prenom = (hit.get("nom") or "").strip().upper(), (hit.get("prenom") or "").strip().upper()
        if not (nom and prenom):
            parts = (full["nom"] or "").strip().split(" ", 1)
            nom, prenom = nom or parts[0], prenom or (parts[1] if len(parts) > 1 else "")
        db.execute("UPDATE users SET nom_famille=?, prenom=? WHERE id=?", (nom, prenom, uid))
        return nom, prenom

    # ------------------------------------------------------------------ fiches d'une personne, année par année
    @bp.route("/<int:uid>/years", methods=["GET"])
    @login_required
    def person_years(uid):
        """Années pour lesquelles la personne a une fiche (navigation entre années dans la fiche)."""
        db = get_db()
        try:
            if uid != request.user["id"] and not (can_manage(request.user) and in_scope(db, uid)):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            rows = db.execute("SELECT id, year FROM agents WHERE agent_user_id=? ORDER BY year", (uid,)).fetchall()
            return jsonify([{"id": r["id"], "year": r["year"]} for r in rows])
        finally:
            db.close()

    # ------------------------------------------------------------------ unité de la personne (liste des entités de sa direction)
    def unit_options(db, uid):
        """(unité actuelle, liste des unités proposées) : toute la direction de la personne (direction, services, secteurs,
        équipes) ; sans unité connue, les unités de mon périmètre."""
        units = load_units(db)
        index = people.unit_index(units)
        row = db.execute("SELECT unit_code FROM users WHERE id=?", (uid,)).fetchone()
        current = (row["unit_code"] or "") if row else ""
        if current in index:
            top = ([current] + people.ancestors(index, current))[-1]
            codes = set(people.descendants(units, top))
        else:
            mine, _warning = my_unit_codes(db, units, index)
            codes = set(index) if mine is None else mine
        out = []
        for u in units:
            if u["code"] in codes:
                out.append({"code": u["code"], "libelle": u["libelle"], "level": u["level"], "path": people.unit_path(index, u["code"])})
        return current, out

    @bp.route("/<int:uid>/unit", methods=["GET"])
    @login_required
    def unit_get(uid):
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            if not in_scope(db, uid):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            current, options = unit_options(db, uid)
            return jsonify({"unit_code": current, "units": options})
        finally:
            db.close()

    @bp.route("/<int:uid>/unit", methods=["PUT"])
    @login_required
    def unit_set(uid):
        """Change l'unité (entité) d'une personne parmi les unités de sa direction."""
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        code = ((request.get_json(force=True) or {}).get("unit_code") or "").strip()
        db = get_db()
        try:
            by_id, _kids = children_map(db)
            user = by_id.get(uid)
            if not user or not in_scope(db, uid):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            current, options = unit_options(db, uid)
            if code not in {o["code"] for o in options}:
                return error("Choisissez une unité de la même direction (liste proposée)", 400)
            db.execute("UPDATE users SET unit_code=? WHERE id=?", (code, uid))
            audit_user(db, uid, user["login"], request.user, "modification", "unité", current, code, "Unité modifiée depuis la fiche")
            db.commit()
            return jsonify({"unit_code": code})
        finally:
            db.close()

    # ------------------------------------------------------------------ fiche congés = première période de paramètres
    @bp.route("/<int:uid>/fiche", methods=["POST"])
    @login_required
    def define_period(uid):
        """Définit la première période de paramètres d'une personne : crée sa fiche congés (ou complète une fiche vide)."""
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        import datetime as _dt
        import json as _json
        d = request.get_json(force=True) or {}
        try:
            year = int(d.get("year") or request_year())
        except (TypeError, ValueError):
            return error("Année invalide", 400)
        if not 2000 <= year <= 2100:
            return error("Année invalide", 400)
        pen, duree, quot = (d.get("penibilite") or "").strip(), (d.get("duree_hebdo") or "").strip(), (d.get("quotite") or "").strip()
        jours = str(d.get("jours_hebdo") if d.get("jours_hebdo") is not None else "").strip()
        days = d.get("jours_travailles")
        try:
            days = sorted({int(x) for x in days}) if days else list(range(1, int(jours) + 1))
        except (TypeError, ValueError):
            return error("Jours travaillés invalides", 400)
        if not days or any(x < 1 or x > 7 for x in days) or (jours.isdigit() and len(days) != int(jours)):
            return error("Cochez exactement %s jour(s) travaillé(s) par semaine" % jours, 400)
        ferie = bool(d.get("ferie_travaille"))
        st = load_settings()
        pen_names = [p.get("name") if isinstance(p, dict) else p for p in st.get("penibilites", [])]
        durees = (st.get("penibilites_durees") or {}).get(pen) or st.get("durees") or []
        if pen not in pen_names or duree not in [str(x) for x in durees] or quot not in [str(x) for x in st.get("quotites", [])] \
                or jours not in [str(x) for x in st.get("jours_hebdo", [])]:
            return error("Choisissez la pénibilité, la durée, la quotité et le nombre de jours par semaine proposés", 400)
        db = get_db()
        try:
            by_id, _kids = children_map(db)
            user = by_id.get(uid)
            if not user or not user["actif"]:
                return error("Personne introuvable ou inactive", 404)
            if not in_scope(db, uid):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            full = db.execute("SELECT nom, nom_famille, prenom, email, matricule, parent_id FROM users WHERE id=?", (uid,)).fetchone()
            owner_id = full["parent_id"]
            if not owner_id:
                return error("Cette personne n'a pas de valideur : rattachez-la d'abord", 400)
            nom, prenom = split_identity(db, uid, full)
            params = normalize_params({})
            params.update(penibilite=pen, duree_hebdo=duree, quotite=quot, jours_hebdo=int(jours),
                          jours_travailles=days, ferie_travaille=ferie)
            year_start, year_end = _dt.date(year, 1, 1), _dt.date(year, 12, 31)
            start = year_start
            arrival = (d.get("date_arrivee") or "")[:10]
            if not arrival and full["matricule"]:
                try:   # date d'arrivée de Sedit RH, si elle tombe dans l'année (prorata correct)
                    hit = next((a for a in sedit_rh.all_agents() if a.get("matricule") == full["matricule"]), None)
                    arrival = ((hit or {}).get("date_arrivee") or "")[:10]
                except sedit_rh.SeditError:
                    arrival = ""
            if arrival.startswith(str(year)):
                params["date_arrivee"] = arrival
                start = _dt.date.fromisoformat(arrival)
            periods = [{"start": start.isoformat(), "end": year_end.isoformat(), "penibilite": pen, "duree_hebdo": duree,
                        "quotite": quot, "jours_hebdo": int(jours),
                        "jours_travailles": days, "ferie_travaille": ferie}]
            row = db.execute("SELECT id, params, periods FROM agents WHERE agent_user_id=? AND year=?", (uid, year)).fetchone()
            if row:
                if fiche_complete(row):
                    return error("Cette personne a déjà une fiche avec période pour %d" % year, 400)
                old = _json.loads(row["params"]) if row["params"] else {}
                old.update({k: v for k, v in params.items() if v not in ("", None)})
                db.execute("UPDATE agents SET params=?, periods=? WHERE id=?", (_json.dumps(old, ensure_ascii=False),
                                                                                 _json.dumps(periods, ensure_ascii=False), row["id"]))
                fiche_id = row["id"]
            else:
                fiche_id = insert_fiche(db, nom, prenom, full["email"], full["matricule"], uid, owner_id, owner_id, year, params, periods)
            audit_user(db, uid, user["login"], request.user, "modification", "fiche", "",
                       "année=%d; %s / %s / %s / %s j" % (year, pen, duree, quot, jours), "Première période de paramètres")
            db.commit()
            return jsonify({"fiche_id": fiche_id, "year": year})
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ recherche du compte AD (e-mail, identifiant)
    @bp.route("/<int:uid>/ad", methods=["GET"])
    @login_required
    def ad_candidates(uid):
        """Comptes AD possibles pour une personne : par son nom (rapprochement), ou par un texte libre (?q=)."""
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            by_id, _kids = children_map(db)
            if uid not in by_id or not in_scope(db, uid):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            row = db.execute("SELECT nom, nom_famille, prenom FROM users WHERE id=?", (uid,)).fetchone()
        finally:
            db.close()
        q = (request.args.get("q") or "").strip()
        if q:
            try:
                hits = apm.ad_search(q, limit=15)
            except apm.ApmError as exc:
                return jsonify({"status": "indisponible", "candidates": [], "message": str(exc)})
            return jsonify({"status": "unique" if len(hits) == 1 else ("plusieurs" if hits else "aucun"), "candidates": hits})
        nom = (row["nom_famille"] or row["nom"] or "").strip()
        return jsonify(people.ad_match(nom, (row["prenom"] or "").strip()))

    @bp.route("/<int:uid>/ad", methods=["POST"])
    @login_required
    def ad_apply(uid):
        """Rattache un compte AD à la personne : reprend son adresse e-mail et son identifiant AD."""
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        username = ((request.get_json(force=True) or {}).get("username") or "").strip().lower()
        if not username:
            return error("Choisissez un compte AD", 400)
        try:   # l'adresse est relue dans l'annuaire : on ne se fie pas à ce que renvoie le navigateur
            found = next((h for h in apm.ad_search(username, limit=30) if h["username"] == username), None)
        except apm.ApmError as exc:
            return error("Annuaire indisponible : %s" % exc, 502)
        if not found:
            return error("Compte AD introuvable", 404)
        db = get_db()
        try:
            by_id, _kids = children_map(db)
            user = by_id.get(uid)
            if not user or not in_scope(db, uid):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            clash = db.execute("SELECT login FROM users WHERE id<>? AND (lower(ad_login)=? OR lower(login)=?)",
                               (uid, username, username)).fetchone()
            if clash:
                return error("Cet identifiant AD est déjà utilisé par le compte %s" % clash["login"], 400)
            old = db.execute("SELECT email, ad_login FROM users WHERE id=?", (uid,)).fetchone()
            db.execute("UPDATE users SET email=?, ad_login=? WHERE id=?", (found["email"], username, uid))
            db.execute("UPDATE agents SET email=? WHERE agent_user_id=?", (found["email"], uid))
            audit_user(db, uid, user["login"], request.user, "modification", "e-mail", old["email"] or "", found["email"],
                       "Compte AD « %s » rattaché (recherche AD)" % username)
            db.commit()
            return jsonify({"email": found["email"], "ad_login": username})
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ déplacer une personne
    @bp.route("/move", methods=["POST"])
    @login_required
    def move():
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        d = request.get_json(force=True) or {}
        try:
            uid, parent_id = int(d.get("user_id")), int(d.get("parent_id"))
        except (TypeError, ValueError):
            return error("Déplacement invalide", 400)
        db = get_db()
        try:
            by_id, kids = children_map(db)
            user, parent = by_id.get(uid), by_id.get(parent_id)
            if not user or not parent or not parent["actif"]:
                return error("Personne ou destination introuvable", 404)
            if uid == request.user["id"]:
                return error("Vous ne pouvez pas vous déplacer vous-même", 400)
            if user["role"] == "administrateur":
                return error("Un compte administrateur n'a pas de valideur", 400)
            if not in_scope(db, uid) or not in_scope(db, parent_id):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            if parent_id in subtree(kids, uid):
                return error("Impossible de placer une personne sous elle-même ou sous un de ses subordonnés", 400)
            if user["parent_id"] == parent_id:
                return jsonify({"ok": True, "unchanged": True})
            index = people.unit_index(load_units(db))
            old = by_id.get(user["parent_id"])
            db.execute("UPDATE users SET parent_id=? WHERE id=?", (parent_id, uid))
            db.execute("UPDATE agents SET user_id=?, validator_id=? WHERE agent_user_id=?", (parent_id, parent_id, uid))
            by_id[uid] = dict(user, parent_id=parent_id)
            parent = promote(db, parent, user["unit_code"], by_id, index)
            if user["role"] != "agent" and role_levels.get(user["role"], 0) >= role_levels.get(parent["role"], 0):
                db.rollback()
                return error("Le valideur de destination doit être d'un niveau plus élevé que %s" % (user["nom"] or user["login"]), 400)
            audit_user(db, uid, user["login"], request.user, "modification", "responsable",
                       old["login"] if old else "", parent["login"], "Déplacé dans « Mes agents »")
            db.commit()
            return jsonify({"ok": True})
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()

    app.register_blueprint(bp)
