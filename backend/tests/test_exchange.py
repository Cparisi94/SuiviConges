# -*- coding: utf-8 -*-
"""Module « exchange » : événements souhaités à partir des cases, corps des requêtes Graph (sans base de données)."""
import datetime as dt
import time
import unittest
from unittest import mock

import config
import exchange

TODAY = dt.date(2026, 11, 16)                     # un lundi
CODES = {"CA", "RTT", "CM", "TP"}


def key(month, day, half):
    return month * 1000 + day * 10 + half


class DesiredEventsTest(unittest.TestCase):
    def test_journee_demi_journee_teletravail_et_codes_ignores(self):
        cells = {
            str(key(11, 16, 0)): "CA", str(key(11, 16, 1)): "CA",           # journée complète d'absence
            str(key(11, 17, 0)): "RTT",                                     # matin seulement
            str(key(11, 18, 1)): "CM",                                      # après-midi seulement
            str(key(11, 19, 0)): "TT", str(key(11, 19, 1)): "TT",           # télétravail toute la journée
            str(key(11, 20, 0)): "CA", str(key(11, 20, 1)): "TT",           # matin absent, après-midi télétravail
            str(key(11, 23, 0)): "F", str(key(11, 23, 1)): "F",             # férié : ni absence ni télétravail
            str(key(11, 24, 0)): "CA", str(key(11, 24, 1)): "RTT",          # deux absences différentes : une seule journée ABSENT
            str(key(11, 25, 0)): "",                                        # case vide
        }
        out = exchange.desired_events({2026: cells}, TODAY, absence_codes=CODES)
        self.assertEqual(out, {
            ("2026-11-16", "J"): "ABSENT",
            ("2026-11-17", "M"): "ABSENT",
            ("2026-11-18", "A"): "ABSENT",
            ("2026-11-19", "J"): "TT",
            ("2026-11-20", "M"): "ABSENT", ("2026-11-20", "A"): "TT",
            ("2026-11-24", "J"): "ABSENT",
        })

    def test_fenetre_aujourd_hui_fin_de_l_annee_suivante(self):
        cells26 = {str(key(11, 13, 0)): "CA", str(key(11, 13, 1)): "CA", str(key(12, 1, 0)): "CA", str(key(12, 1, 1)): "CA"}
        cells27 = {str(key(12, 31, 0)): "CA", str(key(12, 31, 1)): "CA"}
        cells28 = {str(key(1, 5, 0)): "CA", str(key(1, 5, 1)): "CA"}
        out = exchange.desired_events({2026: cells26, 2027: cells27, 2028: cells28}, TODAY, absence_codes=CODES)
        self.assertEqual(sorted(out), [("2026-12-01", "J"), ("2027-12-31", "J")])           # le passé et au-delà de fin 2027 sont ignorés

    def test_cle_invalide_ignoree(self):
        out = exchange.desired_events({2026: {"abc": "CA", "13370": "CA", str(key(11, 18, 5)): "CA"}}, TODAY, absence_codes=CODES)
        self.assertEqual(out, {})


class PayloadTest(unittest.TestCase):
    def test_absent_toute_la_journee(self):
        p = exchange.event_payload("2026-11-16", "J", "ABSENT")
        self.assertEqual(p["subject"], "ABSENT")                                           # uniquement ce texte
        self.assertEqual((p["showAs"], p["isAllDay"], p["sensitivity"], p["isReminderOn"]), ("oof", True, "private", False))
        self.assertEqual((p["start"]["dateTime"], p["end"]["dateTime"]), ("2026-11-16T00:00:00", "2026-11-17T00:00:00"))
        self.assertEqual(p["start"]["timeZone"], config.EXCHANGE_TIMEZONE)
        self.assertEqual(sorted(p), sorted(["subject", "showAs", "isReminderOn", "sensitivity", "isAllDay", "start", "end"]))   # ni corps, ni lieu, ni participants

    def test_demi_journees(self):
        m = exchange.event_payload("2026-11-16", "M", "ABSENT")
        a = exchange.event_payload("2026-11-16", "A", "ABSENT")
        self.assertFalse(m["isAllDay"])
        self.assertEqual((m["start"]["dateTime"], m["end"]["dateTime"]), ("2026-11-16T08:30:00", "2026-11-16T12:30:00"))
        self.assertEqual((a["start"]["dateTime"], a["end"]["dateTime"]), ("2026-11-16T13:30:00", "2026-11-16T17:30:00"))

    def test_teletravail_travaille_ailleurs(self):
        p = exchange.event_payload("2026-11-19", "J", "TT")
        self.assertEqual((p["showAs"], p["subject"], p["isAllDay"]), ("workingElsewhere", "Télétravail", True))


class _Resp:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data if data is not None else {}, headers or {}

    def json(self):
        return self._data


class ApmCalendarClientTest(unittest.TestCase):
    def setUp(self):
        self._saved = (config.APM_API_URL, config.APM_API_KEY, config.EXCHANGE_APM_EVENTS_PATH)
        config.APM_API_URL, config.APM_API_KEY, config.EXCHANGE_APM_EVENTS_PATH = "https://api.ville.test", "CLE-JAMAIS-AFFICHEE", "/api/v1/o365/calendar/events"
        exchange._avail.update(at=0.0, ok=False, message="")

    def tearDown(self):
        config.APM_API_URL, config.APM_API_KEY, config.EXCHANGE_APM_EVENTS_PATH = self._saved
        exchange._avail.update(at=0.0, ok=False, message="")

    def test_la_route_d_agenda_est_detectee_dans_la_documentation(self):
        doc = {"paths": {"/api/v1/o365/messages/{id}": {}, "/api/v1/o365/calendar/events": {}, "/api/v1/o365/calendar/events/{id}": {}}}
        with mock.patch.object(exchange.requests, "get", return_value=_Resp(200, doc)) as get:
            self.assertEqual(exchange.availability(), (True, ""))
            self.assertEqual(exchange.availability(), (True, ""))                                   # second appel : mémoire
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args[0][0], "https://api.ville.test/swagger.json")
        self.assertEqual(get.call_args[1]["headers"], {"X-API-KEY": "CLE-JAMAIS-AFFICHEE"})

    def test_route_absente_message_clair_et_rien_n_est_envoye(self):
        doc = {"paths": {"/api/v1/o365/messages/{id}": {}, "/api/v1/mail/send": {}}}
        with mock.patch.object(exchange.requests, "get", return_value=_Resp(200, doc)):
            ok, message = exchange.availability(force=True)
        self.assertFalse(ok)
        self.assertIn("/api/v1/o365/calendar/events", message)
        self.assertIn("pas encore", message)

    def test_api_ville_injoignable_ou_non_configuree(self):
        with mock.patch.object(exchange.requests, "get", side_effect=exchange.requests.ConnectionError("x")):
            self.assertFalse(exchange.availability(force=True)[0])
        config.APM_API_KEY = ""
        self.assertIn("APM_API_KEY", exchange.availability(force=True)[1])

    def test_appel_patiente_sur_429_envoie_la_cle_et_signale_les_refus_sans_la_divulguer(self):
        with mock.patch.object(exchange.time, "sleep") as sleep,                 mock.patch.object(exchange.requests, "request", side_effect=[_Resp(429, headers={"Retry-After": "3"}), _Resp(201, {"id": "EV1"})]) as req:
            self.assertEqual(exchange._call("POST", "/api/v1/o365/calendar/events", {"subject": "ABSENT"}), {"id": "EV1"})
        self.assertEqual(req.call_count, 2)
        self.assertEqual(sleep.call_args[0][0], 3.0)
        self.assertEqual(req.call_args[1]["headers"], {"X-API-KEY": "CLE-JAMAIS-AFFICHEE"})
        self.assertEqual(req.call_args[0][1], "https://api.ville.test/api/v1/o365/calendar/events")
        with mock.patch.object(exchange.requests, "request", return_value=_Resp(403, {"error": "Droit manquant"})):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                exchange._call("GET", "/api/v1/o365/calendar/events")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("Droit manquant", str(ctx.exception))
        self.assertNotIn("CLE-JAMAIS-AFFICHEE", str(ctx.exception))
        with mock.patch.object(exchange.requests, "request", return_value=_Resp(204)):
            self.assertEqual(exchange._call("DELETE", "/api/v1/o365/calendar/events/EV1", params={"mailbox": "a@b.fr"}), {})


if __name__ == "__main__":
    unittest.main()
