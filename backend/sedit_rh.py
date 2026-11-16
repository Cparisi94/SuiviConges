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


def _agent_summary(a):
    """Champs utiles à la création d'une personne (jamais l'enregistrement complet)."""
    def lab(key):
        return ((a.get(key) or {}).get("libelle") or "").strip()

    aff = a.get("affectation") or {}
    return {
        "matricule": a.get("matricule") or "", "nom": (a.get("nom") or "").strip(), "prenom": (a.get("prenom") or "").strip(),
        "unit_code": aff.get("code") or "", "unit_libelle": (aff.get("libelle") or "").strip(),
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
