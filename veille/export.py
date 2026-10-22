"""Export de la base : BibTeX (pour JabRef, Zotero...) et liste de liens PDF.

Deux sorties, deux usages :
  - BibTeX : format d'echange vers un gestionnaire de references. Le champ url
    pointe vers la page de l'article chez l'editeur (ou le resolveur DOI), pas
    vers le PDF : on lit et on cite chez la revue, ce qui preserve ses
    statistiques de visite.
  - liste de liens PDF : un lien par ligne, pour un telechargeur groupe
    (aria2c, wget, extension de navigateur), lors d'une recolte deliberee.

La base SQLite reste la source de verite ; ces exports se regenerent a volonte.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from typing import Optional

from . import db

_BIB_ESC = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
    "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_BIB_RE = re.compile("|".join(re.escape(k) for k in _BIB_ESC))


def _bib_escape(text: str) -> str:
    """Echappe les caracteres speciaux LaTeX en une seule passe."""
    return _BIB_RE.sub(lambda m: _BIB_ESC[m.group(0)], " ".join(text.split()))


def _authors(authors_json: Optional[str]) -> list[str]:
    if not authors_json:
        return []
    try:
        return [a for a in json.loads(authors_json) if a]
    except (ValueError, TypeError):
        return []


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isascii() and c.isalpha())


def _family(name: str) -> str:
    """Nom de famille : partie avant la virgule ("Brousseau, Guy"), sinon dernier mot."""
    name = name.strip()
    if "," in name:
        return name.split(",", 1)[0]
    parts = name.split()
    return parts[-1] if parts else ""


def _cite_key(row: sqlite3.Row, used: set[str]) -> str:
    authors = _authors(row["authors_json"])
    last = _ascii(_family(authors[0])) if authors else ""
    last = last or "Anon"
    year = str(row["year"]) if row["year"] else "nd"
    word = next((_ascii(w).capitalize() for w in re.findall(r"\w+", row["title"] or "")
                 if len(_ascii(w)) > 3), "")
    base = f"{last}{year}{word}"
    key, n = base, 0
    while key in used:
        n += 1
        key = f"{base}{chr(ord('a') + (n - 1) % 26)}{'' if n <= 26 else n // 26}"
    used.add(key)
    return key


def _entry(r: sqlite3.Row, key: str) -> str:
    wtype = r["work_type"] or "journal-article"
    container = r["journal"]
    if wtype == "book-chapter":
        kind, container_field = "incollection", "booktitle"
    elif wtype == "book":
        kind, container_field = "book", "series"
    elif wtype == "issue":
        kind, container_field = "misc", "howpublished"
    elif container:
        kind, container_field = "article", "journal"
    else:
        kind, container_field = "misc", "howpublished"

    fields: list[tuple[str, str]] = []
    authors = _authors(r["authors_json"])
    if authors:
        fields.append(("author", " and ".join(_bib_escape(a) for a in authors)))
    if r["title"]:
        fields.append(("title", "{" + _bib_escape(r["title"]) + "}"))
    if container:
        fields.append((container_field, _bib_escape(container)))
    if r["year"]:
        fields.append(("year", str(r["year"])))
    if r["doi"]:
        fields.append(("doi", r["doi"]))
    url = r["landing_url"] or (f"https://doi.org/{r['doi']}" if r["doi"] else None)
    if url:
        fields.append(("url", url))
    if r["language"]:
        fields.append(("language", _bib_escape(r["language"])))
    if r["abstract"]:
        fields.append(("abstract", _bib_escape(r["abstract"])))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{kind}{{{key},\n{body}\n}}"


def to_bibtex(rows: list[sqlite3.Row]) -> str:
    used: set[str] = set()
    entries = [_entry(r, _cite_key(r, used)) for r in rows]
    return "\n\n".join(entries) + ("\n" if entries else "")


def to_url_list(rows: list[sqlite3.Row]) -> str:
    """Un lien de PDF libre par ligne (deduplique, ordre conserve)."""
    seen: set[str] = set()
    lines: list[str] = []
    for r in rows:
        u = r["pdf_url"]
        if u and u not in seen:
            seen.add(u)
            lines.append(u)
    return "\n".join(lines) + ("\n" if lines else "")


def export(
    conn: sqlite3.Connection,
    *,
    bib_path: Optional[str] = None,
    urls_path: Optional[str] = None,
    min_year: Optional[int] = None,
    journal: Optional[str] = None,
    source_id: Optional[int] = None,
    new_since: Optional[str] = None,
    with_pdf: bool = False,
) -> tuple[int, int]:
    """Ecrit les exports demandes. Renvoie (notices exportees, liens PDF)."""
    from pathlib import Path

    rows = db.works_for_export(conn, min_year=min_year, journal=journal,
                               source_id=source_id, new_since=new_since, with_pdf=with_pdf)
    if bib_path:
        Path(bib_path).parent.mkdir(parents=True, exist_ok=True)
        Path(bib_path).write_text(to_bibtex(rows), encoding="utf-8")
    n_urls = 0
    if urls_path:
        pdf_rows = [r for r in rows if r["pdf_url"]]
        Path(urls_path).parent.mkdir(parents=True, exist_ok=True)
        Path(urls_path).write_text(to_url_list(pdf_rows), encoding="utf-8")
        n_urls = len({r["pdf_url"] for r in pdf_rows})
    return len(rows), n_urls
