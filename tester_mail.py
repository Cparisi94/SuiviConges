# -*- coding: utf-8 -*-
"""Test manuel de la configuration mail.json.

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
        print("Envoi désactivé ou configuration incomplète dans mail.json.")
        print("Vérifiez 'enabled', 'host' et 'from'.")
        return 1
    ok, error = send_mail(
        sys.argv[1],
        "[Suivi congés] Test d'envoi",
        "Ceci est un test de la configuration SMTP de l'outil de suivi des congés.",
    )
    if ok:
        print("E-mail de test envoyé à", sys.argv[1])
        return 0
    print("Échec de l'envoi :", error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
