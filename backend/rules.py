# -*- coding: utf-8 -*-
"""
Moteur de calcul - reproduit fidèlement les formules Excel des onglets
"Paramétrage" et "AGENT" du classeur "Modèle Suivi congés 2027.xlsx".

Toutes les fonctions Excel utilisées sont réimplémentées ici :
  FLOOR, ROUND, ROUNDDOWN, VLOOKUP, COUNTIF, DATEDIF, IFERROR ...
"""
from __future__ import annotations

import calendar
import math
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
          "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
MONTHS_SHORT = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
                "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]


# ---------------------------------------------------------------- utilitaires Excel
def excel_round(x, nd: int = 0):
    """ROUND() : arrondi à la valeur la plus proche (0.5 -> supérieur)."""
    try:
        d = Decimal(repr(float(x)))
    except (TypeError, ValueError):
        return 0
    q = Decimal(1).scaleb(-int(nd))
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def excel_floor(number, significance):
    """FLOOR() : arrondi au multiple de 'significance' inférieur ou égal."""
    try:
        n = float(number)
        s = float(significance)
    except (TypeError, ValueError):
        return 0
    if s == 0:
        raise ZeroDivisionError("#DIV/0!")
    if n < 0 and s > 0:
        return math.ceil(n / s) * s
    return math.floor(n / s) * s


def excel_rounddown(x, nd: int = 0):
    """ROUNDDOWN() : arrondi vers zéro."""
    try:
        n = float(x)
    except (TypeError, ValueError):
        return 0
    f = 10 ** int(nd)
    return math.trunc(n * f) / f


def _num(x, default=0.0):
    if x is None or x == "":
        return default
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return default


def fmt_num(v) -> str:
    """Concaténation Excel en français : 4.5 -> '4,5', 5 -> '5'."""
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace(".", ",")


def pct_to_float(v) -> float:
    """'100%' -> 1.0 , '88,5%' -> 0.885 , 0.9 -> 0.9 (coercion Excel)."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if s.endswith("%"):
        s = s[:-1].strip()
        try:
            return float(s) / 100.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _iso(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _f(v, default=0.0):
    """IFERROR : renvoie 'default' sur erreur / valeur vide."""
    if v is None or v == "" or isinstance(v, str):
        return default
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
    except TypeError:
        return default
    return v


# ---------------------------------------------------------------- paramétrage
def build_key(pen, duree, quotite, jours) -> str:
    """Clé de recherche = Paramétrage!F = B & ' - ' & C & ' - ' & D & ' - ' & E."""
    return f"{pen or ''} - {duree or ''} - {quotite or ''} - {fmt_num(jours)}"


def compute_matrix_row(row, settings) -> dict:
    """Colonnes G..L de la matrice Paramétrage (formules Excel)."""
    pen = row.get("pen")
    duree = row.get("duree")
    quotite = row.get("quotite")
    jours = row.get("jours")
    rtt_lu = lookup_duree_rtt(duree, settings)
    js_lu = lookup_penibilite_sujections(pen, settings)
    q = pct_to_float(quotite)
    j = _num(jours)

    g = 5 * j                                            # G : CA
    try:
        h = excel_floor((rtt_lu or 0) * q, 0.5)          # H : RTT annuels
    except ZeroDivisionError:
        h = 0
    if rtt_lu is None:                                   # VLOOKUP introuvable -> IFERROR
        h = 0
    try:
        i = excel_floor((js_lu or 0) * q, 1)             # I : jours de sujétion
    except ZeroDivisionError:
        i = 0
    if js_lu is None:
        i = 0

    base = 365 - ((7 - j) * 52) - 8 - g - i
    try:
        jj = excel_round(base / h, 0) if h else 0        # J : déduction RTT
    except ZeroDivisionError:
        jj = 0
    try:
        kk = excel_round(base / i, 0) if i else 0        # K : déduction JS
    except ZeroDivisionError:
        kk = 0
    # L : droit CET = E*4 (6 lignes du classeur figent la valeur à 0 en dur)
    ll = row["droit_cet"] if isinstance(row.get("droit_cet"), (int, float)) else j * 4

    return {
        "pen": pen, "duree": duree, "quotite": quotite, "jours": jours,
        "key": build_key(pen, duree, quotite, jours),
        "ca": _f(g), "rtt": _f(h), "js": _f(i),
        "ded_rtt": _f(jj), "ded_js": _f(kk), "droit_cet": _f(ll),
    }


def matrix_rows(settings) -> list[dict]:
    return [compute_matrix_row(r, settings) for r in settings.get("matrix", [])]


def matrix_index(settings) -> dict:
    return {r["key"]: r for r in matrix_rows(settings)}


def lookup_duree_rtt(duree, settings):
    """VLOOKUP(durée, Paramétrage!V:W, 2) -> nb RTT annuels (None si introuvable)."""
    for r in settings.get("durees_rtt", []):
        if r.get("name") == duree:
            return _num(r.get("rtt"))
    return None


def lookup_penibilite_sujections(pen, settings):
    """VLOOKUP(pénibilité, Paramétrage!Y:Z, 2) -> nb de sujétions (None si introuvable)."""
    for r in settings.get("penibilites", []):
        if r.get("name") == pen:
            return _num(r.get("sujections"))
    return None


def code_settings(settings) -> dict:
    """Index des codes d'absence : code -> {libelle, color, in_n, in_s}."""
    idx = {}
    for c in settings.get("codes", []):
        code = c.get("code")
        if not code:
            continue
        idx[code] = {
            "code": code,
            "libelle": c.get("libelle") or code,
            "color": (c.get("color") or "FFF2F2F2").replace("#", "").upper(),
            "in_n": bool(c.get("in_n", True)),
            "in_s": bool(c.get("in_s", True)),
        }
    return idx


def ca_prev_code(settings) -> str:
    """B31 : 'CA' & (année-1) sur 2 chiffres -> CA26 pour 2027."""
    year = int(settings.get("general", {}).get("year", 2027))
    return "CA%02d" % ((year - 1) % 100)


# ---------------------------------------------------------------- fiche agent
def _counter(cells) -> Counter:
    c = Counter()
    for cell in cells or []:
        code = cell.get("code")
        if code:
            c[code] += 1
    return c


def add_months(value, months: int):
    """Ajoute des mois à une date en conservant le dernier jour du mois."""
    d = _iso(value)
    if not d:
        return None
    y = d.year + (d.month - 1 + int(months)) // 12
    m = (d.month - 1 + int(months)) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _hour_counter(cassages, hourly, day_code, hour_code, year, as_of,
                  recoveries=None):
    """Compteur d'heures CAH/RTTH/RCH avec validité de 6 mois par crédit.

    Les heures utilisées sont affectées aux crédits les plus anciens (FIFO).
    Seuls les crédits validés alimentent le compteur ; les cassages et les
    déclarations en attente ne sont pas encore crédités.
    """
    as_of = _iso(as_of) or date.today()
    credits = []
    for c in cassages or []:
        if (c.get("code") or "") != day_code:
            continue
        if c.get("pending"):
            continue
        hours = 7.0 * float(c.get("days") or 1)
        valid_until = _iso(c.get("valid_until"))
        if not valid_until:
            base = _iso(c.get("decide_le")) or _iso(c.get("cree_le")) or _iso(c.get("date"))
            valid_until = add_months(base, 6) if base else None
        credits.append({
            "id": c.get("id"),
            "hours": hours,
            "valid_until": valid_until,
            "date": _iso(c.get("decide_le")) or _iso(c.get("date")),
        })
    if hour_code == "RCH":
        for r in recoveries or []:
            if (r.get("code") or "") != "RCH":
                continue
            hours = float(r.get("hours") or 0)
            if hours <= 0:
                continue
            valid_until = _iso(r.get("valid_until"))
            if not valid_until:
                valid_until = add_months(_iso(r.get("absence_date")), 6)
            credits.append({
                "id": r.get("id"),
                "hours": hours,
                "valid_until": valid_until,
                "date": _iso(r.get("absence_date")),
            })
    credits.sort(key=lambda x: (x["valid_until"] or date.max, x["id"] or 0))

    used_total = 0.0
    used_year = 0.0
    for h in hourly or []:
        if (h.get("code") or "") != hour_code:
            continue
        hh = float(h.get("hours") or 0)
        used_total += hh
        hd = _iso(h.get("absence_date")) or _iso(h.get("date"))
        if hd and hd.year == year:
            used_year += hh

    remaining_used = used_total
    available = 0.0
    next_expiry = None
    allocated = {}
    for cr in credits:
        alloc = min(cr["hours"], max(0.0, remaining_used))
        remaining_used -= alloc
        allocated[cr["id"]] = alloc
        left = cr["hours"] - alloc
        if left <= 0:
            continue
        if cr["valid_until"] is None or cr["valid_until"] >= as_of:
            available += left
            if next_expiry is None or (cr["valid_until"] and cr["valid_until"] < next_expiry):
                next_expiry = cr["valid_until"]

    return {
        "credit": sum(c["hours"] for c in credits),
        "used_total": used_total,
        "used_year": used_year,
        "restant": max(0.0, available),
        "next_expiry": next_expiry.isoformat() if next_expiry else "",
        "allocated": allocated,
    }


def compute(agent: dict, cells, settings, today=None, period=None,
            cassages=None, hourly=None, hours_as_of=None,
            recoveries=None) -> dict:
    """Reproduit l'ensemble des formules de l'onglet AGENT."""
    if period is None and agent.get("periods"):
        return compute_multi(agent, cells, settings, today=today,
                             cassages=cassages, hourly=hourly,
                             hours_as_of=hours_as_of, recoveries=recoveries)
    g = settings.get("general", {})
    year = int(g.get("year", 2027))
    year_start = _iso(g.get("year_start")) or date(year, 1, 1)
    year_end = _iso(g.get("year_end")) or date(year, 12, 31)
    ca26 = ca_prev_code(settings)

    if period:
        pen = period.get("penibilite") or ""
        duree = period.get("duree_hebdo") or ""
        quotite = period.get("quotite") or ""
        jours = period.get("jours_hebdo")
        arr = _iso(period.get("start"))
        dep = _iso(period.get("end"))
    else:
        pen = agent.get("penibilite") or ""
        duree = agent.get("duree_hebdo") or ""
        quotite = agent.get("quotite") or ""
        jours = agent.get("jours_hebdo")
        arr = _iso(agent.get("date_arrivee"))
        dep = _iso(agent.get("date_depart"))
    reliquat = agent.get("reliquat")
    solde_cet = agent.get("solde_cet") or 0

    mtx = matrix_index(settings)
    key = build_key(pen, duree, quotite, jours)
    lu = mtx.get(key)

    # ---- comptages (COUNTIF / 2 = demi-journées -> jours)
    cnt = _counter(cells)
    by_month = Counter()
    for cell in cells or []:
        if cell.get("code"):
            by_month[(int(cell.get("month")), cell["code"])] += 1

    def ddays(code):                       # nombre de JOURS saisis pour un code
        return cnt.get(code, 0) / 2.0

    def mdays(months, codes):
        t = 0
        for m in months:
            for c in codes:
                t += by_month.get((m, c), 0)
        return t / 2.0

    ca_pris = ddays("CA") + ddays(ca26) + ddays("CAF")
    ca_pris_ca = ddays("CA") + ddays(ca26)
    ca_pris_hors_ca26 = ddays("CA") + ddays("CAF")
    rtt_pris = ddays("RTT") + ddays("RTTF")
    rtt_pris_rtt = ddays("RTT")
    js_pris = ddays("JS")
    jb_pris = ddays("JB")
    cet_utilise = ddays("CET")
    abs_days = ddays("CM") + ddays("CP") + ddays("CT")     # AQ30

    # ---- compteurs d'heures (CAH / RTTH) et jours cassés
    # Les cassages en attente réservent le jour sans créditer d'heures.
    ca_casse = sum(
        float(c.get("days") or 1)
        for c in (cassages or [])
        if (c.get("code") or "") == "CA" and int(c.get("year") or year) == year
    )
    rtt_casse = sum(
        float(c.get("days") or 1)
        for c in (cassages or [])
        if (c.get("code") or "") == "RTT" and int(c.get("year") or year) == year
    )
    hours_ref = hours_as_of or today or date.today()
    cah = _hour_counter(cassages, hourly, "CA", "CAH", year, hours_ref)
    rth = _hour_counter(cassages, hourly, "RTT", "RTTH", year, hours_ref)
    rch = _hour_counter(cassages, hourly, "RCH", "RCH", year, hours_ref,
                        recoveries=recoveries)

    # ---- prorata (AX16) : arrivée / départ en cours d'année
    if period:
        # Période de paramètres : jours calendaires inclus dans la période.
        prorata = ((dep - arr).days + 1) / 365.0 if arr and dep else 0.0
    elif arr and dep:
        prorata = (dep - arr).days / 365.0
    elif arr:
        prorata = (365 - (arr - year_start).days) / 365.0
    elif dep:
        prorata = (365 - (year_end - dep).days) / 365.0
    else:
        prorata = 1.0
    if prorata < 0:
        prorata = 0.0

    # ---- soldes initiaux (VLOOKUP sur la matrice + prorata)
    ca_lu = _f(lu["ca"]) if lu else 0
    rtt_lu = _f(lu["rtt"]) if lu else 0
    js_lu = _f(lu["js"]) if lu else 0
    ded_rtt_lu = _f(lu["ded_rtt"]) if lu else 0
    ded_js_lu = _f(lu["ded_js"]) if lu else 0
    droit_cet_lu = _f(lu["droit_cet"]) if lu else 0

    ca_droit = excel_round(ca_lu * prorata / 5.0, 1) * 5 if lu else 0   # AZ20
    rtt_total = excel_floor(rtt_lu * prorata, 0.5) if lu else 0         # AX21
    js_total = excel_floor(js_lu * prorata, 1) if lu else 0             # AX22

    # ---- intervalle de génération des sujétions (BC2 / BD2)
    bc2 = js_lu * prorata if lu else 0
    if bc2:
        bd2 = excel_floor(365 / bc2, 1) * prorata
    else:
        bd2 = 0

    # ---- jours écoulés depuis l'arrivée (AY20)
    ref = today or date.today()
    if ref < year_start:
        ref = year_start
    if ref > year_end:
        ref = year_end
    if period and dep and ref > dep:
        ref = dep
    start_ref = arr if arr else year_start
    jours_ecoules = (ref - start_ref).days + 1
    if jours_ecoules < 0:
        jours_ecoules = 0

    # ---- générations (AM21 / AM22 / AM23)
    rtt_genere = 0
    if rtt_total:
        raz = (365 * prorata) / rtt_total
        rtt_genere = excel_floor(jours_ecoules / raz, 0.5) if raz else 0
    js_genere = 0
    if js_total >= 1 and bd2:
        js_genere = excel_floor(jours_ecoules / bd2, 1)

    # ---- bonifications (AI5 / AI6 / AI7 / AI9)
    peak = [1, 2, 3, 4, 11, 12]
    peak_total = mdays(peak, ["CA", "CAF"])
    peak_ca = mdays(peak, ["CA"])
    ai5 = 2 if peak_total >= 8 else 0
    ai6 = 1 if peak_total < 8 else 0
    ai7 = 1 if peak_ca > 4.5 else 0
    jb_genere = 2 if ai5 == 2 else (1 if (ai6 + ai7) == 2 else 0)

    # ---- dates de génération des sujétions (AY4:BA12 -> AT17:AT25)
    suj_dates = []
    cycle_ok = bool(pen and duree and quotite and jours not in (None, ""))
    cap = date(year, 12, 15)
    limit = dep if dep else year_end
    base_date = arr if arr else year_start
    for n in range(1, 10):
        val = None
        if cycle_ok and bd2 and js_lu:
            cand = base_date + timedelta(days=int(bd2) * n)
            if cand > limit:
                val = None
            elif arr:
                val = cap if cand > cap else cand
            else:
                val = cand
        suj_dates.append(val.isoformat() if val else None)

    # ---- reliquat / report CA N-1 (AP8, AP10, AP11)
    has_rel = reliquat not in (None, "")
    rel = _num(reliquat) if has_rel else 0
    ap8 = None if not has_rel else ("RQ" if rel <= 5 else "RP")
    ca26_used = ddays(ca26)
    if has_rel and ap8 == "RQ" and ca26_used < rel:
        ap11 = 1
    elif has_rel and ap8 == "RP" and ca26_used < rel:
        ap11 = 2
    else:
        ap11 = 3
    # Le reliquat saisi est un droit : il est intégré au solde et affiché
    # dans la synthèse, que les jours CA n-1 soient posés ou non.
    rel_restant = rel if has_rel else 0

    # ---- déductions suite à absences (AO30 / AO31)
    rtt_quotient = (abs_days / ded_rtt_lu) if ded_rtt_lu else 0     # AR30
    ded_rtt = 0 if duree == "Annualisé" else excel_rounddown(rtt_quotient, 0)
    js_quotient = (abs_days / ded_js_lu) if ded_js_lu else 0          # AR31
    ded_js = excel_rounddown(js_quotient, 0)

    # ---- soldes restants
    ca_restant = ca_droit + rel_restant - ca_pris - ca_casse          # AM29
    rtt_restant = rtt_total - rtt_pris - ded_rtt - rtt_casse          # AM30
    # Ce qui peut encore être cassé en heures : CA de l'année uniquement
    # (jamais le reliquat reporté) et RTT déjà générés à ce jour.
    ca_current_dispo = max(0.0, ca_droit - ddays("CA") - ca_casse)
    rtt_current_dispo = max(0.0, rtt_genere - rtt_pris_rtt - ded_rtt - rtt_casse)
    js_restant = js_total - js_pris - ded_js                          # AM31
    jb_restant = jb_genere - jb_pris                                  # AM32
    cet_restant = _num(solde_cet) - cet_utilise                       # AM34

    hourly_used_days = (cah["used_year"] + rth["used_year"] + rch["used_year"]) / 7.0
    hourly_restant_days = (cah["restant"] + rth["restant"] + rch["restant"]) / 7.0
    total_pris = ca_pris + rtt_pris + js_pris + jb_pris + hourly_used_days
    total_restant = (ca_restant + rtt_restant + js_restant + jb_restant
                     + hourly_restant_days)

    # ---- dépôt CET (AQ37:AS38, AL37, AL39)
    ca_cet_pris = min(ca_pris_hors_ca26, ca_droit)
    ar37 = max(0.0, ca_restant) if (lu and ca_cet_pris >= droit_cet_lu) else 0
    as37 = ar37 if ar37 + cet_restant <= 60 else 60 - cet_restant
    cet_ca_eligible = "CET plein" if cet_restant >= 60 else as37
    rtt_cet_pris = min(ddays("RTT"), rtt_total)
    try:
        ar38 = ((rtt_total - rtt_cet_pris) if (lu and ca_cet_pris >= droit_cet_lu) else 0) - ded_rtt
    except TypeError:
        ar38 = 0
    as38 = ar38 if ar38 + cet_restant <= 60 else 60 - cet_restant
    cet_rtt_eligible = "CET plein" if cet_restant >= 60 else min(as38, 12)

    # ---- liste de codes proposée dans la grille
    codes = code_settings(settings)
    code_list = [c for c in codes.values() if c["in_s"]]
    if ap11 in (1, 2):                      # reliquat encore disponible -> CA26
        if ca26 in codes and codes[ca26] not in code_list:
            code_list.append(codes[ca26])
        elif ca26 not in codes:
            code_list.append({"code": ca26, "libelle": "Report CA année N-1",
                              "color": "FFFFFF00", "in_n": True, "in_s": False})
    # conserve l'ordre du paramétrage
    order = {c.get("code"): i for i, c in enumerate(settings.get("codes", []))}
    code_list.sort(key=lambda c: order.get(c["code"], 999))

    label_date = min(ref, year_end)

    return {
        "year": year,
        "year_start": year_start.isoformat(),
        "year_end": year_end.isoformat(),
        "cycle": key,
        "cycle_ok": bool(lu),
        "ca26_code": ca26,

        "prorata": round(prorata, 6),
        "coeff_arrivee": round((365 - (arr - year_start).days) / 365.0, 6) if arr else 0,
        "coeff_depart": round((365 - (year_end - dep).days) / 365.0, 6) if dep else 0,
        "jours_ecoules": jours_ecoules,
        "date_reference": label_date.isoformat(),

        "ca_droit": ca_droit,
        "ca_pris_ca": ca_pris_ca,
        "ca_current_dispo": ca_current_dispo,
        "rtt_pris_rtt": rtt_pris_rtt,
        "rtt_current_dispo": rtt_current_dispo,
        "reliquat_restant": rel_restant,
        "reliquat_initial": rel if has_rel else 0,
        "reliquat_mode": ap8,
        "rtt_total": rtt_total,
        "js_total": js_total,
        "droit_cet": droit_cet_lu,
        "ca_casse": ca_casse,
        "rtt_casse": rtt_casse,
        "cah_credit": cah["credit"],
        "cah_used": cah["used_total"],
        "cah_used_year": cah["used_year"],
        "cah_restant": cah["restant"],
        "cah_next_expiry": cah["next_expiry"],
        "rth_credit": rth["credit"],
        "rth_used": rth["used_total"],
        "rth_used_year": rth["used_year"],
        "rth_restant": rth["restant"],
        "rth_next_expiry": rth["next_expiry"],
        "rch_credit": rch["credit"],
        "rch_used": rch["used_total"],
        "rch_used_year": rch["used_year"],
        "rch_restant": rch["restant"],
        "rch_next_expiry": rch["next_expiry"],

        "rtt_genere": rtt_genere,
        "js_genere": js_genere,
        "jb_genere": jb_genere,
        "suj_dates": suj_dates,
        "suj_interval": bd2,
        "bc2": bc2,

        "counts": {
            "ca": ca_pris, "ca_hors_ca26": ca_pris_hors_ca26, "ca26": ca26_used,
            "caf": ddays("CAF"), "rtt": ddays("RTT"), "rttf": ddays("RTTF"),
            "js": js_pris, "jb": jb_pris, "cet": cet_utilise,
            "abs": abs_days,
            "rttf_total": ddays("CAF"), "rttf_rtt": ddays("RTTF"),
        },
        "solde": {
            "ca": {"pris": ca_pris, "pris_ca": ca_pris_ca,
                   "restant": ca_restant, "current_dispo": ca_current_dispo,
                   "casse": ca_casse, "droit_net": ca_droit - ca_casse},
            "rtt": {"pris": rtt_pris, "pris_rtt": rtt_pris_rtt,
                    "restant": rtt_restant, "current_dispo": rtt_current_dispo,
                    "casse": rtt_casse,
                    "deduction": ded_rtt, "quotient": round(rtt_quotient, 4),
                    "diviseur": ded_rtt_lu},
            "js": {"pris": js_pris, "restant": js_restant,
                   "deduction": ded_js, "quotient": round(js_quotient, 4),
                   "diviseur": ded_js_lu},
            "jb": {"pris": jb_pris, "restant": jb_restant},
            "cet": {"pris": cet_utilise, "restant": cet_restant,
                    "initial": _num(solde_cet)},
            "cah": cah,
            "rth": rth,
            "rch": rch,
            "total": {"pris": total_pris, "restant": total_restant},
        },
        "fractionnes": {"ca": ddays("CAF"), "rtt": ddays("RTTF")},
        "bonif": {"ai5": ai5, "ai6": ai6, "ai7": ai7, "peak": peak_total,
                  "peak_ca": peak_ca},
        "cet_info": {
            "ca_pris": ca_cet_pris,
            "rtt_pris": rtt_cet_pris,
            "ca_eligible": cet_ca_eligible,
            "rtt_eligible": cet_rtt_eligible,
        },
        "code_list": code_list,
    }


def _cell_in_period(cell, start, end, year):
    try:
        month = int(cell.get("month") or 0)
        day = int(cell.get("day") or 0)
    except (TypeError, ValueError):
        return False
    if not month or not day:
        return False
    try:
        d = date(year, month, day)
    except ValueError:
        return False
    return start <= d <= end


def compute_multi(agent, cells, settings, today=None,
                  cassages=None, hourly=None, hours_as_of=None,
                  recoveries=None):
    """Calcule les droits période par période, puis les additionne.

    Les paramètres variables (pénibilité, durée, quotité, jours/semaine) sont
    lus dans agent['periods']. Le reliquat, le CET et les compteurs d'heures
    restent globaux.
    """
    periods = [
        p for p in (agent.get("periods") or [])
        if _iso(p.get("start")) and _iso(p.get("end"))
    ]
    if not periods:
        return compute(agent, cells, settings, today=today,
                       cassages=cassages, hourly=hourly, hours_as_of=hours_as_of,
                       recoveries=recoveries)

    g = settings.get("general", {})
    year = int(g.get("year", 2027))
    results = []
    for p in periods:
        start = _iso(p.get("start"))
        end = _iso(p.get("end"))
        sub = dict(agent)
        sub["reliquat"] = 0
        sub["solde_cet"] = 0
        sub["periods"] = []
        sub_cells = [c for c in (cells or []) if _cell_in_period(c, start, end, year)]
        results.append((p, compute(sub, sub_cells, settings, today=today, period=p)))
    if not results:
        return compute(agent, cells, settings, today=today,
                       cassages=cassages, hourly=hourly, hours_as_of=hours_as_of,
                       recoveries=recoveries)

    last_p = results[-1][0]
    global_agent = dict(agent)
    for key in ("penibilite", "duree_hebdo", "quotite", "jours_hebdo"):
        global_agent[key] = last_p.get(key)
    global_agent["periods"] = []
    gres = compute(global_agent, cells, settings, today=today,
                   cassages=cassages, hourly=hourly, hours_as_of=hours_as_of,
                   recoveries=recoveries)

    ca_droit = sum(r["ca_droit"] for _, r in results)
    rtt_total = sum(r["rtt_total"] for _, r in results)
    js_total = sum(r["js_total"] for _, r in results)
    rtt_genere = sum(r["rtt_genere"] for _, r in results)
    js_genere = sum(r["js_genere"] for _, r in results)
    ded_rtt = sum(r["solde"]["rtt"]["deduction"] for _, r in results)
    ded_js = sum(r["solde"]["js"]["deduction"] for _, r in results)
    prorata = sum(r["prorata"] for _, r in results)

    counts = gres["counts"]
    ca_pris_ca = counts["ca"] - counts.get("caf", 0)
    ca_pris_current = counts["ca"] - counts.get("ca26", 0) - counts.get("caf", 0)
    rtt_pris_rtt = counts["rtt"]
    ca_current_dispo = max(0.0, ca_droit - ca_pris_current - gres["ca_casse"])
    rtt_current_dispo = max(0.0, rtt_genere - rtt_pris_rtt - ded_rtt - gres["rtt_casse"])
    solde = {
        "ca": {
            "pris": counts["ca"],
            "pris_ca": ca_pris_ca,
            "restant": ca_droit + gres["reliquat_restant"] - counts["ca"] - gres["ca_casse"],
            "current_dispo": ca_current_dispo,
            "casse": gres["ca_casse"],
            "droit_net": ca_droit - gres["ca_casse"],
        },
        "rtt": {
            "pris": counts["rtt"],
            "pris_rtt": rtt_pris_rtt,
            "restant": rtt_total - counts["rtt"] - ded_rtt - gres["rtt_casse"],
            "current_dispo": rtt_current_dispo,
            "casse": gres["rtt_casse"],
            "deduction": ded_rtt,
            "quotient": results[-1][1]["solde"]["rtt"]["quotient"],
            "diviseur": results[-1][1]["solde"]["rtt"]["diviseur"],
        },
        "js": {
            "pris": counts["js"],
            "restant": js_total - counts["js"] - ded_js,
            "deduction": ded_js,
            "quotient": results[-1][1]["solde"]["js"]["quotient"],
            "diviseur": results[-1][1]["solde"]["js"]["diviseur"],
        },
        "jb": {
            "pris": counts["jb"],
            "restant": gres["jb_genere"] - counts["jb"],
        },
        "cet": {
            "pris": counts["cet"],
            "restant": gres["solde"]["cet"]["restant"],
            "initial": gres["solde"]["cet"]["initial"],
        },
        "cah": gres["solde"]["cah"],
        "rth": gres["solde"]["rth"],
        "rch": gres["solde"]["rch"],
    }
    solde["total"] = {
        "pris": (solde["ca"]["pris"] + solde["rtt"]["pris"] + solde["js"]["pris"]
                 + solde["jb"]["pris"]
                 + (solde["cah"]["used_year"] + solde["rth"]["used_year"]
                    + solde["rch"]["used_year"]) / 7.0),
        "restant": (solde["ca"]["restant"] + solde["rtt"]["restant"]
                    + solde["js"]["restant"] + solde["jb"]["restant"]
                    + (solde["cah"]["restant"] + solde["rth"]["restant"]
                       + solde["rch"]["restant"]) / 7.0),
    }

    out = dict(gres)
    out.update({
        "prorata": round(prorata, 6),
        "ca_droit": ca_droit,
        "ca_pris_ca": ca_pris_ca,
        "ca_current_dispo": ca_current_dispo,
        "rtt_pris_rtt": rtt_pris_rtt,
        "rtt_current_dispo": rtt_current_dispo,
        "rtt_total": rtt_total,
        "js_total": js_total,
        "droit_cet": gres["droit_cet"],
        "rtt_genere": rtt_genere,
        "js_genere": js_genere,
        "jb_genere": gres["jb_genere"],
        "suj_dates": [d for _, r in results for d in (r.get("suj_dates") or [])],
        "suj_interval": results[-1][1]["suj_interval"],
        "bc2": results[-1][1]["bc2"],
        "cycle": results[-1][1]["cycle"],
        "cycle_ok": all(r["cycle_ok"] for _, r in results),
        "counts": counts,
        "solde": solde,
        "fractionnes": gres["fractionnes"],
        "bonif": gres["bonif"],
        "cet_info": gres["cet_info"],
        "code_list": gres["code_list"],
        "reliquat_restant": gres["reliquat_restant"],
        "reliquat_initial": gres["reliquat_initial"],
        "reliquat_mode": gres["reliquat_mode"],
        "coeff_arrivee": gres["coeff_arrivee"],
        "coeff_depart": gres["coeff_depart"],
        "jours_ecoules": gres["jours_ecoules"],
        "date_reference": gres["date_reference"],
    })
    return out


def agent_summary(agent, cells, settings, today=None, cassages=None, hourly=None,
                  recoveries=None) -> dict:
    """Synthèse compacte pour le tableau de bord."""
    c = compute(agent, cells, settings, today=today, cassages=cassages,
                hourly=hourly, recoveries=recoveries)
    return {
        "id": agent.get("id"),
        "nom": agent.get("nom"),
        "owner_id": agent.get("owner_id"),
        "owner_name": agent.get("owner_name"),
        "is_manager": int(agent.get("is_manager") or 0),
        "cycle": c["cycle"],
        "penibilite": agent.get("penibilite"),
        "ca": c["solde"]["ca"],
        "rtt": c["solde"]["rtt"],
        "js": c["solde"]["js"],
        "jb": c["solde"]["jb"],
        "cet": c["solde"]["cet"],
        "cah": c["solde"]["cah"],
        "rth": c["solde"]["rth"],
        "rch": c["solde"]["rch"],
        "total": c["solde"]["total"],
        "updated_at": agent.get("updated_at"),
    }
