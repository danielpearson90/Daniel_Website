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
import re
import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
DIST = ROOT / "dist"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ContentError(Exception):
    """Malformed or invalid content; message is shown to the user verbatim."""


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


def load_projects() -> list[dict]:
    path = CONTENT / "projects.toml"
    d = load_toml(path)
    items = _table_list(d, "project", path)
    for i, p in enumerate(items, 1):
        _check_table(p, f"{_rel(path)}: [[project]] #{i}",
                     {"title": str, "years": str, "description": str}, {"collaborators": "strlist"})
        p.setdefault("collaborators", [])
    return items


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
        _check_table(r, where, {"title": str}, {"course": list})
        r.setdefault("course", [])
        for j, c in enumerate(r["course"], 1):
            _check_table(c, f"{where} course #{j}", {"code": str, "name": str, "years": str})
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
# BibTeX parser
# ---------------------------------------------------------------------------

_OWNER_RE = re.compile(r"\{?\s*\\myname\s*\{\s*pearson\s*\}(?:\s*\})?", re.IGNORECASE)
_OWNER_TOKEN = "\x00OWNER\x00"


class BibError(ContentError):
    pass


def parse_bibtex(text: str, source: str = "<bib>") -> list[dict]:
    """Parse BibTeX into [{'type', 'key', 'fields': {name: raw string}}].

    Handles nested braces, "quoted" values, bare numbers/@string macros, `#` concatenation,
    (...) or {...} entry delimiters, and skips @comment/@preamble and text between entries.
    Field values keep their LaTeX; use `clean_latex` for display text.
    """
    pos, n = 0, len(text)
    entries: list[dict] = []
    strings: dict[str, str] = {}

    def line_of(p: int) -> int:
        return text.count("\n", 0, p) + 1

    def fail(msg: str, p: int):
        raise BibError(f"{source}:{line_of(p)}: {msg}")

    def skip_ws(p: int) -> int:
        while p < n:
            if text[p].isspace():
                p += 1
            elif text[p] == "%":  # comment line (only honoured between tokens)
                while p < n and text[p] != "\n":
                    p += 1
            else:
                break
        return p

    def read_braced(p: int) -> tuple[str, int]:
        start, depth = p, 0
        while p < n:
            c = text[p]
            if c == "\\":
                p += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:p], p + 1
            p += 1
        fail("unbalanced '{' (value never closed)", start)

    def read_quoted(p: int) -> tuple[str, int]:
        start, depth = p, 0
        p += 1
        while p < n:
            c = text[p]
            if c == "\\":
                p += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == '"' and depth == 0:
                return text[start + 1:p], p + 1
            p += 1
        fail('unterminated "quoted" value', start)

    def read_value(p: int) -> tuple[str, int]:
        parts = []
        while True:
            p = skip_ws(p)
            if p >= n:
                fail("unexpected end of file in field value", n - 1)
            c = text[p]
            if c == "{":
                v, p = read_braced(p)
            elif c == '"':
                v, p = read_quoted(p)
            else:
                m = re.compile(r"[\w:.\-]+").match(text, p)
                if not m:
                    fail(f"unexpected character {c!r} in field value", p)
                word = m.group(0)
                v = word if word.isdigit() else strings.get(word.lower(), None)
                if v is None:
                    fail(f"undefined @string macro '{word}'", p)
                p = m.end()
            parts.append(v)
            p = skip_ws(p)
            if p < n and text[p] == "#":
                p += 1
                continue
            return "".join(parts), p

    while True:
        at = text.find("@", pos)
        if at < 0:
            break
        m = re.compile(r"@\s*(\w+)\s*").match(text, at)
        if not m:
            fail("'@' not followed by an entry type", at)
        etype = m.group(1).lower()
        p = skip_ws(m.end())
        if p >= n or text[p] not in "{(":
            fail(f"expected '{{' after @{etype}", p)
        close = "}" if text[p] == "{" else ")"
        if etype in ("comment", "preamble"):
            if close == "}":
                _, pos = read_braced(p)
            else:
                pos = text.find(")", p) + 1 or n
            continue
        p += 1
        if etype == "string":
            m2 = re.compile(r"\s*([\w\-]+)\s*=").match(text, p)
            if not m2:
                fail("malformed @string", p)
            val, p = read_value(m2.end())
            strings[m2.group(1).lower()] = val
            p = skip_ws(p)
            if p >= n or text[p] != close:
                fail("expected end of @string", p)
            pos = p + 1
            continue
        mk = re.compile(r"\s*([^\s,{}=]+)\s*,").match(text, p)
        if not mk:
            fail(f"@{etype} entry has no citation key (expected 'key,')", p)
        entry = {"type": etype, "key": mk.group(1), "fields": {}, "line": line_of(at)}
        p = mk.end()
        while True:
            p = skip_ws(p)
            if p >= n:
                fail(f"entry '{entry['key']}' is not closed", at)
            if text[p] == close:
                p += 1
                break
            if text[p] == ",":
                p += 1
                continue
            mf = re.compile(r"([A-Za-z][\w\-]*)\s*=").match(text, p)
            if not mf:
                fail(f"expected 'field = value' in entry '{entry['key']}'", p)
            name = mf.group(1).lower()
            val, p = read_value(mf.end())
            if name in entry["fields"]:
                fail(f"duplicate field '{name}' in entry '{entry['key']}'", p)
            entry["fields"][name] = val
        entries.append(entry)
        pos = p

    seen = {}
    for e in entries:
        if e["key"] in seen:
            raise BibError(f"{source}:{e['line']}: duplicate citation key '{e['key']}' "
                           f"(first at line {seen[e['key']]})")
        seen[e["key"]] = e["line"]
    return entries


# LaTeX -> plain unicode -----------------------------------------------------

_ACCENTS = {"`": "\u0300", "'": "\u0301", "^": "\u0302", "~": "\u0303", '"': "\u0308",
            "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
            "c": "\u0327", "k": "\u0328", "r": "\u030a"}
_SPECIAL = {"ss": "ß", "o": "ø", "O": "Ø", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
            "aa": "å", "AA": "Å", "l": "ł", "L": "Ł", "i": "ı", "j": "ȷ"}


def clean_latex(s: str) -> str:
    """Convert a BibTeX field value to plain text (unicode, no braces, whitespace collapsed).

    The result is NOT HTML-escaped; the renderer must escape it.
    """
    s = _OWNER_RE.sub("Pearson", s)

    # \"u, \'{e}, {\"u}, \c{c}, \v s ...
    def accent(m: re.Match) -> str:
        cmd, base = m.group(1), m.group(2) or m.group(3)
        if base in ("i", "j") and cmd not in ("u", "v"):
            base = {"i": "i", "j": "j"}[base]
        return unicodedata.normalize("NFC", base + _ACCENTS[cmd])

    s = re.sub(r"\\([`'^~\"=.])\s*(?:\{\s*\\?([A-Za-z])\s*\}|\\?([A-Za-z]))", accent, s)
    s = re.sub(r"\\([uvHckr])\s*(?:\{\s*([A-Za-z])\s*\}|\s([A-Za-z]))", accent, s)
    s = re.sub(r"\\(ss|oe|OE|ae|AE|aa|AA|o|O|l|L)(?![A-Za-z])\s*", lambda m: _SPECIAL[m.group(1)], s)
    s = re.sub(r"\\([&%$#_{}])", r"\1", s)
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = s.replace("``", "\u201c").replace("''", "\u201d").replace("~", "\u00a0")
    s = re.sub(r"\\(?:emph|textit|textbf|textrm|texttt|textsc)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\[A-Za-z]+\s*", "", s)  # drop any remaining unknown commands
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


# Authors --------------------------------------------------------------------

def _split_depth0(s: str, sep_re: re.Pattern) -> list[str]:
    """Split on `sep_re` matches that occur at brace depth 0."""
    parts, depth, last, i = [], 0, 0, 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif depth == 0:
            m = sep_re.match(s, i)
            if m and m.end() > i:
                parts.append(s[last:i])
                last = i = m.end()
                continue
        i += 1
    parts.append(s[last:])
    return [p.strip() for p in parts if p.strip()]


_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_COMMA = re.compile(r",")
_SPACE = re.compile(r"\s+")


def _initials(given: str) -> str:
    given = re.sub(r"\([^)]*\)", " ", given)  # drop parenthesised nicknames, e.g. "Phillip (Xin)"
    words = []
    for word in clean_latex(given).replace(".", ". ").split():
        pieces = []
        for piece in word.split("-"):
            piece = piece.strip(".")
            if not piece:
                continue
            # "WF" -> "W. F."; "Mike" -> "M."
            letters = list(piece) if piece.isupper() and len(piece) <= 3 else [piece[0].upper()]
            pieces.append(" ".join(f"{l}." for l in letters))
        if pieces:
            words.append("-".join(pieces))
    return " ".join(words)


def parse_authors(raw: str, owner_short: str = "D. Pearson") -> list[dict]:
    """Parse a BibTeX author/editor field.

    Returns [{'family', 'initials', 'text' ("Surname, I. I."), 'is_owner'}].
    Both "Surname, Given" and "Given Surname" forms are accepted; a multi-word surname must be
    written "Le Pelley, Mike" or "{Le Pelley}". The site owner (`{\\myname{pearson}}`) gets
    is_owner=True and is formatted from `owner_short` ("D. Pearson" -> "Pearson, D.").
    """
    o_words = owner_short.split()
    owner_family = o_words[-1]
    owner_initials = " ".join(o_words[:-1])
    raw = _OWNER_RE.sub(_OWNER_TOKEN, raw)
    people = []
    for chunk in _split_depth0(raw, _AND):
        if chunk == _OWNER_TOKEN:
            people.append({"family": owner_family, "initials": owner_initials,
                           "text": f"{owner_family}, {owner_initials}", "is_owner": True})
            continue
        if _OWNER_TOKEN in chunk:
            raise BibError(f"author {chunk!r}: \\myname{{pearson}} must stand alone as an author")
        if chunk.lower() == "others":
            people.append({"family": "et al.", "initials": "", "text": "et al.", "is_owner": False})
            continue
        comma = _split_depth0(chunk, _COMMA)
        if len(comma) >= 2:
            family, given = comma[0], comma[-1]
        else:
            words = _split_depth0(chunk, _SPACE)
            family, given = words[-1], " ".join(words[:-1])
        family_c = clean_latex(family)
        initials = _initials(given)
        text = f"{family_c}, {initials}" if initials else family_c
        people.append({"family": family_c, "initials": initials, "text": text, "is_owner": False})
    if not people:
        raise BibError(f"empty author list: {raw!r}")
    return people


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
    return {
        "site": site,
        "projects": load_projects(),
        "people": load_people(),
        "teaching": load_teaching(),
        "news": load_news(),
        "publications": load_publications(owner),
        "talks": load_talks(owner),
    }


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------

def check(data: dict) -> None:
    site = data["site"]
    print(f"site.toml        name={site['name']!r} links={[l['label'] for l in site['link']]} "
          f"base_url={site['base_url']!r}")
    print(f"projects.toml    {len(data['projects'])} projects")
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
# RENDERING  (STUB: to be implemented once templates/ markup is final)
# ---------------------------------------------------------------------------
# Planned: render_home / render_research / render_publications / render_talks /
# render_people / render_news, each returning an HTML string built with
# string.Template from templates/, html.escape() for all content-file text except
# news text and site bio paragraphs; write_site() wipes dist/, copies static/, writes pages.

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
    print("error: HTML rendering is not implemented yet (use --check)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
