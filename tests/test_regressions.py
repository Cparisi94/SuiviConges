# -*- coding: utf-8 -*-
"""Tests de non-regression du prototype Suivi des conges.

Lancement :
    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import tempfile
import unittest

import db


class PrototypeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_db_path = db.DB_PATH
        cls.tmpdir = tempfile.mkdtemp(prefix="conges-tests-")
        cls.test_db = os.path.join(cls.tmpdir, "test.db")
        db.DB_PATH = cls.test_db
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
        conn.commit()
        conn.close()

        import app as application
        application.app.config["TESTING"] = True
        cls.app_module = application
        cls.client = application.app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.old_db_path
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _call(self, method, path, uid=1, payload=None):
        headers = {"X-User-Id": str(uid)}
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

    def test_backup_and_restore_check(self):
        from backup_db import create_backup, verify_backup
        backup_dir = os.path.join(self.tmpdir, "backups")
        path, result = create_backup(db_path=self.test_db, backup_dir=backup_dir, keep=2)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(result["ok"])
        check = verify_backup(path)
        self.assertTrue(check["ok"])
        self.assertEqual(check["counts"]["users"], 5)


if __name__ == "__main__":
    unittest.main()
