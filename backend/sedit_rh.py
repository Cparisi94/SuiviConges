# -*- coding: utf-8 -*-
"""Client de l'API Sedit RH (agents et organisation de la Ville, lecture seule).

L'adresse et la clé viennent de la configuration (SEDITRH_API_URL, SEDITRH_API_KEY). La clé est transmise en
`Authorization: Bearer` et n'est jamais renvoyée à l'écran ni journalisée. Toute panne (réseau, clé refusée, droit
manquant, erreur du serveur) lève `SeditError` avec un message lisible.

Pour compter les agents, on interroge les effectifs agrégés (`/api/v1/effectifs`, droit `effectifs:read`) : aucune
donnée personnelle n'est lue. La liste des agents en poste (`/api/v1/agents`, droit `agents:read`) n'est lue qu'à la
demande de l'administrateur (organisation RH, matricules, création d'agents) et seulement gardée en mémoire.
"""
import threading
import re
import time

import requests

import config


class SeditError(Exception):
    """Sedit RH est injoignable ou refuse la requête ; `status` = code HTTP éventuel."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def configured():
    return bool(config.SEDITRH_API_URL and config.SEDITRH_API_KEY)


def _verify():
    if config.VILLE_CA_FILE:
        return config.VILLE_CA_FILE
    return not config.VILLE_ALLOW_SELF_SIGNED_CERTS


def _get(path, params=None, timeout=30):
    if not configured():
        raise SeditError("L'API Sedit RH n'est pas configurée (SEDITRH_API_URL et SEDITRH_API_KEY dans .env)")
    try:
        resp = requests.get(
            config.SEDITRH_API_URL.rstrip("/") + path, params=params,
            headers={"Authorization": "Bearer " + config.SEDITRH_API_KEY},
            timeout=timeout, verify=_verify(),
        )
    except requests.RequestException as exc:
        raise SeditError("API Sedit RH injoignable (%s)" % exc.__class__.__name__) from exc
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError as exc:
            raise SeditError("Réponse de l'API Sedit RH illisible", 200) from exc
    try:
        detail = (resp.json() or {}).get("detail") or ""
    except ValueError:
        detail = ""
    if resp.status_code == 401:
        raise SeditError("Clé refusée par l'API Sedit RH (clé invalide, expirée ou suspendue)", 401)
    if resp.status_code == 403:
        raise SeditError("Accès refusé par l'API Sedit RH%s" % (" : " + detail if detail else ""), 403)
    raise SeditError("Erreur de l'API Sedit RH (HTTP %s)%s" % (resp.status_code, " : " + detail if detail else ""), resp.status_code)


_CET_TTL = 600                # un solde est conservé 10 minutes
_cet_cache = {}               # matricule -> (instant, {"solde", "comptes"} ou None s'il n'a pas de CET)


def cet_balances(matricules):
    """Soldes de CET (en jours) des matricules donnés : {matricule: {"solde": float, "comptes": int}} ; un agent sans CET est absent.

    Le solde est `solde_calcule` de l'API Sedit RH (solde initial + dépôts - retraits) pour les comptes ouverts. Droit `cet:read` requis
    sur la clé ; une seule requête par lot de 100 matricules ; résultat conservé 10 minutes."""
    mats = sorted({(m or "").strip() for m in matricules if (m or "").strip()})
    out, todo, now = {}, [], time.monotonic()
    with _lock:
        for m in mats:
            hit = _cet_cache.get(m)
            if hit and now - hit[0] < _CET_TTL:
                if hit[1] is not None:
                    out[m] = hit[1]
            else:
                todo.append(m)
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        data = _get("/api/v1/cet", {"matricules": ",".join(batch), "ouvert": "true", "limit": 500}, timeout=120)
        found = {}
        for compte in data.get("data") or []:
            m = (compte.get("matricule") or "").strip()
            s = found.setdefault(m, {"solde": 0.0, "comptes": 0})
            s["solde"] += float(compte.get("solde_calcule") or 0)
            s["comptes"] += 1
        with _lock:
            stamp = time.monotonic()
            for m in batch:
                _cet_cache[m] = (stamp, found.get(m))
        out.update(found)
    return out


def start_warmup(period=240):
    """Garde en mémoire l'organisation et la liste des agents de Sedit RH (rafraîchies toutes les 4 minutes, avant l'expiration du cache de
    5 minutes) : une page ne reste plus bloquée, avec une connexion PostgreSQL occupée, le temps d'un appel lent à Sedit RH."""
    if not configured():
        return

    def loop():
        while True:
            for fn in (organisation_units, all_agents):
                try:
                    fn(force=True)
                except Exception as exc:  # noqa: BLE001 — l'application reste utilisable sans Sedit RH
                    print("[sedit-rh] préchauffage impossible (%s) : %s" % (fn.__name__, exc))
            time.sleep(period)

    threading.Thread(target=loop, daemon=True, name="sedit-warmup").start()


_end_cache = {}               # matricule -> (instant, date de fin de contrat ISO ou None)


def contract_end(matricule):
    """Date de fin de contrat (AAAA-MM-JJ) d'un agent dans Sedit RH (champ « date de départ » de sa fiche), ou None s'il n'en a pas.

    Interroge la fiche de l'agent (même s'il n'est plus en poste) ; résultat conservé 10 minutes. Lève SeditError si Sedit RH est injoignable."""
    matricule = (matricule or "").strip()
    if not matricule:
        return None
    with _lock:
        hit = _end_cache.get(matricule)
    if hit and time.monotonic() - hit[0] < _CET_TTL:
        return hit[1]
    try:
        data = _get("/api/v1/agents/" + matricule, timeout=60)
    except SeditError as exc:
        if exc.status == 404:
            data = {"data": {}}                      # agent inconnu de Sedit RH : pas de date connue
        else:
            raise
    fin = ((data.get("data") or {}).get("date_depart") or "")[:10] or None
    with _lock:
        _end_cache[matricule] = (time.monotonic(), fin)
    return fin


ABSENCE_LABELS = {"CM": "Congé maladie", "GEM": "Garde d'enfant malade", "CT": "Maternité, paternité, adoption",
                  "CP": "Présence parentale", "SF": "Soins à un membre de la famille"}
_abs_cache = {}               # (matricule, année) -> (instant, liste)


def absences(matricule, year):
    """Absences saisies dans Sedit RH pour une personne et une année civile : [{"code", "libelle", "debut", "fin"}].

    Seuls le code du calendrier (CM, GEM, CT, CP, SF), son libellé court et les dates sont repris : jamais la nature détaillée de l'arrêt
    (longue maladie, ALD, accident…). Droit `absences:read` requis sur la clé ; résultat conservé 10 minutes."""
    matricule = (matricule or "").strip()
    key = (matricule, int(year))
    with _lock:
        hit = _abs_cache.get(key)
    if hit and time.monotonic() - hit[0] < _CET_TTL:
        return hit[1]
    data = _get("/api/v1/absences", {"matricule": matricule, "du": "%d-01-01" % int(year), "au": "%d-12-31" % int(year), "limit": 500}, timeout=120)
    out = []
    for a in data.get("data") or []:
        code = ((a.get("famille") or {}).get("code_app") or "").strip()
        debut = (a.get("date_debut") or "")[:10]
        if code not in ABSENCE_LABELS or not debut:
            continue
        out.append({"code": code, "libelle": ABSENCE_LABELS[code], "debut": debut, "fin": (a.get("date_fin") or debut)[:10]})
    out.sort(key=lambda x: (x["debut"], x["code"]))
    with _lock:
        _abs_cache[key] = (time.monotonic(), out)
    return out


def cet_cached(matricule):
    """Solde de CET (jours) déjà lu pour ce matricule, sans appel réseau ; None s'il n'est pas en mémoire ou si l'agent n'a pas de CET."""
    with _lock:
        hit = _cet_cache.get((matricule or "").strip())
    if hit and time.monotonic() - hit[0] < _CET_TTL and hit[1] is not None:
        return hit[1]["solde"]
    return None


def headcount():
    """Nombre d'agents en poste et ventilation par statut : {"total": int, "par_statut": [{code, libelle, effectif}]}."""
    data = _get("/api/v1/effectifs", {"par": "statut"})
    rows = [
        {"code": r.get("code") or "", "libelle": r.get("libelle") or "", "effectif": int(r.get("effectif") or 0)}
        for r in (data.get("data") or [])
    ]
    total = (data.get("meta") or {}).get("total")
    if total is None:
        total = sum(r["effectif"] for r in rows)
    return {"total": int(total), "par_statut": sorted(rows, key=lambda r: -r["effectif"])}


# --------------------------------------------------------------------------- #
#  Agents en poste (données personnelles : conservés en mémoire seulement, quelques minutes)
# --------------------------------------------------------------------------- #
CACHE_SECONDS = 300
PAGE_SIZE = 500          # maximum accepté par l'API
_cache = {"at": 0.0, "agents": None}
_lock = threading.Lock()


def clear_cache():
    with _lock:
        _cache.update(at=0.0, agents=None)


def all_agents(force=False):
    """Tous les agents en poste (lecture par pages de 500), mis en cache 5 minutes.

    Les agents ne sont jamais écrits sur disque ni en base : seuls les agents que l'administrateur choisit
    de créer ou de rapprocher sont enregistrés (identité, matricule)."""
    with _lock:
        if not force and _cache["agents"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["agents"]
    agents, offset = [], 0
    for _ in range(100):  # garde-fou : 50 000 agents au maximum
        data = _get("/api/v1/agents", {"limit": PAGE_SIZE, "en_poste": "true", "offset": offset}, timeout=120)
        agents.extend(data.get("data") or [])
        meta = data.get("meta") or {}
        if not meta.get("has_more"):
            break
        offset = meta.get("next_offset", offset + PAGE_SIZE)
    with _lock:
        _cache.update(at=time.monotonic(), agents=agents)
    return agents


# --------------------------------------------------------------------------- #
#  Recherche prédictive d'un agent et organisation (unités)
# --------------------------------------------------------------------------- #
def _fold(value):
    import unicodedata
    text = unicodedata.normalize("NFKD", (value or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(text.replace("-", " ").replace("'", " ").split())


_DIRECTEUR = re.compile(r"^\s*DIRECT(EUR|RICE)\b")
_NON_DIRECTEUR = re.compile(r"ADJOINT|GENERAL")


def _est_directeur(a):
    """Poste de directeur d'une direction (« DIRECTEUR·TRICE DES SYSTEMES D'INFORMATION ») : ni adjoint, ni direction générale."""
    import unicodedata
    poste = unicodedata.normalize("NFKD", ((a.get("poste") or {}).get("libelle") or "").replace("·", " ")).encode("ascii", "ignore").decode().upper()
    return bool(_DIRECTEUR.search(poste)) and not _NON_DIRECTEUR.search(poste)


def _unite_agent(a):
    """Unité d'un agent : son affectation, sauf pour un directeur, rattaché à sa direction (BF) et non au secteur où il est affecté (BF1)."""
    aff = a.get("affectation") or {}
    direction = a.get("direction") or {}
    if _est_directeur(a) and (direction.get("code") or "").strip():
        return (direction.get("code") or "").strip(), (direction.get("libelle") or "").strip()
    return aff.get("code") or "", (aff.get("libelle") or "").strip()


def _agent_summary(a):
    """Champs utiles à la création d'une personne (jamais l'enregistrement complet)."""
    def lab(key):
        return ((a.get(key) or {}).get("libelle") or "").strip()

    unit_code, unit_libelle = _unite_agent(a)
    return {
        "matricule": a.get("matricule") or "", "nom": (a.get("nom") or "").strip(), "prenom": (a.get("prenom") or "").strip(),
        "unit_code": unit_code, "unit_libelle": unit_libelle,
        "direction": lab("direction"), "service": lab("service"), "secteur": lab("secteur"),
        "statut": lab("statut"), "fonction": lab("fonction"), "date_arrivee": (a.get("date_arrivee") or "")[:10],
        "date_depart": (a.get("date_depart") or "")[:10],
    }


def search_agents(query, limit=12):
    """Saisie prédictive : agents en poste dont le nom, le prénom ou le matricule contient tous les mots saisis.

    L'API filtre sur un seul terme : on interroge avec le mot le plus long puis on filtre les autres localement."""
    words = _fold(query).split()
    if not words or max(len(w) for w in words) < 2:
        return []
    lead = max(words, key=len)
    data = _get("/api/v1/agents", {"q": lead, "en_poste": "true", "limit": 100})
    out = []
    for a in data.get("data") or []:
        hay = _fold("%s %s %s" % (a.get("nom"), a.get("prenom"), a.get("matricule")))
        if all(w in hay for w in words):
            out.append(_agent_summary(a))
    out.sort(key=lambda x: (x["nom"], x["prenom"]))
    return out[:limit]


_ORG = {"at": 0.0, "units": None}


def organisation_units(force=False):
    """Liste à plat des unités (direction > service > secteur > équipe) : [{code, libelle, level, parent_code, position}]."""
    with _lock:
        if not force and _ORG["units"] is not None and time.monotonic() - _ORG["at"] < CACHE_SECONDS:
            return _ORG["units"]
    data = _get("/api/v1/organisation", timeout=60)
    units, seen = [], set()

    def add(node, level, parent):
        code = (node.get("code") or "").strip()
        if not code or code in seen:
            return code
        seen.add(code)
        units.append({"code": code, "libelle": (node.get("libelle") or "").strip(), "level": level,
                      "parent_code": parent, "position": len(units)})
        return code

    for d in data.get("data") or []:
        dc = add(d, "direction", "")
        for s in d.get("services") or []:
            sc = add(s, "service", dc)
            for sec in s.get("secteurs") or []:
                secc = add(sec, "secteur", sc)
                for eq in sec.get("equipes") or []:
                    add(eq, "equipe", secc)
    # Des équipes (ex. « Équipe projet éduc. innovation inclusion », BF1112) ne figurent pas dans /organisation mais sont
    # portées par des agents : on les ajoute (niveau « équipe »), rattachées à l'unité connue la plus proche (préfixe du code).
    try:
        for a in all_agents():
            for key in ("service", "secteur", "affectation"):
                u = a.get(key) or {}
                code, label = (u.get("code") or "").strip(), (u.get("libelle") or "").strip()
                if not code or code in seen or not label:
                    continue
                parent = next((code[:n] for n in range(len(code) - 1, 0, -1) if code[:n] in seen),
                              ((a.get("direction") or {}).get("code") or ""))
                if parent and parent in seen:
                    seen.add(code)
                    units.append({"code": code, "libelle": label, "level": "equipe", "parent_code": parent, "position": len(units)})
    except SeditError:
        pass
    with _lock:
        _ORG.update(at=time.monotonic(), units=units)
    return units
