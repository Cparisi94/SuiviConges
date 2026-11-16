# -*- coding: utf-8 -*-
"""Tests de non-regression du prototype Suivi des conges.

Lancement :
    python -m unittest discover -s tests -v
"""
import contextlib
import json
import unittest
import uuid
from unittest import mock

import config

# Schéma PostgreSQL temporaire, créé puis supprimé par la classe de test : la base
# réelle de l'application n'est jamais touchée.
config.PG_SCHEMA = "conges_test_" + uuid.uuid4().hex[:8]

import apm  # noqa: E402
import audit_logs  # noqa: E402
import db  # noqa: E402
import mail_templates  # noqa: E402
import mailer  # noqa: E402
import pg_db  # noqa: E402
import ratelimit  # noqa: E402
import rh_import  # noqa: E402
import sedit_rh  # noqa: E402


class PrototypeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg_db.reset_pool()
        db.init_db()
        conn = db.get_db()
        users = [
            (1, "admin", "Administrateur", "administrateur", None, 1),
            (2, "DRH", "Direction RH", "direction", 1, 0),
            (3, "SECT1", "Secteur 1", "secteur", 2, 0),
            (4, "AGENT1", "Agent Un", "agent", 3, 0),
            (5, "AGENT2", "Agent Deux", "agent", 3, 0),
        ]
        for uid, login, nom, role, parent, admin in users:
            conn.execute(
                "INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (uid, login, nom, "x", admin, role, parent),
            )
        conn.execute(
            "INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
            "VALUES (1, 3, 4, 'AGENT', 'UN', 'agent@example.fr', 3, 2026, '{}', '[]')"
        )
        for table in ("users", "agents"):
            conn.execute("ALTER TABLE %s ALTER COLUMN id RESTART WITH 1000" % table)
        conn.commit()
        conn.close()

        import app as application
        application.app.config["TESTING"] = True
        cls.app_module = application
        cls.client = application.app.test_client()

    @classmethod
    def tearDownClass(cls):
        pg_db.drop_schema()

    def setUp(self):
        ratelimit.reset()

    def _call(self, method, path, uid=1, payload=None):
        with self.client.session_transaction() as sess:
            sess["uid"] = uid
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return self.client.open(
            path,
            method=method,
            headers=headers,
            data=json.dumps(payload) if payload is not None else None,
        )

    def test_users_sorted_by_validation_level_then_login(self):
        response = self._call("GET", "/api/users")
        self.assertEqual(response.status_code, 200)
        users = response.get_json()
        roles = [u["role"] for u in users]
        levels = {
            "administrateur": 8, "dgs": 7, "dga": 6, "direction": 5,
            "service": 4, "secteur": 3, "unite": 2, "equipe": 1, "agent": 0,
        }
        self.assertEqual(roles, sorted(roles, key=lambda r: -levels.get(r, 0)))
        for role in ("agent",):
            logins = [u["login"] for u in users if u["role"] == role]
            self.assertEqual(logins, sorted(logins))

    def test_account_audit_on_update(self):
        response = self._call("PUT", "/api/users/5", payload={"actif": False, "login": "AGENT2BIS"})
        self.assertEqual(response.status_code, 200)
        response = self._call("GET", "/api/users/audit")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        fields = {row["field"] for row in rows if row["target_login"] == "AGENT2BIS"}
        self.assertIn("activation", fields)
        self.assertIn("login", fields)

    def test_hourly_delete_is_reserved_to_validators(self):
        conn = db.get_db()
        cur = conn.execute(
            "INSERT INTO hourly_absences (agent_id, code, absence_date, start_time, end_time, hours, request_id, year) "
            "VALUES (1, 'CAH', '2026-11-12', '09:00', '10:00', 1, NULL, 2026)"
        )
        hourly_id = cur.lastrowid
        conn.commit()
        conn.close()
        denied = self._call("DELETE", f"/api/hourly/{hourly_id}", uid=4)
        self.assertEqual(denied.status_code, 403)
        allowed = self._call("DELETE", f"/api/hourly/{hourly_id}", uid=2)
        self.assertEqual(allowed.status_code, 200)

    def test_rch_counter_fifo_and_expiry(self):
        from rules import _hour_counter
        recoveries = [
            {"id": 1, "code": "RCH", "hours": 4, "absence_date": "2026-05-01", "valid_until": "2026-11-01"},
            {"id": 2, "code": "RCH", "hours": 6, "absence_date": "2026-10-01", "valid_until": "2027-04-01"},
        ]
        hourly = [
            {"code": "RCH", "absence_date": "2026-06-01", "hours": 3},
        ]
        result = _hour_counter([], hourly, "RCH", "RCH", 2026, "2026-11-10", recoveries=recoveries)
        self.assertEqual(result["credit"], 10.0)
        self.assertEqual(result["used_total"], 3.0)
        self.assertEqual(result["restant"], 6.0)
        self.assertEqual(result["next_expiry"], "2027-04-01")

    def test_absence_codes_for_hr_dashboard(self):
        from app import ABSENCE_CODES
        self.assertIn("CAH", ABSENCE_CODES)
        self.assertIn("RTT", ABSENCE_CODES)
        self.assertNotIn("TT", ABSENCE_CODES)
        self.assertNotIn("RC", ABSENCE_CODES)


    # --- Authentification (local / Active Directory via l'APM) et mails ----------------- #
    def _make_user(self, login, password="secret123", ad_login="", admin=0):
        from werkzeug.security import generate_password_hash
        conn = db.get_db()
        conn.execute(
            "INSERT INTO users (login, ad_login, nom, mot_de_passe, admin, role, parent_id, actif) "
            "VALUES (?,?,?,?,?,?,?,1) ON CONFLICT (login) DO NOTHING",
            (login, ad_login, login, generate_password_hash(password), admin,
             "administrateur" if admin else "secteur", None if admin else 2),
        )
        conn.commit()
        conn.close()

    def _login(self, login, password):
        return self.client.post("/api/auth/login", json={"login": login, "password": password})

    def test_login_local_mode(self):
        self._make_user("LOC1")
        with mock.patch.object(config, "AUTH_MODE", "local"):
            self.assertEqual(self._login("LOC1", "secret123").status_code, 200)
            self.assertEqual(self._login("LOC1", "mauvais").status_code, 401)
            self.assertEqual(self._login("INCONNU", "x").status_code, 401)

    def test_login_ad_mode_uses_ad_login_and_ignores_local_password(self):
        self._make_user("AD1", ad_login="prenom.nom")
        calls = []

        def fake_auth(username, password):
            calls.append(username)
            return password == "mdp-ad"

        with mock.patch.object(config, "AUTH_MODE", "ad"), \
                mock.patch.object(apm, "ad_authenticate", fake_auth):
            self.assertEqual(self._login("AD1", "mdp-ad").status_code, 200)
            self.assertEqual(calls[-1], "prenom.nom")
            self.assertEqual(self._login("AD1", "secret123").status_code, 401)  # mot de passe local refusé

    def test_login_ad_mode_service_down_and_admin_fallback(self):
        self._make_user("AD2")
        self._make_user("ADM2", admin=1)

        def down(username, password):
            raise apm.ApmError("APM injoignable")

        with mock.patch.object(config, "AUTH_MODE", "ad"), \
                mock.patch.object(apm, "ad_authenticate", down):
            self.assertEqual(self._login("AD2", "x").status_code, 503)
            self.assertEqual(self._login("ADM2", "secret123").status_code, 200)  # compte de secours

    def test_password_change_refused_for_ad_accounts(self):
        self._make_user("AD3")
        uid = db.get_db().execute("SELECT id FROM users WHERE login='AD3'").fetchone()["id"]
        payload = {"current_password": "secret123", "new_password": "nouveau-mdp-1",
                   "confirm_password": "nouveau-mdp-1"}
        with mock.patch.object(config, "AUTH_MODE", "ad"):
            self.assertEqual(self._call("POST", "/api/me/password", uid=uid, payload=payload).status_code, 400)
        with mock.patch.object(config, "AUTH_MODE", "local"):
            self.assertEqual(self._call("POST", "/api/me/password", uid=uid, payload=payload).status_code, 200)

    def test_mail_sent_through_apm_with_footer(self):
        sent = {}

        def fake_post(url, json=None, headers=None, timeout=None, verify=None):
            sent.update(url=url, body=json, headers=headers)
            return mock.Mock(status_code=200, json=lambda: {"status": "success"})

        with self._enabled(True), \
                mock.patch.object(config, "APM_API_URL", "https://apm.test"), \
                mock.patch.object(config, "APM_API_KEY", "cle-de-test"), \
                mock.patch.object(apm.requests, "post", fake_post):
            ok, error = mailer.send_mail("agent@example.fr", "Sujet", "Bonjour <b>\nhttp://x.fr/a")
        self.assertTrue(ok, error)
        self.assertEqual(sent["url"], "https://apm.test/api/v1/mail/send")
        self.assertEqual(sent["headers"], {"X-API-KEY": "cle-de-test"})
        self.assertEqual(sent["body"]["to"], "agent@example.fr")
        self.assertIn("&lt;b&gt;", sent["body"]["content"])  # contenu échappé
        self.assertIn('<a href="http://x.fr/a">', sent["body"]["content"])
        self.assertEqual(sent["body"]["footer1"], config.MAIL_FOOTER1)
        self.assertEqual(sent["body"]["footerColor"], config.MAIL_FOOTER_COLOR)

    def test_mail_disabled_or_apm_down_never_raises(self):
        with self._enabled(False):
            self.assertFalse(mailer.send_mail("a@b.fr", "s", "c")[0])
        with self._enabled(True), \
                mock.patch.object(config, "APM_API_URL", "https://apm.test"), \
                mock.patch.object(config, "APM_API_KEY", "k"), \
                mock.patch.object(apm.requests, "post", side_effect=apm.requests.ConnectionError("x")):
            ok, error = mailer.send_mail("a@b.fr", "s", "c")
        self.assertFalse(ok)
        self.assertIn("APM", error)


    # --- API /api/v1 : clés API, périmètres, pagination, limites ----------------------- #
    def _new_key(self, name="App test", scopes=("agents:read",), **extra):
        payload = {"name": name, "scopes": list(scopes), **extra}
        resp = self._call("POST", "/api/v1/admin/api-keys", uid=1, payload=payload)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        return resp.get_json()

    def _get_v1(self, path, key):
        return self.client.get(path, headers={"X-API-Key": key})

    def test_status_is_public_and_minimal(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"]["state"], "ok")
        self.assertIn(body["sedit_rh"], ("configured", "not_configured"))
        self.assertNotIn("password", json.dumps(body).lower())

    def test_api_requires_a_valid_key(self):
        self.assertEqual(self.client.get("/api/v1/agents").status_code, 401)
        self.assertEqual(self._get_v1("/api/v1/agents", "cgk_" + "0" * 64).status_code, 401)
        self.assertEqual(self._get_v1("/api/v1/agents", "nimporte").status_code, 401)

    def test_key_admin_is_reserved_to_administrators_and_never_stores_plain_key(self):
        denied = self._call("GET", "/api/v1/admin/api-keys", uid=2)
        self.assertEqual(denied.status_code, 403)
        created = self._new_key("App secret")
        self.assertTrue(created["key"].startswith("cgk_"))
        listing = self._call("GET", "/api/v1/admin/api-keys", uid=1).get_json()
        self.assertNotIn(created["key"], json.dumps(listing))
        self.assertNotIn("key_hash", json.dumps(listing))
        stored = db.get_db().execute(
            "SELECT key_hash FROM api_keys WHERE id=?", (created["id"],)).fetchone()["key_hash"]
        self.assertNotEqual(stored, created["key"])

    def test_key_scopes_and_pagination(self):
        key = self._new_key("Lecteur fiches", scopes=("agents:read",))["key"]
        resp = self._get_v1("/api/v1/agents?year=2026&limit=1&offset=0", key)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual((body["limit"], body["offset"]), (1, 0))
        self.assertGreaterEqual(body["total"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["nom"], "AGENT")
        self.assertNotIn("params", body["items"][0])  # pas de données RH détaillées dans la liste
        self.assertEqual(self._get_v1("/api/v1/agents/1/balance", key).status_code, 403)
        self.assertEqual(self._get_v1("/api/v1/requests", key).status_code, 403)

    def test_revoked_expired_and_ip_restricted_keys_are_refused(self):
        revoked = self._new_key("A révoquer")
        self._call("PUT", "/api/v1/admin/api-keys/%s" % revoked["id"], uid=1, payload={"actif": False})
        self.assertEqual(self._get_v1("/api/v1/agents", revoked["key"]).status_code, 401)
        expired = self._new_key("Expirée", expires_at="2020-01-01")
        self.assertEqual(self._get_v1("/api/v1/agents", expired["key"]).status_code, 401)
        outside = self._new_key("Autre réseau", allowed_ips="10.1.2.0/24")
        self.assertEqual(self._get_v1("/api/v1/agents", outside["key"]).status_code, 403)
        inside = self._new_key("Réseau local", allowed_ips="127.0.0.1")
        self.assertEqual(self._get_v1("/api/v1/agents", inside["key"]).status_code, 200)

    def test_invalid_key_settings_are_rejected(self):
        for payload in ({"name": "x", "scopes": ["inconnu:read"]}, {"name": "x", "scopes": []},
                        {"name": "x", "scopes": ["agents:read"], "allowed_ips": "pas-une-ip"},
                        {"name": "x", "scopes": ["agents:read"], "expires_at": "demain"},
                        {"name": "", "scopes": ["agents:read"]}):
            resp = self._call("POST", "/api/v1/admin/api-keys", uid=1, payload=payload)
            self.assertEqual(resp.status_code, 400, payload)

    def test_absences_dates_and_requests_and_balance(self):
        conn = db.get_db()
        conn.execute("INSERT INTO cells (agent_id, jour, code) VALUES (1, 1010, 'CA') "
                     "ON CONFLICT (agent_id, jour) DO NOTHING")
        conn.execute("INSERT INTO cells (agent_id, jour, code) VALUES (1, 1011, 'CA') "
                     "ON CONFLICT (agent_id, jour) DO NOTHING")
        conn.commit()
        conn.close()
        key = self._new_key("Tout", scopes=("absences:read", "requests:read", "balances:read"))["key"]
        absences = self._get_v1("/api/v1/absences?year=2026&agent_id=1", key).get_json()
        self.assertEqual([(i["date"], i["half"]) for i in absences["items"]],
                         [("2026-01-01", "matin"), ("2026-01-01", "apres_midi")])
        none = self._get_v1("/api/v1/absences?year=2026&from=2026-02-01", key).get_json()
        self.assertEqual(none["total"], 0)
        self.assertEqual(self._get_v1("/api/v1/absences?from=pas-une-date", key).status_code, 400)
        self.assertEqual(self._get_v1("/api/v1/requests?year=2026", key).status_code, 200)
        self.assertIn(self._get_v1("/api/v1/agents/1/balance", key).status_code, (200, 422))
        self.assertEqual(self._get_v1("/api/v1/agents/9999/balance", key).status_code, 404)

    def test_calls_are_logged_and_rate_limited(self):
        created = self._new_key("Limitée")
        with mock.patch.object(config, "API_RATE_LIMIT", 2):
            codes = [self._get_v1("/api/v1/agents", created["key"]).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        logs = self._call("GET", "/api/v1/admin/api-keys/%s/logs" % created["id"], uid=1).get_json()
        self.assertEqual(logs["total"], 2)
        self.assertEqual(logs["items"][0]["path"], "/api/v1/agents")

    def test_login_is_throttled_after_repeated_failures(self):
        self._make_user("THR1")
        with mock.patch.object(config, "LOGIN_MAX_FAILURES", 3), mock.patch.object(config, "AUTH_MODE", "local"):
            codes = [self._login("THR1", "faux").status_code for _ in range(3)]
            blocked = self._login("THR1", "secret123").status_code
        self.assertEqual(codes, [401, 401, 401])
        self.assertEqual(blocked, 429)

    def test_cors_only_for_listed_origins(self):
        with mock.patch.object(config, "CORS_ORIGINS", ["https://conges.example.fr"]):
            ok = self.client.get("/api/status", headers={"Origin": "https://conges.example.fr"})
            other = self.client.get("/api/status", headers={"Origin": "https://evil.example"})
        self.assertEqual(ok.headers.get("Access-Control-Allow-Origin"), "https://conges.example.fr")
        self.assertIsNone(other.headers.get("Access-Control-Allow-Origin"))

    def test_openapi_documents_every_v1_route(self):
        spec = self.client.get("/api/v1/openapi.json").get_json()
        documented = set(spec["paths"])
        for rule in self.app_module.app.url_map.iter_rules():
            path = rule.rule
            if path.startswith("/api/v1/") and "/admin/" not in path and path != "/api/v1/openapi.json" \
                    and path != "/api/v1/status":
                self.assertIn(path.replace("<int:agent_id>", "{agent_id}"), documented, path)
        self.assertEqual(self.client.get("/api-docs/", follow_redirects=True).status_code, 200)


    # --- « Se connecter en tant que » ------------------------------------------------------ #
    def _admin_client(self, uid=1):
        client = self.app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = uid
        return client

    def test_act_as_search_maps_ad_hits_to_accounts_and_flags_unusable_ones(self):
        self._make_user("ACT_AGENT", ad_login="jean.martin")
        hits = [{"username": "jean.martin", "displayName": "MARTIN Jean", "email": "j@x.fr"},
                {"username": "inconnu.ad", "displayName": "INCONNU AD", "email": ""},
                {"username": "admin", "displayName": "Admin AD", "email": ""}]
        with mock.patch.object(apm, "configured", return_value=True), \
                mock.patch.object(apm, "ad_search", return_value=hits):
            items = self._admin_client().get("/api/admin/act-as/search?q=mar").get_json()["items"]
        by_user = {i["username"]: i for i in items}
        self.assertTrue(by_user["jean.martin"]["selectable"])
        self.assertEqual(by_user["jean.martin"]["account"]["login"], "ACT_AGENT")
        self.assertFalse(by_user["inconnu.ad"]["selectable"])      # pas de compte dans l'application
        self.assertFalse(by_user["admin"]["selectable"])           # administrateur : interdit
        self.assertEqual(self._admin_client(2).get("/api/admin/act-as/search?q=mar").status_code, 403)

    def test_act_as_search_falls_back_to_local_accounts_when_ad_is_down(self):
        self._make_user("ACT_LOCAL")
        with mock.patch.object(apm, "configured", return_value=True), \
                mock.patch.object(apm, "ad_search", side_effect=apm.ApmError("down")):
            body = self._admin_client().get("/api/admin/act-as/search?q=ACT_LOC").get_json()
        self.assertTrue(body["ad_error"])
        self.assertIn("ACT_LOCAL", [i["account"]["login"] for i in body["items"]])

    def test_act_as_switches_identity_audits_real_actor_and_can_return(self):
        self._make_user("ACT_T1")
        conn = db.get_db()
        target_id = conn.execute("SELECT id FROM users WHERE login='ACT_T1'").fetchone()["id"]
        conn.close()
        c = self._admin_client()
        self.assertEqual(c.post("/api/admin/act-as", json={"user_id": target_id}).status_code, 200)
        me = c.get("/api/me").get_json()["user"]
        self.assertEqual(me["login"], "ACT_T1")
        self.assertEqual(me["impersonation"]["by"]["login"], "admin")
        # droits exacts du compte usurpé : pas d'administration, pas de nouvelle usurpation
        self.assertEqual(c.get("/api/v1/admin/api-keys").status_code, 403)
        self.assertEqual(c.post("/api/admin/act-as", json={"user_id": 4}).status_code, 403)
        # pas de changement du mot de passe du compte usurpé
        resp = c.post("/api/me/password", json={"current_password": "secret123",
                      "new_password": "nouveau-mdp-1", "confirm_password": "nouveau-mdp-1"})
        self.assertEqual(resp.status_code, 403)
        # le journal garde l'administrateur comme acteur
        conn = db.get_db()
        start = conn.execute("SELECT actor_login, target_login FROM user_audit WHERE action='usurpation' "
                             "AND field='début' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual((start["actor_login"], start["target_login"]), ("admin", "ACT_T1"))
        self.assertEqual(c.delete("/api/admin/act-as").status_code, 200)
        self.assertNotIn("impersonation", c.get("/api/me").get_json()["user"])
        self.assertEqual(c.get("/api/me").get_json()["user"]["login"], "admin")
        conn = db.get_db()
        ended = conn.execute("SELECT COUNT(*) AS c FROM user_audit WHERE action='usurpation' AND field='fin'").fetchone()
        conn.close()
        self.assertGreaterEqual(ended["c"], 1)

    def test_act_as_refuses_admin_self_inactive_and_non_admin_callers(self):
        self._make_user("ACT_ADM2", admin=1)
        conn = db.get_db()
        conn.execute("INSERT INTO users (login, nom, mot_de_passe, admin, role, actif) "
                     "VALUES ('ACT_OFF','Off','x',0,'agent',0) ON CONFLICT (login) DO NOTHING")
        conn.commit()
        ids = {r["login"]: r["id"] for r in conn.execute(
            "SELECT id, login FROM users WHERE login IN ('ACT_ADM2','ACT_OFF')").fetchall()}
        conn.close()
        c = self._admin_client()
        for target in (ids["ACT_ADM2"], ids["ACT_OFF"], 1, 999999):
            self.assertIn(c.post("/api/admin/act-as", json={"user_id": target}).status_code, (403, 404), target)
        self.assertEqual(self._admin_client(4).post("/api/admin/act-as", json={"user_id": 5}).status_code, 403)

    def test_logout_ends_an_impersonation_and_actions_are_attributed_to_the_admin(self):
        self._make_user("ACT_T2")
        conn = db.get_db()
        target_id = conn.execute("SELECT id FROM users WHERE login='ACT_T2'").fetchone()["id"]
        conn.close()
        c = self._admin_client()
        c.post("/api/admin/act-as", json={"user_id": target_id})
        c.post("/api/auth/logout")
        self.assertEqual(c.get("/api/me").status_code, 401)
        conn = db.get_db()
        ended = conn.execute("SELECT actor_login FROM user_audit WHERE action='usurpation' AND field='fin' "
                             "AND target_login='ACT_T2'").fetchone()
        conn.close()
        self.assertEqual(ended["actor_login"], "admin")


    # --- Journal des connexions, e-mails (gabarits, journal), matricule -------------------- #
    @staticmethod
    @contextlib.contextmanager
    def _enabled(value):
        """Active ou désactive l'envoi des e-mails (réglage de l'administrateur) le temps d'un bloc."""
        before = mail_templates.is_enabled()
        mail_templates.save({"enabled": value})
        try:
            yield
        finally:
            mail_templates.save({"enabled": before})

    def _mail_on(self):
        return [self._enabled(True),
                mock.patch.object(config, "APM_API_URL", "https://apm.test"),
                mock.patch.object(config, "APM_API_KEY", "cle-test")]

    def _fake_post(self, sent):
        def fake(url, json=None, headers=None, timeout=None, verify=None):
            sent.append(json)
            return mock.Mock(status_code=200, json=lambda: {"status": "success"})
        return mock.patch.object(apm.requests, "post", fake)

    def test_login_journal_records_success_failure_and_is_admin_only(self):
        self._make_user("JRN1")
        with mock.patch.object(config, "AUTH_MODE", "local"):
            self.assertEqual(self._login("JRN1", "secret123").status_code, 200)
            self.assertEqual(self._login("JRN1", "faux").status_code, 401)
            self.assertEqual(self._login("INCONNU-JRN", "x").status_code, 401)
        body = self._call("GET", "/api/admin/login-logs?q=JRN1", uid=1).get_json()
        events = [(i["event"], i["success"], i["reason"], i["method"]) for i in body["items"]]
        self.assertIn(("connexion", 1, "", "local"), events)
        self.assertIn(("echec", 0, "mot_de_passe", "local"), events)
        self.assertTrue(all(i["ip"] for i in body["items"]))
        unknown = self._call("GET", "/api/admin/login-logs?q=INCONNU-JRN", uid=1).get_json()
        self.assertEqual(unknown["items"][0]["reason"], "inconnu")
        only_ok = self._call("GET", "/api/admin/login-logs?q=JRN1&success=1", uid=1).get_json()
        self.assertTrue(all(i["success"] == 1 for i in only_ok["items"]))
        self.assertEqual(self._call("GET", "/api/admin/login-logs", uid=2).status_code, 403)
        self.assertEqual(self._call("GET", "/api/admin/login-logs?from=pas-une-date", uid=1).status_code, 400)

    def test_ad_login_and_act_as_are_journaled_with_method(self):
        self._make_user("JRN2", ad_login="jrn.deux")
        with mock.patch.object(config, "AUTH_MODE", "ad"), mock.patch.object(apm, "ad_authenticate", lambda u, p: p == "mdp"):
            self.assertEqual(self._login("JRN2", "mdp").status_code, 200)
        body = self._call("GET", "/api/admin/login-logs?q=JRN2", uid=1).get_json()
        self.assertEqual(body["items"][0]["method"], "ad")

    def test_mail_journal_and_templates(self):
        sent = []
        patches = self._mail_on()
        with patches[0], patches[1], patches[2], self._fake_post(sent):
            ok, err = mailer.send_template("test_envoi", "agent@example.fr", {"administrateur": "Admin", "date": "01/01/2027"})
        self.assertTrue(ok, err)
        self.assertEqual(sent[0]["to"], "agent@example.fr")
        self.assertIn("Admin", sent[0]["content"])
        log = self._call("GET", "/api/admin/mail-logs?q=agent@example.fr", uid=1).get_json()
        self.assertEqual((log["items"][0]["status"], log["items"][0]["template"]), ("envoye", "test_envoi"))
        detail = self._call("GET", "/api/admin/mail-logs/%s" % log["items"][0]["id"], uid=1).get_json()
        self.assertIn("Admin", detail["body"])
        # envoi désactivé : journalisé « non_envoye », jamais d'exception
        with self._enabled(False):
            ok, _ = mailer.send_template("test_envoi", "off@example.fr", {"administrateur": "A", "date": "d"})
        self.assertFalse(ok)
        off = self._call("GET", "/api/admin/mail-logs?q=off@example.fr", uid=1).get_json()
        self.assertEqual(off["items"][0]["status"], "non_envoye")
        self.assertEqual(self._call("GET", "/api/admin/mail-logs", uid=2).status_code, 403)

    def test_mail_settings_customize_layout_and_templates(self):
        listing = self._call("GET", "/api/admin/mail-settings", uid=1).get_json()
        keys = [t["key"] for t in listing["templates"]]
        self.assertIn("nouvelle_demande", keys)
        self.assertIn("relance_demandes", keys)
        self.assertIn("agent", [v for t in listing["templates"] if t["key"] == "nouvelle_demande" for v in t["variables"]])
        bad = self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"templates": {"test_envoi": {
            "subject": "Bonjour {inconnue}", "body": "x"}}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"layout": {"footer_color": "rouge"}}).status_code, 400)
        self.assertEqual(self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"layout": {"header_title": "x"}}).status_code, 400)
        self.assertEqual(self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"layout": {"from_email": "pas-un-mail"}}).status_code, 400)
        ok = self._call("PUT", "/api/admin/mail-settings", uid=1, payload={
            "layout": {"from_name": "DRH Ivry", "from_email": "drh@example.fr",
                       "footer1": "Ligne 1", "footer_color": "#445566", "signature": "L'équipe RH"},
            "templates": {"test_envoi": {"subject": "Essai {administrateur}", "body": "Salut {administrateur} <b>", "enabled": True}}})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        sent = []
        patches = self._mail_on()
        with patches[0], patches[1], patches[2], self._fake_post(sent):
            mailer.send_template("test_envoi", "x@example.fr", {"administrateur": "Marc", "date": "d"})
        body = sent[0]
        self.assertEqual(body["subject"], "Essai Marc")
        self.assertEqual((body["from_name"], body["from_email"]), ("DRH Ivry", "drh@example.fr"))
        self.assertEqual((body["footer1"], body["footerColor"]), ("Ligne 1", "#445566"))
        self.assertNotIn("background:", body["content"])     # pas d'en-tête maison : celui de l'APM s'applique
        self.assertIn("&lt;b&gt;", body["content"])          # le texte reste échappé
        self.assertIn("L&#x27;équipe RH", body["content"])   # signature commune
        # prévisualisation sans enregistrement + retour aux valeurs d'origine
        prev = self._call("POST", "/api/admin/mail-settings/preview", uid=1, payload={
            "key": "nouvelle_demande", "subject": "Sujet {agent}", "body": "Fiche : {lien_fiche}\nAgent {agent}"}).get_json()
        self.assertIn("DUPONT Marie", prev["subject"] + prev["text"])
        self.assertEqual(sorted(prev), ["html", "subject", "text"])   # ni en-tête ni pied de page dans l'aperçu
        self.assertNotIn("Ivry", prev["html"])
        reset = self._call("POST", "/api/admin/mail-settings/reset", uid=1, payload={"key": "test_envoi"}).get_json()
        tpl = [t for t in reset["templates"] if t["key"] == "test_envoi"][0]
        self.assertEqual(tpl["subject"], tpl["default_subject"])
        mail_templates.save({"layout": dict(mail_templates.DEFAULT_LAYOUT)})   # nettoie pour les autres tests

    def test_empty_variable_lines_are_dropped(self):
        text = mail_templates.substitute("Fiche : {lien_fiche}\nAgent : {agent}", {"lien_fiche": "", "agent": "X"})
        self.assertEqual(text, "Agent : X")

    def test_mail_test_endpoint_and_retention_purge(self):
        sent = []
        patches = self._mail_on()
        with self._enabled(False), patches[1], patches[2], self._fake_post(sent):   # envoi DÉSACTIVÉ : le test part quand même
            resp = self._call("POST", "/api/admin/mail-settings/test", uid=1, payload={"to": "essai@example.fr"}).get_json()
            other = self._call("POST", "/api/admin/mail-settings/test", uid=1,
                               payload={"to": "essai2@example.fr", "key": "nouvelle_demande"}).get_json()
        self.assertTrue(resp["ok"], resp)
        self.assertTrue(other["ok"], other)
        self.assertEqual(sent[0]["to"], "essai@example.fr")
        self.assertTrue(sent[1]["subject"].startswith("[TEST] "))
        self.assertEqual(self._call("POST", "/api/admin/mail-settings/test", uid=1, payload={"to": "pas-un-mail"}).status_code, 400)
        self.assertEqual(self._call("PUT", "/api/admin/log-retention", uid=1, payload={"connexions_jours": 5, "emails_jours": 90}).status_code, 400)
        self.assertEqual(self._call("PUT", "/api/admin/log-retention", uid=1, payload={"connexions_jours": 400, "emails_jours": 90}).status_code, 200)
        conn = db.get_db()
        conn.execute("INSERT INTO login_logs (at, event, login) VALUES ('2000-01-01 00:00:00','connexion','vieux')")
        conn.execute("INSERT INTO mail_logs (at, to_addr, status) VALUES ('2000-01-01 00:00:00','vieux@x.fr','envoye')")
        conn.commit()
        conn.close()
        removed = audit_logs.purge()
        self.assertGreaterEqual(removed[0], 1)
        self.assertGreaterEqual(removed[1], 1)
        audit_logs.save_retention(365, 365)

    def test_matricule_on_users_fiches_and_api(self):
        resp = self._call("POST", "/api/users", uid=1, payload={
            "login": "MAT1", "password": "secret123", "role": "agent", "parent_id": 3, "matricule": "A-1234"})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["matricule"], "A-1234")
        dup = self._call("POST", "/api/users", uid=1, payload={
            "login": "MAT2", "password": "secret123", "role": "agent", "parent_id": 3, "matricule": "A-1234"})
        self.assertEqual(dup.status_code, 400)
        self.assertEqual(self._call("POST", "/api/users", uid=1, payload={
            "login": "MAT3", "password": "secret123", "role": "agent", "parent_id": 3, "matricule": "a b!"}).status_code, 400)
        uid = resp.get_json()["id"]
        upd = self._call("PUT", "/api/users/%s" % uid, uid=1, payload={"matricule": "B5678"})
        self.assertEqual(upd.get_json()["matricule"], "B5678")
        listing = self._call("GET", "/api/users", uid=1).get_json()
        self.assertIn("B5678", [u["matricule"] for u in listing])
        # fiche : le matricule est enregistré sur la fiche et sur le compte de l'agent
        fiche = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "MATRIC", "prenom": "TEST", "email": "m@example.fr", "year": 2026, "owner_id": 3,
            "validator_id": 3, "matricule": "C9999"})
        self.assertEqual(fiche.status_code, 200, fiche.get_json())
        self.assertEqual(fiche.get_json()["matricule"], "C9999")
        clash = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "AUTRE", "prenom": "TEST", "email": "a@example.fr", "year": 2026, "owner_id": 3,
            "validator_id": 3, "matricule": "C9999"})
        self.assertEqual(clash.status_code, 400)
        agent_login = fiche.get_json()["agent_login"]
        conn = db.get_db()
        self.assertEqual(conn.execute("SELECT matricule FROM users WHERE login=?", (agent_login,)).fetchone()["matricule"], "C9999")
        conn.close()
        key = self._new_key("Matricules", scopes=("agents:read",))["key"]
        found = self._get_v1("/api/v1/agents?year=2026&q=C9999", key).get_json()
        self.assertEqual([i["matricule"] for i in found["items"]], ["C9999"])

    def test_password_ui_flags_and_user_creation_without_password_in_ad_mode(self):
        self._make_user("ADFLAG")
        conn = db.get_db()
        uid = conn.execute("SELECT id FROM users WHERE login='ADFLAG'").fetchone()["id"]
        conn.close()
        with mock.patch.object(config, "AUTH_MODE", "ad"):
            me = self._call("GET", "/api/me", uid=uid).get_json()["user"]
            self.assertTrue(me["password_by_ad"])
            self.assertEqual(me["auth_mode"], "ad")
            self.assertFalse(self._call("GET", "/api/me", uid=1).get_json()["user"]["password_by_ad"])
            ok = self._call("POST", "/api/users", uid=1, payload={"login": "SANSMDP", "role": "agent", "parent_id": 3})
            self.assertEqual(ok.status_code, 200, ok.get_json())
            admin = self._call("POST", "/api/users", uid=1, payload={"login": "ADMSANS", "role": "administrateur"})
            self.assertEqual(admin.status_code, 400)   # un administrateur garde un mot de passe de secours
        with mock.patch.object(config, "AUTH_MODE", "local"):
            self.assertEqual(self._call("POST", "/api/users", uid=1, payload={"login": "SANSMDP2", "role": "agent", "parent_id": 3}).status_code, 400)


    def test_mail_sending_switch_is_an_admin_setting(self):
        before = self._call("GET", "/api/admin/mail-settings", uid=1).get_json()
        self.assertFalse(before["enabled"])                       # désactivé par défaut
        on = self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"enabled": True}).get_json()
        self.assertTrue(on["enabled"])
        self.assertTrue(mailer.load_config() is not None or not apm.configured())
        self.assertTrue(mail_templates.is_enabled())
        off = self._call("PUT", "/api/admin/mail-settings", uid=1, payload={"enabled": False}).get_json()
        self.assertFalse(off["enabled"])
        self.assertIsNone(mailer.load_config())
        self.assertEqual(self._call("PUT", "/api/admin/mail-settings", uid=2, payload={"enabled": True}).status_code, 403)

    def test_automatic_mail_stays_blocked_when_disabled_but_is_journaled(self):
        sent = []
        patches = self._mail_on()
        with self._enabled(False), patches[1], patches[2], self._fake_post(sent):
            ok, err = mailer.send_template("test_envoi", "bloque@example.fr", {"administrateur": "A", "date": "d"})
        self.assertFalse(ok)
        self.assertEqual(sent, [])
        log = self._call("GET", "/api/admin/mail-logs?q=bloque@example.fr", uid=1).get_json()
        self.assertEqual(log["items"][0]["status"], "non_envoye")
        self.assertIn("désactivé", log["items"][0]["error"])


    # --- API Sedit RH : test de connexion et nombre d'agents ---------------------------- #
    def _sedit(self, status=200, payload=None, side_effect=None, calls=None):
        def fake_get(url, params=None, headers=None, timeout=None, verify=None):
            if calls is not None:
                calls.append({"url": url, "params": params, "headers": headers})
            if side_effect:
                raise side_effect
            return mock.Mock(status_code=status, json=lambda: payload)
        return [mock.patch.object(config, "SEDITRH_API_URL", "http://sedit.test"),
                mock.patch.object(config, "SEDITRH_API_KEY", "srh_live_secret123"),
                mock.patch.object(sedit_rh.requests, "get", fake_get)]

    def test_sedit_rh_counts_agents_and_never_exposes_the_key(self):
        payload = {"data": [{"code": "CDI", "libelle": "CDI", "effectif": 77},
                            {"code": "TIT", "libelle": "Titulaire", "effectif": 1340}], "meta": {"total": 1417}}
        calls = []
        p = self._sedit(payload=payload, calls=calls)
        with p[0], p[1], p[2]:
            result = self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()
            info = self._call("GET", "/api/admin/sedit-rh", uid=1).get_json()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["total_agents"], 1417)
        self.assertEqual([s["code"] for s in result["par_statut"]], ["TIT", "CDI"])   # trié par effectif décroissant
        self.assertEqual(calls[0]["url"], "http://sedit.test/api/v1/effectifs")
        self.assertEqual(calls[0]["params"], {"par": "statut"})
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer srh_live_secret123"})
        self.assertNotIn("srh_live_secret123", json.dumps(result) + json.dumps(info))
        self.assertTrue(info["configured"] and info["key_set"])
        self.assertEqual(self._call("POST", "/api/admin/sedit-rh/test", uid=2).status_code, 403)

    def test_sedit_rh_total_falls_back_to_the_sum_and_errors_are_explained(self):
        p = self._sedit(payload={"data": [{"code": "A", "libelle": "A", "effectif": 5}, {"code": "B", "libelle": "B", "effectif": 7}]})
        with p[0], p[1], p[2]:
            self.assertEqual(self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()["total_agents"], 12)
        with mock.patch.object(config, "SEDITRH_API_URL", ""):
            r = self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()
            self.assertFalse(r["ok"])
            self.assertIn("pas configurée", r["error"])
        p = self._sedit(status=403, payload={"detail": "Scope manquant : effectifs:read"})
        with p[0], p[1], p[2]:
            r = self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()
            self.assertEqual((r["ok"], r["status"]), (False, 403))
            self.assertIn("effectifs:read", r["error"])
        p = self._sedit(status=401, payload={})
        with p[0], p[1], p[2]:
            r = self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()
            self.assertIn("Clé refusée", r["error"])
        p = self._sedit(side_effect=sedit_rh.requests.ConnectionError("x"))
        with p[0], p[1], p[2]:
            r = self._call("POST", "/api/admin/sedit-rh/test", uid=1).get_json()
            self.assertIn("injoignable", r["error"])
            self.assertIsNotNone(r["latency_ms"])


    # --- Sedit RH : matricules, organisation, création d'agents ---------------------------- #
    @staticmethod
    def _rh_agent(matricule, nom, prenom, d, s=None, sec=None, arrivee="2010-01-01", fonction="Agent"):
        unit = lambda u: {"code": u[0], "libelle": u[1]} if u else {"code": None, "libelle": None}
        return {"matricule": matricule, "nom": nom, "prenom": prenom, "statut": {"code": "TIT", "libelle": "Titulaire"},
                "direction": unit(d), "service": unit(s), "secteur": unit(sec), "fonction": {"code": "1", "libelle": fonction},
                "date_arrivee": arrivee, "date_depart": None, "en_poste": True}

    def _rh_patches(self, agents, ad=None):
        def fake_ad(query, limit=15):
            return list((ad or {}).get(query.upper(), []))
        return [mock.patch.object(sedit_rh, "all_agents", lambda force=False: agents),
                mock.patch.object(apm, "configured", return_value=True),
                mock.patch.object(apm, "ad_search", fake_ad)]

    def test_rh_matricules_are_proposed_then_applied_only_when_certain(self):
        fiche = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "ZZRAPPRO", "prenom": "UN", "email": "r@example.fr", "year": 2026, "owner_id": 3, "validator_id": 3}).get_json()
        twin = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "ZZJUMEAU", "prenom": "UN", "email": "j@example.fr", "year": 2026, "owner_id": 3, "validator_id": 3}).get_json()
        absent = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "ZZABSENT", "prenom": "UN", "email": "a@example.fr", "year": 2026, "owner_id": 3, "validator_id": 3}).get_json()
        rh = [self._rh_agent("RHZ1", "ZZRappro", "Un", ("D1", "DIR TEST")),
              self._rh_agent("RHZ2", "ZZJumeau", "Un", ("D1", "DIR TEST")),
              self._rh_agent("RHZ3", "ZZJumeau", "Un", ("D1", "DIR TEST"))]
        p = self._rh_patches(rh)
        with p[0], p[1], p[2]:
            body = self._call("GET", "/api/admin/rh/matricules", uid=1).get_json()
            by_login = {i["login"]: i for i in body["items"]}
            self.assertEqual(by_login[fiche["agent_login"]]["status"], "certain")
            self.assertEqual(by_login[fiche["agent_login"]]["matricule"], "RHZ1")
            self.assertEqual(by_login[twin["agent_login"]]["status"], "ambigu")           # homonymes : jamais proposé
            self.assertEqual(by_login[absent["agent_login"]]["status"], "introuvable")
            applied = self._call("POST", "/api/admin/rh/matricules/apply", uid=1, payload={"items": [
                {"agent_user_id": fiche["agent_id"], "matricule": "RHZ1"},
                {"agent_user_id": twin["agent_id"], "matricule": "INCONNU"}]}).get_json()
            self.assertEqual(applied["applied"], 1)
            self.assertEqual(len(applied["refused"]), 1)
            again = self._call("POST", "/api/admin/rh/matricules/apply", uid=1, payload={"items": [
                {"agent_user_id": fiche["agent_id"], "matricule": "RHZ1"}]}).get_json()
            self.assertEqual(again["applied"], 0)                                           # déjà renseigné : rien d'écrasé
            self.assertEqual(self._call("GET", "/api/admin/rh/matricules", uid=2).status_code, 403)
        conn = db.get_db()
        self.assertEqual(conn.execute("SELECT matricule FROM users WHERE id=?", (fiche["agent_id"],)).fetchone()["matricule"], "RHZ1")
        self.assertEqual(conn.execute("SELECT matricule FROM agents WHERE id=?", (fiche["id"],)).fetchone()["matricule"], "RHZ1")
        conn.close()

    def test_rh_organisation_tree_merges_levels_and_flags_agents_already_in_app(self):
        fiche = self._call("POST", "/api/agents", uid=1, payload={
            "nom": "ZZARBRE", "prenom": "UN", "email": "t@example.fr", "year": 2026, "owner_id": 3, "validator_id": 3}).get_json()
        rh = [self._rh_agent("ARB1", "ZZArbre", "Un", ("T1", "DIRECTION ARBRE"), ("T1S", "SERVICE ARBRE"), ("T1K", "SECTEUR ARBRE")),
              self._rh_agent("ARB2", "ZZNouveau", "Deux", ("T1", "DIRECTION ARBRE"), ("T1S", "SERVICE ARBRE"), ("T1S", "SERVICE ARBRE")),
              self._rh_agent("ARB3", "ZZSolo", "Trois", ("T2", "DIRECTION SOLO"), ("T2", "DIRECTION SOLO"), ("T2", "DIRECTION SOLO"))]
        p = self._rh_patches(rh)
        with p[0], p[1], p[2]:
            tree = self._call("GET", "/api/admin/rh/organisation", uid=1).get_json()
            self.assertEqual(self._call("GET", "/api/admin/rh/organisation", uid=4).status_code, 403)
        d1 = [n for n in tree["tree"] if n["code"] == "T1"][0]
        s1 = d1["children"][0]
        self.assertEqual((d1["level"], s1["level"], s1["code"]), ("direction", "service", "T1S"))
        self.assertEqual((d1["total"], d1["missing"]), (2, 1))
        k1 = s1["children"][0]
        self.assertEqual((k1["level"], k1["code"], len(k1["agents"])), ("secteur", "T1K", 1))
        self.assertTrue(k1["agents"][0]["in_app"])                                           # ZZARBRE UN est dans l'application
        self.assertEqual(k1["agents"][0]["login"], fiche["agent_login"])
        self.assertEqual([a["matricule"] for a in s1["agents"]], ["ARB2"])                   # secteur identique au service : fusionné
        d2 = [n for n in tree["tree"] if n["code"] == "T2"][0]
        self.assertEqual((len(d2["children"]), [a["matricule"] for a in d2["agents"]]), (0, ["ARB3"]))  # service et secteur fusionnés

    def test_rh_import_creates_accounts_units_and_agents_and_is_idempotent(self):
        conn = db.get_db()
        conn.execute("INSERT INTO users (login, nom, mot_de_passe, admin, role, parent_id, actif) "
                     "VALUES ('SVC-EXIST','SERVICE IMPORT','x',0,'service',3,1) ON CONFLICT (login) DO NOTHING")
        conn.commit()
        service_id = conn.execute("SELECT id FROM users WHERE login='SVC-EXIST'").fetchone()["id"]
        conn.close()
        rh = [self._rh_agent("IMP1", "ZZImport", "Alice", ("I1", "DIRECTION IMPORT"), ("I1S", "SERVICE IMPORT"), ("I1K", "SECTEUR IMPORT")),
              self._rh_agent("IMP2", "ZZImport", "Bob", ("I1", "DIRECTION IMPORT"), ("I1S", "SERVICE IMPORT")),
              self._rh_agent("IMP3", "ZZSeul", "Carl", ("I2", "DIRECTION SEULE"), arrivee="2026-03-02")]
        ad = {"ZZIMPORT": [{"username": "alice.zzimport", "displayName": "ZZIMPORT Alice", "email": "alice@ville.fr"},
                           {"username": "bob.zzimport", "displayName": "ZZIMPORT Bob", "email": "bob@ville.fr"}],
              "ZZSEUL": []}
        payload = {"matricules": ["IMP1", "IMP2", "IMP3", "NOPE"], "year": 2026, "create_units": True, "use_ad": True}
        p = self._rh_patches(rh, ad)
        with p[0], p[1], p[2]:
            preview = self._call("POST", "/api/admin/rh/import/preview", uid=1, payload=payload).get_json()
            self.assertEqual(preview["counts"], {"a_creer": 3, "existe": 0, "ignore": 1})
            self.assertEqual(sorted(u["libelle"] for u in preview["units_new"]),
                             ["DIRECTION IMPORT", "DIRECTION SEULE", "SECTEUR IMPORT"])   # le service existe déjà
            conn = db.get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) AS c FROM users WHERE matricule IN ('IMP1','IMP2','IMP3')").fetchone()["c"], 0)  # aperçu : rien d'écrit
            conn.close()
            done = self._call("POST", "/api/admin/rh/import", uid=1, payload=payload).get_json()
            self.assertEqual((len(done["created"]), len(done["units_created"])), (3, 3))
            again = self._call("POST", "/api/admin/rh/import", uid=1, payload=payload).get_json()
            self.assertEqual((len(again["created"]), len(again["units_created"])), (0, 0))   # idempotent : déjà présents
            self.assertEqual(self._call("POST", "/api/admin/rh/import", uid=2, payload=payload).status_code, 403)
        conn = db.get_db()
        users = {r["matricule"]: r for r in conn.execute(
            "SELECT id, login, nom, email, ad_login, matricule, role, parent_id FROM users WHERE matricule IN ('IMP1','IMP2','IMP3')").fetchall()}
        units = {r["nom"]: r for r in conn.execute(
            "SELECT id, login, nom, role, parent_id FROM users WHERE nom IN ('DIRECTION IMPORT','SECTEUR IMPORT','DIRECTION SEULE')").fetchall()}
        self.assertEqual(units["DIRECTION IMPORT"]["role"], "direction")
        self.assertEqual((units["SECTEUR IMPORT"]["role"], units["SECTEUR IMPORT"]["parent_id"]), ("secteur", service_id))  # sous le service existant
        self.assertTrue(units["DIRECTION IMPORT"]["login"].startswith("DIR-"))
        self.assertEqual(users["IMP1"]["parent_id"], units["SECTEUR IMPORT"]["id"])      # propriétaire = niveau le plus bas
        self.assertEqual(users["IMP2"]["parent_id"], service_id)                          # compte de service existant réutilisé
        self.assertEqual(users["IMP3"]["parent_id"], units["DIRECTION SEULE"]["id"])
        self.assertEqual((users["IMP1"]["email"], users["IMP1"]["ad_login"], users["IMP1"]["role"]), ("alice@ville.fr", "alice.zzimport", "agent"))
        self.assertEqual(users["IMP3"]["email"], "")                                      # AD sans résultat : e-mail à renseigner
        fiche = conn.execute("SELECT year, params, matricule FROM agents WHERE matricule='IMP3'").fetchone()
        self.assertEqual(fiche["year"], 2026)
        self.assertEqual(json.loads(fiche["params"])["date_arrivee"], "2026-03-02")      # date d'arrivée dans l'année de la fiche
        self.assertNotIn("date_arrivee", {k for k, v in json.loads(conn.execute("SELECT params FROM agents WHERE matricule='IMP1'").fetchone()["params"]).items() if v})
        audit = conn.execute("SELECT actor_login FROM user_audit WHERE comment='Création depuis Sedit RH' LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(audit["actor_login"], "admin")

    def test_rh_import_needs_an_owner_and_reports_sedit_errors(self):
        rh = [self._rh_agent("OWN1", "ZZOwner", "Un", ("O1", "DIRECTION OWNER"))]
        p = self._rh_patches(rh)
        with p[0], p[1], p[2]:
            base = {"matricules": ["OWN1"], "year": 2026, "use_ad": False}
            none = self._call("POST", "/api/admin/rh/import/preview", uid=1, payload={**base, "create_units": False}).get_json()
            self.assertEqual(none["counts"]["ignore"], 1)                                 # ni compte d'unité ni propriétaire
            self.assertIn("propriétaire", none["items"][0]["reason"])
            ok = self._call("POST", "/api/admin/rh/import", uid=1, payload={**base, "create_units": False, "default_owner_id": 3}).get_json()
            self.assertEqual(len(ok["created"]), 1)
            self.assertEqual(self._call("POST", "/api/admin/rh/import", uid=1, payload={"year": 2026, "matricules": []}).status_code, 400)
            self.assertEqual(self._call("POST", "/api/admin/rh/import", uid=1, payload={"year": 1800, "matricules": ["X"]}).status_code, 400)
        with mock.patch.object(sedit_rh, "all_agents", side_effect=sedit_rh.SeditError("API Sedit RH injoignable")):
            resp = self._call("GET", "/api/admin/rh/organisation", uid=1)
            self.assertEqual(resp.status_code, 502)
            self.assertIn("injoignable", resp.get_json()["error"])


    # ---- Rôles Administrateur / Valideur / Agent, unités SIRH, création d'une personne -----------------------------
    UNITS = [
        {"code": "D1", "libelle": "DIRECTION RH", "level": "direction", "parent_code": "", "position": 0},
        {"code": "S1", "libelle": "SERVICE PAIE", "level": "service", "parent_code": "D1", "position": 1},
        {"code": "K1", "libelle": "SECTEUR PAIE 1", "level": "secteur", "parent_code": "S1", "position": 2},
        {"code": "D2", "libelle": "DIRECTION AUTRE", "level": "direction", "parent_code": "", "position": 3},
    ]

    def _units_patch(self):
        return mock.patch.object(sedit_rh, "organisation_units", lambda force=False: [dict(u) for u in self.UNITS])

    def _seed_period_settings(self):
        conn = db.get_db()
        for key, value in (("penibilites", [{"name": "Modérée"}]), ("penibilites_durees", {"Modérée": ["38 heures"]}),
                           ("durees", ["38 heures"]), ("quotites", ["100%"]), ("jours_hebdo", [5])):
            self.app_module.set_setting(conn, key, value)
        conn.commit()
        conn.close()

    def test_calendar_coverage_blocks_requests_outside_periods(self):
        ag = {"year": 2026, "periods": json.dumps([{"start": "2026-01-01", "end": "2026-08-31"}]), "params": "{}"}
        cov = self.app_module._agent_coverage(ag)
        self.assertTrue(self.app_module._cell_covered(cov, 2026, 8310))     # 31 août (matin) : clé 8310
        self.assertFalse(self.app_module._cell_covered(cov, 2026, 9010))
        self.assertEqual(self.app_module._agent_coverage({"year": 2026, "periods": "[]", "params": json.dumps({"date_arrivee": "2026-03-02"})}),
                         [{"start": "2026-03-02", "end": "2026-12-31", "days": [1, 2, 3, 4, 5], "ferie": False}])
        # Jours travaillés : samedi / dimanche non décomptés, férié seulement si l'agent le travaille.
        self.assertFalse(self.app_module._cell_covered(cov, 2026, 8290))                       # samedi 29 août
        self.assertTrue(self.app_module._cell_covered(cov, 2026, 8280))                        # vendredi 28 août : travaillé
        self.assertFalse(self.app_module._cell_covered(cov, 2026, 5010, {"2026-05-01"}))       # 1er mai, vendredi férié, non travaillé
        self.assertTrue(self.app_module._cell_covered(cov, 2026, 5010))                        # sans calendrier de fériés : travaillé
        four = {"year": 2026, "periods": json.dumps([{"start": "2026-01-01", "end": "2026-12-31", "jours_travailles": [1, 2, 3, 4, 5, 7], "ferie_travaille": True}]), "params": "{}"}
        cov4 = self.app_module._agent_coverage(four)
        self.assertTrue(self.app_module._cell_covered(cov4, 2026, 5010, {"2026-05-01"}))       # férié travaillé
        self.assertFalse(self.app_module._cell_covered(cov4, 2026, 5020))                      # 2 mai = samedi : non travaillé
        self.assertTrue(self.app_module._cell_covered(cov4, 2026, 5030))                       # 3 mai = dimanche coché
        self.assertIsNone(self.app_module._normalize_periods([{"start": "2026-01-01", "end": "2026-12-31", "jours_hebdo": 4, "jours_travailles": [1, 2, 3]}], {}, 2026))  # 3 jours cochés pour 4/sem.

    def test_org_units_sync_and_access(self):
        with self._units_patch():
            rows = self._call("GET", "/api/org-units?refresh=1", uid=1).get_json()
        self.assertEqual([r["code"] for r in rows], ["D1", "S1", "K1", "D2"])
        self.assertEqual(rows[2]["path"], "DIRECTION RH › SERVICE PAIE › SECTEUR PAIE 1")
        self.assertEqual(self._call("GET", "/api/org-units", uid=4).status_code, 403)          # un agent n'a pas accès

    def test_sirh_search_filters_every_word(self):
        data = {"data": [
            {"matricule": "0001", "nom": "PARISI", "prenom": "Christophe", "affectation": {"code": "K1", "libelle": "SECTEUR PAIE 1"}},
            {"matricule": "0002", "nom": "PARISI", "prenom": "Alice"},
            {"matricule": "0003", "nom": "DURAND", "prenom": "Christophe"},
        ]}
        calls = []
        with mock.patch.object(sedit_rh, "_get", lambda path, params=None, timeout=30: calls.append(params) or data):
            hits = sedit_rh.search_agents("christophe parisi")
            self.assertEqual([h["matricule"] for h in hits], ["0001"])
            self.assertEqual(hits[0]["unit_code"], "K1")
            self.assertEqual(calls[0]["q"], "christophe")                       # l'API reçoit le mot le plus long
            self.assertEqual(sedit_rh.search_agents("p"), [])                    # trop court : aucun appel
        self.assertEqual(len(calls), 1)

    def test_ad_match_unique_several_none(self):
        import people

        def hit(u, n, m=""):
            return {"username": u, "displayName": n, "email": m}

        with mock.patch.object(apm, "configured", lambda: True):
            with mock.patch.object(apm, "ad_search", lambda q, limit=15: [hit("cparisi", "PARISI Christophe", "c.parisi@ville.fr")]):
                r = people.ad_match("PARISI", "Christophe")
            self.assertEqual((r["status"], r["candidates"][0]["username"]), ("unique", "cparisi"))
            two = [hit("cparisi", "PARISI Christophe"), hit("cparisi2", "PARISI Christophe (2)")]
            with mock.patch.object(apm, "ad_search", lambda q, limit=15: two):
                r = people.ad_match("PARISI", "Christophe")
                self.assertEqual((r["status"], r["candidates"][0]["username"]), ("unique", "cparisi"))   # identifiant attendu : cparisi
            # Deux comptes de même nom, un seul avec messagerie : c'est celui-là (compte de test sans e-mail écarté).
            with mock.patch.object(apm, "ad_search", lambda q, limit=15: [hit("mchevaliertest", "MARC CHEVALIER"), hit("machevalier", "CHEVALIER Marc", "m@ville.fr")]):
                r = people.ad_match("CHEVALIER", "Marc")
                self.assertEqual((r["status"], r["candidates"][0]["username"]), ("unique", "machevalier"))
            with mock.patch.object(apm, "ad_search", lambda q, limit=15: [hit("a", "DUPONT Jean"), hit("b", "DUPONT Jean-Luc")]):
                self.assertEqual(people.ad_match("DUPONT", "Jean")["status"], "plusieurs")
            with mock.patch.object(apm, "ad_search", lambda q, limit=15: []):
                self.assertEqual(people.ad_match("ZZ", "Zed")["status"], "aucun")
        with mock.patch.object(apm, "configured", lambda: False):
            self.assertEqual(people.ad_match("A", "B")["status"], "indisponible")

    def test_create_person_agent_valideur_and_rules(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        # Agent affecté au service PAIE : le valideur est le compte « Direction RH » (compte d'unité hérité, unité supérieure).
        r = self._call("POST", "/api/users/person", uid=1, payload={
            "profil": "agent", "nom": "Zzparisi", "prenom": "Christophe", "matricule": "P0001", "email": "c.parisi@ville.fr",
            "ad_login": "cparisi", "unit_code": "S1"})
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertEqual((body["profil"], body["role"], body["parent_id"], body["unit_code"]), ("agent", "agent", 2, "S1"))
        # Pas de fiche à la création : elle naît avec la première période de paramètres.
        self.assertIsNone(body["fiche_id"])
        self._seed_period_settings()
        bad = self._call("POST", "/api/my-agents/%d/fiche" % body["id"], uid=1, payload={"year": 2026, "penibilite": "Inconnue", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5})
        self.assertEqual(bad.status_code, 400)
        ok = self._call("POST", "/api/my-agents/%d/fiche" % body["id"], uid=1, payload={"year": 2026, "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        conn = db.get_db()
        fiche = conn.execute("SELECT user_id, validator_id, nom, prenom, periods FROM agents WHERE id=?", (ok.get_json()["fiche_id"],)).fetchone()
        conn.close()
        self.assertEqual((fiche["user_id"], fiche["validator_id"], fiche["nom"], fiche["prenom"]), (2, 2, "ZZPARISI", "CHRISTOPHE"))
        self.assertEqual(json.loads(fiche["periods"])[0]["start"], "2026-01-01")
        self.assertEqual(self._call("POST", "/api/my-agents/%d/fiche" % body["id"], uid=1, payload={"year": 2026, "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5}).status_code, 400)  # déjà une période
        # Un valideur de service, validé par l'unité Direction RH.
        with mock.patch.object(config, "AUTH_MODE", "ad"):
            v = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "nom": "Zzchef", "prenom": "Paul", "unit_code": "S1", "validator_unit_code": "D1"})
            self.assertEqual(v.status_code, 200, v.get_json())
            vb = v.get_json()
            self.assertEqual((vb["profil"], vb["role"], vb["parent_id"], vb["validator_unit_code"]), ("valideur", "service", 2, "D1"))
            # Un nouvel agent du secteur PAIE 1 est rattaché à ce valideur (unité supérieure la plus proche).
            a2 = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "agent", "nom": "Zzdeux", "prenom": "Anne", "unit_code": "K1"}).get_json()
            self.assertEqual(a2["parent_id"], vb["id"])
            # Unité validatrice qui n'est pas supérieure : refusée ; unité sans valideur : refusée explicitement.
            bad = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "nom": "Zzbad", "prenom": "X", "unit_code": "S1", "validator_unit_code": "D2"})
            self.assertEqual(bad.status_code, 400)
            self.assertIn("supérieure", bad.get_json()["error"])
            none = self._call("POST", "/api/users/person", uid=1, payload={"profil": "agent", "nom": "Zznone", "prenom": "Y", "unit_code": "D2"})
            self.assertEqual(none.status_code, 400)
            self.assertIn("Aucun valideur", none.get_json()["error"])
        # Garde-fous : matricule déjà pris, unité inconnue, profil invalide, administrateur réservé aux administrateurs.
        dup = self._call("POST", "/api/users/person", uid=1, payload={"profil": "agent", "nom": "Zzdup", "prenom": "Z", "matricule": "P0001", "unit_code": "S1"})
        self.assertEqual(dup.status_code, 400)
        self.assertEqual(self._call("POST", "/api/users/person", uid=1, payload={"profil": "agent", "nom": "Q", "prenom": "Q", "unit_code": "NOPE"}).status_code, 400)
        self.assertEqual(self._call("POST", "/api/users/person", uid=1, payload={"profil": "dga", "nom": "Q", "prenom": "Q"}).status_code, 400)
        self.assertEqual(self._call("POST", "/api/users/person", uid=2, payload={"profil": "administrateur", "nom": "Q", "prenom": "Q"}).status_code, 403)
        self.assertEqual(self._call("POST", "/api/users/person", uid=4, payload={"profil": "agent", "nom": "Q", "prenom": "Q", "unit_code": "S1"}).status_code, 403)
        listing = {u["login"]: u for u in self._call("GET", "/api/users", uid=1).get_json()}
        self.assertEqual((listing["admin"]["profil"], listing["admin"]["admin"], listing["DRH"]["profil"], listing["AGENT1"]["profil"]), ("valideur", 1, "valideur", "agent"))

    def test_update_profil_valideur_keeps_internal_level(self):
        r = self._call("PUT", "/api/users/3", uid=1, payload={"role": "valideur", "parent_id": 2})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual((r.get_json()["role"], r.get_json()["profil"]), ("secteur", "valideur"))

    def test_admin_is_a_right_on_top_of_agent_or_valideur(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        with mock.patch.object(config, "AUTH_MODE", "ad"):
            # Sans mot de passe local, pas d'administrateur ; seul un administrateur peut accorder le droit.
            no_pw = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "admin": True, "nom": "Zzadm", "prenom": "Ann", "unit_code": "S1"})
            self.assertEqual(no_pw.status_code, 400)
            self.assertEqual(self._call("POST", "/api/users/person", uid=2, payload={
                "profil": "valideur", "admin": True, "nom": "Zzadm", "prenom": "Ann", "unit_code": "S1",
                "password": "Secours-123"}).status_code, 403)
            ok = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "admin": True, "nom": "Zzadm", "prenom": "Ann", "unit_code": "S1", "password": "Secours-123"})
            self.assertEqual(ok.status_code, 200, ok.get_json())
            body = ok.get_json()
            self.assertEqual((body["profil"], body["role"], body["admin"]), ("valideur", "service", 1))
            # Il garde son niveau interne mais obtient les droits d'administration (accès à tout le périmètre).
            me = self._call("GET", "/api/me", uid=body["id"]).get_json()["user"]
            self.assertEqual((me["profil"], me["admin"]), ("valideur", 1))
            self.assertEqual(self._call("GET", "/api/admin/sedit-rh", uid=body["id"]).status_code, 200)
            # L'administrateur peut aussi être retiré / accordé à un agent existant, sans changer son rôle.
            r = self._call("PUT", "/api/users/4", uid=1, payload={"admin": True, "role": "agent"})
            self.assertEqual((r.get_json()["role"], r.get_json()["admin"]), ("agent", 1))
            r = self._call("PUT", "/api/users/4", uid=1, payload={"admin": False, "role": "agent"})
            self.assertEqual((r.get_json()["role"], r.get_json()["admin"]), ("agent", 0))
            # On ne retire pas ses propres droits.
            self.assertEqual(self._call("PUT", "/api/users/%d" % body["id"], uid=body["id"], payload={"admin": False}).status_code, 400)

    def test_admin_sees_his_team_unless_view_all(self):
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif) VALUES (2010,'ADMTEAM','Admin Equipe','x',1,'direction',NULL,1)")
        conn.commit()
        conn.close()
        try:
            with self.client.session_transaction() as sess:
                sess["uid"] = 2010
            mine = self.client.get("/api/agents?year=2026").get_json()
            everything = self.client.get("/api/agents?year=2026", headers={"X-Scope": "all"}).get_json()
            self.assertEqual(len(mine), 0)                                  # sans équipe : rien, même administrateur
            self.assertGreaterEqual(len(everything), 1)                    # « Voir tout » : toutes les fiches
            self.assertEqual(self.client.get("/api/requests/counts").get_json()["to_validate"], 0)
            tree = self.client.get("/api/my-agents", headers={"X-Scope": "all"}).get_json()
            self.assertTrue(tree.get("all"))
            # Un non-administrateur ne peut pas élargir son périmètre avec l'en-tête.
            with self.client.session_transaction() as sess:
                sess["uid"] = 3
            self.assertEqual(self.client.get("/api/my-agents", headers={"X-Scope": "all"}).get_json().get("all"), None)
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM users WHERE id=2010")
            conn.commit()
            conn.close()

    def test_my_leave_returns_own_fiche_even_for_a_validator(self):
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif) VALUES (2020,'MLVAL','Val','x',0,'service',2,1)")
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
                     "VALUES (2020, 2, 2020, 'VAL', 'X', '', 2, 2026, '{}', '[]')")
        conn.commit()
        conn.close()
        try:
            r = self._call("GET", "/api/my-leave?year=2026", uid=2020).get_json()
            self.assertEqual(r["fiche_id"], 2020)                 # sa fiche est hors de son équipe, elle reste atteignable
            self.assertIsNone(self._call("GET", "/api/my-leave?year=2025", uid=2020).get_json()["fiche_id"])
            self.assertEqual(self._call("GET", "/api/agents/2020?year=2026", uid=2020).status_code, 200)
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM agents WHERE id=2020")
            conn.execute("DELETE FROM users WHERE id=2020")
            conn.commit()
            conn.close()

    def test_mail_dates_are_ranges_and_templates_have_buttons(self):
        import mail_templates
        import mailer
        cells = [4000 + d * 10 + h for d in (20, 21, 22, 23, 24) for h in (0, 1)]
        self.assertEqual(mailer.format_ranges(cells, 2026), ["du 20 avril 2026 au 24 avril 2026"])
        self.assertEqual(mailer.format_ranges([4241, 4270, 4271], 2026), ["du 24 avril 2026 (après-midi) au 27 avril 2026"])   # week-end sauté
        self.assertEqual(mailer.format_ranges([4200], 2026), ["le 20 avril 2026 (matin)"])
        self.assertEqual(mailer.format_ranges([4200, 4201, 4220, 4221], 2026), ["le 20 avril 2026", "le 22 avril 2026"])
        r = mail_templates.render("nouvelle_demande", mail_templates.TEMPLATES["nouvelle_demande"]["sample"])
        self.assertIn(">Valider</a>", r["html"])
        self.assertIn(">Refuser</a>", r["html"])
        self.assertIn("calendrier d&#x27;équipe</a>", r["html"])
        self.assertNotIn("[[bouton", r["text"])
        self.assertIn("Valider : https://", r["text"])
        # Sans adresse de l'application, les lignes de bouton disparaissent (variables vides).
        empty = dict(mail_templates.TEMPLATES["nouvelle_demande"]["sample"], lien_valider="", lien_refuser="", lien_calendrier="")
        self.assertNotIn("Valider", mail_templates.render("nouvelle_demande", empty)["html"].split("validation")[1])

    def test_mail_action_page_needs_a_click_and_checks_rights(self):
        import mail_actions
        conn = db.get_db()
        conn.execute("INSERT INTO leave_requests (id, agent_id, user_id, year, code, cells, days, status, validator_id) "
                     "VALUES (2040, 1, 4, 2026, 'CA', '[5010, 5011]', 1, 'en_attente', 3)")
        conn.commit()
        conn.close()
        secret = self.app_module.app.secret_key
        good = mail_actions.make_token(secret, 2040, 3)
        try:
            page = self.client.get("/api/mail-action/" + good + "?a=validee")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Valider", page.get_data(as_text=True))
            conn = db.get_db()
            self.assertEqual(conn.execute("SELECT status FROM leave_requests WHERE id=2040").fetchone()["status"], "en_attente")  # GET sans effet
            conn.close()
            self.assertIn("Lien invalide", self.client.get("/api/mail-action/pas-un-jeton").get_data(as_text=True))
            # Un agent n'est pas habilité à décider, même avec un jeton signé à son nom.
            denied = self.client.post("/api/mail-action/" + mail_actions.make_token(secret, 2040, 4), data={"decision": "refusee"})
            self.assertIn("Décision non enregistrée", denied.get_data(as_text=True))
            done = self.client.post("/api/mail-action/" + good, data={"decision": "refusee", "comment": "Période chargée"})
            self.assertIn("refusée", done.get_data(as_text=True))
            conn = db.get_db()
            row = conn.execute("SELECT status, decision_comment FROM leave_requests WHERE id=2040").fetchone()
            ev = conn.execute("SELECT actor_id FROM leave_request_events WHERE request_id=2040 AND action='refusee'").fetchone()
            conn.close()
            self.assertEqual((row["status"], row["decision_comment"], ev["actor_id"]), ("refusee", "Période chargée", 3))
            self.assertIn("déjà traitée", self.client.get("/api/mail-action/" + good).get_data(as_text=True))
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM leave_request_events WHERE request_id=2040")
            conn.execute("DELETE FROM leave_requests WHERE id=2040")
            conn.commit()
            conn.close()

    def test_delegation_periods_auto_and_done_list(self):
        import datetime as dtm
        import delegation
        today = dtm.date.today()
        conn = db.get_db()
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
                     "VALUES (2050, 2, 3, 'SECT', 'UN', '', 2, ?, '{}', '[]')", (today.year,))
        conn.execute("INSERT INTO leave_requests (id, agent_id, user_id, year, code, cells, days, status, validator_id) "
                     "VALUES (2051, 1, 4, 2026, 'CA', '[5010, 5011]', 1, 'validee', 3)")
        conn.execute("INSERT INTO leave_request_events (request_id, action, actor_id, comment) VALUES (2051, 'validee', 2, 'Vu en délégation')")
        conn.commit()
        conn.close()
        try:
            conn = db.get_db()
            self.assertIsNone(delegation.active_delegate(conn, 3))                       # rien de configuré
            conn.close()
            r = self._call("GET", "/api/delegation", uid=3).get_json()
            self.assertEqual((r["delegate"]["login"], r["auto"], r["periods"], r["active_now"]), ("DRH", False, [], False))
            self.assertEqual([(x["agent"], x["par"], x["dates"]) for x in r["done"]],
                             [("AGENT UN", "Direction RH", ["le 1 mai 2026"])])          # validé par le délégataire, pas par moi
            # Période explicite, même sans congés.
            period = {"start": (today - dtm.timedelta(days=1)).isoformat(), "end": (today + dtm.timedelta(days=2)).isoformat()}
            added = self._call("POST", "/api/delegation/periods", uid=3, payload=period)
            self.assertEqual(added.status_code, 200, added.get_json())
            conn = db.get_db()
            self.assertEqual(delegation.active_delegate(conn, 3)["id"], 2)
            self.assertIn(3, delegation.delegators_of(conn, 2))
            self.assertIsNone(delegation.active_delegate(conn, 3, today + dtm.timedelta(days=30)))
            conn.close()
            self.assertEqual(self._call("DELETE", "/api/delegation/periods/%d" % added.get_json()["id"], uid=3).status_code, 200)
            # Délégation automatique : seulement quand le valideur est absent (journée complète dans sa propre fiche).
            self.assertEqual(self._call("PUT", "/api/delegation/auto", uid=3, payload={"auto": True}).status_code, 200)
            conn = db.get_db()
            self.assertIsNone(delegation.active_delegate(conn, 3))
            base = today.month * 1000 + today.day * 10
            conn.execute("INSERT INTO cells (agent_id, jour, code) VALUES (2050, ?, 'CA'), (2050, ?, 'CA')", (base, base + 1))
            conn.commit()
            self.assertEqual(delegation.active_delegate(conn, 3)["id"], 2)
            conn.close()
            # Refus : période passée, dates inversées, valideur sans responsable.
            self.assertEqual(self._call("POST", "/api/delegation/periods", uid=3, payload={"start": "2020-01-01", "end": "2020-01-05"}).status_code, 400)
            self.assertEqual(self._call("POST", "/api/delegation/periods", uid=3, payload={"start": "2030-02-01", "end": "2030-01-01"}).status_code, 400)
            self.assertEqual(self._call("POST", "/api/delegation/periods", uid=1, payload=period).status_code, 400)
            self.assertEqual(self._call("GET", "/api/delegation", uid=4).status_code, 403)
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM cells WHERE agent_id=2050")
            conn.execute("DELETE FROM leave_request_events WHERE request_id=2051")
            conn.execute("DELETE FROM leave_requests WHERE id=2051")
            conn.execute("DELETE FROM agents WHERE id=2050")
            conn.execute("DELETE FROM delegations WHERE user_id=3")
            conn.execute("UPDATE users SET delegate_auto=0 WHERE id=3")
            conn.commit()
            conn.close()

    def test_hr_tree_uses_unit_names_with_the_responsible_first(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif, unit_code) VALUES (2060,'HRCHEF','CHEF PAUL','x',0,'service',2,1,'S1')")
        conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif) VALUES (2061,'HRAG','AGENT UN','x',0,'agent',2060,1)")
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) VALUES (2060, 2, 2060, 'CHEF', 'PAUL', '', 2, 2026, '{}', '[]')")
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) VALUES (2061, 2060, 2061, 'ZAGENT', 'UN', '', 2060, 2026, '{}', '[]')")
        conn.commit()
        conn.close()
        try:
            data = self._call("GET", "/api/hr-dashboard?year=2026", uid=1).get_json()

            def find(nodes, label):
                for n in nodes:
                    if n["label"] == label:
                        return n
                    sub = find(n.get("children") or [], label)
                    if sub:
                        return sub
                return None

            unit = find(data["tree"], "SERVICE PAIE")                      # le nom de l'entité, pas « CHEF PAUL »
            self.assertIsNotNone(unit)
            self.assertIsNone(find(data["tree"], "CHEF PAUL"))
            self.assertEqual([(f["label"], bool(f.get("resp"))) for f in unit["fiches"]], [("CHEF PAUL", True), ("ZAGENT UN", False)])
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM agents WHERE id IN (2060, 2061)")
            conn.execute("DELETE FROM users WHERE id IN (2060, 2061)")
            conn.commit()
            conn.close()

    def test_own_fiche_is_a_request_even_for_an_admin(self):
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif) VALUES (2070,'ADMOWN','Admin Own','x',1,'direction',2,1)")
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
                     "VALUES (2070, 2, 2070, 'OWN', 'ADMIN', 'a@b.fr', 2, 2026, '{}', '[]')")
        conn.commit()
        conn.close()
        try:
            me = self._call("GET", "/api/agents/2070?year=2026", uid=2070).get_json()
            self.assertEqual((me["can_edit_cells"], me["can_request"]), (False, True))      # demande, pas de saisie directe
            other = self._call("GET", "/api/agents/2070?year=2026", uid=1).get_json()      # un autre administrateur saisit directement
            self.assertTrue(other["can_edit_cells"])
            conn = db.get_db()
            admin_row = row = dict(conn.execute("SELECT * FROM users WHERE id=2070").fetchone())
            self.assertEqual(self.app_module._request_validator(conn, admin_row), 2)       # sa demande va à son valideur
            conn.close()
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM agents WHERE id=2070")
            conn.execute("DELETE FROM users WHERE id=2070")
            conn.commit()
            conn.close()

    def test_unit_list_is_the_whole_direction_and_email_matricule_are_locked(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        conn = db.get_db()
        conn.execute("UPDATE users SET unit_code='K1', email='ag1@ville.fr', matricule='LOCK01' WHERE id=4")
        conn.execute("UPDATE agents SET matricule='LOCK01' WHERE id=1")
        conn.commit()
        conn.close()
        try:
            r = self._call("GET", "/api/my-agents/4/unit", uid=1).get_json()
            # K1 (secteur) → toute la direction D1 : la direction, ses services et ses secteurs ; pas D2.
            self.assertEqual((r["unit_code"], sorted(u["code"] for u in r["units"])), ("K1", ["D1", "K1", "S1"]))
            ok = self._call("PUT", "/api/my-agents/4/unit", uid=1, payload={"unit_code": "S1"})
            self.assertEqual(ok.status_code, 200, ok.get_json())
            self.assertEqual(self._call("PUT", "/api/my-agents/4/unit", uid=1, payload={"unit_code": "D2"}).status_code, 400)   # autre direction
            self.assertEqual(self._call("GET", "/api/my-agents/4/unit", uid=4).status_code, 403)                                  # un agent n'a pas accès
            # E-mail et matricule, une fois renseignés, ne se modifient plus depuis la fiche.
            fiche = self._call("GET", "/api/agents/1?year=2026", uid=1).get_json()
            body = {"nom": fiche["nom"], "prenom": fiche["prenom"], "email": "pirate@x.fr", "matricule": "AUTRE99",
                    "validator_id": fiche["validator_id"], "params": fiche["params"], "periods": fiche["periods"], "cells": fiche["cells"]}
            conn = db.get_db()
            before = conn.execute("SELECT email, matricule FROM agents WHERE id=1").fetchone()
            conn.close()
            upd = self._call("PUT", "/api/agents/1", uid=1, payload=body)
            self.assertEqual(upd.status_code, 200, upd.get_json())
            conn = db.get_db()
            after = conn.execute("SELECT email, matricule FROM agents WHERE id=1").fetchone()
            conn.close()
            self.assertEqual((after["email"], after["matricule"]), ("agent@example.fr", "LOCK01"))
        finally:
            conn = db.get_db()
            conn.execute("UPDATE users SET unit_code='', email='', matricule='' WHERE id=4")
            conn.execute("UPDATE agents SET matricule='' WHERE id=1")
            conn.commit()
            conn.close()

    def test_duplicate_carries_the_period_and_years_are_listed(self):
        periods = [{"start": "2026-01-01", "end": "2026-06-30", "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5},
                   {"start": "2026-07-01", "end": "2026-12-31", "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "80%",
                    "jours_hebdo": 4, "jours_travailles": [1, 2, 3, 4], "ferie_travaille": True}]
        conn = db.get_db()
        conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
                     "VALUES (2080, 2, 5, 'PERIODE', 'UN', '', 2, 2026, '{}', ?)", (json.dumps(periods),))
        conn.commit()
        conn.close()
        try:
            r = self._call("POST", "/api/agents/duplicate", uid=1, payload={"ids": [2080], "year": 2027})
            self.assertEqual(len(r.get_json()["created"]), 1, r.get_json())
            conn = db.get_db()
            new = conn.execute("SELECT periods, params FROM agents WHERE agent_user_id=5 AND year=2027").fetchone()
            conn.close()
            per = json.loads(new["periods"])
            # La période en vigueur en fin d'année (80 %, 4 jours, fériés travaillés) couvre toute l'année suivante.
            self.assertEqual([(x["start"], x["end"], x["quotite"], x["jours_travailles"], x["ferie_travaille"]) for x in per],
                             [("2027-01-01", "2027-12-31", "80%", [1, 2, 3, 4], True)])
            again = self._call("POST", "/api/agents/duplicate", uid=1, payload={"ids": [2080], "year": 2027}).get_json()
            self.assertEqual((again["created"], "existe déjà" in again["errors"][0]["error"]), ([], True))
            years = self._call("GET", "/api/my-agents/5/years", uid=1).get_json()
            self.assertEqual([y["year"] for y in years], [2026, 2027])
            self.assertEqual(self._call("GET", "/api/my-agents/5/years", uid=4).status_code, 403)       # un autre agent n'y a pas accès
            self.assertEqual(self._call("GET", "/api/my-agents/4/years", uid=4).status_code, 200)       # on voit ses propres années
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM agents WHERE agent_user_id=5 AND year IN (2026, 2027) AND id>=2080 OR (agent_user_id=5 AND year=2027)")
            conn.commit()
            conn.close()

    def test_units_include_teams_carried_by_agents_but_missing_from_the_tree(self):
        tree = {"data": [{"code": "BF", "libelle": "DSI", "services": [{"code": "BF1", "libelle": "DSI", "secteurs": []}]}]}
        agents = [{"matricule": "1", "direction": {"code": "BF"}, "service": {"code": "BF1", "libelle": "DSI"},
                   "secteur": {"code": "BF1112", "libelle": "EQUIPE PROJET EDUC. INNOVATION INCLUSION"}, "affectation": {"code": "BF1", "libelle": "DSI"}}]
        sedit_rh._ORG.update(at=0.0, units=None)
        with mock.patch.object(sedit_rh, "_get", lambda path, params=None, timeout=30: tree),                 mock.patch.object(sedit_rh, "all_agents", lambda force=False: agents):
            units = {u["code"]: u for u in sedit_rh.organisation_units(force=True)}
        sedit_rh._ORG.update(at=0.0, units=None)
        self.assertEqual((units["BF1112"]["parent_code"], units["BF1112"]["level"]), ("BF1", "equipe"))   # rattachée à BF1 (préfixe connu)
        self.assertEqual(sorted(units), ["BF", "BF1", "BF1112"])

    def test_local_unit_and_unit_head(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        conn = db.get_db()
        conn.execute("UPDATE users SET unit_code='S1' WHERE id=4")
        conn.commit()
        conn.close()
        try:
            made = self._call("POST", "/api/my-agents/units", uid=1, payload={"libelle": "Numérique éducatif", "parent_code": "S1"})
            self.assertEqual(made.status_code, 200, made.get_json())
            code = made.get_json()["code"]
            self.assertEqual(self._call("POST", "/api/my-agents/units", uid=1, payload={"libelle": "numérique éducatif", "parent_code": "S1"}).status_code, 400)  # doublon
            self.assertEqual(self._call("POST", "/api/my-agents/units", uid=1, payload={"libelle": "X", "parent_code": "NOPE"}).status_code, 400)
            opts = self._call("GET", "/api/my-agents/4/unit", uid=1).get_json()["units"]
            self.assertIn(code, [u["code"] for u in opts])                                     # la liste de la direction contient l'unité locale
            ok = self._call("PUT", "/api/my-agents/4/unit", uid=1, payload={"unit_code": code, "head": True})
            self.assertEqual(ok.status_code, 200, ok.get_json())
            unit = [u for u in self._call("GET", "/api/my-agents/4/unit", uid=1).get_json()["units"] if u["code"] == code][0]
            self.assertEqual((unit["local"], unit["head_user_id"], unit["level"]), (True, 4, "secteur"))
            # La synchronisation Sedit RH ne supprime pas les unités locales.
            with self._units_patch():
                self._call("GET", "/api/org-units?refresh=1", uid=1)
            self.assertIn(code, [u["code"] for u in self._call("GET", "/api/org-units", uid=1).get_json()])
            self.assertEqual(self._call("POST", "/api/my-agents/units", uid=4, payload={"libelle": "Y", "parent_code": "S1"}).status_code, 403)   # un agent ne crée pas d'unité
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM org_units WHERE local=1")
            conn.execute("UPDATE users SET unit_code='' WHERE id=4")
            conn.commit()
            conn.close()

    def test_planning_reasons_for_my_team_and_presence_only_for_supervisors(self):
        conn = db.get_db()
        for fid, owner, who, nom in ((2090, 1, 2, "DRH"), (2091, 2, 3, "SECT")):
            conn.execute("INSERT INTO agents (id, user_id, agent_user_id, nom, prenom, email, validator_id, year, params, periods) "
                         "VALUES (?,?,?,?,'X','',?,2026,'{}','[]')", (fid, owner, who, nom, owner))
        conn.execute("INSERT INTO cells (agent_id, jour, code) VALUES (2090, 5010, 'CA'), (2091, 5020, 'RTT'), (1, 5030, 'CA')")
        conn.commit()
        conn.close()
        try:
            def rows(uid):
                data = self._call("GET", "/api/planning?year=2026&month=5&all=1", uid=uid).get_json()
                return {a["id"]: a for a in data["agents"]}

            boss = rows(3)                                                       # SECT1 : encadrant de AGENT1 ; DRH est son propre encadrant
            self.assertEqual(boss[1]["cells"], {"5030": "CA"})                   # ses agents : la raison
            self.assertEqual(boss[2091]["cells"], {"5020": "RTT"})               # sa propre fiche : la raison
            self.assertEqual((boss[2090]["cells"], boss[2090]["supervisor"], boss[2090]["masked"]), ({"5010": "A"}, True, True))   # son valideur : présence / absence
            agent = rows(4)                                                      # simple agent : jamais la raison, mais voit ses encadrants
            self.assertEqual(agent[1]["cells"], {"5030": "A"})
            self.assertIn(2090, agent)
            self.assertEqual(agent[2090]["cells"], {"5010": "A"})
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM cells WHERE agent_id IN (2090, 2091) OR (agent_id=1 AND jour=5030)")
            conn.execute("DELETE FROM agents WHERE id IN (2090, 2091)")
            conn.commit()
            conn.close()

    def test_login_is_case_insensitive(self):
        conn = db.get_db()
        conn.execute("UPDATE users SET mot_de_passe=? WHERE id=3", (self.app_module.generate_password_hash("Motdepasse-1"),))
        conn.commit()
        conn.close()
        with mock.patch.object(config, "AUTH_MODE", "local"):
            for name in ("SECT1", "sect1", "Sect1"):
                r = self.client.post("/api/auth/login", json={"login": name, "password": "Motdepasse-1"})
                self.assertEqual(r.status_code, 200, name)
                self.assertEqual(r.get_json()["user"]["login"], "SECT1")
            self.assertEqual(self.client.post("/api/auth/login", json={"login": "inconnu", "password": "x"}).status_code, 401)

    def test_my_agents_tree_sirh_list_attach_and_move(self):
        conn = db.get_db()
        for uid, login, role, parent, unit in ((2003, "MAVAL", "service", 2, "D1"), (2001, "MAAG1", "agent", 2003, "K1"),
                                                (2002, "MAAG2", "agent", 2003, "K1")):
            conn.execute("INSERT INTO users (id, login, nom, mot_de_passe, admin, role, parent_id, actif, unit_code) "
                         "VALUES (?,?,?,?,0,?,?,1,?)", (uid, login, login, "x", role, parent, unit))
        conn.commit()
        conn.close()

        def rh(mat, nom, prenom, unit):
            return {"matricule": mat, "nom": nom, "prenom": prenom, "affectation": {"code": unit, "libelle": unit},
                    "date_arrivee": "2010-01-01", "en_poste": True}

        agents = [rh("MA100", "ZZALPHA", "Anna", "K1"), rh("MA200", "ZZBETA", "Bob", "D2")]
        try:
            with self._units_patch(), mock.patch.object(sedit_rh, "all_agents", lambda force=False: agents):
                self._call("GET", "/api/org-units?refresh=1", uid=1)
                tree = self._call("GET", "/api/my-agents", uid=2003).get_json()
                self.assertEqual((tree["id"], [c["login"] for c in tree["children"]], tree["count"]), (2003, ["MAAG1", "MAAG2"], 2))
                # Seuls les agents de mon unité ou en dessous (K1 sous D1), pas ceux de D2, ni les accès d'un agent.
                lst = self._call("GET", "/api/my-agents/sirh", uid=2003).get_json()
                self.assertEqual([i["matricule"] for i in lst["items"]], ["MA100"])
                self.assertEqual(self._call("GET", "/api/my-agents", uid=4).status_code, 403)
                # Déposer Anna sous MAAG1 : elle est créée sous lui, MAAG1 devient valideur (niveau sous celui de MAVAL) et garde son unité.
                r = self._call("POST", "/api/my-agents/attach", uid=2003, payload={"matricule": "MA100", "parent_id": 2001, "unit_code": "K1"})
                self.assertEqual(r.status_code, 200, r.get_json())
                conn = db.get_db()
                anna = conn.execute("SELECT id, parent_id, unit_code, role FROM users WHERE matricule='MA100'").fetchone()
                self.assertIsNone(conn.execute("SELECT 1 FROM agents WHERE agent_user_id=?", (anna["id"],)).fetchone())  # pas de fiche sans période
                boss = conn.execute("SELECT role, unit_code FROM users WHERE id=2001").fetchone()
                conn.close()
                self._seed_period_settings()
                self.assertEqual(self._call("POST", "/api/my-agents/%d/fiche" % anna["id"], uid=2003, payload={
                    "year": 2026, "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5}).status_code, 200)
                conn = db.get_db()
                fiche = conn.execute("SELECT user_id, validator_id FROM agents WHERE agent_user_id=?", (anna["id"],)).fetchone()
                conn.close()
                self.assertEqual((anna["parent_id"], anna["unit_code"], anna["role"]), (2001, "K1", "agent"))
                self.assertEqual((fiche["user_id"], fiche["validator_id"]), (2001, 2001))
                # Bouton « Dupliquer pour N+1 » : proposé tant que la fiche de l'année suivante n'existe pas.
                def anna_node():
                    stack = [self._call("GET", "/api/my-agents?year=2026&depth=all", uid=2003).get_json()]
                    while stack:
                        n = stack.pop()
                        if n["matricule"] == "MA100":
                            return n
                        stack.extend(n["children"])

                self.assertEqual(anna_node()["fiche"]["next_exists"], False)
                dup = self._call("POST", "/api/agents/duplicate", uid=2003, payload={"ids": [anna_node()["fiche"]["id"]], "year": 2027})
                self.assertEqual(len(dup.get_json()["created"]), 1, dup.get_json())
                self.assertEqual(anna_node()["fiche"]["next_exists"], True)
                self.assertEqual((boss["role"], boss["unit_code"]), ("secteur", "K1"))        # niveau de son unité (secteur), sous celui de MAVAL (service)
                # Anna est maintenant dans l'application : plus proposée. Hors périmètre ou doublon : refusé.
                self.assertEqual(self._call("GET", "/api/my-agents/sirh", uid=2003).get_json()["total"], 0)
                # Hors de mon unité : absent de la liste par défaut, proposé avec « toute la collectivité », et rattachable.
                self.assertEqual(self._call("GET", "/api/my-agents/sirh?scope=all", uid=2003).get_json()["total"], 1)
                self.assertEqual(self._call("POST", "/api/my-agents/attach", uid=2003, payload={"matricule": "MA200", "parent_id": 2001}).status_code, 200)
                # Mais jamais sous une personne qui n'est pas dans mon périmètre.
                self.assertEqual(self._call("POST", "/api/my-agents/attach", uid=2003, payload={"matricule": "MA200", "parent_id": 3}).status_code, 403)
                self.assertEqual(self._call("POST", "/api/my-agents/attach", uid=2003, payload={"matricule": "MA100", "parent_id": 2001}).status_code, 400)
                # Déplacement : MAAG2 sous MAAG1 ; interdit sous soi-même / un subordonné ; hors périmètre refusé.
                self.assertEqual(self._call("POST", "/api/my-agents/move", uid=2003, payload={"user_id": 2002, "parent_id": 2001}).status_code, 200)
                self.assertEqual(self._call("POST", "/api/my-agents/move", uid=2003, payload={"user_id": 2001, "parent_id": 2002}).status_code, 400)
                self.assertEqual(self._call("POST", "/api/my-agents/move", uid=2003, payload={"user_id": 3, "parent_id": 2001}).status_code, 403)
                tree = self._call("GET", "/api/my-agents", uid=2003).get_json()
                self.assertEqual(tree["count"], 4)
                # Par défaut : mes personnes directes ; « toute ma ligne hiérarchique » : de proche en proche.
                self.assertEqual([c["login"] for c in tree["children"]], ["MAAG1"])
                self.assertEqual((tree["children"][0]["children"], tree["children"][0]["more"], tree["children"][0]["count"]), ([], True, 3))
                full = self._call("GET", "/api/my-agents?depth=all", uid=2003).get_json()
                self.assertEqual(len(full["children"][0]["children"]), 3)
                # Recherche AD : candidats puis rattachement (l'adresse est relue dans l'annuaire, jamais prise du navigateur).
                hits = [{"username": "ma-zzdeux", "displayName": "ZZDEUX Anne", "email": "anne@ville.fr"}]
                with mock.patch.object(apm, "configured", lambda: True), mock.patch.object(apm, "ad_search", lambda q, limit=15: hits):
                    cand = self._call("GET", "/api/my-agents/2002/ad?q=zzdeux", uid=2003).get_json()
                    self.assertEqual((cand["status"], cand["candidates"][0]["username"]), ("unique", "ma-zzdeux"))
                    ok = self._call("POST", "/api/my-agents/2002/ad", uid=2003, payload={"username": "ma-zzdeux", "email": "pirate@x.fr"})
                    self.assertEqual((ok.status_code, ok.get_json()["email"]), (200, "anne@ville.fr"))
                    self.assertEqual(self._call("POST", "/api/my-agents/2001/ad", uid=2003, payload={"username": "ma-zzdeux"}).status_code, 400)   # déjà pris
                    self.assertEqual(self._call("POST", "/api/my-agents/3/ad", uid=2003, payload={"username": "ma-zzdeux"}).status_code, 403)       # hors périmètre
                conn = db.get_db()
                self.assertEqual(conn.execute("SELECT email, ad_login FROM users WHERE id=2002").fetchone()["email"], "anne@ville.fr")
                conn.close()
                # Nom et prénom séparés dans la fiche, même pour un compte créé avant l'enregistrement du prénom (repris de Sedit RH).
                conn = db.get_db()
                conn.execute("UPDATE users SET matricule='MA300', nom='ZZGAMMA GINA', nom_famille='', prenom='' WHERE id=2002")
                conn.commit()
                conn.close()
                agents.append(rh("MA300", "ZZGAMMA", "Gina", "K1"))
                self.assertEqual(self._call("POST", "/api/my-agents/2002/fiche", uid=2003, payload={
                    "year": 2026, "penibilite": "Modérée", "duree_hebdo": "38 heures", "quotite": "100%", "jours_hebdo": 5}).status_code, 200)
                conn = db.get_db()
                gina = conn.execute("SELECT nom, prenom FROM agents WHERE agent_user_id=2002").fetchone()
                acct = conn.execute("SELECT nom_famille, prenom FROM users WHERE id=2002").fetchone()
                conn.close()
                self.assertEqual((gina["nom"], gina["prenom"], acct["nom_famille"], acct["prenom"]), ("ZZGAMMA", "GINA", "ZZGAMMA", "GINA"))
        finally:
            conn = db.get_db()
            conn.execute("DELETE FROM agents WHERE user_id IN (2001, 2002, 2003) OR agent_user_id IN (SELECT id FROM users WHERE matricule IN ('MA100', 'MA200'))")
            conn.execute("DELETE FROM users WHERE id IN (2001, 2002, 2003) OR matricule IN ('MA100', 'MA200')")
            conn.commit()
            conn.close()

    def test_business_rules_document_is_served(self):
        r = self._call("GET", "/api/docs/regles-metier", uid=4)
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertIn("# Règles métier", text)
        self.assertIn("Mon équipe", text)

    def test_direction_valideur_is_validated_by_a_dga(self):
        with self._units_patch():
            self._call("GET", "/api/org-units?refresh=1", uid=1)
        with mock.patch.object(config, "AUTH_MODE", "ad"):
            dga = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "level": "dga", "nom": "Zzdga", "prenom": "Dora"})
            self.assertEqual(dga.status_code, 200, dga.get_json())
            self.assertEqual((dga.get_json()["role"], dga.get_json()["unit_code"]), ("dga", ""))
            # Une direction n'a pas d'unité supérieure : son valideur est le DGA choisi.
            d = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "nom": "Zzdir", "prenom": "Marc", "unit_code": "D2", "supervisor_id": dga.get_json()["id"]})
            self.assertEqual(d.status_code, 200, d.get_json())
            self.assertEqual((d.get_json()["role"], d.get_json()["parent_id"]), ("direction", dga.get_json()["id"]))
            # Un DGA ne peut pas être validé par un niveau inférieur.
            bad = self._call("POST", "/api/users/person", uid=1, payload={
                "profil": "valideur", "level": "dga", "nom": "Zzbad2", "prenom": "Z", "supervisor_id": d.get_json()["id"]})
            self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
