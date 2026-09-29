#!/usr/bin/env python3
"""Static site generator for the personal academic website (stdlib only, Python 3.11+).

Layout: see SPEC.md.  This file currently implements the DATA LAYER only
(loading + validating content, parsing BibTeX, grouping/sorting).  HTML rendering
is a stub at the bottom and will be added once the templates are finalised.

    python3 build.py --check     parse all content and print a summary (no output written)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import shutil
import string
import sys
import tomllib
from pathlib import Path

from bibtex import BibError, ContentError, clean_latex, parse_authors, parse_bibtex

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
DIST = ROOT / "dist"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# TOML loading and validation
# ---------------------------------------------------------------------------

def load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ContentError(f"{_rel(path)}: file not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise ContentError(f"{_rel(path)}: invalid TOML: {exc}") from None


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def _check_table(tbl, where: str, required: dict, optional: dict | None = None) -> None:
    """Validate one TOML table: required/optional key -> type (or tuple of types)."""
    if not isinstance(tbl, dict):
        raise ContentError(f"{where}: expected a table")
    for key, typ in required.items():
        if key not in tbl:
            raise ContentError(f"{where}: missing required key '{key}'")
        _check_type(tbl[key], typ, f"{where}: key '{key}'")
    allowed = set(required) | set(optional or {})
    for key, val in tbl.items():
        if key in (optional or {}):
            _check_type(val, optional[key], f"{where}: key '{key}'")
        elif key not in allowed:
            raise ContentError(f"{where}: unknown key '{key}' (allowed: {', '.join(sorted(allowed))})")


def _check_type(val, typ, where: str) -> None:
    if typ == "strlist":
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise ContentError(f"{where} must be a list of strings")
    elif not isinstance(val, typ):
        name = typ.__name__ if isinstance(typ, type) else "/".join(t.__name__ for t in typ)
        raise ContentError(f"{where} must be of type {name}, got {type(val).__name__}")


def _table_list(data: dict, key: str, path: Path, required: bool = False) -> list:
    items = data.get(key, [])
    if key not in data and required:
        raise ContentError(f"{_rel(path)}: missing [[{key}]] entries")
    if not isinstance(items, list):
        raise ContentError(f"{_rel(path)}: '{key}' must be an array of tables ([[{key}]])")
    return items


def load_site() -> dict:
    path = CONTENT / "site.toml"
    d = load_toml(path)
    _check_table(
        d, _rel(path),
        required={"name": str, "owner_short": str, "position": str, "affiliation": str,
                  "email": str, "base_url": str, "bio": "strlist"},
        optional={"portrait": str, "portrait_alt": str, "link": list, "nav": list},
    )
    if d["base_url"] and not re.match(r"^https?://", d["base_url"]):
        raise ContentError(f"{_rel(path)}: base_url must be empty or start with http:// or https://")
    d["base_url"] = d["base_url"].rstrip("/")
    for i, link in enumerate(_table_list(d, "link", path), 1):
        _check_table(link, f"{_rel(path)}: [[link]] #{i}", {"label": str, "url": str})
    for i, nav in enumerate(_table_list(d, "nav", path), 1):
        _check_table(nav, f"{_rel(path)}: [[nav]] #{i}", {"file": str, "label": str})
    d.setdefault("link", [])
    d.setdefault("nav", [])
    return d


def load_projects(pub_keys: set[str]) -> dict:
    """{"intro": [paragraphs], "items": [projects]}."""
    path = CONTENT / "projects.toml"
    d = load_toml(path)
    _check_table(d, _rel(path), {}, {"intro": "strlist", "project": list})
    items = _table_list(d, "project", path)
    for i, p in enumerate(items, 1):
        where = f"{_rel(path)}: [[project]] #{i}"
        _check_table(p, where, {"title": str, "description": str},
                     {"collaborators": "strlist", "papers": "strlist"})
        p.setdefault("collaborators", [])
        p.setdefault("papers", [])
        for key in p["papers"]:
            if key not in pub_keys:
                raise ContentError(f"{where} ('{p['title']}'): paper key '{key}' not found in "
                                   f"content/publications.bib")
    return {"intro": d.get("intro", []), "items": items}


def load_people() -> dict:
    path = CONTENT / "people.toml"
    d = load_toml(path)
    members = _table_list(d, "member", path)
    collabs = _table_list(d, "collaborator", path)
    for i, m in enumerate(members, 1):
        _check_table(m, f"{_rel(path)}: [[member]] #{i}", {"name": str, "role": str},
                     {"note": str, "url": str})
    for i, c in enumerate(collabs, 1):
        _check_table(c, f"{_rel(path)}: [[collaborator]] #{i}", {"name": str, "institution": str},
                     {"url": str})
    return {"members": members, "collaborators": collabs}


def load_teaching() -> list[dict]:
    path = CONTENT / "teaching.toml"
    d = load_toml(path)
    roles = _table_list(d, "role", path)
    for i, r in enumerate(roles, 1):
        where = f"{_rel(path)}: [[role]] #{i}"
        _check_table(r, where, {"title": str}, {"course": list, "section": str})
        r.setdefault("course", [])
        for j, c in enumerate(r["course"], 1):
            _check_table(c, f"{where} course #{j}", {"code": str, "name": str}, {"years": str})
    return roles


def parse_iso_date(text: str, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        raise ContentError(f"{where}: date {text!r} is not a valid YYYY-MM-DD date") from None


def load_news() -> list[dict]:
    """News items, newest first. Adds `date_obj` and `date_label` ("Sep 2026")."""
    path = CONTENT / "news.toml"
    d = load_toml(path)
    items = _table_list(d, "item", path)
    for i, it in enumerate(items, 1):
        where = f"{_rel(path)}: [[item]] #{i}"
        _check_table(it, where, {"date": str, "text": str})
        it["date_obj"] = parse_iso_date(it["date"], where)
        it["date_label"] = f"{MONTHS[it['date_obj'].month - 1]} {it['date_obj'].year}"
    return sorted(items, key=lambda it: it["date_obj"], reverse=True)


# ---------------------------------------------------------------------------
# Bib entries -> clean records (parser lives in bibtex.py)
# ---------------------------------------------------------------------------

# Entries -> clean records ---------------------------------------------------

def _year_of(fields: dict, where: str) -> int:
    for key in ("year", "date"):
        m = re.search(r"\b(1[89]\d\d|20\d\d)\b", fields.get(key, ""))
        if m:
            return int(m.group(1))
    raise BibError(f"{where}: no usable 'year' or 'date' field")


def _common(entry: dict, source: str, owner_short: str) -> dict:
    f = entry["fields"]
    where = f"{source}:{entry['line']}: entry '{entry['key']}'"
    for req in ("title", "author"):
        if not f.get(req, "").strip():
            raise BibError(f"{where}: missing required field '{req}'")
    rec = {
        "key": entry["key"],
        "type": entry["type"],
        "title": clean_latex(f["title"]),
        "authors": parse_authors(f["author"], owner_short),
        "year": _year_of(f, where),
        "pdf": f.get("pdf", "").strip() or None,
        "url": f.get("url", "").strip() or None,
        "doi": f.get("doi", "").strip() or None,
        "note": clean_latex(f["note"]) if f.get("note") else None,
    }
    if rec["doi"]:
        rec["doi"] = re.sub(r"^https?://(dx\.)?doi\.org/", "", rec["doi"])
    if not any(a["is_owner"] for a in rec["authors"]):
        raise BibError(f"{where}: site owner (\\myname{{pearson}}) not in author list")
    for k in ("pdf",):
        if rec[k] and not (STATIC / rec[k]).is_file():
            raise BibError(f"{where}: {k} file '{rec[k]}' not found under static/")
    return rec


def publication_record(entry: dict, source: str, owner_short: str) -> dict:
    rec = _common(entry, source, owner_short)
    f = entry["fields"]
    rec["venue"] = clean_latex(f.get("journal") or f.get("booktitle") or f.get("howpublished") or "")
    rec["volume"] = clean_latex(f.get("volume", "")) or None
    rec["number"] = clean_latex(f.get("number", "")) or None
    rec["pages"] = clean_latex(f.get("pages", "")) or None
    rec["editors"] = parse_authors(f["editor"], owner_short) if f.get("editor") else []
    if not rec["venue"] and entry["type"] not in ("unpublished", "misc"):
        raise BibError(f"{source}:{entry['line']}: entry '{entry['key']}': no journal/booktitle")
    return rec


def talk_record(entry: dict, source: str, owner_short: str) -> dict:
    rec = _common(entry, source, owner_short)
    f = entry["fields"]
    rec["event"] = clean_latex(f.get("howpublished", ""))
    rec["location"] = clean_latex(f.get("location", "")) or None
    if not rec["event"]:
        raise BibError(f"{source}:{entry['line']}: entry '{entry['key']}': missing 'howpublished' (event)")
    return rec


def group_by_year(records: list[dict]) -> list[tuple[int, list[dict]]]:
    """[(year, [records...])], years descending; order within a year follows the file."""
    years = sorted({r["year"] for r in records}, reverse=True)
    return [(y, [r for r in records if r["year"] == y]) for y in years]


def load_publications(owner_short: str = "D. Pearson") -> list[tuple[int, list[dict]]]:
    path = CONTENT / "publications.bib"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ContentError(f"{_rel(path)}: file not found") from None
    recs = [publication_record(e, _rel(path), owner_short) for e in parse_bibtex(text, _rel(path))]
    _check_duplicate_titles(recs, _rel(path))
    return group_by_year(recs)


def load_talks(owner_short: str = "D. Pearson") -> list[tuple[int, list[dict]]]:
    path = CONTENT / "talks.bib"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ContentError(f"{_rel(path)}: file not found") from None
    recs = [talk_record(e, _rel(path), owner_short) for e in parse_bibtex(text, _rel(path))]
    return group_by_year(recs)


def _check_duplicate_titles(recs: list[dict], source: str) -> None:
    seen = {}
    for r in recs:
        norm = re.sub(r"\W+", " ", r["title"].lower()).strip()
        if norm in seen:
            raise BibError(f"{source}: '{r['key']}' and '{seen[norm]}' have the same title")
        seen[norm] = r["key"]


def load_all() -> dict:
    site = load_site()
    owner = site["owner_short"]
    publications = load_publications(owner)
    pub_keys = {r["key"] for _, recs in publications for r in recs}
    return {
        "site": site,
        "projects": load_projects(pub_keys),
        "people": load_people(),
        "teaching": load_teaching(),
        "news": load_news(),
        "publications": publications,
        "talks": load_talks(owner),
    }


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------

def check(data: dict) -> None:
    site = data["site"]
    print(f"site.toml        name={site['name']!r} links={[l['label'] for l in site['link']]} "
          f"base_url={site['base_url']!r}")
    print(f"projects.toml    {len(data['projects']['items'])} projects, {len(data['projects']['intro'])} intro paragraphs")
    print(f"people.toml      {len(data['people']['members'])} members, "
          f"{len(data['people']['collaborators'])} collaborators")
    courses = sum(len(r['course']) for r in data['teaching'])
    print(f"teaching.toml    {len(data['teaching'])} roles, {courses} courses")
    print(f"news.toml        {len(data['news'])} items, newest first: "
          f"{[n['date'] for n in data['news']]}")
    npub = sum(len(g) for _, g in data["publications"])
    print(f"\npublications.bib {npub} entries")
    for year, recs in data["publications"]:
        print(f"  {year}")
        for r in recs:
            authors = "; ".join(("**" + a["text"] + "**") if a["is_owner"] else a["text"]
                                for a in r["authors"])
            ed = f" (ed. {'; '.join(e['text'] for e in r['editors'])})" if r["editors"] else ""
            vol = f", {r['volume']}" if r["volume"] else ""
            num = f"({r['number']})" if r["number"] else ""
            pg = f", {r['pages']}" if r["pages"] else ""
            extra = "".join(f" [{k}]" for k in ("doi", "pdf") if r[k])
            print(f"    {authors}. ({r['year']}). {r['title']} {r['venue']}{ed}{vol}{num}{pg}"
                  f"{'. ' + r['note'] if r['note'] else ''}{extra}   <{r['type']}:{r['key']}>")
    ntalk = sum(len(g) for _, g in data["talks"])
    print(f"\ntalks.bib        {ntalk} entries")
    for year, recs in data["talks"]:
        print(f"  {year}")
        for r in recs:
            authors = "; ".join(("**" + a["text"] + "**") if a["is_owner"] else a["text"]
                                for a in r["authors"])
            print(f"    {r['title']} | {r['event']} | {r['location']} | {authors}"
                  f"{' [pdf]' if r['pdf'] else ''}")
    print("\nOK: all content parsed.")


# ---------------------------------------------------------------------------
# RENDERING  (markup reference: templates/MARKUP.md)
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def dash(s: str) -> str:
    """Escape text, turning '--' into an en dash (used for year ranges in TOML)."""
    return esc(s).replace("--", "\u2013")


def local_url(url: str) -> str:
    """Absolute/mailto/anchor URLs pass through; other paths live under static/ in dist/."""
    if re.match(r"^([a-z][a-z0-9+.-]*:|#|/)", url, re.IGNORECASE):
        return url
    return "static/" + url.lstrip("./")


def a(href: str, label: str) -> str:
    return f'<a href="{esc(href)}">{esc(label)}</a>'


def group(label: str, body: str, level: int = 2) -> str:
    return (f'    <section class="group">\n      <h{level} class="group-label">{dash(label)}</h{level}>\n'
            f'      <div class="group-body">\n{body}\n      </div>\n    </section>\n')


def entries(items: list[str], compact: bool = False) -> str:
    cls = "entries entries--compact" if compact else "entries"
    lis = "\n".join(f'          <li class="entry">\n{i}\n          </li>' for i in items)
    return f'        <ul class="{cls}">\n{lis}\n        </ul>'


def p(cls: str, inner: str) -> str:
    return f'            <p class="{cls}">{inner}</p>'


def end_with_period(s: str) -> str:
    return s if s.endswith((".", "?", "!")) else s + "."


def format_title(t: str) -> str:
    return esc(t[:-1] if t.endswith(".") and not t.endswith("..") else t)


def format_authors(authors: list[dict]) -> str:
    names = [f"<strong>{esc(x['text'])}</strong>" if x["is_owner"] else esc(x["text"]) for x in authors]
    if len(names) <= 2:
        return " &amp; ".join(names)
    return ", ".join(names[:-1]) + ", &amp; " + names[-1]


def links(*pairs: tuple[str, str | None]) -> str:
    out = " ".join(f'<a href="{esc(u)}">{l}</a>' for l, u in pairs if u)
    return f' <span class="entry-links">{out}</span>' if out else ""


def publication_entry(r: dict) -> str:
    venue = []
    if r["venue"]:
        v = esc(r["venue"])
        if r["type"] == "incollection":
            eds = " & ".join(f"{e['initials']} {e['family']}" for e in r["editors"])
            venue.append(f"In {esc(eds)} (Ed.), <em>{v}</em>" if eds else f"In <em>{v}</em>")
        else:
            venue.append(f"<em>{v}</em>")
    vol = (esc(r["volume"]) if r["volume"] else "") + (f"({esc(r['number'])})" if r["number"] else "")
    if vol:
        venue.append(vol)
    if r["pages"]:
        venue.append(esc(r["pages"]))
    text = end_with_period(", ".join(venue)) if venue else ""
    if r["note"]:
        text += (" " if text else "") + end_with_period(esc(r["note"]))
    doi = f"https://doi.org/{r['doi']}" if r["doi"] else r["url"]
    text += links(("PDF", local_url(r["pdf"]) if r["pdf"] else None), ("DOI", doi))
    return "\n".join([p("entry-title", format_title(r["title"])),
                      p("entry-authors", format_authors(r["authors"])),
                      p("entry-venue", text.strip())])


def talk_entry(r: dict) -> str:
    text = end_with_period(esc(", ".join(x for x in (r["event"], r["location"]) if x)))
    text += links(("Poster", local_url(r["pdf"]) if r["pdf"] else None))
    return p("entry-title", format_title(r["title"])) + "\n" + p("entry-venue", text)


def news_entry(n: dict) -> str:
    return (f'            <time class="entry-meta" datetime="{n["date"]}">{n["date_label"]}</time>\n'
            + p("entry-text", n["text"]))  # inline HTML by design


def named_entry(name: str, url: str | None, detail: str) -> str:
    title = a(url, name) if url else esc(name)
    return p("entry-title", title) + "\n" + p("entry-detail", esc(detail))


def render_home(d: dict) -> str:
    site = d["site"]
    contact = []
    if site["email"]:
        contact.append(a("mailto:" + site["email"], "Email"))
    contact += [a(local_url(l["url"]), l["label"]) for l in site["link"]]
    lis = "\n".join(f"            <li>{c}</li>" for c in contact)
    bio = "\n".join(f"          <p>{para}</p>" for para in site["bio"])  # inline HTML by design
    img = ""
    if site.get("portrait"):
        img = (f'      <img class="portrait" src="{esc(local_url(site["portrait"]))}" '
               f'alt="{esc(site.get("portrait_alt", site["name"]))}" width="400" height="500">\n')
    intro = (f'    <section class="intro">\n{img}      <div class="intro-text">\n'
             f'        <h1 class="name">{esc(site["name"])}</h1>\n'
             f'        <p class="position">{esc(site["position"])}</p>\n'
             f'        <div class="prose">\n{bio}\n        </div>\n'
             f'        <nav class="contact" aria-label="Contact">\n          <ul>\n{lis}\n          </ul>\n        </nav>\n'
             f'      </div>\n    </section>\n')
    latest = entries([news_entry(n) for n in d["news"][:3]])
    return intro + group("news", latest + '\n        <p class="more"><a href="news.html">All news</a></p>')


def short_citation(r: dict) -> str:
    """'Surname et al. (Year). Title.' with the title linked to its DOI (or local PDF)."""
    fam = [x["family"] for x in r["authors"]]
    fam = [esc(f) for f in fam]
    who = fam[0] if len(fam) == 1 else f"{fam[0]} &amp; {fam[1]}" if len(fam) == 2 else f"{fam[0]} et al."
    href = f"https://doi.org/{r['doi']}" if r["doi"] else local_url(r["pdf"]) if r["pdf"] else r["url"]
    title = format_title(r["title"])
    title = f'<a href="{esc(href)}">{title}</a>' if href else title
    return f"{who} ({r['year']}). {title}."


def render_research(d: dict) -> str:
    pubs = {r["key"]: r for _, rs in d["publications"] for r in rs}
    out = []
    if d["projects"]["intro"]:
        paras = "\n".join(f"        <p>{para}</p>" for para in d["projects"]["intro"])  # inline HTML by design
        out.append(f'    <div class="prose research-intro">\n{paras}\n    </div>')
    for pr in d["projects"]["items"]:
        parts = [f'      <h2 class="project-title">{esc(pr["title"])}</h2>',
                 f'      <p class="project-text">{pr["description"]}</p>']  # inline HTML by design
        if pr["collaborators"]:
            parts.append(f'      <p class="entry-detail">With {esc(", ".join(pr["collaborators"]))}</p>')
        if pr["papers"]:
            lis = "\n".join(f'        <li class="entry"><p class="entry-detail">{short_citation(pubs[k])}</p></li>'
                            for k in pr["papers"])
            parts.append('      <p class="project-papers-label">Key papers</p>\n'
                         f'      <ul class="entries entries--compact">\n{lis}\n      </ul>')
        out.append('    <article class="project">\n' + "\n".join(parts) + "\n    </article>")
    return '    <div class="projects">\n' + "\n".join(out) + "\n    </div>\n"


def render_publications(d: dict) -> str:
    return "".join(group(str(y), entries([publication_entry(r) for r in rs])) for y, rs in d["publications"])


def render_talks(d: dict) -> str:
    return "".join(group(str(y), entries([talk_entry(r) for r in rs])) for y, rs in d["talks"])


def render_teaching(d: dict) -> str:
    out, level = "", 2
    for role in d["teaching"]:
        if role.get("section"):  # a heading before this role; later role labels nest under it
            out += f'    <h2 class="section-title">{esc(role["section"])}</h2>\n'
            level = 3
        rows = "\n".join(
            '          <li class="entry entry-row">\n'
            f'            <span class="entry-code">{esc(c["code"])}</span>\n'
            f'            <span class="entry-name">{esc(c["name"])}</span>\n'
            + (f'            <span class="entry-years">{dash(c["years"])}</span>\n' if c.get("years") else "")
            + '          </li>'
            for c in role["course"])
        out += group(role["title"], f'        <ul class="entries entries--compact">\n{rows}\n        </ul>', level)
    return out


def render_people(d: dict) -> str:
    out = ""
    if d["people"]["members"]:
        items = [named_entry(m["name"], m.get("url"),
                             f"{m['role'].rstrip('.')}. {m['note']}" if m.get("note") else m["role"])
                 for m in d["people"]["members"]]
        out += group("lab members", entries(items, compact=True))
    if d["people"]["collaborators"]:
        items = [named_entry(c["name"], c.get("url"), c["institution"]) for c in d["people"]["collaborators"]]
        out += group("collaborators", entries(items, compact=True))
    return out


def render_news(d: dict) -> str:
    years = sorted({n["date_obj"].year for n in d["news"]}, reverse=True)
    return "".join(group(str(y), entries([news_entry(n) for n in d["news"] if n["date_obj"].year == y]))
                   for y in years)


PAGES = {  # file -> (renderer, meta description)
    "research.html": (render_research, "Current research projects."),
    "publications.html": (render_publications, "Publications, grouped by year."),
    "talks.html": (render_talks, "Conference talks and posters, grouped by year."),
    "teaching.html": (render_teaching, "Teaching roles and courses."),
    "people.html": (render_people, "Lab members and collaborators."),
    "news.html": (render_news, "News and updates."),
}


def build_site(data: dict) -> list[str]:
    """Wipe dist/, copy static/, render all pages (+ sitemap when base_url is set)."""
    site = data["site"]
    base = string.Template((TEMPLATES / "base.html").read_text(encoding="utf-8"))
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST / "static")
    today = dt.date.today()
    labels = {n["file"]: n["label"] for n in site["nav"]}
    pages = {"index.html": (render_home, f"{site['name']}, cognitive psychologist.")} | PAGES
    for fname, (fn, desc) in pages.items():
        nav = "\n".join(
            f'        <li><a href="{esc(n["file"])}"' + (' aria-current="page"' if n["file"] == fname else "")
            + f'>{esc(n["label"])}</a></li>' for n in site["nav"])
        title = site["name"] if fname == "index.html" else f"{labels.get(fname, fname)} \u00b7 {site['name']}"
        content = fn(data)
        if fname != "index.html":
            content = f'    <h1 class="page-title">{esc(labels.get(fname, fname))}</h1>\n' + content
        canon = (f'  <link rel="canonical" href="{esc(site["base_url"] + "/" + fname)}">\n'
                 if site["base_url"] else "")
        html_out = base.substitute(
            title=esc(title), description=esc(desc), canonical=canon, name=esc(site["name"]), nav=nav,
            content=content.rstrip("\n"), year=today.year, built_iso=today.isoformat(),
            built=f"{today.day} {today.strftime('%B %Y')}")
        (DIST / fname).write_text(html_out, encoding="utf-8")
    if site["base_url"]:
        urls = "".join(f"  <url><loc>{esc(site['base_url'] + '/' + f)}</loc></url>\n" for f in pages)
        (DIST / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + urls + "</urlset>\n", encoding="utf-8")
    return list(pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the personal website into dist/.")
    ap.add_argument("--check", action="store_true", help="parse all content, print a summary, write nothing")
    args = ap.parse_args(argv)
    try:
        data = load_all()
    except ContentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        check(data)
        return 0
    files = build_site(data)
    print(f"Built {len(files)} pages into {DIST.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
