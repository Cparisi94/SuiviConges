# -*- coding: utf-8 -*-
"""Point d'entrée WSGI du BACKEND MOBILE (gunicorn) : voir mobile_mode.py.

    gunicorn -b 0.0.0.0:8115 --workers 1 --threads 8 wsgi_mobile:application

Contrairement à `wsgi.py`, il n'appelle PAS `bootstrap()` : ni migrations, ni compte initial, ni relances par e-mail, ni synchronisation Outlook, ni
préchauffage de Sedit RH. Ces tâches restent celles du backend principal, qui doit être démarré en premier (même base de données) ; les lancer ici les
exécuterait en double (e-mails envoyés deux fois).
"""
import os

os.environ["CONGES_MODE"] = "mobile"            # avant l'import : l'application active alors la liste blanche de routes

import app as core  # noqa: E402

application = core.app
