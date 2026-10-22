"""Test hors ligne du backfill des references via Crossref.

Lancement : python tests/test_references.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille import db, references
from veille.models import RawRecord


def _mkdb():
    conn = db.connect(tempfile.mktemp(suffix=".db"))
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id,name,connector,enabled) VALUES (1,'T','oai',1)")
    conn.commit()
    return conn


def _add(conn, ext, year, doi=None):
    rec = RawRecord(source_id=1, external_id=ext, title=ext, authors=[], year=year,
                    journal="Annales", doi=doi, abstract=None,
                    full_text_url=None, oa_url=None)
    wid, _ = db.upsert_work(conn, rec)
    return wid


def fake_json(url, params):
    # Crossref /works/{doi} avec references structurees et non structurees
    if url.endswith("10.4000/adsc.954"):
        return {"message": {"reference": [
            {"unstructured": "Duval R., 1995, Semiosis et pensee humaine."},
            {"author": "Brousseau G.", "year": "1998",
             "article-title": "Theorie des situations didactiques", "DOI": "10.x/bro"},
        ]}}
    return {"message": {}}  # pas de references


def test_backfill():
    conn = _mkdb()
    w_doi = _add(conn, "adsc954", 2024, doi="10.4000/adsc.954")
    w_norefs = _add(conn, "adsc999", 2024, doi="10.4000/adsc.999")  # Crossref ne renvoie rien
    w_nodoi = _add(conn, "flm1", 2024, doi=None)                     # pas de DOI -> ignore

    bf = references.ReferenceBackfiller(get_json=fake_json, page_pause=0.0)
    seen, filled = references.backfill_references(conn, backfiller=bf)

    # deux notices a DOI examinees (w_nodoi exclu), une seule completee
    assert (seen, filled) == (2, 1), (seen, filled)

    refs = json.loads(conn.execute(
        "SELECT refs_json FROM works WHERE id=?", (w_doi,)).fetchone()["refs_json"])
    assert refs[0].startswith("Duval R."), refs
    assert "Brousseau G." in refs[1] and "DOI:10.x/bro" in refs[1], refs

    # idempotence : les deux notices examinees (avec ou sans references) ne
    # sont plus reinterrogees au passage suivant
    seen2, filled2 = references.backfill_references(conn, backfiller=bf)
    assert (seen2, filled2) == (0, 0), (seen2, filled2)
    # sauf si l'on demande explicitement un reexamen
    seen3, _ = references.backfill_references(conn, backfiller=bf, recheck_days=0)
    assert seen3 == 1, seen3  # w_norefs, examinee sans resultat
    print("  ok backfill references (formatage, DOI sans refs, sans DOI, idempotence)")


if __name__ == "__main__":
    test_backfill()
    print("TOUS LES TESTS PASSENT")
