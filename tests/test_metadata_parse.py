"""Tests hors ligne du connecteur metadata (Crossref + repli OpenAlex).

Lancement : python tests/test_metadata_parse.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.connectors import MetadataConnector

CROSSREF_PAGE1 = {
    "message": {
        "next-cursor": "CURSOR2",
        "items": [
            {
                "DOI": "10.1007/s10649-025-10001-x",
                "title": ["Spatial   reasoning and geometry learning"],
                "author": [
                    {"family": "Smith", "given": "Jane"},
                    {"family": "García", "given": "Luis"},
                ],
                "issued": {"date-parts": [[2025, 3]]},
                "container-title": ["Educational Studies in Mathematics"],
                "abstract": "<jats:p>This study examines <jats:italic>spatial</jats:italic> reasoning &amp; geometry.</jats:p>",
                "reference": [
                    {"unstructured": "Duval R. (1995). Semiosis et pensee humaine."},
                    {"DOI": "10.1000/x", "author": "Dehaene", "year": "2011",
                     "article-title": "The number sense"},
                ],
                "language": "en",
            },
            {
                "DOI": "10.1016/j.jmathb.2026.10002",
                "title": ["Student schemes for limits"],
                "author": [{"family": "Rojas", "given": "Osvaldo"}],
                "issued": {"date-parts": [[2026, 1]]},
                "container-title": ["The Journal of Mathematical Behavior"],
                "language": "en",
            },
        ],
    }
}
CROSSREF_EMPTY = {"message": {"next-cursor": "CURSOR3", "items": []}}

OPENALEX_FALLBACK = {
    "abstract_inverted_index": {"Limits": [0], "are": [1], "notoriously": [2], "hard": [3]}
}


def fake_get_json(url, params):
    if "api.openalex.org" in url:
        return OPENALEX_FALLBACK
    if params.get("cursor") == "*":
        return CROSSREF_PAGE1
    return CROSSREF_EMPTY


def test_metadata():
    source = {"id": 6, "name": "ESM", "issn_print": "0013-1954", "issn_online": "1573-0816"}
    conn = MetadataConnector(get_json=fake_get_json, page_pause=0.0)
    recs = list(conn.fetch_new(source, since=None))

    assert len(recs) == 2, f"attendu 2, obtenu {len(recs)}"

    a = recs[0]
    assert a.doi == "10.1007/s10649-025-10001-x"
    assert a.title == "Spatial reasoning and geometry learning", a.title  # espaces compactes
    assert a.authors == ["Smith, Jane", "García, Luis"], a.authors
    assert a.year == 2025
    assert a.journal == "Educational Studies in Mathematics"
    assert a.language == "en"
    # resume JATS nettoye : plus de balises, entites decodees
    assert "<" not in a.abstract and "jats" not in a.abstract, a.abstract
    assert "spatial reasoning & geometry" in a.abstract, a.abstract
    assert len(a.references) == 2, a.references
    assert a.references[0].startswith("Duval"), a.references[0]
    assert "DOI:10.1000/x" in a.references[1], a.references[1]

    b = recs[1]
    assert b.abstract == "Limits are notoriously hard", b.abstract  # repli OpenAlex
    print("  ok crossref + repli openalex + pagination")


if __name__ == "__main__":
    test_metadata()
    print("TOUS LES TESTS PASSENT")
