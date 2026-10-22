"""Tests hors ligne de l'export BibTeX et liste d'URL.

Lancement : python tests/test_export.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille import db, export
from veille.models import FileKind, RawRecord


def _mkdb():
    conn = db.connect(tempfile.mktemp(suffix=".db"))
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id,name,connector,enabled) VALUES (1,'T','metadata',1)")
    conn.commit()
    return conn


def _add(conn, ext, title, year, doi=None, authors=None, journal="ESM", abstract=None):
    rec = RawRecord(source_id=1, external_id=ext, title=title, authors=authors or [],
                    year=year, journal=journal, doi=doi, abstract=abstract,
                    full_text_url=None, oa_url=None)
    wid, _ = db.upsert_work(conn, rec)
    return wid


def test_bibtex_and_urls():
    conn = _mkdb()
    w1 = _add(conn, "w1", "Logarithmes & jeux : 100% action", 2026,
              doi="10.1/abc", authors=["Benjamin Wack", "A. Autre"], abstract="Resume.")
    w2 = _add(conn, "w2", "Sans PDF ni DOI", 2024, authors=["Marie Curie"])
    db.add_file(conn, w1, kind=FileKind.PUBLISHER, url="https://ed.example/art1")
    db.add_file(conn, w1, kind=FileKind.OA, url="https://oa.example/art1.pdf")

    bib = Path(tempfile.mktemp(suffix=".bib"))
    urls = Path(tempfile.mktemp(suffix=".txt"))
    n, n_urls = export.export(conn, bib_path=str(bib), urls_path=str(urls))

    assert n == 2, n
    text = bib.read_text(encoding="utf-8")
    # caracteres speciaux echappes, titre protege par accolades
    assert r"\& jeux : 100\% action" in text, text
    assert "author = {Benjamin Wack and A. Autre}" in text
    assert "doi = {10.1/abc}" in text
    # url citable = page editeur (pas le PDF), pour preserver les stats revue
    assert "url = {https://ed.example/art1}" in text
    assert "art1.pdf" not in text  # le PDF ne va PAS dans le .bib
    # w2 sans DOI ni landing -> pas de champ url, type @article quand meme (revue connue)
    assert "Sans PDF ni DOI" in text

    # liste d'URL : seulement le PDF de w1
    assert urls.read_text(encoding="utf-8").strip() == "https://oa.example/art1.pdf"
    assert n_urls == 1
    print("  ok export BibTeX (echappement, url citable, PDF exclu) + liste d'URL")


def test_filters():
    conn = _mkdb()
    a = _add(conn, "a", "Recent avec PDF", 2026, doi="10.2/x")
    _add(conn, "b", "Ancien sans PDF", 2019, doi="10.3/y")
    db.add_file(conn, a, kind=FileKind.OA, url="https://oa.example/a.pdf")

    # filtre annee
    rows = db.works_for_export(conn, min_year=2025)
    assert [r["external_id"] for r in rows] == ["a"], [r["external_id"] for r in rows]

    # filtre with_pdf
    rows = db.works_for_export(conn, with_pdf=True)
    assert [r["external_id"] for r in rows] == ["a"]
    assert rows[0]["pdf_url"] == "https://oa.example/a.pdf"
    print("  ok filtres export (min_year, with_pdf, pdf_url joint)")


if __name__ == "__main__":
    test_bibtex_and_urls()
    test_filters()
    print("TOUS LES TESTS PASSENT")
