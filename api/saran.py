import json, os, urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0][:100]
        try:
            base = os.environ["SUPABASE_URL"].rstrip("/"); key = os.environ["SUPABASE_ANON_KEY"]
            req = urllib.request.Request(base + "/rest/v1/rpc/saran", json.dumps({"q": q}).encode(),
                                         dict({"apikey": key, "Content-Type": "application/json"}, **({"Authorization": "Bearer " + key} if key.startswith("eyJ") else {})))
            with urllib.request.urlopen(req, timeout=6) as f: out = json.loads(f.read() or "[]")
        except Exception: out = []
        b = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=300"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
