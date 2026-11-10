# -*- coding: utf-8 -*-
"""Test manuel de l'envoi de mail via l'APM (CONGES_MAIL_ENABLED, APM_API_URL, APM_API_KEY).

Usage :
    python tester_mail.py destinataire@example.fr
"""
import sys

from mailer import load_config, send_mail


def main():
    if len(sys.argv) < 2:
        print("Usage : python tester_mail.py destinataire@example.fr")
        return 1
    cfg = load_config()
    if not cfg:
        print("Envoi désactivé ou APM non configurée.")
        print("Vérifiez CONGES_MAIL_ENABLED, APM_API_URL et APM_API_KEY dans .env.")
        return 1
    ok, error = send_mail(
        sys.argv[1],
        "[Suivi congés] Test d'envoi",
        "Ceci est un test d'envoi par l'APM de l'outil de suivi des congés.",
    )
    if ok:
        print("E-mail de test envoyé à", sys.argv[1])
        return 0
    print("Échec de l'envoi :", error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
