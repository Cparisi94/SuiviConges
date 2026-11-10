# -*- coding: utf-8 -*-
"""Cohérence du versionnage : version.py, CHANGELOG.md et MANIFEST.md doivent rester en phase.

Ces tests échouent si une version est livrée sans documentation (voir CLAUDE.md, « Procédure de
livraison d'une version »). Ils n'ont pas besoin de la base de données.
"""
import os
import re
import unittest

import version

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _as_tuple(value):
    return tuple(int(part) for part in value.split("."))


class VersionTests(unittest.TestCase):
    def test_version_format_and_journal_head(self):
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(version.VERSIONS[0]["version"], version.VERSION)

    def test_journal_entries_are_well_formed_and_ordered(self):
        numbers = [_as_tuple(v["version"]) for v in version.VERSIONS]
        self.assertEqual(numbers, sorted(numbers, reverse=True), "Les versions doivent être de la plus récente à la plus ancienne")
        self.assertEqual(len(set(numbers)), len(numbers), "Version en double")
        for entry in version.VERSIONS:
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["version"])
            self.assertIn(entry["type"], ("minor", "patch"), entry["version"])
            self.assertTrue(entry["titre"].strip(), entry["version"])
            self.assertTrue(entry["items"], "Aucune nouveauté listée pour %s" % entry["version"])

    def test_changelog_matches_the_journal(self):
        changelog = _read("CHANGELOG.md")
        headings = re.findall(r"^## (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2}) — (.+)$", changelog, re.MULTILINE)
        self.assertEqual(
            [(v["version"], v["date"], v["titre"]) for v in version.VERSIONS],
            [(h[0], h[1], h[2].strip()) for h in headings],
            "CHANGELOG.md doit lister les mêmes versions (numéro, date, titre) que backend/version.py",
        )

    def test_manifest_mentions_the_current_version(self):
        manifest = _read("MANIFEST.md")
        self.assertIn("v%s" % version.VERSION, manifest.split("---", 1)[0], "Le statut du MANIFEST.md doit citer la version courante")
        self.assertIn("**%s**" % version.VERSION, manifest, "Le journal des versions du MANIFEST.md doit contenir la version courante")


class VersionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as application
        cls.client = application.app.test_client()

    def test_version_and_changelog_endpoints(self):
        body = self.client.get("/api/version").get_json()
        self.assertEqual(body["version"], version.VERSION)
        log = self.client.get("/api/changelog").get_json()
        self.assertEqual(log["version"], version.VERSION)
        self.assertEqual(log["versions"][0]["version"], version.VERSION)

    def test_swagger_declares_the_current_version(self):
        spec = self.client.get("/api/v1/openapi.json").get_json()
        self.assertEqual(spec["info"]["version"], version.VERSION)


if __name__ == "__main__":
    unittest.main()
