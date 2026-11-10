' Demarrage du prototype Outil conges (port 5567)
' Dossier volontairement separe de la version de production (port 5566).
Option Explicit

Dim sh, py, dir
Set sh = CreateObject("WScript.Shell")

py = "C:\Users\CPARISI\AppData\Local\Programs\Python\Python312\pythonw.exe"
' Chemin court pour eviter les accents du dossier "Projet par defaut".
dir = "C:\Users\CPARISI\DOCUME~1\PROJET~1\SUIVI-~2"

sh.Environment("Process")("CONGES_PORT") = "5567"
sh.CurrentDirectory = dir
sh.Run """" & py & """ """ & dir & "\serve.py""", 0, False
