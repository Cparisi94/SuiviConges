# -*- coding: utf-8 -*-
"""Serveur de développement de la version mobile : remplace nginx sur un poste sans Docker.

Sert `public/` et relaie vers le backend la MÊME liste blanche que nginx.conf.template (toute autre route d'API : 404).
    python dev_server.py [port] [url du backend]          (défaut : 8113, http://127.0.0.1:8110)
Ne sert qu'au développement : en DMZ, c'est le conteneur nginx de ce dossier qui est déployé.
"""
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8113
BACKEND = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8110").rstrip("/")

# (méthodes autorisées, expression du chemin) : miroir de la liste blanche de nginx.conf.template
ALLOWED = [
    ({"POST"}, re.compile(r"^/api/auth/login$")),
    ({"POST"}, re.compile(r"^/api/auth/logout$")),
    ({"GET"}, re.compile(r"^/api/me$")),
    ({"GET"}, re.compile(r"^/api/mobile/(summary|days|calendar)$")),
    ({"POST"}, re.compile(r"^/api/mobile/calendar/(link|revoke)$")),
    ({"POST"}, re.compile(r"^/api/requests$")),
    ({"POST"}, re.compile(r"^/api/mobile/requests/[0-9]+/(cancel|cancel-request)$")),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "conges-mobile-dev"

    def _send(self, status, body=b"", ctype="text/plain; charset=utf-8", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _api(self):
        path = self.path.split("?", 1)[0]
        # flux d'abonnement ICS : /cal/<jeton>.ics -> /api/ical/<jeton>.ics (comme le fait nginx), sans session
        feed = re.match(r"^/cal/([A-Za-z0-9_-]{20,80})\.ics$", path)
        if feed and self.command in ("GET", "HEAD"):
            self.path = "/api/ical/%s.ics" % feed.group(1)
            path = self.path
            rule = {"GET", "HEAD"}
        else:
            rule = None
        rule = rule or next((m for m, rx in ALLOWED if rx.match(path)), None)
        if rule is None:
            return self._send(404, b'{"error":"Introuvable"}', "application/json")
        if self.command not in rule:
            return self._send(405, b'{"error":"Methode non autorisee"}', "application/json")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json"), "X-Forwarded-For": self.client_address[0]}
        if self.headers.get("Cookie"):
            headers["Cookie"] = self.headers["Cookie"]
        try:
            r = requests.request(self.command, BACKEND + self.path, data=body, headers=headers, timeout=60, allow_redirects=False)
        except requests.RequestException as exc:
            return self._send(502, ('{"error":"Backend injoignable (%s)"}' % exc.__class__.__name__).encode(), "application/json")
        extra = [("Set-Cookie", c) for c in r.raw.headers.getlist("Set-Cookie")]
        self._send(r.status_code, r.content, r.headers.get("Content-Type", "application/json"), extra)

    def _static(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._send(200, b"ok")
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(ROOT, rel))
        if not full.startswith(ROOT) or not os.path.isfile(full):
            full = os.path.join(ROOT, "index.html")          # repli, comme try_files de nginx
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")

    def _dispatch(self):
        if self.path.startswith("/api/") or self.path.startswith("/cal/"):
            return self._api()
        return self._static()

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = _dispatch

    def log_message(self, fmt, *args):
        sys.stderr.write("[mobile-dev] " + (fmt % args) + "\n")


if __name__ == "__main__":
    print("Version mobile : http://127.0.0.1:%d  (backend : %s)" % (PORT, BACKEND), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
