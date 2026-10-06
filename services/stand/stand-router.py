#!/usr/bin/env python3
"""Маршрутизация *.stand.yakutov.com на контейнеры стендов (стенды открытые).

Слушает 127.0.0.1:8093, наружу — только через Caddy:
  GET /ask?domain=…  — Caddy on_demand_tls: сертификат только существующим стендам
  GET /check         — forward_auth: для работающего стенда отдаёт
                       X-Stand-Upstream: 127.0.0.1:<порт> и X-Stand-Kind: <вид>,
                       иначе страницу-заглушку; art-* — на сервис артефактов (8094)
"""
import html
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ("127.0.0.1", 8093)
DOMAIN = "stand.yakutov.com"
STANDS = "/var/lib/stand/stands"
ARTIFACTS = "/var/lib/stand/artifacts"
ARTIFACTS_UPSTREAM = "127.0.0.1:8094"
NAME_RE = re.compile(r"^([a-z0-9][a-z0-9-]{0,62})\." + re.escape(DOMAIN) + r"$")

PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="{refresh}">
<title>Стенд {name}</title><style>body{{font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:15vh auto;
padding:0 16px;color:#1d1d1f;background:#fafafa}}@media(prefers-color-scheme:dark){{body{{color:#eee;
background:#161616}}}}h1{{font-size:1.3rem}}</style><h1>Стенд {name}</h1><p>{text}</p></html>"""


def stand_meta(name):
    try:
        with open(os.path.join(STANDS, name, "meta.env")) as f:
            return dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line)
    except (FileNotFoundError, NotADirectoryError):
        return {}


def artifact_exists(name):
    return name.startswith("art-") and os.path.isfile(os.path.join(ARTIFACTS, name, "meta.env"))


def stand_name(host):
    m = NAME_RE.match((host or "").split(":")[0].lower())
    return m.group(1) if m else None


class Handler(BaseHTTPRequestHandler):
    server_version = "stand-router"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, headers=None, body=""):
        data = body.encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if data:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/ask":
            name = stand_name(urllib.parse.parse_qs(url.query).get("domain", [""])[0])
            return self.send(200 if name and (stand_meta(name) or artifact_exists(name)) else 404)
        if url.path != "/check":
            return self.send(404)

        name = stand_name(self.headers.get("X-Forwarded-Host", ""))
        if name and artifact_exists(name):
            return self.send(200, {"X-Stand-Upstream": ARTIFACTS_UPSTREAM, "X-Stand-Kind": "artifact"})
        meta = stand_meta(name) if name else {}
        status = meta.get("status")
        if status == "running":
            return self.send(200, {"X-Stand-Upstream": f"127.0.0.1:{int(meta['port'])}",
                                   "X-Stand-Kind": meta.get("kind") or "epus-frontend"})
        text, refresh = {
            None: ("Стенда нет или он уже удалён.", 3600),
            "building": ("Собирается — страница обновится сама.", 15),
            "failed": ("Сборка упала: " + html.escape(meta.get("error", "")), 3600),
        }.get(status, (html.escape(str(status)), 60))
        self.send(404 if status is None else 503,
                  body=PAGE.format(name=html.escape(name or "?"), text=text, refresh=refresh))


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
