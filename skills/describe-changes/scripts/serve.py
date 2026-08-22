#!/usr/bin/env python3
"""serve.py — serve a describe-changes report dir over HTTP and capture feedback.

Usage: serve.py <report-dir> [--port 8790]
  GET  /            → index.html
  POST /feedback    → appends each event to <report-dir>/feedback.jsonl (one JSON per line)
Prints LAN + Tailscale URLs. Kills a previous server on the same port (pid file in the report dir's parent).
Runs in the foreground by default — start it with `nohup … &` or the skill's recipe (see SKILL.md).
"""
import argparse, json, os, subprocess, sys, signal, socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

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
    ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args(); d = os.path.abspath(a.dir)
    pidfile = os.path.join(os.path.dirname(d), f".serve-{a.port}.pid")
    if os.path.exists(pidfile):
        try:
            old = int(open(pidfile).read().strip()); os.kill(old, signal.SIGTERM); print(f"(stopped previous server pid {old})")
        except Exception: pass
    fb_path = os.path.join(d, "feedback.jsonl")

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw): super().__init__(*args, directory=d, **kw)
        def log_message(self, *args): pass
        def do_POST(self):
            if self.path.rstrip("/").endswith("/feedback") or self.path == "/feedback":
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
    print("┌─ describe-changes report ready ─────────────────────────────")
    print(f"│  Local:      http://localhost:{a.port}/")
    if lan: print(f"│  LAN:        http://{lan}:{a.port}/")
    if ts:  print(f"│  Tailscale:  http://{ts}:{a.port}/")
    print(f"│  Feedback →  {fb_path}")
    print(f"│  PID {os.getpid()} — stop with: kill {os.getpid()}")
    print("└──────────────────────────────────────────────────────────────", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        try: os.remove(pidfile)
        except Exception: pass

if __name__ == "__main__":
    main()
