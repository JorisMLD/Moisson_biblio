"""Tests hors ligne : parsing OAI, pagination par resumptionToken, dedup.

Lancement : python tests/test_oai_parse.py
Aucune dependance reseau (la couche HTTP est remplacee par une fixture).
"""

import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille import db
from veille.connectors import OaiConnector
from veille.models import FileKind, RawRecord

PAGE1 = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <ListRecords>
  <record>
   <header><identifier>oai:adsc:1</identifier><datestamp>2026-01-15</datestamp></header>
   <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
     <dc:title>Visualisation et raisonnement en geometrie</dc:title>
     <dc:creator>Dupont, Jean</dc:creator>
     <dc:creator>Martin, Sofia</dc:creator>
     <dc:date>2026</dc:date>
     <dc:description>Court.</dc:description>
     <dc:description>Un resume plus long, choisi car plus informatif que le precedent.</dc:description>
     <dc:identifier>https://journals.openedition.org/adsc/1234</dc:identifier>
     <dc:identifier>https://doi.org/10.4000/adsc.1234</dc:identifier>
     <dc:source>Annales de didactique et de sciences cognitives</dc:source>
     <dc:language>fr</dc:language>
    </oai_dc:dc>
   </metadata>
  </record>
  <record>
   <header status="deleted"><identifier>oai:adsc:2</identifier><datestamp>2026-01-16</datestamp></header>
  </record>
  <resumptionToken>TOKEN_PAGE2</resumptionToken>
 </ListRecords>
</OAI-PMH>"""

PAGE2 = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <ListRecords>
  <record>
   <header><identifier>oai:adsc:3</identifier><datestamp>2026-01-17</datestamp></header>
   <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
     <dc:title>Eye tracking et lecture de figures</dc:title>
     <dc:creator>Rivera, Alejandro</dc:creator>
     <dc:date>2025-11-01</dc:date>
     <dc:identifier>https://journals.openedition.org/adsc/1300</dc:identifier>
    </oai_dc:dc>
   </metadata>
  </record>
  <resumptionToken></resumptionToken>
 </ListRecords>
</OAI-PMH>"""


def fake_http_get(base_url, params):
    if params.get("resumptionToken") == "TOKEN_PAGE2":
        return PAGE2
    return PAGE1


def test_parse_and_pagination():
    conn_source = {
        "id": 1, "base_url": "http://example.test/oai",
        "metadata_prefix": "oai_dc", "oai_set": "adsc",
    }
    oai = OaiConnector(http_get=fake_http_get, page_pause=0.0)
    recs = list(oai.fetch_new(conn_source, since=None))

    kept = [r for r in recs if not r.deleted]
    deleted = [r for r in recs if r.deleted]
    assert len(kept) == 2, f"attendu 2 notices, obtenu {len(kept)}"
    assert len(deleted) == 1, "la notice supprimee doit etre signalee"

    r1 = kept[0]
    assert r1.doi == "10.4000/adsc.1234", r1.doi
    assert r1.year == 2026, r1.year
    assert r1.authors == ["Dupont, Jean", "Martin, Sofia"], r1.authors
    assert r1.journal == "Annales de didactique et de sciences cognitives"
    assert r1.abstract.startswith("Un resume plus long"), "doit choisir le resume le plus long"
    assert r1.full_text_url == "https://journals.openedition.org/adsc/1234"
    assert r1.language == "fr"

    r3 = kept[1]  # vient de la page 2 : prouve que le resumptionToken a ete suivi
    assert r3.year == 2025, r3.year
    assert r3.doi is None
    assert r3.external_id == "oai:adsc:3"
    print("  ok parsing + pagination")


def test_db_dedup():
    with tempfile.TemporaryDirectory() as d, closing(db.connect(Path(d) / "t.db")) as conn:
        db.init_db(conn)
        sid = db.upsert_source(conn, name="Annales", connector="oai")

        oai = OaiConnector(http_get=fake_http_get, page_pause=0.0)
        recs = [r for r in oai.fetch_new({"id": sid, "base_url": "x",
                "metadata_prefix": "oai_dc", "oai_set": None}, since=None)
                if not r.deleted]

        # premier passage : tout est nouveau
        statuses = []
        for r in recs:
            wid, st = db.upsert_work(conn, r)
            statuses.append(st)
            if r.full_text_url:
                db.add_file(conn, wid, kind=FileKind.OA, url=r.full_text_url)
        assert statuses == ["new", "new"], statuses

        # second passage identique : tout doit etre reconnu (pas de doublon)
        statuses2 = [db.upsert_work(conn, r)[1] for r in recs]
        assert statuses2 == ["updated", "updated"], statuses2

        n_works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        n_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert n_works == 2, n_works
        assert n_files == 2, n_files  # les deux notices ont une URL de texte integral
        print("  ok deduplication + fichiers")


def test_dedup_distinct_dois():
    """Deux notices de DOI differents mais de meme empreinte restent distinctes."""
    with tempfile.TemporaryDirectory() as d, closing(db.connect(Path(d) / "t.db")) as conn:
        db.init_db(conn)
        sid = db.upsert_source(conn, name="Journal X", connector="metadata")

        def rec(doi):
            return RawRecord(source_id=sid, external_id=doi or "x", title="Éditorial",
                             year=2025, journal="Journal X", doi=doi)

        # Deux editoriaux 2025 distincts (DOI differents) : deux notices.
        assert db.upsert_work(conn, rec("10.1/a"))[1] == "new"
        assert db.upsert_work(conn, rec("10.1/b"))[1] == "new"
        assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 2

        # Meme DOI revu : mise a jour, pas de doublon.
        assert db.upsert_work(conn, rec("10.1/a"))[1] == "updated"
        # Version sans DOI du meme article : fusion par empreinte, pas de 3e ligne.
        assert db.upsert_work(conn, rec(None))[1] == "updated"
        assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 2
        print("  ok dedup DOI distincts")


if __name__ == "__main__":
    test_parse_and_pagination()
    test_db_dedup()
    test_dedup_distinct_dois()
    print("TOUS LES TESTS PASSENT")
