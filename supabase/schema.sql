-- RHF Cari - skema Supabase (Postgres). Jalankan SEKALI di Supabase > SQL Editor > New query > Run.
create extension if not exists pg_trgm with schema extensions;

create table if not exists pages (
  url   text primary key,
  host  text not null,
  title text,
  text  text,
  links jsonb not null default '[]',
  rank  real  not null default 0,
  len   int   not null default 0,
  ts    timestamptz not null default now(),
  fts   tsvector generated always as (
          setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
          setweight(to_tsvector('simple', coalesce(left(text, 200000), '')), 'B')) stored
);
create index if not exists pages_fts  on pages using gin (fts);
create index if not exists pages_host on pages (host);
create index if not exists pages_ts   on pages (ts);

create table if not exists queue (
  id   bigint generated always as identity primary key,
  url  text unique not null,
  host text not null,
  done boolean not null default false
);
create index if not exists queue_todo on queue (host, done, id);

-- Keamanan: tabel tertutup untuk publik. Hanya fungsi di bawah yang bisa dipanggil lewat kunci anon.
alter table pages enable row level security;
alter table queue enable row level security;

-- Daftar kata (untuk "Maksud Anda" & autocomplete), diperbarui setelah tiap crawl.
create materialized view if not exists kata as
  select word, ndoc from ts_stat('select fts from pages');
create index if not exists kata_trgm on kata using gin (word extensions.gin_trgm_ops);
revoke all on kata from anon, authenticated;

-- Pencarian. Mendukung: kata biasa, "frasa pas", -kecualikan, kata1 or kata2; filter situs lewat parameter.
create or replace function cari(q text, situs text default null, lim int default 10, ofs int default 0)
returns table (url text, title text, cuplikan text, skor real, total bigint)
language sql stable security definer set search_path = public, extensions as $$
  with tq as (select websearch_to_tsquery('simple', q) as tsq),
  hit as (
    select p.url, p.title, p.text,
           (ts_rank_cd(p.fts, tq.tsq, 32) * (1 + 0.3 * p.rank))::real as skor,
           count(*) over () as total
    from pages p, tq
    where p.fts @@ tq.tsq
      and (situs is null or p.host = situs or p.host like '%.' || situs)
    order by 4 desc
    limit least(lim, 50) offset greatest(ofs, 0)
  )
  select h.url, h.title,
         ts_headline('simple', left(h.text, 20000), (select tsq from tq),
                     'MaxFragments=1, MaxWords=35, MinWords=15, StartSel=[[, StopSel=]]') as cuplikan,
         h.skor, h.total
  from hit h order by h.skor desc;
$$;

-- "Maksud Anda": ganti kata yang tidak ada di index dengan kata termirip.
create or replace function maksud(q text) returns text
language plpgsql stable security definer set search_path = public, extensions as $$
declare w text; m text; hasil text := ''; ganti boolean := false;
begin
  for w in select regexp_split_to_table(lower(q), '[^a-z0-9]+') loop
    if w = '' then continue; end if;
    if length(w) > 3 and not exists (select 1 from kata k where k.word = w) then
      select k.word into m from kata k where k.word % w order by similarity(k.word, w) desc, k.ndoc desc limit 1;
      if m is not null then hasil := hasil || m || ' '; ganti := true; continue; end if;
    end if;
    hasil := hasil || w || ' ';
  end loop;
  if ganti then return trim(hasil); end if;
  return null;
end $$;

-- Autocomplete untuk kata terakhir yang diketik.
create or replace function saran(q text) returns setof text
language plpgsql stable security definer set search_path = public, extensions as $$
declare depan text; akhir text;
begin
  q := lower(q); akhir := substring(q from '([a-z0-9]+)$');
  if akhir is null or length(akhir) < 2 then return; end if;
  depan := left(q, length(q) - length(akhir));
  return query select depan || k.word from kata k
               where k.word like akhir || '%' and k.word <> akhir order by k.ndoc desc limit 6;
end $$;

-- Hanya untuk crawler (service key): peringkat sederhana berdasar jumlah link masuk, lalu segarkan daftar kata.
create or replace function hitung_rank() returns void
language sql security definer set search_path = public set statement_timeout = '180s' as $$
  with masuk as (
    select l.u as url, count(*)::float as n
    from pages p, jsonb_array_elements_text(p.links) as l(u) group by l.u),
  mx as (select coalesce(max(ln(1 + n)), 1) as m from masuk)
  update pages g set rank = coalesce(r.v, 0)
  from (select g1.url, ln(1 + coalesce(x.n, 0)) / (select m from mx) as v
        from pages g1 left join masuk x on x.url = g1.url) r
  where r.url = g.url;
$$;

create or replace function segarkan() returns void
language plpgsql security definer set search_path = public, extensions set statement_timeout = '180s' as $$
begin
  perform hitung_rank();
  refresh materialized view kata;
end $$;

create or replace function daftar_situs() returns setof text
language sql stable security definer set search_path = public as $$ select distinct host from pages $$;

revoke all on function cari(text, text, int, int), maksud(text), saran(text),
                       hitung_rank(), segarkan(), daftar_situs() from public, anon, authenticated;
grant execute on function cari(text, text, int, int), maksud(text), saran(text) to anon, authenticated;
grant execute on function hitung_rank(), segarkan(), daftar_situs() to service_role;
