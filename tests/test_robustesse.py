"""Tests des comportements ajoutes en version 1.0 : reglages, politique HTTP,
migration de base, normalisation des DOI, resolution par lots, export BibTeX,
ligne de commande. Tous hors ligne.

Lancement : python -m pytest
"""

import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille import config, db, export, http, resolve, run
from veille.connectors import OaiConnector
from veille.models import FileKind, RawRecord, normalize_doi


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    config.set_current(config.Settings())


def _mkdb(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO sources (id,name,connector,enabled) VALUES (1,'T','metadata',1)")
    conn.commit()
    return conn


def _add(conn, ext, year, doi=None, title=None, authors=None, journal="ESM", wtype="journal-article"):
    rec = RawRecord(source_id=1, external_id=ext, title=title or ext, authors=authors or [],
                    year=year, journal=journal, doi=doi, work_type=wtype)
    return db.upsert_work(conn, rec)[0]


# --- reglages --------------------------------------------------------------

def test_config_priorite(tmp_path, monkeypatch):
    dbp = tmp_path / "veille.db"
    config.save(dbp, config.Settings(email="fichier@ex.org", openalex_api_key="k1"))
    monkeypatch.delenv("VEILLE_EMAIL", raising=False)
    assert config.load(dbp).email == "fichier@ex.org"
    monkeypatch.setenv("VEILLE_EMAIL", "env@ex.org")
    assert config.load(dbp).email == "env@ex.org"
    assert config.load(dbp, cli_email="cli@ex.org").email == "cli@ex.org"
    assert config.get().openalex_api_key == "k1"
    assert config.valid_email("a.b@univ-lyon1.fr") and not config.valid_email("pas un mail")


# --- politique HTTP --------------------------------------------------------

def _mock(monkeypatch, responses):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        status, headers, body = responses[min(len(calls), len(responses)) - 1]
        return httpx.Response(status, headers=headers, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(http, "_client", lambda browser: client)
    return calls


def test_http_404_immediat(monkeypatch):
    calls = _mock(monkeypatch, [(404, {}, {})])
    with pytest.raises(http.HttpError) as e:
        http.fetch("https://api.example.org/x")
    assert e.value.status == 404 and len(calls) == 1


def test_http_5xx_puis_succes(monkeypatch):
    calls = _mock(monkeypatch, [(503, {}, {}), (200, {}, {"ok": 1})])
    assert http.fetch("https://api.example.org/x") == {"ok": 1}
    assert len(calls) == 2


def test_http_429_retry_after(monkeypatch):
    calls = _mock(monkeypatch, [(429, {"Retry-After": "7"}, {}), (200, {}, {"ok": 2})])
    assert http.fetch("https://api.example.org/x") == {"ok": 2}
    assert len(calls) == 2


def test_http_429_persistant(monkeypatch):
    _mock(monkeypatch, [(429, {}, {})])
    with pytest.raises(http.HttpError) as e:
        http.fetch("https://api.example.org/x", attempts=3)
    assert e.value.status == 429


def test_user_agent_porte_email():
    config.set_current(config.Settings(email="moi@ex.org"))
    assert "mailto:moi@ex.org" in http.api_user_agent()
    config.set_current(config.Settings())
    assert "mailto" not in http.api_user_agent()


# --- base ------------------------------------------------------------------

def test_migration_ancienne_base(tmp_path):
    path = tmp_path / "ancienne.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL, connector TEXT NOT NULL,
            issn_print TEXT, issn_online TEXT, base_url TEXT, oai_set TEXT,
            metadata_prefix TEXT NOT NULL DEFAULT 'oai_dc', consultation_path TEXT,
            enabled INTEGER NOT NULL DEFAULT 1, last_run TEXT, notes TEXT);
        CREATE TABLE works (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, external_id TEXT,
            doi TEXT, fingerprint TEXT NOT NULL, title TEXT NOT NULL,
            authors_json TEXT NOT NULL DEFAULT '[]', year INTEGER, journal TEXT, abstract TEXT,
            language TEXT, oa_status TEXT, refs_json TEXT NOT NULL DEFAULT '[]',
            first_seen TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO sources (id,name,connector) VALUES (1,'T','metadata');
        INSERT INTO works (source_id,doi,fingerprint,title,first_seen,updated_at)
            VALUES (1,'10.1007/ABC','fp','Titre','2026-01-01','2026-01-01');
    """)
    old.commit()
    old.close()
    conn = db.connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(works)")}
    assert {"work_type", "pdf_checked_at", "refs_checked_at"} <= cols
    assert conn.execute("SELECT doi FROM works").fetchone()["doi"] == "10.1007/abc"


def test_doi_casse_et_prefixe(tmp_path):
    assert normalize_doi("https://doi.org/10.1007/S10649-X.") == "10.1007/s10649-x"
    conn = _mkdb(tmp_path)
    a = _add(conn, "a", 2025, doi="10.1007/ABC")
    b = _add(conn, "b", 2025, doi="https://doi.org/10.1007/abc")
    assert a == b
    assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1


# --- OAI : dc:relation n'est pas une bibliographie -------------------------

OAI_XML = """<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <ListRecords><record>
  <header><identifier>oai:x:1</identifier><datestamp>2026-01-01</datestamp></header>
  <metadata><oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
      xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title>Un article</dc:title>
   <dc:identifier>https://doi.org/10.4000/adsc.954</dc:identifier>
   <dc:relation>https://journals.openedition.org/adsc/850</dc:relation>
   <dc:relation>info:eu-repo/semantics/reference/issn/2804-2514</dc:relation>
   <dc:date>2024</dc:date>
  </oai_dc:dc></metadata>
 </record></ListRecords></OAI-PMH>"""


def test_oai_relation_pas_references():
    src = {"id": 1, "name": "ADSC", "base_url": "https://oai", "metadata_prefix": "oai_dc",
           "oai_set": None}
    recs = list(OaiConnector(http_get=lambda u, p: OAI_XML, page_pause=0).fetch_new(src, None))
    assert len(recs) == 1
    assert recs[0].references == []
    assert recs[0].doi == "10.4000/adsc.954"


# --- resolution ------------------------------------------------------------

def test_resolve_quota_arrete_proprement(tmp_path):
    conn = _mkdb(tmp_path)
    for i in range(120):
        _add(conn, f"w{i}", 2025, doi=f"10.1/x{i}")

    calls = {"n": 0}

    def fake(url, params):
        if "openalex" in url:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise http.HttpError("quota", 429)
            return {"results": []}
        return {"response": {"docs": []}}

    seen, found = resolve.resolve_pdf_urls(conn, resolve.PdfUrlResolver(fake, page_pause=0))
    assert seen == 50 and found == 0           # seul le premier lot est examine
    restant = db.works_without_free_pdf(conn, min_year=2000, require_doi=True)
    assert len(restant) == 70                  # le reste attend le prochain passage


def test_resolve_lot_refuse_repli_individuel(tmp_path):
    conn = _mkdb(tmp_path)
    _add(conn, "a", 2025, doi="10.1/a")
    _add(conn, "b", 2025, doi="10.1/b,bizarre")

    def fake(url, params):
        if url.endswith("/works") and "filter" in params:
            if "," in params["filter"].split(":", 1)[1]:
                raise http.HttpError("400", 400)
            return {"results": [{"doi": "https://doi.org/10.1/a",
                                 "best_oa_location": {"pdf_url": "https://oa/a.pdf"}}]}
        if "/doi:" in url:
            return {"best_oa_location": {"pdf_url": "https://oa/b.pdf"}}
        return {"response": {"docs": []}}

    seen, found = resolve.resolve_pdf_urls(conn, resolve.PdfUrlResolver(fake, page_pause=0))
    assert (seen, found) == (2, 2)


def test_resolve_ignore_numeros_et_sans_doi(tmp_path):
    conn = _mkdb(tmp_path)
    _add(conn, "num", 2025, title="Numero 123", wtype="issue")
    _add(conn, "sansdoi", 2025)
    seen, found = resolve.resolve_pdf_urls(
        conn, resolve.PdfUrlResolver(lambda u, p: pytest.fail("aucune requete attendue")))
    assert (seen, found) == (0, 0)


# --- export ----------------------------------------------------------------

def test_bibtex_cles_echappement_types(tmp_path):
    conn = _mkdb(tmp_path)
    w = _add(conn, "c1", 2017, doi="10.1007/978-3-319-1_2",
             title="Tâches {et} preuves & 50% de réussite",
             authors=["Brousseau, Guy", "Müller, Anna"],
             journal="Task Design in Mathematics Education", wtype="book-chapter")
    db.add_file(conn, w, kind=FileKind.PUBLISHER, url="https://link.springer.com/ch")
    _add(conn, "n1", 2025, title="Numéro 123 - Petit x (2025)", journal="Petit x", wtype="issue")
    bib = export.to_bibtex(db.works_for_export(conn))
    assert "@incollection{Brousseau2017Taches," in bib
    assert "booktitle = {Task Design in Mathematics Education}" in bib
    assert r"Tâches \{et\} preuves \& 50\% de réussite" in bib
    assert "@misc{Anon2025Numero," in bib and "howpublished = {Petit x}" in bib
    assert "url = {https://link.springer.com/ch}" in bib


# --- ligne de commande -----------------------------------------------------

def test_cli_setup_stats_export(tmp_path, capsys):
    dbp = tmp_path / "donnees" / "veille.db"
    run.main(["--db", str(dbp), "--email", "etu@univ.fr", "setup", "--no-prompt"])
    saved = json.loads((tmp_path / "donnees" / "config.json").read_text(encoding="utf-8"))
    assert saved["email"] == "etu@univ.fr"
    conn = db.connect(dbp)
    assert db.count_sources(conn) >= 15
    run.main(["--db", str(dbp), "stats"])
    assert "TOTAL" in capsys.readouterr().out
    bib = tmp_path / "out" / "v.bib"
    run.main(["--db", str(dbp), "export", "--bib", str(bib)])
    assert bib.exists()


def test_cli_update_sans_revue(tmp_path, capsys):
    run.main(["--db", str(tmp_path / "vide.db"), "update"])
    assert "setup" in capsys.readouterr().err
