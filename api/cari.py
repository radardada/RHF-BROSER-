import json, os, re, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

def rpc(fn, args):
    base = os.environ["SUPABASE_URL"].rstrip("/"); key = os.environ["SUPABASE_ANON_KEY"]
    req = urllib.request.Request("%s/rest/v1/rpc/%s" % (base, fn), json.dumps(args).encode(),
                                 dict({"apikey": key, "Content-Type": "application/json"}, **({"Authorization": "Bearer " + key} if key.startswith("eyJ") else {})))
    with urllib.request.urlopen(req, timeout=8) as f: return json.loads(f.read() or "null")

class handler(BaseHTTPRequestHandler):
    def reply(self, obj, code=200, cache="public, s-maxage=60, stale-while-revalidate=300"):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query); q = qs.get("q", [""])[0][:200].strip()
        p = qs.get("p", ["1"])[0]; p = max(1, min(50, int(p))) if p.isdigit() else 1
        if not q: return self.reply({"q": "", "total": 0, "hasil": []})
        m = re.search(r"(?i)\bsite:(\S+)", q); situs = re.sub(r"^www\.", "", m.group(1).lower()) if m else None
        q2 = re.sub(r"(?i)\bsite:\S+", " ", q).strip()
        try:
            rows = rpc("cari", {"q": q2, "situs": situs, "lim": 10, "ofs": (p - 1) * 10}) or []
            total = rows[0]["total"] if rows else 0
            saran = rpc("maksud", {"q": q2}) if total < 3 and q2 else None
        except Exception as e:
            return self.reply({"error": "Pencarian gagal: " + str(e)[:120]}, 502, "no-store")
        self.reply({"q": q, "halaman": p, "total": total, "saran": saran,
                    "hasil": [{"url": r["url"], "judul": r["title"], "cuplikan": r["cuplikan"], "skor": r["skor"]} for r in rows]})
