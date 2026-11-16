# -*- coding: utf-8 -*-
"""Unité par défaut d'un agent issu de Sedit RH : un directeur est rattaché à sa direction, pas au secteur où il est affecté."""
import unittest

import sedit_rh


def _agent(poste, direction=("BF", "DIRECTION DES SYSTEMES D'INFORMATION"), affectation=("BF1", "SECTEUR DSI")):
    return {
        "matricule": "0000001", "nom": "NOM", "prenom": "PRENOM",
        "direction": {"code": direction[0], "libelle": direction[1]} if direction else None,
        "affectation": {"code": affectation[0], "libelle": affectation[1]},
        "poste": {"code": "PT1", "libelle": poste},
    }


class UniteDuDirecteurTest(unittest.TestCase):
    def test_directeur_rattache_a_sa_direction(self):
        s = sedit_rh._agent_summary(_agent("DIRECTEUR·TRICE DES SYSTEMES D'INFORMATION"))
        self.assertEqual(s["unit_code"], "BF")
        self.assertEqual(s["unit_libelle"], "DIRECTION DES SYSTEMES D'INFORMATION")

    def test_directrice_au_feminin(self):
        self.assertEqual(sedit_rh._agent_summary(_agent("Directrice des finances"))["unit_code"], "BF")

    def test_adjoint_et_direction_generale_gardent_leur_affectation(self):
        self.assertEqual(sedit_rh._agent_summary(_agent("DIRECTEUR ADJOINT DES SYSTEMES D'INFORMATION"))["unit_code"], "BF1")
        self.assertEqual(sedit_rh._agent_summary(_agent("DIRECTEUR GENERAL DES SERVICES"))["unit_code"], "BF1")

    def test_autre_poste_garde_son_affectation(self):
        self.assertEqual(sedit_rh._agent_summary(_agent("RESPONSABLE ADMINISTRATIF·TIVE ET FINANCIER·E"))["unit_code"], "BF1")
        self.assertEqual(sedit_rh._agent_summary(_agent("CHARGE DE MISSION AUPRES DU DIRECTEUR"))["unit_code"], "BF1")

    def test_directeur_sans_direction_connue_garde_son_affectation(self):
        self.assertEqual(sedit_rh._agent_summary(_agent("DIRECTEUR·TRICE DES FINANCES", direction=None))["unit_code"], "BF1")


if __name__ == "__main__":
    unittest.main()
