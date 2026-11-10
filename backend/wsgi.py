# -*- coding: utf-8 -*-
"""Point d'entrée WSGI (gunicorn) : applique les migrations, crée le compte initial si la base est vide,
démarre les tâches de fond, puis expose l'application.

    gunicorn -b 0.0.0.0:8110 --workers 1 --threads 8 wsgi:application

Un seul processus (plusieurs threads) : les relances automatiques et la limitation de débit sont
en mémoire de processus ; plusieurs processus enverraient les relances en double.
"""
import app as core

core.bootstrap()
application = core.app
