# -*- coding: utf-8 -*-
"""Absences de Sedit RH (CM, GEM, CT, CP, SF) intégrées au planning et aux compteurs.

- Lues dans Sedit RH à chaque affichage d'un planning ou d'un compteur (`fetch=True`), puis **conservées en base** (table `absences_rh`) ;
  si Sedit RH ne répond pas, la dernière lecture sert : les compteurs restent calculables.
- Transformées en demi-journées sur les seuls jours TRAVAILLÉS de la personne (ni week-end, ni jour férié non travaillé, ni hors période) et jamais
  sur une demi-journée déjà saisie dans la fiche : elles rejoignent alors le calcul des soldes, dont les déductions de RTT et de sujétions
  (règle existante : CM + CP + CT).
"""
import datetime as dt
import logging

import sedit_rh

log = logging.getLogger(__name__)
REFRESH_SECONDS = 60          # deux affichages rapprochés (planning puis compteurs) ne relisent Sedit RH qu'une fois


def stored(db, matricule, year):
    """Dernière lecture conservée en base : [{"code", "libelle", "debut", "fin"}]."""
    rows = db.execute("SELECT code, libelle, debut, fin FROM absences_rh WHERE matricule=? AND annee=? ORDER BY debut, code",
                      (matricule, int(year))).fetchall()
    return [{"code": r["code"], "libelle": r["libelle"], "debut": str(r["debut"])[:10], "fin": str(r["fin"])[:10]} for r in rows]


def refresh(db, matricule, year):
    """Relit Sedit RH et remplace la copie en base. Retourne (absences, avertissement) ; en cas de panne, (dernière lecture, message)."""
    try:
        items = sedit_rh.absences(matricule, year, max_age=REFRESH_SECONDS)
    except sedit_rh.SeditError as exc:
        log.warning("Absences Sedit RH non relues (%s) : %s", matricule, exc)
        return stored(db, matricule, year), str(exc)
    db.execute("DELETE FROM absences_rh WHERE matricule=? AND annee=?", (matricule, int(year)))
    for a in items:
        db.execute("INSERT INTO absences_rh (matricule, annee, code, libelle, debut, fin) VALUES (?,?,?,?,?,?)",
                   (matricule, int(year), a["code"], a.get("libelle") or "", a["debut"], a["fin"]))
    db.commit()
    return items, None


def items_for(db, matricule, year, fetch):
    """(absences, avertissement) d'une personne : relues dans Sedit RH si `fetch`, sinon la copie en base."""
    matricule = (matricule or "").strip()
    if not matricule:
        return [], None
    return refresh(db, matricule, year) if fetch else (stored(db, matricule, year), None)


def half_cells(items, year, covered):
    """{"1050": "CM", …} : demi-journées de l'année `year` couvertes par les absences ; `covered(key)` dit si la demi-journée est travaillée."""
    out = {}
    for a in items:
        try:
            day, last = dt.date.fromisoformat(a["debut"][:10]), dt.date.fromisoformat(a["fin"][:10])
        except (KeyError, ValueError):
            continue
        while day <= last:
            if day.year == int(year):
                for half in (0, 1):
                    key = day.month * 1000 + day.day * 10 + half
                    if covered(key):
                        out.setdefault(str(key), a["code"])
            day += dt.timedelta(days=1)
    return out
