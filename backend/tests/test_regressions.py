# -*- coding: utf-8 -*-
"""Tests de non-regression du prototype Suivi des conges.

Lancement :
    python -m unittest discover -s tests -v
"""
import json
import unittest
import uuid
from unittest import mock

import config

# Schéma PostgreSQL temporaire, créé puis supprimé par la classe de test : la base
# réelle de l'application n'est jamais touchée.
config.PG_SCHEMA = "conges_test_" + uuid.uuid4().hex[:8]

import apm  # noqa: E402
import db  # noqa: E402
import mailer  # noqa: E402
import pg_db  # noqa: E402
import ratelimit  # noqa: E402


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

        with mock.patch.object(config, "MAIL_ENABLED", True), \
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
        with mock.patch.object(config, "MAIL_ENABLED", False):
            self.assertFalse(mailer.send_mail("a@b.fr", "s", "c")[0])
        with mock.patch.object(config, "MAIL_ENABLED", True), \
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


if __name__ == "__main__":
    unittest.main()
