# -*- coding: utf-8 -*-
"""Soldes de CET lus dans l'API Sedit RH : regroupement par matricule, somme des comptes ouverts, lots et cache."""
import threading
import time
import unittest
from unittest import mock

import sedit_rh


def _compte(matricule, solde):
    return {"matricule": matricule, "solde_calcule": solde, "ouvert": True}


class CetBalancesTest(unittest.TestCase):
    """Soldes de CET : regroupement par matricule, cache en base (simulée ici) et recalcul en arrière-plan."""

    def setUp(self):
        sedit_rh._cet_cache.clear()
        sedit_rh._cet_inflight.clear()
        sedit_rh._cet_retry_after[0] = 0.0
        self.db = {}                                                    # simule la table sedit_cet_cache
        self._patches = [
            mock.patch.object(sedit_rh, "_db_load", lambda mats: {m: self.db[m] for m in mats if m in self.db}),
            mock.patch.object(sedit_rh, "_db_store", lambda items: self.db.update(items)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    @staticmethod
    def _solde(out):
        return {m: (v["solde"], v["comptes"]) for m, v in out.items()}

    def test_somme_des_comptes_et_matricule_sans_cet_absent(self):
        data = {"data": [_compte("0000001", 60.0), _compte("0000002", 10.0), _compte("0000002", 2.5)]}
        with mock.patch.object(sedit_rh, "_get", return_value=data) as get:
            out = sedit_rh.cet_balances(["0000001", "0000002", "0000003", " ", None])
        self.assertEqual(self._solde(out), {"0000001": (60.0, 1), "0000002": (12.5, 2)})
        self.assertRegex(out["0000001"]["as_of"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args[0][1]["matricules"], "0000001,0000002,0000003")     # une requête, matricules triés et dédoublonnés
        self.assertEqual(get.call_args[0][1]["ouvert"], "true")

    def test_cache_et_lots_de_100(self):
        mats = ["%07d" % i for i in range(250)]
        with mock.patch.object(sedit_rh, "_get", return_value={"data": []}) as get:
            sedit_rh.cet_balances(mats)
            self.assertEqual(get.call_count, 3)                                              # 100 + 100 + 50
            sedit_rh.cet_balances(mats)
            self.assertEqual(get.call_count, 3)                                              # le second appel vient du cache (même les absents)

    def test_le_cache_survit_a_un_redemarrage(self):
        with mock.patch.object(sedit_rh, "_get", return_value={"data": [_compte("0000001", 60.0)]}):
            sedit_rh.cet_balances(["0000001"])
        self.assertIn("0000001", self.db)                                                    # enregistré en base
        sedit_rh._cet_cache.clear()                                                          # « redémarrage » : la mémoire est vide
        with mock.patch.object(sedit_rh, "_get", side_effect=AssertionError("pas d'appel : le cache de la base suffit")):
            self.assertEqual(self._solde(sedit_rh.cet_balances(["0000001"])), {"0000001": (60.0, 1)})
            self.assertEqual(sedit_rh.cet_cached("0000001"), 60.0)

    def test_solde_perime_servi_tout_de_suite_et_recalcule_en_arriere_plan(self):
        old = time.time() - 3 * sedit_rh._CET_TTL
        sedit_rh._cet_cache["0000001"] = (old, {"solde": 10.0, "comptes": 1})
        started = threading.Event()
        release = threading.Event()

        def slow_get(path, params=None, timeout=30):
            started.set()
            release.wait(5)
            return {"data": [_compte("0000001", 42.0)]}

        with mock.patch.object(sedit_rh, "_get", slow_get):
            t0 = time.time()
            out = sedit_rh.cet_balances(["0000001"])
            self.assertLess(time.time() - t0, 1.0)                                           # la page n'attend pas Sedit RH
            self.assertEqual(self._solde(out), {"0000001": (10.0, 1)})                       # ancienne valeur, tout de suite
            self.assertTrue(started.wait(3))                                                 # le recalcul a démarré en arrière-plan
            release.set()
            for _ in range(50):
                if sedit_rh.cet_cached("0000001") == 42.0:
                    break
                time.sleep(0.05)
        self.assertEqual(sedit_rh.cet_cached("0000001"), 42.0)                               # valeur recalculée
        self.assertEqual(self.db["0000001"][1]["solde"], 42.0)                               # et enregistrée en base
        self.assertEqual(sedit_rh._cet_inflight, set())

    def test_panne_de_sedit_rh_ancienne_valeur_conservee_et_pas_de_boucle(self):
        sedit_rh._cet_cache["0000001"] = (time.time() - 3 * sedit_rh._CET_TTL, {"solde": 10.0, "comptes": 1})
        calls = []

        def failing(path, params=None, timeout=30):
            calls.append(1)
            raise sedit_rh.SeditError("Sedit RH injoignable")

        with mock.patch.object(sedit_rh, "_get", failing):
            self.assertEqual(self._solde(sedit_rh.cet_balances(["0000001"])), {"0000001": (10.0, 1)})   # pas d'erreur : la valeur connue reste servie
            for _ in range(60):
                if sedit_rh._cet_retry_after[0] > time.time():
                    break
                time.sleep(0.05)
            self.assertEqual(self._solde(sedit_rh.cet_balances(["0000001"])), {"0000001": (10.0, 1)})
            time.sleep(0.2)
        self.assertEqual(len(calls), 1)                                                      # pas de nouvel essai avant une minute

    def test_jamais_lu_et_api_en_panne_erreur_propagee(self):
        with mock.patch.object(sedit_rh, "_get", side_effect=sedit_rh.SeditError("Accès refusé", 403)):
            with self.assertRaises(sedit_rh.SeditError):
                sedit_rh.cet_balances(["0000001"])


class ContractEndTest(unittest.TestCase):
    def setUp(self):
        sedit_rh._end_cache.clear()

    def test_date_de_depart_cache_et_agent_inconnu(self):
        with mock.patch.object(sedit_rh, "_get", return_value={"data": {"matricule": "0000001", "date_depart": "2027-06-30"}}) as get:
            self.assertEqual(sedit_rh.contract_end(" 0000001 "), "2027-06-30")
            self.assertEqual(sedit_rh.contract_end("0000001"), "2027-06-30")
            self.assertEqual(get.call_count, 1)                                                                # second appel : cache
            self.assertEqual(get.call_args[0][0], "/api/v1/agents/0000001")
        with mock.patch.object(sedit_rh, "_get", return_value={"data": {"date_depart": None}}):
            self.assertIsNone(sedit_rh.contract_end("0000002"))                                                # pas de date de départ
        with mock.patch.object(sedit_rh, "_get", side_effect=sedit_rh.SeditError("Introuvable", 404)):
            self.assertIsNone(sedit_rh.contract_end("0000003"))                                                # agent inconnu : pas de date
        with mock.patch.object(sedit_rh, "_get", side_effect=sedit_rh.SeditError("Injoignable")):
            with self.assertRaises(sedit_rh.SeditError):
                sedit_rh.contract_end("0000004")                                                               # panne : propagée (le report l'indique)
        self.assertIsNone(sedit_rh.contract_end(""))


def _abs(code_app, debut, fin=None, **plus):
    return dict({"famille": {"code": "x", "libelle": "Libellé détaillé de la famille", "code_app": code_app}, "date_debut": debut, "date_fin": fin,
                 "nature": {"code": "ALD"}, "type": {"code": "CLM1"}}, **plus)


class AbsencesRhTest(unittest.TestCase):
    def setUp(self):
        sedit_rh._abs_cache.clear()

    def test_codes_du_calendrier_dates_et_aucun_detail_medical(self):
        data = {"data": [_abs("GEM", "2026-03-10", "2026-03-10"), _abs("CM", "2026-02-02", "2026-02-06"), _abs("CM", "2026-05-04", None), _abs("ZZ", "2026-06-01", "2026-06-02")]}
        with mock.patch.object(sedit_rh, "_get", return_value=data) as get:
            out = sedit_rh.absences(" 0000001 ", 2026)
        self.assertEqual(out, [
            {"code": "CM", "libelle": "Congé maladie", "debut": "2026-02-02", "fin": "2026-02-06"},
            {"code": "GEM", "libelle": "Garde d'enfant malade", "debut": "2026-03-10", "fin": "2026-03-10"},
            {"code": "CM", "libelle": "Congé maladie", "debut": "2026-05-04", "fin": "2026-05-04"},          # fin absente : le jour de début
        ])                                                                                                    # code inconnu écarté ; ni nature ni type (ALD, longue maladie…)
        self.assertEqual(get.call_args[0][1]["matricule"], "0000001")
        self.assertEqual((get.call_args[0][1]["du"], get.call_args[0][1]["au"]), ("2026-01-01", "2026-12-31"))
        with mock.patch.object(sedit_rh, "_get", side_effect=AssertionError("cache")):
            self.assertEqual(len(sedit_rh.absences("0000001", 2026)), 3)                                       # second appel : cache

    def test_erreur_de_l_api_est_propagee(self):
        with mock.patch.object(sedit_rh, "_get", side_effect=sedit_rh.SeditError("Accès refusé", 403)):
            with self.assertRaises(sedit_rh.SeditError):
                sedit_rh.absences("0000001", 2026)


if __name__ == "__main__":
    unittest.main()
