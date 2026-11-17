# -*- coding: utf-8 -*-
"""Backend mobile sur le poste de développement : http://127.0.0.1:8115 (la page est servie à la racine ; derrière nginx : /mobile/).

    cd backend
    ../.venv/Scripts/python run_mobile.py

Le backend principal doit tourner (migrations, tâches de fond) : ce processus-ci n'en lance aucune (voir wsgi_mobile.py).
"""
import os

os.environ["CONGES_MODE"] = "mobile"

import app as core  # noqa: E402

if __name__ == "__main__":
    core.app.run(host="127.0.0.1", port=int(os.environ.get("CONGES_MOBILE_PORT", "8115")), debug=False)
