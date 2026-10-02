#!/usr/bin/env python3
"""RHF Cari - crawler untuk Supabase. Hanya library standar Python 3.8+. Dijalankan oleh GitHub Actions.

  python crawler/rhf_crawl.py crawl https://id.wikipedia.org --max 2000
  python crawler/rhf_crawl.py crawl --semua            # segarkan semua situs yang sudah ada di database

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (rahasia!), RHF_CONTACT (email/URL kontakmu), RHF_TEXT_MAX (opsional)
Patuh robots.txt + Crawl-delay, baca sitemap (bersarang/.gz), semua link internal diikuti, antrean disimpan di Supabase.
"""
import sys, os, re, time, json, gzip, html, argparse, urllib.request, urllib.error, urllib.robotparser
from urllib.parse import urljoin, urlparse, urldefrag, quote
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta

UA = "RHFCariBot/1.1 (+%s)" % os.environ.get("RHF_CONTACT", "mesin pencari pribadi")
TEXT_MAX = int(os.environ.get("RHF_TEXT_MAX", 30000))  # batas teks/halaman; database gratis Supabase hanya 500 MB
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".gz", ".tar", ".mp3", ".mp4", ".webm",
            ".avi", ".mov", ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".exe", ".apk", ".iso", ".7z", ".rar")
TRACK = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_src|mc_)", re.I)

# ---------------------------------------------------------------- Supabase REST
def rest(method, path, body=None, prefer=None, tries=4):
    base = os.environ["SUPABASE_URL"].rstrip("/"); key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"): h["Authorization"] = "Bearer " + key  # kunci lama = JWT; kunci baru sb_* cukup lewat apikey
    if prefer: h["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        try:
            req = urllib.request.Request(base + "/rest/v1/" + path, data, h, method=method)
            with urllib.request.urlopen(req, timeout=60) as f:
                raw = f.read(); return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:300]
            if e.code < 500 and e.code != 429 or i == tries - 1: raise RuntimeError("Supabase %s %s -> %d %s" % (method, path.split("?")[0], e.code, msg))
        except Exception as e:
            if i == tries - 1: raise
        time.sleep(2 ** i)

def inlist(vals):  # nilai untuk filter in.(...) PostgREST
    return "(" + ",".join('"%s"' % v.replace("\\", "\\\\").replace('"', '\\"') for v in vals) + ")"

# ---------------------------------------------------------------- util
def hk(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h

def norm(u):
    u = urldefrag(u)[0]; p = urlparse(u)
    if p.scheme not in ("http", "https"): return u
    q = "&".join(x for x in p.query.split("&") if x and not TRACK.match(x.split("=")[0]))
    return p._replace(query=q, netloc=p.netloc.lower()).geturl()

class Parse(HTMLParser):
    def __init__(s):
        super().__init__(); s.title = ""; s.text = []; s.links = []; s.meta = []; s._skip = 0; s._t = False
    def handle_starttag(s, t, a):
        if t in ("script", "style"): s._skip += 1
        if t == "title": s._t = True
        if t == "meta":
            d = dict(a); k = (d.get("name") or d.get("property") or "").lower()
            if k in ("description", "og:description", "twitter:description", "keywords") and d.get("content"): s.meta.append(d["content"])
        if t == "img":
            for k, v in a:
                if k == "alt" and v: s.text.append(v)
        if t == "a":
            for k, v in a:
                if k == "href" and v: s.links.append(v)
    def handle_endtag(s, t):
        if t in ("script", "style"): s._skip = max(0, s._skip - 1)
        if t == "title": s._t = False
    def handle_data(s, d):
        if s._t: s.title += d
        elif not s._skip: s.text.append(d)

def parse_page(url, raw, base):
    p = Parse(); p.feed(raw)
    title = " ".join(p.title.split()) or url
    text = " ".join(" ".join(p.meta + p.text).split())
    links = [norm(urljoin(base, l)) for l in p.links]
    links = [l for l in dict.fromkeys(links) if l.startswith("http") and not urlparse(l).path.lower().endswith(SKIP_EXT)]
    row = {"url": url[:2000], "host": hk(url), "title": title[:500], "text": text[:TEXT_MAX], "links": links[:500],
           "len": len(text.split()), "ts": datetime.now(timezone.utc).isoformat()}
    return row, links

def _get(url, maxb=5_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=15) as f: b = f.read(maxb)
    if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
    return b.decode("utf-8", "ignore")

def sitemap_urls(site, limit=5000, depth=0, seen=None):
    seen = set() if seen is None else seen; out = []
    if depth == 0:
        cands = [urljoin(site, "/sitemap.xml")]
        try: cands = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", _get(urljoin(site, "/robots.txt"))) + cands
        except Exception: pass
    else: cands = [site]
    for sm in dict.fromkeys(cands):
        if sm in seen or len(out) >= limit: continue
        seen.add(sm)
        try: x = _get(sm)
        except Exception: continue
        locs = [html.unescape(l) for l in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", x)]
        if "<sitemapindex" in x and depth < 3:
            for l in locs:
                out += sitemap_urls(l, limit - len(out), depth + 1, seen)
                if len(out) >= limit: break
        else: out += locs
    return out[:limit]

def load_robots(scheme, host):
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request("%s://%s/robots.txt" % (scheme, host), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as f: rp.parse(f.read(500_000).decode("utf-8", "ignore").splitlines())
    except urllib.error.HTTPError as e:
        rp.parse([] if e.code not in (401, 403) and e.code < 500 else ["User-agent: *", "Disallow: /"])
    except Exception: rp.parse(["User-agent: *", "Disallow: /"])
    rp.modified()
    return rp

# ---------------------------------------------------------------- crawl
def crawl(seeds, maxn=1000, delay=1.0, folder=False, ulang=False, segar=7, menit=330):
    t_end = time.time() + menit * 60; maxn = maxn or 10 ** 9
    ex = [norm(x) for x in seeds]
    if not ex: print("tidak ada URL"); return
    def folder_of(u):
        p = urlparse(u); path = p.path
        if not path.endswith("/"): path = path[:path.rfind("/") + 1] if "." in path.rsplit("/", 1)[-1] else path + "/"
        return "%s://%s%s" % (p.scheme, p.netloc, path or "/")
    pre = tuple(folder_of(e) for e in ex); hosts = {hk(e) for e in ex}
    roots = list(dict.fromkeys(urlparse(e).scheme + "://" + urlparse(e).netloc for e in ex))
    sm = []
    for r in roots: sm += sitemap_urls(r, min(maxn, 20000))
    if sm: print("sitemap:", len(sm), "URL ditemukan")
    first = ex + ([] if folder else [r + "/" for r in roots]) + [u for u in sm if hk(u) in hosts and (not folder or u.startswith(pre))]
    first = [u for u in dict.fromkeys(norm(u) for u in first) if len(u) < 2000]
    hl = inlist(sorted(hosts))
    rest("PATCH", "queue?host=in." + quote(hl), {"done": False})            # buka ulang antrean situs ini
    add_queue(first)
    fresh = set()
    if not ulang:                                                             # halaman yang masih segar dilewati
        since = (datetime.now(timezone.utc) - timedelta(days=segar)).strftime("%Y-%m-%dT%H:%M:%SZ"); off = 0
        while True:
            rows = rest("GET", "pages?select=url&host=in.%s&ts=gt.%s&limit=1000&offset=%d" % (quote(hl), since, off)) or []
            fresh.update(r["url"] for r in rows); off += 1000
            if len(rows) < 1000: break
        print("halaman segar dilewati:", len(fresh))
    robots = {}; last = {}; got = 0; buf = []
    def flush():
        if buf: rest("POST", "pages?on_conflict=url", buf[:], "resolution=merge-duplicates,return=minimal"); buf.clear()
    try:
        while got < maxn and time.time() < t_end:
            batch = rest("GET", "queue?select=id,url&done=eq.false&host=in.%s&order=id.asc&limit=50" % quote(hl)) or []
            if not batch: break
            newlinks = []
            for item in batch:
                if got >= maxn or time.time() >= t_end: break
                url = item["url"]
                if url in fresh: continue
                host = urlparse(url).netloc
                if host not in robots: robots[host] = load_robots(urlparse(url).scheme, host)
                try:
                    if not robots[host].can_fetch(UA, url): print("diblokir robots.txt", url); continue
                    d = max(delay, float(robots[host].crawl_delay(UA) or 0)); gap = d - (time.time() - last.get(host, 0))
                    if gap > 0: time.sleep(gap)
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=15) as f:
                        last[host] = time.time(); final = norm(f.geturl()); ct = f.headers.get("Content-Type", "")
                        if "text/html" not in ct: continue
                        m = re.search(r"charset=([\w-]+)", ct)
                        raw = f.read(1_500_000).decode(m.group(1) if m else "utf-8", "ignore")
                        if hk(final) not in hosts: continue
                except Exception as e:
                    last[host] = time.time(); print("lewati", url, str(e)[:80]); continue
                row, links = parse_page(url, raw, final); got += 1; buf.append(row)
                print("[%d/%s] %s" % (got, maxn if maxn < 10 ** 9 else "tanpa batas", url))
                if row["len"] < 5: print("   ! teks hampir kosong (situs JavaScript, crawler tidak bisa baca isinya)")
                newlinks += [l for l in links if hk(l) in hosts and (not folder or l.startswith(pre))]
                if len(buf) >= 20: flush()
            flush(); add_queue(newlinks)
            if got < maxn and time.time() < t_end:  # batch tuntas -> tandai selesai (kalau berhenti di tengah, diulang run berikutnya)
                rest("PATCH", "queue?id=in.(%s)" % ",".join(str(i["id"]) for i in batch), {"done": True})
    except KeyboardInterrupt:
        print("\ndihentikan, menyimpan...")
    finally:
        flush()
    print("selesai: %d halaman baru/diperbarui. Menghitung peringkat..." % got)
    rest("POST", "rpc/segarkan", {})

def add_queue(urls):
    urls = [u for u in dict.fromkeys(urls) if u.startswith("http") and len(u) < 2000]
    for i in range(0, len(urls), 500):
        rest("POST", "queue?on_conflict=url", [{"url": u, "host": hk(u)} for u in urls[i:i + 500]], "resolution=ignore-duplicates,return=minimal")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["crawl"]); ap.add_argument("urls", nargs="*")
    ap.add_argument("--max", type=int, default=1000, help="maks halaman per run; 0 = tanpa batas")
    ap.add_argument("--delay", type=float, default=1.0); ap.add_argument("--folder", action="store_true")
    ap.add_argument("--ulang", action="store_true", help="abaikan halaman yang masih segar")
    ap.add_argument("--segar", type=int, default=7); ap.add_argument("--menit", type=int, default=330, help="batas waktu run")
    ap.add_argument("--semua", action="store_true", help="segarkan semua situs yang ada di database")
    a = ap.parse_args(); urls = a.urls
    if a.semua: urls = ["https://" + h + "/" for h in (rest("POST", "rpc/daftar_situs", {}) or [])]
    crawl(urls, a.max, a.delay, a.folder, a.ulang, a.segar, a.menit)
