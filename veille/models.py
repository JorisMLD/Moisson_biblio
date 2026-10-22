"""Modele de donnees commun a tous les connecteurs.

Chaque connecteur, quelle que soit sa source (API, OAI-PMH, scraping), produit
des objets RawRecord identiques. Le reste de la chaine (normalisation,
deduplication, persistance) ne connait que ce format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FileKind(str, Enum):
    """Nature d'un lien rattache a une notice.

    PUBLISHER : page de l'article chez l'editeur (lien citable, pas un PDF).
    OA        : PDF en acces ouvert, chez la revue ou un depot (rang 1).
    HAL_AUTHOR: version auteur deposee dans HAL (rang 2, en secours).
    """

    PUBLISHER = "publisher"
    OA = "oa"
    HAL_AUTHOR = "hal_author"


SOURCE_RANK: dict[FileKind, int] = {
    FileKind.PUBLISHER: 1,
    FileKind.OA: 1,
    FileKind.HAL_AUTHOR: 2,
}


class WorkType(str, Enum):
    """Type de document, pour un export BibTeX juste."""

    ARTICLE = "journal-article"
    CHAPTER = "book-chapter"
    BOOK = "book"
    ISSUE = "issue"          # numero entier (revues IREM au grain du numero)
    OTHER = "other"


_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
    "http://dx.doi.org/", "doi.org/", "doi:",
)


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Forme canonique d'un DOI : minuscules, sans prefixe de resolveur.

    Les DOI ne sont pas sensibles a la casse ; sans normalisation, un meme
    article vu en majuscules par une source et en minuscules par une autre
    serait compte deux fois.
    """
    if not doi:
        return None
    d = doi.strip().lower()
    for p in _DOI_PREFIXES:
        if d.startswith(p):
            d = d[len(p):]
            break
    d = d.strip().rstrip(".")
    return d or None


@dataclass
class RawRecord:
    """Une notice normalisee, indifferente au connecteur qui l'a produite."""

    source_id: int
    external_id: str                       # identifiant stable cote source (id OAI ou DOI)
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    full_text_url: Optional[str] = None    # page de l'article chez l'editeur
    oa_url: Optional[str] = None           # PDF en acces ouvert, si connu
    references: list[str] = field(default_factory=list)
    language: Optional[str] = None
    work_type: str = WorkType.ARTICLE.value
    datestamp: Optional[str] = None        # datestamp OAI de la notice, le cas echeant
    deleted: bool = False                  # notice marquee supprimee cote entrepot
