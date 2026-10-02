# RHF Cari (Vercel + GitHub + Supabase)

```
Browser ──> Vercel (public/ + api/*.py) ──RPC──> Supabase Postgres (pages, queue, fungsi cari)
                                                      ▲
GitHub Actions (crawler/rhf_crawl.py) ── service key ─┘   ← dipicu dari /admin.html atau tiap Minggu
```

## 1. Supabase
1. supabase.com → New project.
2. SQL Editor → New query → tempel isi `supabase/schema.sql` → Run.
3. Project Settings → API: catat **Project URL**, kunci **anon** dan **service_role**
   (kalau hanya ada kunci `sb_publishable_`/`sb_secret_`, itu juga bisa dipakai).

## 2. GitHub
```bash
cd rhf-cari
git init && git add . && git commit -m "RHF Cari"
git branch -M main
git remote add origin https://github.com/USERNAME/rhf-cari.git
git push -u origin main
```
Repo → Settings → Secrets and variables → Actions → New repository secret:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role), `RHF_CONTACT` (emailmu).

Buat token untuk panel admin: GitHub → Settings → Developer settings → Fine-grained tokens →
hanya repo ini, izin **Actions: Read and write** → salin tokennya.

## 3. Vercel
vercel.com → Add New → Project → import repo (Framework: Other). Environment Variables:
`SUPABASE_URL`, `SUPABASE_ANON_KEY` (anon, BUKAN service_role), `ADMIN_KEY` (password bebas),
`GH_TOKEN` (token di atas), `GH_REPO` (`USERNAME/rhf-cari`). Deploy.

## 4. Pakai
Buka `https://proyekmu.vercel.app/admin.html` → isi kunci admin + link situs → Mulai crawl.
Selesai dalam beberapa menit-jam (lihat tab Actions), lalu cari di halaman utama.
Manual: Actions → crawl → Run workflow.

Batasan: Supabase gratis = 500 MB (teks per halaman dibatasi 30.000 karakter, ubah `RHF_TEXT_MAX`);
situs JavaScript tidak terbaca; fitur browser/proxy/Tor versi lokal tidak ikut (tidak bisa jalan di Vercel).
