# -*- coding: utf-8 -*-
"""Lancement en mode partagé : accessible depuis le réseau (0.0.0.0).

Ce script est utilisé par le raccourci de démarrage automatique. Les traces
sont écrites dans serveur.log car pythonw.exe n'a pas de console.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "serveur.log")

try:
    _log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log
except OSError:
    pass

import app as application  # noqa: E402

if __name__ == "__main__":
    application.bootstrap()
    host = os.environ.get("CONGES_HOST", "0.0.0.0")
    port = int(os.environ.get("CONGES_PORT", "5000"))
    print("=== Demarrage Outil conges (partage) sur %s:%s ===" % (host, port))
    application.app.run(host=host, port=port, debug=False, use_reloader=False)
