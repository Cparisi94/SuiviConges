# -*- coding: utf-8 -*-
"""Aides communes aux routes de l'API : pagination et réponses d'erreur normalisées."""
from flask import jsonify, request


def error(message, status):
    """Corps d'erreur normalisé : {"error": "..."}."""
    return jsonify({"error": message}), status


def page_args(default=50, maximum=200):
    """(limit, offset) lus dans ?limit=&offset= ; valeurs invalides ramenées aux bornes."""
    def to_int(name, fallback):
        try:
            return int(request.args.get(name, fallback))
        except (TypeError, ValueError):
            return fallback

    limit = max(1, min(to_int("limit", default), maximum))
    offset = max(0, to_int("offset", 0))
    return limit, offset


def paged(items, total, limit, offset):
    """Enveloppe de liste paginée."""
    return jsonify({"total": total, "limit": limit, "offset": offset, "items": items})
