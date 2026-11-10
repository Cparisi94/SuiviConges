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
