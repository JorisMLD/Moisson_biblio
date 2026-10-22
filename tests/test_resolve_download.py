"""Tests hors ligne de la resolution d'URL (OpenAlex/HAL) et du telechargement.

Lancement : python tests/test_resolve_download.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille import db, download, resolve
from veille.models import FileKind, RawRecord


def _mkdb():
    conn = db.connect(tempfile.mktemp(suffix=".db"))
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id,name,connector,enabled) "
                 "VALUES (1,'Test','metadata',1)")
    conn.commit()
    return conn


def _add(conn, ext, title, year, doi=None, authors=None):
    rec = RawRecord(source_id=1, external_id=ext, title=title, authors=authors or [],
                    year=year, journal="Test", doi=doi, abstract=None,
                    full_text_url=None, oa_url=None)
    wid, _ = db.upsert_work(conn, rec)
    return wid


# --- parsing -----------------------------------------------------------------

def test_parsers():
    assert resolve.openalex_pdf_url(
        {"best_oa_location": {"pdf_url": "u1"}}) == "u1"
    assert resolve.openalex_pdf_url(
        {"best_oa_location": {}, "locations": [{"is_oa": True, "pdf_url": "u2"}]}) == "u2"
    # open_access.oa_url est souvent une page d'accueil : on ne le retient pas
    assert resolve.openalex_pdf_url({"open_access": {"oa_url": "u3"}}) is None
    # une localisation fermee ne fournit pas de PDF libre
    assert resolve.openalex_pdf_url(
        {"primary_location": {"is_oa": False, "pdf_url": "ferme.pdf"}}) is None
    assert resolve.openalex_pdf_url({"best_oa_location": {}}) is None
    assert resolve.hal_pdf_url(
        {"response": {"docs": [{"fileMain_s": "h1"}]}}) == "h1"
    assert resolve.hal_pdf_url(
        {"response": {"docs": [{"files_s": ["h2"]}]}}) == "h2"
    assert resolve.hal_pdf_url({"response": {"docs": []}}) is None
    assert resolve._norm_doi("https://doi.org/10.1/AB") == "10.1/ab"
    assert resolve._norm_doi("10.1/AB") == "10.1/ab"
    assert resolve._norm_doi(None) is None
    # OpenEdition : derivation directe DOI -> URL PDF
    assert resolve.openedition_pdf_url("10.4000/educationdidactique.10190") == \
        "https://journals.openedition.org/educationdidactique/pdf/10190"
    assert resolve.openedition_pdf_url("https://doi.org/10.4000/adsc.954") == \
        "https://journals.openedition.org/adsc/pdf/954"
    assert resolve.openedition_pdf_url("10.1007/s10649-025-1") is None  # pas OpenEdition
    print("  ok parsing OpenAlex / HAL + normalisation DOI + derivation OpenEdition")


def test_openedition_no_network():
    conn = _mkdb()
    _add(conn, "oe", "Article OpenEdition", 2024, doi="10.4000/educationdidactique.10190")

    def boom(url, params):  # ne doit JAMAIS etre appele pour OpenEdition
        raise AssertionError(f"appel reseau inattendu : {url}")

    r = resolve.PdfUrlResolver(get_json=boom, page_pause=0.0)
    seen, found = resolve.resolve_pdf_urls(conn, resolver=r)
    assert (seen, found) == (1, 1), (seen, found)
    row = conn.execute("SELECT kind, url FROM files WHERE work_id IN "
                       "(SELECT id FROM works WHERE external_id='oe')").fetchone()
    assert row["kind"] == "oa"
    assert row["url"] == "https://journals.openedition.org/educationdidactique/pdf/10190"
    print("  ok resolution OpenEdition sans aucun appel reseau")


# --- resolution end-to-end ---------------------------------------------------

def fake_json(url, params):
    if "openalex" in url:
        # appel en lot : filter = doi:A|B|C
        filt = params.get("filter", "")
        results = []
        if "10.1/withpdf" in filt:
            results.append({"doi": "https://doi.org/10.1/withpdf",
                            "best_oa_location": {"pdf_url": "https://oa.example/x.pdf"}})
        if "10.2/nopdf" in filt:
            results.append({"doi": "https://doi.org/10.2/nopdf",
                            "best_oa_location": {}})
        # 10.3/none : absent des resultats
        return {"results": results}
    if "archives-ouvertes" in url:
        if "10.2/nopdf" in params.get("q", ""):
            return {"response": {"docs": [{"doiId_s": "10.2/nopdf",
                                           "fileMain_s": "https://hal.example/a.pdf"}]}}
        return {"response": {"docs": []}}
    return {}


def test_resolve_end_to_end():
    conn = _mkdb()
    _add(conn, "w1", "Avec PDF OA", 2025, doi="10.1/withpdf")
    _add(conn, "w2", "Sans PDF OA mais HAL", 2024, doi="10.2/nopdf")
    _add(conn, "w3", "Introuvable", 2023, doi="10.3/none")

    r = resolve.PdfUrlResolver(get_json=fake_json, page_pause=0.0)
    seen, found = resolve.resolve_pdf_urls(conn, resolver=r)
    assert (seen, found) == (3, 2), (seen, found)

    files = {(row["external_id"], row["kind"]): row["url"] for row in conn.execute(
        "SELECT w.external_id, f.kind, f.url FROM works w JOIN files f ON f.work_id=w.id")}
    assert files[("w1", "oa")] == "https://oa.example/x.pdf"
    assert files[("w2", "hal_author")] == "https://hal.example/a.pdf"
    assert not any(k[0] == "w3" for k in files)  # rien resolu

    # idempotence : w3, examinee sans succes, n'est pas reinterrogee...
    seen2, found2 = resolve.resolve_pdf_urls(conn, resolver=r)
    assert (seen2, found2) == (0, 0), (seen2, found2)
    # ... sauf reexamen demande
    seen3, _ = resolve.resolve_pdf_urls(conn, resolver=r, recheck_days=0)
    assert seen3 == 1, seen3
    print("  ok resolution OpenAlex en lot -> HAL en repli, rangs oa/hal_author, idempotence")


# --- telechargement ----------------------------------------------------------

def test_download_threshold():
    conn = _mkdb()
    wr = _add(conn, "recent", "Recent 2026", 2026)
    wo = _add(conn, "vieux", "Ancien 2024", 2024)
    db.add_file(conn, wr, kind=FileKind.OA, url="https://x/recent.pdf")
    db.add_file(conn, wo, kind=FileKind.OA, url="https://x/vieux.pdf")

    calls = []
    def fake_bytes(url):
        calls.append(url)
        return b"%PDF-1.7 fake content"

    out = Path(tempfile.mkdtemp())
    seen, ok = download.download_pdfs(conn, out, min_year=2026,
                                      get_bytes=fake_bytes, page_pause=0.0)
    # seul le 2026 est eligible
    assert (seen, ok) == (1, 1), (seen, ok)
    assert calls == ["https://x/recent.pdf"], calls
    assert (out / "recent.pdf").exists()
    row = conn.execute("SELECT path FROM files f JOIN works w ON w.id=f.work_id "
                       "WHERE w.external_id='recent'").fetchone()
    assert row["path"] and row["path"].endswith("recent.pdf"), row["path"]
    print("  ok telechargement seuille (2026 oui, 2024 non, chemin enregistre)")


def test_download_rejects_non_pdf():
    conn = _mkdb()
    w = _add(conn, "html", "Mur d'abonnement", 2026)
    db.add_file(conn, w, kind=FileKind.OA, url="https://x/paywall")
    out = Path(tempfile.mkdtemp())
    seen, ok = download.download_pdfs(conn, out, min_year=2026,
                                      get_bytes=lambda u: b"<html>nope</html>",
                                      page_pause=0.0)
    assert (seen, ok) == (1, 0), (seen, ok)  # examine mais rejete (pas %PDF)
    assert not (out / "html.pdf").exists()
    print("  ok rejet d'un contenu non-PDF")


def test_resolve_min_year_and_require_doi():
    conn = _mkdb()
    _add(conn, "old", "Vieux article", 1985, doi="10.9/old")
    _add(conn, "new", "Article recent", 2025, doi="10.9/new")
    _add(conn, "nodoi", "Numero 12", 2025, doi=None)

    seen_filters = []
    def spy_json(url, params):
        if "openalex" in url:
            filt = params.get("filter", "")
            seen_filters.append(filt)
            results = []
            if "10.9/new" in filt:
                results.append({"doi": "https://doi.org/10.9/new",
                                "best_oa_location": {"pdf_url": "https://oa/new.pdf"}})
            return {"results": results}
        return {"response": {"docs": []}}

    r = resolve.PdfUrlResolver(get_json=spy_json, page_pause=0.0)
    seen, found = resolve.resolve_pdf_urls(conn, resolver=r, min_year=2000,
                                           require_doi=True)
    # seul "new" est examine : "old" sous le seuil, "nodoi" sans DOI
    assert (seen, found) == (1, 1), (seen, found)
    assert all("10.9/old" not in f for f in seen_filters), seen_filters
    print("  ok resolve borne par annee + require_doi (lot OpenAlex)")


if __name__ == "__main__":
    test_parsers()
    test_openedition_no_network()
    test_resolve_end_to_end()
    test_resolve_min_year_and_require_doi()
    test_download_threshold()
    test_download_rejects_non_pdf()
    print("TOUS LES TESTS PASSENT")
