"""Test hors ligne du parseur FLM (connecteur scraper).

Le fixture reproduit la structure observee sur flm-journal.org : liste des
numeros, puis lignes d'articles (auteurs, titre, lien de detail).

Lancement : python tests/test_scraper_parse.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.connectors import ScraperConnector

TOC = """<html><body>
<ul>
 <li>Vol. 45 Num. 3 (2025)</li>
 <li>Vol. 46 Num. 1 (2026)</li>
</ul>
<h2>for the learning of mathematics</h2>
<table>
 <tr><td>
   <a href="https://flm-journal.org/index.php?do=search&lang=en&search=Daiki+Urayama&operator=and">Daiki Urayama</a> ,
   <a href="https://flm-journal.org/index.php?do=search&lang=en&search=Thorsten+Scheiner&operator=and">Thorsten Scheiner</a>
   <i><a href="https://flm-journal.org/index.php?do=subscribe2_to_flm&lang=en">Making values count</a></i>
   <a href="https://flm-journal.org/index.php?do=details&lang=en&vol=46&num=1&pages=2-8&ArtID=1570"><b>ABSTRACT</b></a> 2
 </td></tr>
 <tr><td>
   <a href="https://flm-journal.org/index.php?do=search&lang=en&search=Younkyung+Hong&operator=and">Younkyung Hong</a>
   <i><a href="https://flm-journal.org/index.php?do=subscribe2_to_flm&lang=en">Communication: Navigating culturally relevant mathematics</a></i> 21
 </td></tr>
 <tr><td>
   <a href="https://flm-journal.org/index.php?do=search&lang=en&search=-&operator=and">-</a>
   <i><a href="https://flm-journal.org/index.php?do=subscribe2_to_flm&lang=en">front cover</a></i> 0
 </td></tr>
</table>
</body></html>"""

DETAILS_1570 = """<html><body>
<b>ABSTRACT:</b> This paper proposes embedding axiology as a foundational
orientation alongside ontology and epistemology.
<a href="javascript:history.back()">Go Back</a>
</body></html>"""


def fake_get(url):
    if "do=details" in url and "ArtID=1570" in url:
        return DETAILS_1570
    if "do=current" in url:
        return TOC
    raise AssertionError(f"URL inattendue : {url}")


def test_flm():
    source = {"id": 10, "name": "For the Learning of Mathematics",
              "base_url": "https://flm-journal.org/"}
    conn = ScraperConnector(http_get=fake_get, page_pause=0.0, enrich_abstracts=True)
    recs = list(conn.fetch_new(source, since=None))

    # front cover ecarte : 2 articles reels
    assert len(recs) == 2, f"attendu 2 articles, obtenu {len(recs)}"

    a = recs[0]
    assert a.external_id == "flm:art:1570", a.external_id
    assert a.title == "Making values count", a.title
    assert a.authors == ["Daiki Urayama", "Thorsten Scheiner"], a.authors
    assert a.year == 2026, a.year
    assert a.journal == "For the Learning of Mathematics"
    assert a.doi is None
    assert a.full_text_url and "do=details" in a.full_text_url
    assert a.abstract and a.abstract.startswith("This paper proposes"), a.abstract

    b = recs[1]
    # le prefixe "Communication:" est retire, l'annee vient du numero courant
    assert b.title.startswith("Navigating culturally"), b.title
    assert b.year == 2026, b.year
    assert b.abstract is None  # pas de page de detail, donc pas de resume
    assert b.external_id.startswith("flm:46:1:"), b.external_id
    print("  ok parsing FLM (numero courant + resume + nettoyage titre)")


def test_irem_issue_level():
    from tests.fixtures_irem import LISTING

    source = {"id": 11, "name": "Petit x",
              "base_url": "https://irem.univ-grenoble-alpes.fr/",
              "consultation_path": "/revues/petit-x/consultation/"}
    # enrich off : grain du numero, un seul fetch
    conn = ScraperConnector(http_get=lambda u: LISTING, page_pause=0.0,
                            enrich_abstracts=False)
    recs = list(conn.fetch_new(source, since=None))

    # 5 numeros dans la liste de contenu ; les 2 liens du plan de site ecartes
    assert len(recs) == 5, f"attendu 5 numeros, obtenu {len(recs)}"
    by_id = {r.external_id: r for r in recs}

    # ere recente : URL a plat, cle = identifiant .kjsp
    n123 = by_id["iremgren:1742582"]
    assert n123.year == 2025 and "123" in n123.title, n123.title
    assert n123.full_text_url.startswith("https://irem.univ-grenoble-alpes.fr/numero-123")
    assert n123.journal == "Petit x" and n123.authors == [] and n123.doi is None

    # ere ancienne : arborescence conservee
    assert by_id["iremgren:1547194"].year == 2024
    # numero thematique
    assert by_id["iremgren:1351520"].year == 2023
    # hors-serie : ni numero ni annee, mais une entree quand meme
    hs = by_id["iremgren:1081112"]
    assert hs.year is None and "Hors-série" in hs.title, hs.title
    # numero double
    assert by_id["iremgren:650322"].year == 2019
    print("  ok parsing IREM grain numero (3 eres d'URL, hors-serie, plan de site ignore)")


def test_irem_drilldown():
    from tests.fixtures_irem import ONE_ISSUE, ISSUE_PAGE, ART_PAGE

    def router(u):
        if "1742582" in u:            # page du numero
            return ISSUE_PAGE
        if ".kjsp" in u:              # page d'article
            return ART_PAGE
        return ONE_ISSUE              # page de consultation

    source = {"id": 11, "name": "Petit x",
              "base_url": "https://irem.univ-grenoble-alpes.fr/",
              "consultation_path": "/revues/petit-x/consultation/"}
    # enrich on : numero -> articles -> auteurs + PDF
    conn = ScraperConnector(http_get=router, page_pause=0.0, enrich_abstracts=True)
    recs = list(conn.fetch_new(source, since=None))

    assert len(recs) == 2, f"attendu 2 articles, obtenu {len(recs)}"
    a = recs[0]
    assert a.external_id == "iremgren:1742585", a.external_id
    assert a.title.startswith("Logarithmes en jeu"), a.title
    assert a.year == 2025, a.year  # annee du numero, pas DC.Date (2026)
    assert a.authors == ["Benjamin Wack"], a.authors  # universite ecartee
    assert a.abstract is None  # non expose par la page
    assert a.full_text_url.endswith("1742585.kjsp?RH=1774606601620")
    assert a.oa_url == "https://irem.univ-grenoble-alpes.fr/medias/fichier/123x1_1774606864373-pdf"
    assert recs[1].external_id == "iremgren:1742587"
    print("  ok drill-down IREM grain article (titre, auteurs DC.Creator, PDF oa_url, annee du numero)")


if __name__ == "__main__":
    test_flm()
    test_irem_issue_level()
    test_irem_drilldown()
    print("TOUS LES TESTS PASSENT")
