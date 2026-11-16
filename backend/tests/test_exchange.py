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


class GraphClientTest(unittest.TestCase):
    def setUp(self):
        exchange._token_cache.update(value="", until=0.0)
        self._saved = (config.GRAPH_TENANT_ID, config.GRAPH_CLIENT_ID, config.GRAPH_CLIENT_SECRET)
        config.GRAPH_TENANT_ID, config.GRAPH_CLIENT_ID, config.GRAPH_CLIENT_SECRET = "tenant-x", "client-x", "SECRET-JAMAIS-AFFICHE"

    def tearDown(self):
        config.GRAPH_TENANT_ID, config.GRAPH_CLIENT_ID, config.GRAPH_CLIENT_SECRET = self._saved
        exchange._token_cache.update(value="", until=0.0)

    def test_jeton_client_credentials_mis_en_cache(self):
        with mock.patch.object(exchange.requests, "post", return_value=_Resp(200, {"access_token": "JETON", "expires_in": 3600})) as post:
            self.assertEqual(exchange._token(), "JETON")
            self.assertEqual(exchange._token(), "JETON")
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args[0][0].endswith("/tenant-x/oauth2/v2.0/token"))
        self.assertEqual(post.call_args[1]["data"]["grant_type"], "client_credentials")
        self.assertEqual(post.call_args[1]["data"]["scope"], "https://graph.microsoft.com/.default")

    def test_refus_d_authentification_sans_fuite_du_secret(self):
        with mock.patch.object(exchange.requests, "post", return_value=_Resp(401, {"error": "invalid_client"})):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                exchange._token()
        self.assertNotIn("SECRET-JAMAIS-AFFICHE", str(ctx.exception))

    def test_graph_patiente_sur_429_puis_reussit_et_signale_les_refus(self):
        exchange._token_cache.update(value="JETON", until=time.monotonic() + 600)
        with mock.patch.object(exchange.time, "sleep") as sleep, \
                mock.patch.object(exchange.requests, "request", side_effect=[_Resp(429, headers={"Retry-After": "3"}), _Resp(201, {"id": "EV1"})]) as req:
            self.assertEqual(exchange._graph("POST", "/users/a@b.fr/events", {"subject": "ABSENT"}), {"id": "EV1"})
        self.assertEqual(req.call_count, 2)
        self.assertEqual(sleep.call_args[0][0], 3.0)
        self.assertEqual(req.call_args[1]["headers"]["Authorization"], "Bearer JETON")
        with mock.patch.object(exchange.requests, "request", return_value=_Resp(403, {"error": {"message": "Access is denied"}})):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                exchange._graph("GET", "/users/a@b.fr/events")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("Access is denied", str(ctx.exception))
        with mock.patch.object(exchange.requests, "request", return_value=_Resp(204)):
            self.assertEqual(exchange._graph("DELETE", "/users/a@b.fr/events/EV1"), {})


if __name__ == "__main__":
    unittest.main()
