"""Panel admin: memicu GitHub Action untuk menjelajah seluruh situs dari satu link. Dilindungi ADMIN_KEY."""
import json, os, hmac, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

class handler(BaseHTTPRequestHandler):
    def reply(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        try: d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 5000)) or "{}")
        except Exception: return self.reply({"error": "Body bukan JSON"}, 400)
        admin = os.environ.get("ADMIN_KEY", "")
        if not admin or not hmac.compare_digest(str(d.get("key", "")), admin):
            time.sleep(1.5); return self.reply({"error": "Kunci salah"}, 401)
        url = str(d.get("url", "")).strip()
        if url and not url.startswith("http"): url = "https://" + url
        if url and not urlparse(url).netloc: return self.reply({"error": "URL tidak valid"}, 400)
        mx = str(d.get("max", "1000")); mx = mx if mx.isdigit() else "1000"
        repo = os.environ.get("GH_REPO", "").strip()
        for pre in ("https://github.com/", "http://github.com/", "github.com/"):
            if repo.lower().startswith(pre): repo = repo[len(pre):]
        repo = repo.strip("/")
        if repo.endswith(".git"): repo = repo[:-4]
        token = os.environ.get("GH_TOKEN", "").strip()
        branch = os.environ.get("GH_BRANCH", "main").strip() or "main"
        if repo.count("/") != 1 or not token:
            return self.reply({"error": "Env belum benar: GH_REPO harus 'user/repo' (terbaca: '%s'), GH_TOKEN %s. Redeploy setelah mengubah env." % (repo, "ada" if token else "KOSONG")}, 500)
        body = json.dumps({"ref": branch, "inputs": {"url": url, "max": mx, "folder": "true" if d.get("folder") else "false"}}).encode()
        req = urllib.request.Request("https://api.github.com/repos/%s/actions/workflows/crawl.yml/dispatches" % repo, body,
            {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "rhf-cari", "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            try: pesan = json.loads(e.read().decode("utf-8", "ignore")).get("message", "")[:150]
            except Exception: pesan = ""
            return self.reply({"error": "GitHub menolak (%d) untuk repo '%s' branch '%s': %s" % (e.code, repo, branch, pesan)}, 502)
        except Exception as e:
            return self.reply({"error": "Gagal menghubungi GitHub: " + str(e)[:80]}, 502)
        self.reply({"ok": True, "pesan": "Crawl dimulai di GitHub Actions" + (": " + url if url else " (segarkan semua situs)")})
        
