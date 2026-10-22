"""Completion des bibliographies via Crossref.

Les notices moissonnees en OAI (OpenEdition, Rematec) arrivent sans
bibliographie : le format oai_dc ne la porte pas. Beaucoup ont toutefois un DOI,
et Crossref connait souvent leurs references. Pour chaque notice a DOI sans
references et pas encore examinee, on interroge Crossref et on range la liste
dans refs_json, au meme format que le connecteur metadata.

Sert a reconstituer le reseau de citations, donc l'histoire des notions.
Chaque notice examinee est datee (refs_checked_at), qu'elle ait des references
ou non : on ne la reinterroge pas au passage suivant.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Optional
from urllib.parse import quote

from . import config, db, http
from .connectors.metadata import CROSSREF_URL, MetadataConnector, _default_get_json

log = logging.getLogger("veille")

GetJson = Callable[[str, dict], dict]


class ReferenceBackfiller:
    def __init__(
        self,
        get_json: Optional[GetJson] = None,
        *,
        mailto: Optional[str] = None,
        page_pause: float = 0.34,
    ) -> None:
        self._get_json = get_json or _default_get_json
        self._mailto = mailto if mailto is not None else config.get().email
        self._page_pause = page_pause

    def fetch(self, doi: str) -> Optional[list[str]]:
        """References d'un DOI selon Crossref : liste (eventuellement vide), ou
        None si la requete a echoue (la notice sera alors reprise plus tard)."""
        params = {"select": "reference"}
        if self._mailto:
            params["mailto"] = self._mailto
        try:
            time.sleep(self._page_pause)
            data = self._get_json(f"{CROSSREF_URL}/{quote(doi, safe='/')}", params)
        except http.HttpError as exc:
            if exc.status == 404:
                return []  # DOI inconnu de Crossref (autre agence) : rien a attendre
            return None
        except Exception:
            return None
        refs = (data.get("message") or {}).get("reference") or []
        return MetadataConnector._references(refs)


def backfill_references(
    conn: sqlite3.Connection,
    backfiller: Optional[ReferenceBackfiller] = None,
    *,
    limit: Optional[int] = None,
    page_pause: float = 0.34,
    min_year: Optional[int] = None,
    recheck_days: Optional[int] = None,
) -> tuple[int, int]:
    """Complete les references manquantes. Renvoie (examinees, completees)."""
    backfiller = backfiller or ReferenceBackfiller(page_pause=page_pause)
    works = db.works_missing_references(conn, min_year=min_year,
                                        recheck_days=recheck_days, limit=limit)
    if works:
        log.info("références : %d notice(s) à examiner", len(works))
    examined = filled = 0
    for n, w in enumerate(works, 1):
        refs = backfiller.fetch(w["doi"])
        if refs is None:
            continue
        examined += 1
        if refs:
            db.set_references(conn, w["id"], refs)
            filled += 1
        else:
            db.mark_checked(conn, "refs_checked_at", [w["id"]])
        if n % 200 == 0:
            log.info("  ... %d / %d, %d bibliographie(s) complétée(s)", n, len(works), filled)
    return examined, filled
