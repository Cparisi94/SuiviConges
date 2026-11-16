# -*- coding: utf-8 -*-
"""Module « exchange » : synchronisation des absences avec l'agenda Outlook de l'agent, via l'API Ville (APM).

Pour un agent qui l'a demandé (users.exchange_sync = 1) :
- chaque jour d'absence (codes de ABSENCE_CODES) devient un événement **« ABSENT »**, affiché « Absent du bureau » (showAs = oof) ;
  une demi-journée donne un événement sur le matin ou l'après-midi, une journée complète un événement « toute la journée » ;
- un jour **demandé** (demande en attente de validation) devient « ABSENT » en disponibilité **« Provisoire »** (tentative) ; une fois validé, l'événement passe en « Absent du bureau » ;
- chaque jour de télétravail (code TT) devient un événement **« Télétravail »** affiché « Travaille ailleurs » (showAs = workingElsewhere).
Rien d'autre n'est écrit (ni motif, ni code, ni détail : l'événement est en plus marqué « privé »). La synchronisation couvre
d'aujourd'hui à la fin de l'année suivante ; la table `exchange_events` retient les événements créés pour les mettre à jour
ou les supprimer quand la fiche change ou que l'agent désactive la synchronisation.

Les appels passent par l'**API Ville** (APM, https://api.ivry.local, clé X-API-KEY de l'application : APM_API_URL / APM_API_KEY),
jamais directement par l'API Ville. Contrat attendu de l'APM (route d'agenda, EXCHANGE_APM_EVENTS_PATH) :
  POST   {chemin}            corps : {"mailbox": "<e-mail>", "subject", "start", "end", "isAllDay", "showAs", "isReminderOn", "sensitivity"}  ->  {"id": "<événement>"}
  DELETE {chemin}/{id}?mailbox=<e-mail>                                                                                                  ->  204
La route n'existe pas encore dans la documentation actuelle de l'APM (seuls les messages /api/v1/o365/messages y figurent) : tant qu'elle
est absente, le module se déclare indisponible et rien n'est envoyé.
"""
import datetime as dt
import threading
import time

import requests

import apm
import config
from db import get_db

ABSENT_SUBJECT = "ABSENT"
TT_SUBJECT = "Télétravail"
_TIMEOUT = 30
_running = set()                     # utilisateurs dont une synchronisation est en cours (évite les doublons)
_running_lock = threading.Lock()
_avail = {"at": 0.0, "ok": False, "message": ""}
_AVAIL_TTL = 600


class ExchangeError(Exception):
    """L'API Ville est injoignable ou refuse la requête ; `status` = code HTTP éventuel."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def configured():
    """L'API Ville est configurée (adresse et clé) : condition nécessaire, pas suffisante (voir `availability`)."""
    return apm.configured()


def _verify():
    if config.VILLE_CA_FILE:
        return config.VILLE_CA_FILE
    return not config.VILLE_ALLOW_SELF_SIGNED_CERTS


def availability(force=False):
    """(disponible, message) : la route d'agenda existe-t-elle dans la documentation de l'API Ville ? Résultat conservé 10 minutes."""
    if not apm.configured():
        return False, "L'API Ville n'est pas configurée (APM_API_URL et APM_API_KEY dans .env)"
    if not force and time.monotonic() - _avail["at"] < _AVAIL_TTL:
        return _avail["ok"], _avail["message"]
    ok, message = False, ""
    try:
        resp = requests.get(config.APM_API_URL.rstrip("/") + "/swagger.json", headers={"X-API-KEY": config.APM_API_KEY}, timeout=_TIMEOUT, verify=_verify())
        paths = (resp.json() or {}).get("paths") or {} if resp.status_code == 200 else {}
        ok = any(p == config.EXCHANGE_APM_EVENTS_PATH or p.startswith(config.EXCHANGE_APM_EVENTS_PATH + "/") for p in paths)
        if not ok:
            message = ("L'API Ville ne propose pas encore la route d'agenda Outlook (%s) : la synchronisation n'est pas disponible" % config.EXCHANGE_APM_EVENTS_PATH
                       if resp.status_code == 200 else "Documentation de l'API Ville illisible (HTTP %s)" % resp.status_code)
    except (requests.RequestException, ValueError) as exc:
        message = "API Ville injoignable (%s)" % exc.__class__.__name__
    _avail.update(at=time.monotonic(), ok=ok, message=message)
    return ok, message


def _call(method, path, body=None, params=None):
    """Appel de l'API Ville ; réessaie quelques fois si elle demande de patienter (429, 503). Retourne le JSON (ou {})."""
    if not apm.configured():
        raise ExchangeError("L'API Ville n'est pas configurée (APM_API_URL et APM_API_KEY dans .env)")
    for attempt in range(4):
        try:
            resp = requests.request(method, config.APM_API_URL.rstrip("/") + path, json=body, params=params, timeout=_TIMEOUT,
                                    verify=_verify(), headers={"X-API-KEY": config.APM_API_KEY})
        except requests.RequestException as exc:
            raise ExchangeError("API Ville injoignable (%s)" % exc.__class__.__name__) from exc
        if resp.status_code in (429, 503) and attempt < 3:
            try:
                wait = float(resp.headers.get("Retry-After", "2"))
            except ValueError:
                wait = 2.0
            time.sleep(min(30.0, max(1.0, wait)))
            continue
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 204:
            return {}
        try:
            data = resp.json() or {}
            detail = data.get("error") or data.get("message") or data.get("detail") or ""
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except ValueError:
            detail = ""
        raise ExchangeError("API Ville : HTTP %s%s" % (resp.status_code, " — " + detail[:200] if detail else ""), resp.status_code)
    raise ExchangeError("API Ville : trop de tentatives")


# --------------------------------------------------------------------------- #
#  Événements souhaités à partir des cases de la fiche
# --------------------------------------------------------------------------- #
_ABSENCE_CODES = set()


def set_absence_codes(codes):
    """Liste des codes d'absence : celle de l'application (taux d'absence du tableau de bord RH), fournie au démarrage."""
    _ABSENCE_CODES.clear()
    _ABSENCE_CODES.update(codes)


def _absence_codes():
    return _ABSENCE_CODES


def kind_of(code, absence_codes=None):
    """ABSENT pour un code d'absence, TT pour le télétravail, None sinon (présence, week-end, férié…)."""
    code = (code or "").strip()
    if code == "TT":
        return "TT"
    return "ABSENT" if code in (absence_codes if absence_codes is not None else _absence_codes()) else None


def desired_events(cells_by_year, today=None, until=None, absence_codes=None, pending_by_year=None):
    """{(AAAA-MM-JJ, part): kind} : part = J (journée), M (matin) ou A (après-midi) ; kind = ABSENT, TT ou PROV.

    `cells_by_year` : {année: {clé de case: code}} ; la clé est mois*1000 + jour*10 + demi-journée (0 matin, 1 après-midi).
    `pending_by_year` : mêmes cases pour les jours **demandés** (demande en attente de validation) : une absence demandée donne PROV
    (absent à titre provisoire) tant qu'elle n'est pas validée ; une case déjà posée dans la fiche prévaut.
    Seuls les jours du 1er janvier de l'année en cours à `until` (fin de l'année suivante par défaut) sont retenus (les absences déjà passées de l'année y figurent aussi)."""
    today = today or dt.date.today()
    until = until or dt.date(today.year + 1, 12, 31)
    start = dt.date(today.year, 1, 1)
    halves = {}
    sources = [(cells_by_year, False), (pending_by_year or {}, True)]
    for source, provisional in sources:
        for year, cells in source.items():
            for key, code in (cells or {}).items():
                k = kind_of(code, absence_codes)
                if not k:
                    continue
                if provisional:
                    if k != "ABSENT":
                        continue                       # une demande ne porte que sur des absences (le télétravail se pose directement dans la fiche)
                    k = "PROV"
                try:
                    n = int(key)
                    day = dt.date(int(year), n // 1000, (n % 1000) // 10)
                except (TypeError, ValueError):
                    continue
                half = n % 10
                if half not in (0, 1) or not (start <= day <= until):
                    continue
                if provisional and half in halves.get(day, {}):
                    continue                           # la fiche l'emporte sur une demande
                halves.setdefault(day, {})[half] = k
    out = {}
    for day, h in halves.items():
        if h.get(0) and h.get(0) == h.get(1):
            out[(day.isoformat(), "J")] = h[0]
        else:
            if h.get(0):
                out[(day.isoformat(), "M")] = h[0]
            if h.get(1):
                out[(day.isoformat(), "A")] = h[1]
    return out


def _hours(spec):
    start, _, end = spec.partition("-")
    return start.strip(), end.strip()


def event_payload(day_iso, part, kind):
    """Corps de la requête d'agenda : uniquement le titre, les horaires et l'état de disponibilité."""
    day = dt.date.fromisoformat(day_iso)
    tz = config.EXCHANGE_TIMEZONE
    body = {
        "subject": TT_SUBJECT if kind == "TT" else ABSENT_SUBJECT,
        "showAs": {"ABSENT": "oof", "PROV": "tentative", "TT": "workingElsewhere"}[kind],
        "isReminderOn": False,
        "sensitivity": "private",
    }
    if part == "J":
        body.update(isAllDay=True, start={"dateTime": day.isoformat() + "T00:00:00", "timeZone": tz},
                    end={"dateTime": (day + dt.timedelta(days=1)).isoformat() + "T00:00:00", "timeZone": tz})
    else:
        start, end = _hours(config.EXCHANGE_MORNING if part == "M" else config.EXCHANGE_AFTERNOON)
        body.update(isAllDay=False, start={"dateTime": "%sT%s:00" % (day.isoformat(), start), "timeZone": tz},
                    end={"dateTime": "%sT%s:00" % (day.isoformat(), end), "timeZone": tz})
    return body


# --------------------------------------------------------------------------- #
#  Synchronisation d'un agent
# --------------------------------------------------------------------------- #
def _user_pending(db, user_id, today):
    """{année: {clé de case: code}} des jours demandés et pas encore validés (demandes « en attente »)."""
    import json
    out = {}
    for r in db.execute("SELECT a.year, r.code, r.cells FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
                        "WHERE a.agent_user_id=? AND r.status='en_attente' AND a.year>=? AND a.year<=?",
                        (user_id, today.year, today.year + 1)).fetchall():
        try:
            keys = json.loads(r["cells"]) if isinstance(r["cells"], str) else (r["cells"] or [])
        except ValueError:
            keys = []
        for key in keys:
            try:
                out.setdefault(int(r["year"]), {})[str(int(key))] = r["code"]
            except (TypeError, ValueError):
                continue
    return out


def _user_cells(db, user_id, today):
    out = {}
    for a in db.execute("SELECT id, year FROM agents WHERE agent_user_id=? AND year>=? AND year<=?", (user_id, today.year, today.year + 1)).fetchall():
        out[int(a["year"])] = {str(c["jour"]): c["code"] for c in db.execute("SELECT jour, code FROM cells WHERE agent_id=?", (a["id"],)).fetchall()}
    return out


def _delete_event(mailbox, event_id):
    try:
        _call("DELETE", "%s/%s" % (config.EXCHANGE_APM_EVENTS_PATH, event_id), params={"mailbox": mailbox})
    except ExchangeError as exc:
        if exc.status != 404:                  # déjà supprimé dans Outlook : rien à faire
            raise


def _remote_ids(mailbox, today):
    """Identifiants des événements présents dans l'agenda (fenêtre de synchronisation), ou None si l'API Ville ne sait pas les lister."""
    try:
        data = _call("GET", config.EXCHANGE_APM_EVENTS_PATH, params={"mailbox": mailbox, "start": "%d-01-01" % today.year, "end": "%d-12-31" % (today.year + 1)})
    except ExchangeError:
        return None                            # route de lecture absente (API Ville pas encore à jour) ou panne : on garde le suivi local
    return {e.get("id") for e in (data.get("events") or []) if e.get("id")}


def sync_user(db, user_id, today=None):
    """Aligne l'agenda Outlook de l'agent sur sa fiche. Retourne {"created", "deleted", "kept", "error"} ; l'état est mémorisé dans users."""
    today = today or dt.date.today()
    user = db.execute("SELECT id, email, exchange_sync FROM users WHERE id=?", (user_id,)).fetchone()
    stats = {"created": 0, "deleted": 0, "kept": 0, "error": ""}
    if not user or not user["exchange_sync"]:
        return stats
    mailbox = (user["email"] or "").strip()
    try:
        if not mailbox:
            raise ExchangeError("Aucune adresse e-mail sur votre compte : l'agenda Outlook ne peut pas être joint")
        ok, message = availability()
        if not ok:
            raise ExchangeError(message)
        want = desired_events(_user_cells(db, user_id, today), today, pending_by_year=_user_pending(db, user_id, today))
        have = {(r["day"], r["part"]): r for r in db.execute(
            "SELECT day, part, kind, event_id FROM exchange_events WHERE user_id=?", (user_id,)).fetchall()}
        for key, row in list(have.items()):
            if key[0] < dt.date(today.year, 1, 1).isoformat():   # année précédente : on le laisse dans l'agenda, on n'en suit plus
                db.execute("DELETE FROM exchange_events WHERE user_id=? AND day=? AND part=?", (user_id, key[0], key[1]))
                db.commit()
                del have[key]
        remote = _remote_ids(mailbox, today) if have else None
        if remote is not None:
            for key, row in list(have.items()):                  # supprimé à la main dans Outlook : on l'oublie, il sera recréé plus bas
                if row["event_id"] not in remote:
                    db.execute("DELETE FROM exchange_events WHERE user_id=? AND day=? AND part=?", (user_id, key[0], key[1]))
                    db.commit()
                    del have[key]
        for key, row in have.items():                            # supprimés ou modifiés (autre nature)
            if want.get(key) != row["kind"]:
                _delete_event(mailbox, row["event_id"])
                db.execute("DELETE FROM exchange_events WHERE user_id=? AND day=? AND part=?", (user_id, key[0], key[1]))
                db.commit()
                stats["deleted"] += 1
            else:
                stats["kept"] += 1
        for key, kind in sorted(want.items()):
            row = have.get(key)
            if row and row["kind"] == kind:
                continue
            created = _call("POST", config.EXCHANGE_APM_EVENTS_PATH, dict(event_payload(key[0], key[1], kind), mailbox=mailbox))
            db.execute("INSERT INTO exchange_events (user_id, day, part, kind, event_id) VALUES (?,?,?,?,?) "
                       "ON CONFLICT (user_id, day, part) DO UPDATE SET kind=excluded.kind, event_id=excluded.event_id",
                       (user_id, key[0], key[1], kind, created.get("id", "")))
            db.commit()                                          # chaque événement est mémorisé tout de suite : une panne n'en fait pas de doublon
            stats["created"] += 1
        db.execute("UPDATE users SET exchange_synced_at=?, exchange_error='' WHERE id=?", (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    except ExchangeError as exc:
        stats["error"] = str(exc)
        db.execute("UPDATE users SET exchange_error=? WHERE id=?", (str(exc)[:500], user_id))
    db.commit()
    return stats


def disable_user(db, user_id):
    """Désactive la synchronisation et retire de l'agenda les événements créés. Retourne le nombre d'événements supprimés."""
    user = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    mailbox = ((user["email"] if user else "") or "").strip()
    deleted, error = 0, ""
    for row in db.execute("SELECT day, part, event_id FROM exchange_events WHERE user_id=?", (user_id,)).fetchall():
        try:
            if mailbox:
                _delete_event(mailbox, row["event_id"])
            db.execute("DELETE FROM exchange_events WHERE user_id=? AND day=? AND part=?", (user_id, row["day"], row["part"]))
            db.commit()
            deleted += 1
        except ExchangeError as exc:
            error = str(exc)
            break
    if not error:
        db.execute("DELETE FROM exchange_events WHERE user_id=?", (user_id,))
    db.execute("UPDATE users SET exchange_sync=0, exchange_error=? WHERE id=?", (error[:500], user_id))
    db.commit()
    return deleted


def disable_user_async(user_id):
    """Retire en arrière-plan les événements de l'agenda (la case est déjà décochée côté base)."""
    with _running_lock:
        if user_id in _running:
            return False
        _running.add(user_id)

    def run():
        db = get_db()
        try:
            disable_user(db, user_id)
        except Exception as exc:  # noqa: BLE001
            try:
                db.execute("UPDATE users SET exchange_error=? WHERE id=?", (("Erreur inattendue : %s" % exc)[:500], user_id))
                db.commit()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()
            with _running_lock:
                _running.discard(user_id)

    threading.Thread(target=run, name="conges-exchange-off-%s" % user_id, daemon=True).start()
    return True


def status(db, user_id):
    row = db.execute("SELECT email, exchange_sync, exchange_synced_at, exchange_error FROM users WHERE id=?", (user_id,)).fetchone()
    n = db.execute("SELECT COUNT(*) AS n FROM exchange_events WHERE user_id=?", (user_id,)).fetchone()["n"]
    with _running_lock:
        busy = user_id in _running
    available, message = availability()
    return {"configured": available, "message": message, "enabled": bool(row and row["exchange_sync"]), "email": (row["email"] if row else "") or "",
            "synced_at": (row["exchange_synced_at"] if row else "") or "", "error": (row["exchange_error"] if row else "") or "",
            "events": int(n), "running": busy, "morning": config.EXCHANGE_MORNING, "afternoon": config.EXCHANGE_AFTERNOON}


def sync_user_async(user_id):
    """Lance la synchronisation en arrière-plan (elle peut durer plusieurs secondes) ; sans effet si elle est déjà en cours."""
    with _running_lock:
        if user_id in _running:
            return False
        _running.add(user_id)

    def run():
        db = get_db()
        try:
            sync_user(db, user_id)
        except Exception as exc:  # noqa: BLE001 — ne doit pas faire tomber l'application
            try:
                db.execute("UPDATE users SET exchange_error=? WHERE id=?", (("Erreur inattendue : %s" % exc)[:500], user_id))
                db.commit()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()
            with _running_lock:
                _running.discard(user_id)

    threading.Thread(target=run, name="conges-exchange-%s" % user_id, daemon=True).start()
    return True


def start_exchange_scheduler():
    """Synchronise périodiquement les agents qui l'ont demandée (les écarts de la fiche passent ainsi dans l'agenda)."""
    if config.DISABLE_REMINDERS or not configured():
        return None

    def run():
        while True:
            try:
                db = get_db()
                try:
                    ids = [r["id"] for r in db.execute("SELECT id FROM users WHERE exchange_sync=1 AND actif=1").fetchall()]
                finally:
                    db.close()
                if ids and availability()[0]:
                    for uid in ids:
                        sync_user_async(uid)
                        time.sleep(1)
            except Exception as exc:  # noqa: BLE001
                print("[exchange] synchronisation automatique impossible : %s" % exc)
            time.sleep(max(120, config.EXCHANGE_INTERVAL_MIN * 60))

    thread = threading.Thread(target=run, name="conges-exchange", daemon=True)
    thread.start()
    print("[exchange] planificateur de synchronisation démarré")
    return thread
