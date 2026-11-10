# -*- coding: utf-8 -*-
"""Limitation de débit en mémoire (fenêtre glissante).

Suffisant pour un processus unique ; avec plusieurs processus (gunicorn -w N), chaque
processus compte séparément : la limite effective est alors multipliée par N.
"""
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_events = defaultdict(deque)


def allow(bucket, limit, window_seconds):
    """Enregistre un événement ; False si `limit` événements ont déjà eu lieu dans la fenêtre."""
    now = time.monotonic()
    with _lock:
        events = _events[bucket]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


def blocked(bucket, limit, window_seconds):
    """True si la limite est atteinte, sans enregistrer d'événement."""
    now = time.monotonic()
    with _lock:
        events = _events[bucket]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        return len(events) >= limit


def record(bucket):
    with _lock:
        _events[bucket].append(time.monotonic())


def reset():
    with _lock:
        _events.clear()
