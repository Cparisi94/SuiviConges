# -*- coding: utf-8 -*-
"""Abonnement iCalendar (ICS) : les congés de l'agent dans l'agenda de son téléphone, avec leur état.

- `GET /api/mobile/calendar` : état de mon abonnement (actif ? créé le ? dernière lecture ?) ;
- `POST /api/mobile/calendar/link` : crée (ou **remplace**) mon lien secret ; le jeton n'est renvoyé qu'ici, seul son haché est conservé ;
- `POST /api/mobile/calendar/revoke` : arrête la synchronisation (le lien cesse de fonctionner) ;
- `GET /api/ical/<jeton>.ics` : le flux, **sans session** (le jeton fait foi), lu par l'application Agenda du téléphone.

Contenu du flux — ma propre fiche seulement, années en cours et suivante :
- jour **validé** : « ✅ Congé annuel » (STATUS:CONFIRMED) ; jour **demandé** : « ⏳ Congé annuel (en attente) » (STATUS:TENTATIVE) ;
  demande d'annulation en cours : « ⏳ … (annulation demandée) » ; refusé ou annulé : absent ;
- journée entière = événement « toute la journée » (les jours consécutifs de même type et de même état sont regroupés) ; demi-journée = événement du matin
  ou de l'après-midi (horaires EXCHANGE_MORNING / EXCHANGE_AFTERNOON) ;
- jamais de motif sensible : maladie, congés parentaux et familiaux, absences syndicales ou disciplinaires s'affichent « Absence » ;
  les absences en heures et le temps partiel n'y figurent pas.
"""
import datetime as dt
import hashlib
import json
import re
import secrets
import sys

from flask import Blueprint, Response, jsonify, request

import config
import ratelimit
from db import get_db
from http_utils import error

bp = Blueprint("ical", __name__)

HOURLY = {"CAH", "RTTH", "RCH"}                      # absences en heures : pas d'événement
NOT_LEAVE = {"TP"}                                   # temps partiel : pas un congé
NEUTRAL = {"CM", "GEM", "CT", "CP", "SF", "AI", "ET", "GR", "SX"}      # motifs sensibles : « Absence » sans détail
STATUS_TEXT = {"validee": ("✅ ", "", "CONFIRMED", "OPAQUE"), "attente": ("⏳ ", " (en attente)", "TENTATIVE", "TRANSPARENT"),
               "annulation": ("⏳ ", " (annulation demandée)", "TENTATIVE", "TRANSPARENT")}


def _core():
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_agent_by_id") and hasattr(main, "app"):
        return main
    import app as core
    return core


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _esc(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """Pliage des lignes à 75 octets (RFC 5545) : les suites commencent par une espace."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def _hours(text, default):
    try:
        a, b = text.split("-")
        return a.strip(), b.strip()
    except (ValueError, AttributeError):
        return default


def build_feed(db, user_id, today=None):
    """Texte ICS des congés de la personne (voir l'en-tête du module)."""
    core = _core()
    today = today or dt.date.today()
    settings = core.load_settings()
    labels = {c["code"]: (c.get("libelle") or c["code"]) for c in (settings.get("codes") or []) if c.get("code")}
    morning = _hours(config.EXCHANGE_MORNING, ("08:30", "12:30"))
    afternoon = _hours(config.EXCHANGE_AFTERNOON, ("13:30", "17:30"))
    events = []                                                       # (jour ISO, moitié 0/1, code, état)
    for fiche in db.execute("SELECT id, year FROM agents WHERE agent_user_id=? AND year IN (?,?) ORDER BY year, id", (user_id, today.year, today.year + 1)).fetchall():
        year = int(fiche["year"])
        state = {}                                                    # clé de demi-journée -> (code, état)
        for key, code in core._agent_cells(db, fiche["id"]).items():
            state[int(key)] = (code, "validee")
        for r in db.execute("SELECT code, cells, status FROM leave_requests WHERE agent_id=? AND request_type='absence' AND status IN ('en_attente','annulation_demandee')", (fiche["id"],)).fetchall():
            try:
                keys = [int(k) for k in json.loads(r["cells"] or "[]")]
            except (ValueError, TypeError):
                continue
            for key in keys:
                state[key] = (r["code"], "attente" if r["status"] == "en_attente" else "annulation")
        for key, (code, st) in state.items():
            if code in HOURLY or code in NOT_LEAVE or not (code in core.ABSENCE_CODES or re.fullmatch(r"CA\d{2}", code)):      # CA25… = reliquat de l'an dernier
                continue
            try:
                day = dt.date(year, key // 1000, (key % 1000) // 10)
            except ValueError:
                continue
            events.append((day.isoformat(), key % 10, code, st))
    events.sort()
    # une journée entière (matin + après-midi de même type et même état) ; les journées consécutives identiques sont regroupées
    byday = {}
    for day, half, code, st in events:
        byday.setdefault(day, {})[half] = (code, st)
    singles, fulls = [], []
    for day, halves in sorted(byday.items()):
        if 0 in halves and 1 in halves and halves[0] == halves[1]:
            fulls.append((day, halves[0]))
        else:
            for half, (code, st) in halves.items():
                singles.append((day, half, code, st))
    runs = []
    for day, (code, st) in fulls:
        d = dt.date.fromisoformat(day)
        if runs and runs[-1]["kind"] == (code, st) and runs[-1]["end"] + dt.timedelta(days=1) == d:
            runs[-1]["end"] = d
        else:
            runs.append({"kind": (code, st), "start": d, "end": d})

    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    user_key = hashlib.sha256(("conges-ics-%s" % user_id).encode()).hexdigest()[:16]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ville d'Ivry//Suivi des conges//FR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Mes congés", "X-WR-CALDESC:Congés validés et demandés (Suivi des congés)", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]

    def tag(code):
        """Empreinte du type dans l'identifiant de l'événement : le code lui-même (CM…) ne doit jamais apparaître dans le fichier."""
        return hashlib.sha256(code.encode()).hexdigest()[:6]

    def title(code, st):
        icon, suffix, _s, _t = STATUS_TEXT[st]
        return icon + ("Absence" if code in NEUTRAL else labels.get(code) or ("Congé annuel (reliquat)" if re.fullmatch(r"CA\d{2}", code) else code)) + suffix

    def add(uid, summary, st, start, end, all_day):
        _i, _x, status, transp = STATUS_TEXT[st]
        lines.extend(["BEGIN:VEVENT", "UID:%s@conges.ivry" % uid, "DTSTAMP:" + stamp,
                      ("DTSTART;VALUE=DATE:" + start) if all_day else ("DTSTART:" + start),
                      ("DTEND;VALUE=DATE:" + end) if all_day else ("DTEND:" + end),
                      "SUMMARY:" + _esc(summary), "STATUS:" + status, "TRANSP:" + transp, "CLASS:PRIVATE", "END:VEVENT"])

    for run in runs:
        code, st = run["kind"]
        add("%s-%s-%s-%s" % (user_key, run["start"].isoformat(), tag(code), "j"), title(code, st), st,
            run["start"].strftime("%Y%m%d"), (run["end"] + dt.timedelta(days=1)).strftime("%Y%m%d"), True)
    for day, half, code, st in singles:
        a, b = (morning if half == 0 else afternoon)
        d = day.replace("-", "")
        add("%s-%s-%s-%s" % (user_key, day, tag(code), "m" if half == 0 else "a"), title(code, st), st,
            "%sT%s00" % (d, a.replace(":", "")), "%sT%s00" % (d, b.replace(":", "")), False)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def init_ical(app, login_required):
    @bp.route("/api/mobile/calendar", methods=["GET"])
    @login_required
    def status():
        db = get_db()
        try:
            row = db.execute("SELECT created_at, last_used_at FROM calendar_tokens WHERE user_id=?", (request.user["id"],)).fetchone()
        finally:
            db.close()
        return jsonify({"active": bool(row), "created_at": (row["created_at"] if row else "")[:16], "last_used_at": (row["last_used_at"] if row else "")[:16]})

    @bp.route("/api/mobile/calendar/link", methods=["POST"])
    @login_required
    def link():
        """Crée mon lien d'abonnement (le précédent, s'il existe, cesse de fonctionner) : le jeton n'est montré qu'ici."""
        token = secrets.token_urlsafe(32)
        db = get_db()
        try:
            db.execute("DELETE FROM calendar_tokens WHERE user_id=?", (request.user["id"],))
            db.execute("INSERT INTO calendar_tokens (user_id, token_hash, created_at) VALUES (?,?,?)", (request.user["id"], _hash(token), _now()))
            db.commit()
        finally:
            db.close()
        return jsonify({"token": token})

    @bp.route("/api/mobile/calendar/revoke", methods=["POST"])
    @login_required
    def revoke():
        db = get_db()
        try:
            db.execute("DELETE FROM calendar_tokens WHERE user_id=?", (request.user["id"],))
            db.commit()
        finally:
            db.close()
        return jsonify({"active": False})

    @bp.route("/api/ical/<token>.ics", methods=["GET"])
    @bp.route("/cal/<token>.ics", methods=["GET"])               # même flux sous l'adresse que publie le frontend mobile
    def feed(token):
        """Flux ICS : pas de session, le jeton (256 bits, comparé par son haché) fait foi. Réponse identique pour un jeton inconnu ou révoqué."""
        if len(token) < 20 or len(token) > 80:
            return error("Introuvable", 404)
        digest = _hash(token)
        if ratelimit.blocked("ical-miss:" + (request.remote_addr or "?"), 30, 600):          # trop de jetons inconnus essayés depuis cette adresse
            return error("Trop de requêtes", 429)
        if not ratelimit.allow("ical:" + digest[:16], 60, 60) or not ratelimit.allow("icalip:" + (request.remote_addr or "?"), 240, 60):
            return error("Trop de requêtes", 429)
        db = get_db()
        try:
            row = db.execute("SELECT user_id, last_used_at FROM calendar_tokens WHERE token_hash=?", (digest,)).fetchone()
            if not row:
                ratelimit.record("ical-miss:" + (request.remote_addr or "?"))
                return error("Introuvable", 404)
            now = _now()
            if not row["last_used_at"] or row["last_used_at"][:16] != now[:16]:
                db.execute("UPDATE calendar_tokens SET last_used_at=? WHERE user_id=?", (now, row["user_id"]))
                db.commit()
            body = build_feed(db, row["user_id"])
        finally:
            db.close()
        resp = Response(body, mimetype="text/calendar")
        resp.headers["Content-Type"] = "text/calendar; charset=utf-8"
        resp.headers["Cache-Control"] = "private, max-age=600"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    app.register_blueprint(bp)
