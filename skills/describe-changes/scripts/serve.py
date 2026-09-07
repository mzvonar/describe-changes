#!/usr/bin/env python3
"""serve.py — serve a describe-changes report dir over HTTP and capture feedback.

Usage: serve.py <report-dir> [--port 8790] [--token T | --no-token]
  GET  /            → index.html
  POST /feedback    → appends each event to <report-dir>/feedback.jsonl (one JSON per line)

The server binds 0.0.0.0 ON PURPOSE — reading the report on a phone is the point, and that
cannot work from a loopback bind. What the bind does NOT decide is who may read it: the report
directory holds `raw.diff` and `substantive.diff`, i.e. the whole change, so every request is
gated on a per-run secret unless you opt out.

  * A fresh token is minted per run and printed INSIDE the URLs. Open the printed link and it
    just works: the first request carries `?k=…`, the reply sets a cookie, and every relative
    request after it (delta pages, the feedback POST) rides the cookie.
  * `--token T` pins it (stable URL across restarts), `--no-token` restores the pre-1.9
    open-to-the-network behaviour for a loopback-only or otherwise trusted setup.
  * A request with neither query nor cookie gets 403 and no file is read.

Prints LAN + Tailscale URLs. Kills a previous server on the same port (pid file in the report dir's parent).
Runs in the foreground by default — start it with `nohup … &` or the skill's recipe (see SKILL.md).
"""
import argparse, hmac, json, os, secrets, subprocess, signal, socket
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

COOKIE = "dc_report"

def ip_lan():
    for cmd in (["ipconfig", "getifaddr", "en0"], ["ipconfig", "getifaddr", "en1"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
            if out: return out
        except Exception: pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return ""

def ip_tailscale():
    try: return subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2).stdout.strip().splitlines()[0]
    except Exception: return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--token", default=None, help="pin the access token instead of minting one")
    ap.add_argument("--no-token", action="store_true", help="serve with NO access control (pre-1.9 behaviour)")
    a = ap.parse_args(); d = os.path.abspath(a.dir)
    token = "" if a.no_token else (a.token or secrets.token_urlsafe(16))
    pidfile = os.path.join(os.path.dirname(d), f".serve-{a.port}.pid")
    if os.path.exists(pidfile):
        try:
            old = int(open(pidfile).read().strip()); os.kill(old, signal.SIGTERM); print(f"(stopped previous server pid {old})")
        except Exception: pass
    fb_path = os.path.join(d, "feedback.jsonl")

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw): super().__init__(*args, directory=d, **kw)
        def log_message(self, *args): pass

        def _ok(self):
            """True when the caller proved the secret. Sets a cookie when it came by query."""
            if not token: return True
            given = parse_qs(urlparse(self.path).query).get("k", [""])[0]
            if given and hmac.compare_digest(given, token):
                self._cookie = token
                return True
            raw = self.headers.get("Cookie", "")
            if raw:
                got = SimpleCookie(raw).get(COOKIE)
                if got and hmac.compare_digest(got.value, token): return True
            return False

        def _deny(self):
            self.send_response(403); self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"403 - this report needs its access token; open the URL printed by serve.py\n")

        def end_headers(self):
            c = getattr(self, "_cookie", "")
            if c: self.send_header("Set-Cookie", f"{COOKIE}={c}; Path=/; SameSite=Lax; Max-Age=86400")
            super().end_headers()

        def do_GET(self):
            if not self._ok(): return self._deny()
            super().do_GET()

        def do_HEAD(self):
            if not self._ok(): return self._deny()
            super().do_HEAD()

        def do_POST(self):
            if not self._ok(): return self._deny()
            if self.path.rstrip("/").endswith("/feedback") or self.path.split("?")[0] == "/feedback":
                n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
                try:
                    events = json.loads(body).get("events", [])
                    with open(fb_path, "a") as fh:
                        for e in events: fh.write(json.dumps(e) + "\n")
                    self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "stored": len(events)}).encode())
                    print(f"feedback: +{len(events)} → {fb_path}", flush=True)
                except Exception as ex:
                    self.send_response(400); self.end_headers(); self.wfile.write(str(ex).encode())
            else:
                self.send_response(404); self.end_headers()

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    open(pidfile, "w").write(str(os.getpid()))
    lan, ts = ip_lan(), ip_tailscale()
    q = f"?k={token}" if token else ""
    print("┌─ describe-changes report ready ─────────────────────────────")
    print(f"│  Local:      http://localhost:{a.port}/{q}")
    if lan: print(f"│  LAN:        http://{lan}:{a.port}/{q}")
    if ts:  print(f"│  Tailscale:  http://{ts}:{a.port}/{q}")
    if os.path.exists(os.path.join(d, "delta.html")):
        print(f"│  Since last: http://localhost:{a.port}/delta.html{q}   (what moved; picker for earlier snapshots)")
    print(f"│  Feedback →  {fb_path}")
    if token: print("│  Access:     token in the URLs above; the first open sets a cookie for the rest.")
    else:     print("│  Access:     OPEN — --no-token was passed; anyone who can reach this port can read the diff.")
    print(f"│  PID {os.getpid()} — stop with: kill {os.getpid()}")
    print("└──────────────────────────────────────────────────────────────", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        try: os.remove(pidfile)
        except Exception: pass

if __name__ == "__main__":
    main()
