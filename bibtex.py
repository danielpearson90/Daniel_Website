"""Minimal BibTeX parser, LaTeX-to-text cleaner and author formatter (stdlib only)."""
from __future__ import annotations

import re
import unicodedata


class ContentError(Exception):
    """Malformed or invalid content; message is shown to the user verbatim."""


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


