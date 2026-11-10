# -*- coding: utf-8 -*-
"""Sauvegardes automatiques de la base SQLite.

- copie coherente via l'API backup de sqlite3 ;
- rotation des fichiers (30 par defaut) ;
- verification d'integrite et test de restauration sur une copie temporaire ;
- planificateur en arriere-plan appele au demarrage de l'application.
"""
import datetime as dt
import os
import shutil
import sqlite3
import threading
import time

from db import DB_PATH, BASE_DIR

BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BACKUP_PREFIX = "suivi-conges-"
DEFAULT_KEEP = 30
DEFAULT_INTERVAL = 6 * 3600
MAX_AGE = 24 * 3600
_lock = threading.Lock()


def _log(message):
    line = "%s [backup] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    print(line)
    try:
        with open(os.path.join(BASE_DIR, "backup.log"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def backup_files(backup_dir=BACKUP_DIR):
    if not os.path.isdir(backup_dir):
        return []
    return sorted(
        os.path.join(backup_dir, name)
        for name in os.listdir(backup_dir)
        if name.startswith(BACKUP_PREFIX) and name.endswith(".db")
    )


def verify_backup(path):
    """Teste l'integrite et une restauration sur une copie temporaire."""
    if not os.path.exists(path):
        return {"ok": False, "error": "fichier absent"}
    test_path = path + ".restore-test"
    try:
        shutil.copy2(path, test_path)
        conn = sqlite3.connect(test_path)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {}
        for table in ("users", "agents", "settings", "leave_requests"):
            try:
                counts[table] = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
        conn.close()
        ok = integrity == "ok"
        return {"ok": ok, "integrity": integrity, "counts": counts, "test_copy": test_path}
    except Exception as exc:  # noqa: BLE001 - le diagnostic ne doit pas casser l'app
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            if os.path.exists(test_path):
                os.remove(test_path)
        except OSError:
            pass


def rotate_backups(backup_dir=BACKUP_DIR, keep=DEFAULT_KEEP):
    files = backup_files(backup_dir)
    if len(files) <= keep:
        return []
    removed = []
    for path in files[:-keep]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError as exc:
            _log("rotation impossible pour %s : %s" % (path, exc))
    if removed:
        _log("%s ancienne(s) sauvegarde(s) supprimee(s)" % len(removed))
    return removed


def create_backup(db_path=DB_PATH, backup_dir=BACKUP_DIR, keep=DEFAULT_KEEP):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(backup_dir, "%s%s.db" % (BACKUP_PREFIX, stamp))
    with _lock:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()
        check = verify_backup(target)
        if not check.get("ok"):
            _log("sauvegarde creee mais verification en echec : %s" % check)
            return target, check
        rotate_backups(backup_dir, keep)
        _log("sauvegarde OK : %s" % target)
        return target, check


def _needs_backup(backup_dir=BACKUP_DIR, max_age=MAX_AGE):
    files = backup_files(backup_dir)
    if not files:
        return True
    latest = max(os.path.getmtime(path) for path in files)
    return (time.time() - latest) >= max_age


def start_backup_scheduler(interval=DEFAULT_INTERVAL, keep=DEFAULT_KEEP):
    """Lance une sauvegarde si necessaire puis verifie regulierement."""
    if os.environ.get("CONGES_DISABLE_BACKUPS") == "1":
        return None

    def run():
        while True:
            try:
                if _needs_backup():
                    create_backup(keep=keep)
            except Exception as exc:  # noqa: BLE001 - une sauvegarde ratee ne doit pas stopper l'app
                _log("echec de la sauvegarde automatique : %s" % exc)
            time.sleep(max(300, int(interval)))

    thread = threading.Thread(target=run, name="conges-backup", daemon=True)
    thread.start()
    _log("planificateur de sauvegarde demarre (rotation %s fichiers)" % keep)
    return thread


if __name__ == "__main__":
    path, result = create_backup()
    print("Sauvegarde :", path)
    print("Verification :", result)
