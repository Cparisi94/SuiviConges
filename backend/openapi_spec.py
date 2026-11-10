# -*- coding: utf-8 -*-
"""Description OpenAPI 3 de l'API /api/v1 et page Swagger UI (/api-docs, ressources embarquées)."""
from flask import jsonify
from flask_swagger_ui import get_swaggerui_blueprint

import version
from api_keys import SCOPES

_PAGE = [
    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 200}},
    {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
]
_YEAR = {"name": "year", "in": "query", "schema": {"type": "integer"},
         "description": "Année des fiches (par défaut : année paramétrée dans l'application)"}
_ERRORS = {
    "401": {"description": "Clé API absente, invalide, désactivée ou expirée"},
    "403": {"description": "Périmètre insuffisant ou IP non autorisée"},
    "429": {"description": "Trop de requêtes"},
}


def _get(summary, scope, parameters=(), extra_errors=()):
    responses = {"200": {"description": "OK"}, **_ERRORS}
    for code, text in extra_errors:
        responses[code] = {"description": text}
    return {"get": {
        "summary": summary, "security": [{"ApiKey": []}], "parameters": list(parameters),
        "description": "Périmètre requis : `%s`" % scope, "responses": responses,
    }}


def build_spec():
    agent_id = {"name": "agent_id", "in": "path", "required": True, "schema": {"type": "integer"}}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Suivi des congés — API",
            "version": version.VERSION,
            "description": "API en lecture seule destinée aux applications de la Ville. "
                           "Authentification par clé API (en-tête `X-API-Key`) délivrée par l'administrateur. "
                           "Périmètres : " + "; ".join("`%s` (%s)" % kv for kv in SCOPES.items()),
        },
        "components": {"securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}},
        "paths": {
            "/api/status": {"get": {"summary": "État de l'application et de ses dépendances (sans clé)",
                                    "responses": {"200": {"description": "OK"}, "503": {"description": "Dégradé"}}}},
            "/api/version": {"get": {"summary": "Version de l'application", "responses": {"200": {"description": "OK"}}}},
            "/api/changelog": {"get": {"summary": "Journal des versions (nouveautés)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/agents": _get("Liste paginée des fiches agents", "agents:read",
                                   _PAGE + [_YEAR, {"name": "q", "in": "query", "schema": {"type": "string"},
                                                    "description": "Recherche sur nom / prénom"}]),
            "/api/v1/agents/{agent_id}": _get("Identité d'une fiche", "agents:read", [agent_id],
                                              [("404", "Fiche introuvable")]),
            "/api/v1/agents/{agent_id}/balance": _get("Soldes (CA, RTT, JS, JB, CET…) d'une fiche", "balances:read",
                                                      [agent_id], [("404", "Fiche introuvable"),
                                                                   ("422", "Calcul impossible")]),
            "/api/v1/absences": _get("Absences saisies, par demi-journée", "absences:read", [
                _YEAR, {"name": "from", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "to", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "agent_id", "in": "query", "schema": {"type": "integer"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 200, "maximum": 1000}},
                {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}}]),
            "/api/v1/requests": _get("Demandes de congés", "requests:read", _PAGE + [
                _YEAR, {"name": "status", "in": "query", "schema": {"type": "string"},
                        "description": "en_attente, validee, refusee, annulee, annulation_demandee…"},
                {"name": "agent_id", "in": "query", "schema": {"type": "integer"}}]),
        },
    }


def register_docs(app):
    spec = build_spec()

    @app.route("/api/v1/openapi.json")
    def openapi_json():
        return jsonify(spec)

    app.register_blueprint(get_swaggerui_blueprint(
        "/api-docs", "/api/v1/openapi.json", config={"app_name": "Suivi des congés — API"},
    ))
