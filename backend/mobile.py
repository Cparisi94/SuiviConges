# -*- coding: utf-8 -*-
"""Version « mobile » minimale : mes compteurs, mes demandes en cours, mon agenda et le calcul d'une demande simple (du … au …).

Deux routes de lecture réservées à **ma propre fiche** (la fiche dont je suis le titulaire) :
- `GET /api/mobile/summary?year=` : compteurs, demandes en cours (en attente, validées à venir), agenda (demi-journées validées et en attente) ;
- `GET /api/mobile/days?du=&au=&debut=&fin=&year=` : demi-journées réellement posables entre deux dates (jours travaillés de la fiche,
  hors fériés, hors cases déjà occupées).

L'annulation passe par `POST /api/mobile/requests/<id>/cancel` (demande en attente) et `.../cancel-request` (demande validée : à accepter par le valideur), réservées à MES demandes.
La demande elle-même est créée par `POST /api/requests` (mêmes contrôles, mêmes mails et même circuit de validation que l'application complète).
"""
import datetime as dt
import json
import re
import sys

from flask import Blueprint, jsonify, request

import mailer
from db import get_db, row_to_dict, user_label
from http_utils import error

bp = Blueprint("mobile", __name__, url_prefix="/api/mobile")

BALANCE_KEYS = {"CA": "ca", "RTT": "rtt", "JS": "js", "JB": "jb", "CET": "cet"}
STATUS_LABELS = {"en_attente": "En attente", "validee": "Validée", "annulation_demandee": "Annulation demandée"}
SHOWN_STATUSES = tuple(STATUS_LABELS)


def _core():
    """Module principal de l'application. Lancé par `python app.py` (poste de développement), il s'appelle `__main__` : un `import app` le
    rechargerait une seconde fois (blueprints enregistrés deux fois, erreur 500) ; sous gunicorn ou dans les tests, c'est `app`."""
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_agent_by_id") and hasattr(main, "app"):
        return main
    import app as core
    return core


def _color(value):
    """Couleur CSS d'un code : « 92D050 » (sans dièse, comme dans les réglages) devient « #92D050 » ; une valeur douteuse donne la couleur par défaut."""
    value = (value or "").strip().lstrip("#")
    return "#" + value if re.fullmatch(r"[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}", value) else "#c4573a"


def _own_fiche(core, db, year):
    return db.execute(
        "SELECT id FROM agents WHERE agent_user_id=? AND year=? ORDER BY id LIMIT 1", (request.user["id"], year)).fetchone()


def _iso(year, key):
    key = int(key)
    return dt.date(int(year), key // 1000, (key % 1000) // 10).isoformat(), key % 10


def init_mobile(app, login_required):
    @bp.route("/summary", methods=["GET"])
    @login_required
    def summary():
        core = _core()
        year = core._request_year()
        db = get_db()
        try:
            settings = core._settings_for_year(core.load_settings(), year)
            codes = {c["code"]: {"label": c.get("libelle") or c["code"], "color": _color(c.get("color"))}
                     for c in (settings.get("codes") or []) if c.get("code")}
            out = {"year": year, "user": {"label": user_label(request.user)}, "fiche": None, "soldes": None, "estime": None,
                   "demandes": [], "agenda": [], "codes": codes, "demandables": [], "feries": [], "couverture": []}
            row = _own_fiche(core, db, year)
            if not row:
                return jsonify(out)
            agent = core._agent_by_id(db, row["id"])
            out["fiche"] = {"id": agent["id"], "year": year}
            out["demandables"] = [{"restant": None, "code": c, "label": (codes.get(c) or {}).get("label") or ("Congés de l'an dernier (reliquat)" if re.fullmatch(r"CA\d{2}", c) else c)}
                                  for c in core._requestable_codes(year)]
            out["feries"] = [str(x[0])[:10] for x in (settings.get("jours_feries") or []) if x]
            out["couverture"] = core._agent_coverage(agent)
            sy = core._agent_summary_for_row(agent, settings)
            if not sy.get("error"):
                def pick(key, label):
                    block = sy.get(key) or {}
                    return {"code": key.upper(), "label": label, "restant": block.get("restant"), "pris": block.get("pris")}
                out["soldes"] = [pick("ca", "Congés annuels"), pick("rtt", "RTT"), pick("js", "Sujétion"), pick("jb", "Bonification"), pick("cet", "CET")]
                out["total"] = {"restant": (sy.get("total") or {}).get("restant"), "pris": (sy.get("total") or {}).get("pris")}
                # solde disponible de chaque type demandable (None = pas de solde suivi : ASA, médaille, reliquat n-1…) : borne la répartition d'une demande
                for item in out["demandables"]:
                    key = BALANCE_KEYS.get(item["code"])
                    item["restant"] = (sy.get(key) or {}).get("restant") if key else None
            est = core._estimated_balance(db, agent["id"])
            if est and est.get("pending"):
                out["estime"] = {"ca": est.get("ca"), "rtt": est.get("rtt"), "jours_en_attente": est.get("pending")}
            # agenda : demi-journées validées et en attente
            validated = core._agent_cells(db, agent["id"])
            pending = core._pending_cells(db, agent["id"])
            for key, code in sorted(validated.items(), key=lambda kv: int(kv[0])):
                day, half = _iso(year, key)
                out["agenda"].append({"d": day, "h": half, "code": code, "s": "validee"})
            for key, code in sorted(pending.items(), key=lambda kv: int(kv[0])):
                day, half = _iso(year, key)
                out["agenda"].append({"d": day, "h": half, "code": code, "s": "attente"})
            # demandes en cours : en attente + validées dont la dernière journée n'est pas passée
            today = dt.date.today().isoformat()
            rows = db.execute(
                "SELECT id, code, cells, days, status, soumis_le FROM leave_requests WHERE agent_id=? AND request_type='absence' "
                "AND status IN ('en_attente','validee','annulation_demandee') ORDER BY id DESC LIMIT 60", (agent["id"],)).fetchall()
            for r in rows:
                try:
                    cells = [int(c) for c in json.loads(r["cells"] or "[]")]
                except (ValueError, TypeError):
                    cells = []
                if not cells:
                    continue
                last, _h = _iso(year, max(cells))
                if r["status"] == "validee" and last < today:
                    continue
                out["demandes"].append({
                    "id": r["id"], "code": r["code"], "label": (codes.get(r["code"]) or {}).get("label", r["code"]),
                    "statut": r["status"], "statut_label": STATUS_LABELS.get(r["status"], r["status"]), "jours": r["days"],
                    "dates": mailer.format_ranges(cells, year), "debut": _iso(year, min(cells))[0], "fin": last,
                    "soumis_le": str(r["soumis_le"] or "")[:10]})
            out["demandes"].sort(key=lambda d: (d["statut"] != "en_attente", d["debut"]))
            return jsonify(out)
        finally:
            db.close()

    @bp.route("/absences-rh", methods=["GET"])
    @login_required
    def absences_rh():
        """Absences saisies dans Sedit RH (CM, GEM, CT, CP, SF) sur MA fiche, en demi-journées travaillées, pour l'agenda (lecture seule, couleur claire).
        Chargées à part : Sedit RH est lent ou peut être indisponible (l'agenda s'affiche alors sans ces jours, sans erreur)."""
        core = _core()
        year = core._request_year()
        db = get_db()
        try:
            row = _own_fiche(core, db, year)
            if not row:
                return jsonify({"items": []})
            agent = core._agent_by_id(db, row["id"])
            coverage = core._agent_coverage(agent)
            holidays = {str(x[0])[:10] for x in (core.load_settings().get("jours_feries") or [])}
            busy = set(core._agent_cells(db, agent["id"])) | set(core._pending_cells(db, agent["id"]))
        finally:
            db.close()
        matricule = (request.user.get("matricule") or "").strip()
        if not matricule:
            return jsonify({"items": [], "warning": "Matricule inconnu"})
        import sedit_rh
        try:
            absences = sedit_rh.absences(matricule, year)
        except sedit_rh.SeditError as exc:
            return jsonify({"items": [], "warning": str(exc)})
        items = []
        for a in absences:
            try:
                day, last = dt.date.fromisoformat(a["debut"]), dt.date.fromisoformat(a["fin"])
            except (KeyError, ValueError):
                continue
            while day <= last:
                if day.year == year:
                    for half in (0, 1):
                        key = day.month * 1000 + day.day * 10 + half
                        if core._cell_covered(coverage, year, key, holidays) and str(key) not in busy:
                            items.append({"d": day.isoformat(), "h": half, "code": a["code"], "s": "rh"})
                day += dt.timedelta(days=1)
        return jsonify({"items": items})

    @bp.route("/days", methods=["GET"])
    @login_required
    def days():
        """Demi-journées posables entre deux dates de ma fiche : `debut` = matin | apres_midi (premier jour), `fin` = midi | soir (dernier jour)."""
        core = _core()
        try:
            du = dt.date.fromisoformat(request.args.get("du", ""))
            au = dt.date.fromisoformat(request.args.get("au", ""))
        except ValueError:
            return error("Dates invalides", 400)
        if au < du:
            return error("La date de fin précède la date de début", 400)
        if (au - du).days > 120:
            return error("Période trop longue (120 jours au plus)", 400)
        year = du.year
        if au.year != year:
            return error("Une demande ne peut pas chevaucher deux années : faites-en une par année", 400)
        debut, fin = request.args.get("debut", "matin"), request.args.get("fin", "soir")
        db = get_db()
        try:
            row = _own_fiche(core, db, year)
            if not row:
                return error("Vous n'avez pas de fiche pour %d" % year, 404)
            agent = core._agent_by_id(db, row["id"])
            coverage = core._agent_coverage(agent)
            holidays = {str(x[0])[:10] for x in (core.load_settings().get("jours_feries") or [])}
            busy = set(core._agent_cells(db, agent["id"])) | set(core._pending_cells(db, agent["id"])) | set(core._hourly_occupied_half(db, agent["id"]))
            cells, ignored, day = [], 0, du
            while day <= au:
                for half in (0, 1):
                    if day == du and half == 0 and debut == "apres_midi":
                        continue
                    if day == au and half == 1 and fin == "midi":
                        continue
                    key = day.month * 1000 + day.day * 10 + half
                    if core._cell_covered(coverage, year, key, holidays) and str(key) not in busy:
                        cells.append(key)
                    elif core._cell_covered(coverage, year, key, holidays):
                        ignored += 1                     # case déjà occupée (absence ou demande en attente)
                day += dt.timedelta(days=1)
            return jsonify({"agent_id": agent["id"], "cells": cells, "jours": len(cells) / 2.0, "deja_occupees": ignored,
                            "resume": mailer.format_ranges(cells, year) if cells else []})
        finally:
            db.close()

    def _own_request(db, request_id):
        """La demande appartient-elle à ma propre fiche ? (un administrateur ne peut pas, d'ici, annuler la demande d'un autre)"""
        row = db.execute("SELECT a.agent_user_id FROM leave_requests r JOIN agents a ON a.id=r.agent_id WHERE r.id=?", (request_id,)).fetchone()
        return bool(row and row["agent_user_id"] == request.user["id"])

    def _delegate(request_id, name):
        db = get_db()
        try:
            mine = _own_request(db, request_id)
        finally:
            db.close()
        if not mine:
            return error("Demande introuvable", 404)
        # mêmes règles que l'application complète (statut, droits, journal) : on appelle sa fonction, sans le décorateur de connexion déjà appliqué ici
        return getattr(_core(), name).__wrapped__(request_id)

    @bp.route("/requests/<int:request_id>/cancel", methods=["POST"])
    @login_required
    def cancel(request_id):
        """Annule une demande **en attente** (immédiat)."""
        return _delegate(request_id, "requests_cancel")

    @bp.route("/requests/<int:request_id>/cancel-request", methods=["POST"])
    @login_required
    def cancel_request(request_id):
        """Demande l'annulation d'une demande **validée** : le valideur doit l'accepter."""
        return _delegate(request_id, "requests_cancel_request")

    app.register_blueprint(bp)
