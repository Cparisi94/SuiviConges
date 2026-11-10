# -*- coding: utf-8 -*-
"""Import des paramètres depuis le classeur Excel d'origine.

Extrait les listes, la matrice de droits et les couleurs des codes, puis
les enregistre dans la base (table `settings`) dans la structure attendue
par `rules.py`.
"""
import os
import shutil
import sys
from datetime import date, timedelta

from openpyxl import load_workbook

from db import get_db, init_db, set_setting

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = r"C:\Users\CPARISI\Documents\Projet par défaut\Modèle Suivi congés 2027.xlsx"

# Couleurs des codes issues des règles de mise en forme conditionnelle (x14)
# de l'onglet AGENT du classeur d'origine. Chaque règle « cellIs equal »
# compare la cellule à 'Base (ne pas supprimer)'!B{N}, où B{N} = Paramétrage!N{N}.
# La couleur ci-dessous est donc celle réellement affichée par Excel.
CODE_ALIASES = {
    "CAF": ("CAH", "Congé annuel en heures", "FFE699"),
    "RTTF": ("RTTH", "RTT en heures", "C6E0B4"),
}

COULEURS_CODES = {
    "AI": "C00000", "AS": "757171", "CA26": "FFFF00", "CAH": "FFE699",
    "CET": "009900", "CM": "FF99FF", "CP": "FF99FF",
    "CT": "FF99FF", "ET": "C00000", "FP": "ED7D31", "GEM": "FF99FF",
    "GR": "F4B084", "JB": "FFC000", "JS": "ACB9CA",
    "MD": "FFFF99", "RTT": "92D050", "RTTH": "C6E0B4",
    "SF": "FF99FF", "SX": "002060", "TP": "BFBFBF", "TT": "00B0F0",
    # CA est coloré par la règle référençant Base!M5 (= Paramétrage!S5)
    "CA": "FFFF00",
}

# Jours fériés France 2026
JOURS_FERIES_2026 = [
    ("01-01", "Jour de l'an"),
    ("04-06", "Lundi de Pâques"),
    ("05-01", "Fête du Travail"),
    ("05-08", "Victoire 1945"),
    ("05-14", "Ascension"),
    ("05-25", "Lundi de Pentecôte"),
    ("07-14", "Fête nationale"),
    ("08-15", "Assomption"),
    ("11-01", "Toussaint"),
    ("11-11", "Armistice 1918"),
    ("12-25", "Noël"),
]

# Jours fériés France 2027 (repris du modèle, hachures du calendrier)
JOURS_FERIES_2027 = [
    ("01-01", "Jour de l'an"),
    ("03-29", "Lundi de Pâques"),
    ("05-01", "Fête du Travail"),
    ("05-06", "Ascension"),
    ("05-08", "Victoire 1945"),
    ("05-17", "Lundi de Pentecôte"),
    ("07-14", "Fête nationale"),
    ("08-15", "Assomption"),
    ("11-01", "Toussaint"),
    ("11-11", "Armistice 1918"),
    ("12-25", "Noël"),
]

# Vacances scolaires zone C (Créteil, Montpellier, Paris, Toulouse, Versailles).
# Calendriers officiels 2025-2026, 2026-2027 et 2027-2028.
# Bornes inclusives : le dernier jour est la veille de la reprise des cours.
VACANCES_SCOLAIRES_ZONE_C = [
    ("2025-12-20", "2026-01-04", "Vacances de Noël"),
    ("2026-02-21", "2026-03-08", "Vacances d'hiver"),
    ("2026-04-18", "2026-05-03", "Vacances de printemps"),
    ("2026-07-04", "2026-08-31", "Vacances d'été"),
    ("2026-10-17", "2026-11-01", "Vacances de la Toussaint"),
    ("2026-12-19", "2027-01-03", "Vacances de Noël"),
    ("2027-02-06", "2027-02-21", "Vacances d'hiver"),
    ("2027-04-03", "2027-04-18", "Vacances de printemps"),
    ("2027-07-03", "2027-09-01", "Vacances d'été"),
    ("2027-10-23", "2027-11-07", "Vacances de la Toussaint"),
    ("2027-12-18", "2028-01-02", "Vacances de Noël"),
]


def _col(ws, letter, first, last):
    """Valeurs non vides d'une colonne (ex. 'N', 3, 26)."""
    from openpyxl.utils import column_index_from_string
    ci = column_index_from_string(letter)
    out = []
    for r in range(first, last + 1):
        v = ws.cell(r, ci).value
        if v is not None and str(v).strip() != "":
            out.append(v)
    return out


def extract(source_path=None):
    source_path = source_path or os.environ.get("SOURCE_XLSX") or DEFAULT_SOURCE
    if not os.path.exists(source_path):
        print("[seed] Classeur source introuvable: %s" % source_path)
        print("[seed] Vous pourrez saisir les paramètres manuellement dans l'application.")
        return False

    wb = load_workbook(source_path, data_only=True)
    pa = wb["Paramétrage"]

    settings = {}

    # ---- année (T1) et bornes (T2/T3 en sérial Excel) --------------------
    year = pa["T1"].value
    if not isinstance(year, int):
        year = 2027

    def serial_to_iso(v):
        """Sérial Excel -> date ISO (epoch 1899-12-30)."""
        if isinstance(v, (int, float)):
            return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
        return None

    year_start = serial_to_iso(pa["T2"].value) or "%d-01-01" % year
    year_end = serial_to_iso(pa["T3"].value) or "%d-12-31" % year
    settings["general"] = {"year": year, "year_start": year_start, "year_end": year_end}

    # ---- codes d'absence (N = liste N, S = liste S) ----------------------
    codes_n = [str(c).strip() for c in _col(pa, "N", 3, 40)]
    codes_s = [str(c).strip() for c in _col(pa, "S", 3, 40)]
    lib_ad = _col(pa, "AD", 3, 12)
    lib_ae = _col(pa, "AE", 3, 12)
    lib_af = _col(pa, "AF", 3, 12)
    lib_ag = _col(pa, "AG", 3, 12)
    lib_ah = _col(pa, "AH", 3, 12)
    lib_ai = _col(pa, "AI", 3, 12)
    lib_aj = _col(pa, "AJ", 3, 12)
    lib_ak = _col(pa, "AK", 3, 12)
    libelles = {}
    for codes, libs in ((lib_ad, lib_ae), (lib_af, lib_ag),
                        (lib_ah, lib_ai), (lib_aj, lib_ak)):
        for code, lib in zip(codes, libs):
            if code:
                libelles[str(code).strip()] = lib

    all_codes = []
    seen = set()
    for code in codes_n + codes_s:
        if code in ("CB", "HS", "RC"):
            continue
        if code and code not in seen:
            seen.add(code)
            target = CODE_ALIASES.get(code)
            if target:
                new_code, new_label, new_color = target
                all_codes.append({
                    "code": new_code,
                    "libelle": new_label,
                    "color": new_color,
                    "in_n": True,
                    "in_s": False,
                })
            else:
                all_codes.append({
                    "code": code,
                    "libelle": libelles.get(code, code),
                    "color": COULEURS_CODES.get(code, "F2F2F2"),
                    "in_n": code in codes_n,
                    "in_s": code in codes_s,
                })
    if not any(c.get("code") == "RCH" for c in all_codes):
        all_codes.append({
            "code": "RCH",
            "libelle": "Récupération en heures",
            "color": "2F75B5",
            "in_n": True,
            "in_s": False,
        })
    settings["codes"] = all_codes

    # ---- pénibilités (O + Y:Z), durées (P), quotités (R), jours (Q) ------
    pen_sujections = {}
    for name, nb in zip(_col(pa, "Y", 3, 12), _col(pa, "Z", 3, 12)):
        pen_sujections[str(name).strip()] = nb
    settings["penibilites"] = [
        {"name": str(p).strip(), "sujections": pen_sujections.get(str(p).strip(), 0)}
        for p in _col(pa, "O", 3, 12)
    ]
    settings["durees"] = [str(d).strip() for d in _col(pa, "P", 3, 20)]
    settings["quotites"] = [str(q).strip() for q in _col(pa, "R", 3, 20)]
    settings["jours_hebdo"] = _col(pa, "Q", 3, 20)

    # ---- durées possibles par pénibilité (T24:V33) -----------------------
    pen_durees = {}
    for letter, pen in (("T", str(pa["T24"].value).strip()),
                        ("U", str(pa["U24"].value).strip()),
                        ("V", str(pa["V24"].value).strip())):
        pen_durees[pen] = [str(d).strip() for d in _col(pa, letter, 25, 40)]
    settings["penibilites_durees"] = pen_durees

    # ---- temps de travail -> NB RTT (V:W) --------------------------------
    settings["temps_travail"] = [
        {"name": str(n).strip(), "rtt": nb}
        for n, nb in zip(_col(pa, "V", 3, 20), _col(pa, "W", 3, 20))
    ]
    settings["durees_rtt"] = settings["temps_travail"]

    # ---- matrice des droits (B:E sur 546 lignes) -------------------------
    # La colonne L (droit CET) vaut "=E*4" sauf sur 6 lignes du classeur
    # (Forte + temps partiel) où elle est figée à 0 en dur. Ces valeurs
    # littérales sont conservées en override pour rester fidèles au modèle.
    wb_f = load_workbook(source_path, data_only=False)
    pa_f = wb_f["Paramétrage"]
    matrix = []
    overrides = 0
    for r in range(3, 600):
        pen = pa.cell(r, 2).value
        duree = pa.cell(r, 3).value
        quot = pa.cell(r, 4).value
        jours = pa.cell(r, 5).value
        if pen is None or duree is None or quot is None or jours is None:
            break
        row = {
            "pen": str(pen).strip(), "duree": str(duree).strip(),
            "quotite": str(quot).strip(), "jours": jours,
        }
        f_l = pa_f.cell(r, 12).value
        cached_l = pa.cell(r, 12).value
        if not (isinstance(f_l, str) and f_l.startswith("=")) and isinstance(cached_l, (int, float)):
            row["droit_cet"] = cached_l
            overrides += 1
        matrix.append(row)
    wb_f.close()
    settings["matrix"] = matrix
    print("[seed] Overrides droit CET (littéraux) :", overrides)

    # ---- jours fériés par défaut (année du modèle) -----------------------
    settings["jours_feries"] = (
        [["2026-%s" % md, lib] for md, lib in JOURS_FERIES_2026]
        + [["2027-%s" % md, lib] for md, lib in JOURS_FERIES_2027]
    )

    # ---- vacances scolaires zone C (2027) --------------------------------
    settings["vacances_scolaires"] = [list(v) for v in VACANCES_SCOLAIRES_ZONE_C]

    wb.close()

    print("[seed] Année du modèle :", year)
    print("[seed] Codes d'absence  :", len(all_codes))
    print("[seed] Matrice          : %d lignes" % len(matrix))
    print("[seed] Pénibilités      :", len(settings["penibilites"]))
    print("[seed] Durées           :", len(settings["durees"]))
    print("[seed] Quotités         :", len(settings["quotites"]))
    print("[seed] Temps de travail :", len(settings["temps_travail"]))

    # Sauvegarde du classeur dans le projet
    src_dir = os.path.join(BASE_DIR, "source")
    os.makedirs(src_dir, exist_ok=True)
    dest = os.path.join(src_dir, os.path.basename(source_path))
    try:
        if os.path.abspath(dest) != os.path.abspath(source_path):
            shutil.copy2(source_path, dest)
            print("[seed] Classeur copié dans", dest)
    except OSError as exc:
        print("[seed] Copie impossible :", exc)

    init_db()
    db = get_db()
    for key, value in settings.items():
        set_setting(db, key, value)
    db.commit()
    db.close()
    print("[seed] Paramètres enregistrés dans la base de données.")
    return True


if __name__ == "__main__":
    extract(sys.argv[1] if len(sys.argv) > 1 else None)
